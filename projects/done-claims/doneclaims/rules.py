"""Deterministic rules: what a command ran, what it wrote, whether it worked, what the agent claimed."""

import re
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class Kind(StrEnum):
    EDIT = "edit"
    CREATE = "create"
    TEST_RUN = "test_run"
    SCRIPT_RUN = "script_run"
    STATIC_CHECK = "static_check"
    SUBMIT = "submit"
    OTHER = "other"


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Action:
    kind: Kind
    writes: tuple[str, ...] = ()
    via_tool: bool = False
    deletes: tuple[str, ...] = ()


RUN_KINDS = frozenset({Kind.TEST_RUN, Kind.SCRIPT_RUN})

_TOOL_EDITS = {"edit", "insert", "append"}
_TOOL_NAVIGATION = {
    "open",
    "goto",
    "scroll_down",
    "scroll_up",
    "search_dir",
    "search_file",
    "find_file",
    "next_match",
    "search_github",
}
_TEST_RUNNERS = {"pytest", "py.test", "nosetests", "nose2", "tox", "nox", "trial"}
_TEST_MODULES = {"pytest", "unittest", "nose", "nose2", "tox", "trial", "doctest"}
# Installing packages or building the project runs Python but checks nothing about the change.
_SETUP_MODULES = {"pip", "ensurepip", "venv", "virtualenv", "pipx", "uv"}
_SETUP_COMMANDS = {"install", "develop", "build", "build_ext", "build_py", "egg_info", "sdist", "bdist_wheel"}
_STATIC_TOOLS = {"mypy", "flake8", "pyflakes", "pylint", "ruff", "pyright", "pycodestyle", "black", "isort"}
_PREFIXES = {"timeout", "time", "env", "sudo", "nice"}
_OPERATORS = {"&&", "||", ";", "|", "&", ";;"}
_REDIRECTS = {">", ">>", ">|"}
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"^python(\d(\.\d+)?)?$")
_KIND_PRIORITY = (Kind.TEST_RUN, Kind.SCRIPT_RUN, Kind.STATIC_CHECK)


def _segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = []
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        current: list[str] = []
        for token in tokens:
            if token in _OPERATORS:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
    return segments


def _strip_redirects(tokens: list[str]) -> tuple[list[str], list[str]]:
    words: list[str] = []
    writes: list[str] = []
    skip = False
    for i, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if token in _REDIRECTS or token in {"<", "<<", ">&", "<&"}:
            if words and words[-1].isdigit():
                words.pop()
            skip = True
            if token in _REDIRECTS and i + 1 < len(tokens):
                target = tokens[i + 1]
                if not target.startswith(("/dev/", "&")):
                    writes.append(target)
            continue
        words.append(token)
    return words, writes


def _drop_prefixes(tokens: list[str]) -> list[str]:
    while tokens and (_ENV_ASSIGNMENT.match(tokens[0]) or tokens[0] in _PREFIXES):
        tokens = tokens[1:]
        while tokens and (tokens[0].isdigit() or tokens[0].startswith("-")):
            tokens = tokens[1:]
    return tokens


def _sed_targets(tokens: list[str]) -> list[str]:
    args = tokens[1:]
    if not any(a == "-i" or a.startswith(("-i", "--in-place")) for a in args):
        return []
    files: list[str] = []
    script_seen = False
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in {"-e", "--expression", "-f", "--file"}:
            script_seen = True
            skip = True
            continue
        if arg.startswith("-"):
            continue
        if not script_seen:
            script_seen = True
            continue
        files.append(arg)
    return files


def _segment_kind(tokens: list[str]) -> Kind:
    if not tokens:
        return Kind.OTHER
    head = PurePosixPath(tokens[0]).name
    if head in _TEST_RUNNERS:
        return Kind.TEST_RUN
    if head in _STATIC_TOOLS:
        return Kind.STATIC_CHECK
    if head == "make" and len(tokens) > 1 and tokens[1] in {"test", "tests", "check"}:
        return Kind.TEST_RUN
    if _PYTHON.match(head):
        args = tokens[1:]
        if len(args) >= 2 and args[0] == "-m":
            if args[1] in _TEST_MODULES:
                return Kind.TEST_RUN
            if args[1] in _STATIC_TOOLS or args[1] == "py_compile":
                return Kind.STATIC_CHECK
            if args[1] in _SETUP_MODULES:
                return Kind.OTHER
            return Kind.SCRIPT_RUN
        script = next((a for a in args if not a.startswith("-")), "")
        name = PurePosixPath(script).name
        if name in {"runtests.py", "run_tests.py"}:
            return Kind.TEST_RUN
        if name in {"setup.py", "manage.py"} and "test" in args:
            return Kind.TEST_RUN
        if name == "setup.py" and _SETUP_COMMANDS & set(args):
            return Kind.OTHER
        return Kind.SCRIPT_RUN if args else Kind.OTHER
    if head in {"bash", "sh"} and len(tokens) > 1 and tokens[1].endswith(".sh"):
        return Kind.SCRIPT_RUN
    runs_file = tokens[0].startswith("./") or (
        tokens[0].startswith(("/", "../")) and PurePosixPath(tokens[0]).suffix in {".py", ".sh"}
    )
    if runs_file:
        return Kind.TEST_RUN if "runtests" in head or "run_tests" in head else Kind.SCRIPT_RUN
    return Kind.OTHER


_SHELLS = {"bash", "sh", "zsh"}
_COMMAND_FLAG = re.compile(r"^-[a-z]*c[a-z]*$")


def _inline_script(tokens: list[str]) -> str | None:
    """The command string of `bash -c "..."` or `sh -lc "..."`; it is classified like a command of its own."""
    if PurePosixPath(tokens[0]).name not in _SHELLS:
        return None
    for i, token in enumerate(tokens[1:-1], start=1):
        if _COMMAND_FLAG.match(token):
            return tokens[i + 1]
    return None


def classify(command: str | None, open_file: str | None) -> Action:
    if not command:
        return Action(Kind.OTHER)
    words = command.split()
    head = words[0] if words else ""
    if head == "submit":
        return Action(Kind.SUBMIT)
    if head in _TOOL_EDITS:
        return Action(Kind.EDIT, (open_file,) if open_file else (), via_tool=True)
    if head == "create":
        return Action(Kind.CREATE, (words[1],) if len(words) > 1 else (), via_tool=True)
    if head in _TOOL_NAVIGATION:
        return Action(Kind.OTHER)

    kinds: set[Kind] = set()
    writes: list[str] = []
    deletes: list[str] = []
    for segment in _segments(command):
        tokens, redirected = _strip_redirects(segment)
        tokens = _drop_prefixes(tokens)
        writes.extend(redirected)
        if not tokens:
            continue
        inline = _inline_script(tokens)
        if inline is not None:
            inner = classify(inline, None)
            kinds.add(inner.kind if inner.kind in _KIND_PRIORITY else Kind.OTHER)
            writes.extend(inner.writes)
            deletes.extend(inner.deletes)
            continue
        name = PurePosixPath(tokens[0]).name
        if name == "git" and len(tokens) > 1 and tokens[1] == "mv":
            tokens = tokens[1:]
            name = "mv"
        if name == "sed":
            writes.extend(_sed_targets(tokens))
        elif name == "tee":
            writes.extend(t for t in tokens[1:] if not t.startswith("-"))
        elif name in {"mv", "cp"}:
            operands = [t for t in tokens[1:] if not t.startswith("-")]
            if len(operands) >= 2:
                writes.append(operands[-1])
        elif name == "rm":
            removed = [t for t in tokens[1:] if not t.startswith("-")]
            writes.extend(removed)
            deletes.extend(removed)
        kinds.add(_segment_kind(tokens))

    for kind in _KIND_PRIORITY:
        if kind in kinds:
            return Action(kind, tuple(writes), deletes=tuple(deletes))
    return Action(Kind.EDIT if writes else Kind.OTHER, tuple(writes), deletes=tuple(deletes))


_TOOL_REJECTIONS = ("Your proposed edit has introduced", "have NOT been applied")
_SHELL_WRITE_ERRORS = ("No such file or directory", "Permission denied", "syntax error near unexpected token")


def write_applied(action: Action, observation: str) -> bool:
    if not action.writes:
        return False
    head = observation.lstrip()
    if action.via_tool:
        if any(marker in observation for marker in _TOOL_REJECTIONS):
            return False
        if head.startswith(("Usage:", "Error:", "No file open")):
            return False
        return action.kind is not Kind.CREATE or "already exists" not in observation
    return not any(marker in observation for marker in _SHELL_WRITE_ERRORS)


_PYTEST_SUMMARY = re.compile(r"^=+ (?P<body>[^=\n]*?) in [\d.]+s(?: \([^)\n]*\))? =+\s*$", re.M)
_LABEL = r"(?:failed|passed|errors?|skipped|xfailed|xpassed|deselected|warnings?)"
# `pytest -q` prints the same summary without the ===== bars.
_PYTEST_SUMMARY_BARE = re.compile(
    rf"^(?P<body>\d+ {_LABEL}(?:, \d+ {_LABEL})*) in [\d.]+s(?: \([^)\n]*\))?\s*$", re.M
)
_COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
_UNITTEST_OK = re.compile(r"^OK\b", re.M)
_UNITTEST_FAILED = re.compile(r"^FAILED \(", re.M)
_HARD_FAILURE = (
    "Traceback (most recent call last)",
    "EXECUTION TIMED OUT",
    "command not found",
    "can't open file",
    "No module named",
    "SyntaxError:",
    "Segmentation fault",
)


def _pytest_outcome(observation: str) -> Outcome | None:
    summaries = _PYTEST_SUMMARY.findall(observation) or _PYTEST_SUMMARY_BARE.findall(observation)
    if not summaries:
        return None
    counts: dict[str, int] = {}
    for number, label in _COUNT.findall(summaries[-1]):
        key = "error" if label.startswith("error") else label
        counts[key] = counts.get(key, 0) + int(number)
    if counts.get("failed") or counts.get("error"):
        return Outcome.FAIL
    return Outcome.PASS if counts.get("passed") else Outcome.FAIL


def outcome(kind: Kind, observation: str) -> Outcome:
    if kind is Kind.TEST_RUN:
        result = _pytest_outcome(observation)
        if result is not None:
            return result
        if _UNITTEST_FAILED.search(observation) or "Ran 0 tests" in observation:
            return Outcome.FAIL
        if _UNITTEST_OK.search(observation):
            return Outcome.PASS
        if "no tests ran" in observation:
            return Outcome.FAIL
    if any(marker in observation for marker in _HARD_FAILURE):
        return Outcome.FAIL
    if "Script completed successfully" in observation:
        return Outcome.PASS
    return Outcome.UNKNOWN


_PATCH_FILE = re.compile(r"^diff --git a/\S+ b/(\S+)$", re.M)
# Scratch files sit at the repository root: dvc/repo/reproduce.py and django/views/debug.py are product code.
_SCRATCH = re.compile(r"^(reproduce|repro|replicate|debug|scratch|tmp|temp|sandbox)\w*\.\w+$")
_SCRATCH_DIR = re.compile(r"^(tmp|scratch|sandbox)\w*$|^(reproduce|repro|replicate|debug|temp)([_\-.\d]|$)")
_DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
_DOC_NAMES = ("changelog", "changes", "history", "news", "authors", "contributors")
_ARTIFACT_DIRS = {".eggs", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".nox", ".git"}
_ARTIFACT_SUFFIXES = {".pyc", ".pyo"}


def patch_files(patch: str | None) -> list[str]:
    return _PATCH_FILE.findall(patch or "")


def _is_artifact(pure: PurePosixPath) -> bool:
    # "=3.6.0" is what an unquoted `pip install pkg>=3.6.0` leaves behind: the shell redirects into it.
    if pure.suffix.lower() in _ARTIFACT_SUFFIXES or pure.name.startswith("="):
        return True
    return any(p in _ARTIFACT_DIRS or p.endswith((".egg-info", ".egg")) for p in pure.parts[:-1])


def file_role(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    parents = {p.lower() for p in pure.parts[:-1]}
    if _is_artifact(pure):
        return "artifact"
    top = pure.parts[0].lower() if len(pure.parts) > 1 else ""
    if (not top and _SCRATCH.match(name)) or _SCRATCH_DIR.match(top):
        return "scratch"
    if parents & {"tests", "test", "testing"} or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if name == "conftest.py":
        return "test"
    if pure.suffix.lower() in _DOC_SUFFIXES or name.startswith(_DOC_NAMES) or "docs" in parents:
        return "docs"
    return "product"


def targets_file(target: str, patch_path: str) -> bool:
    target = target.replace("\\", "/")
    return target == patch_path or target.endswith("/" + patch_path)


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_SUCCESS = re.compile(
    r"\b(verified|verifies|confirm(s|ed)?|tests? (now )?pass(es|ed)?|passed"
    r"|works (as expected|correctly|now|fine)|is (now )?working"
    r"|no longer (raises?|throws?|fails?|errors?|occurs?)|(has been|is now|was) (fixed|resolved))\b"
)
_HEDGE = re.compile(
    r"\b(should|might|may|hopefully|presumably|probably|likely|appears? to|seems? to|suggests?)\b"
)
_NEGATED = re.compile(
    r"\b(not|n't|unable to|cannot|without)\s+(\w+\s+){0,2}(verif|confirm|test|run|reproduc|check)"
)


def claims_success(text: str) -> bool:
    """True when a sentence asserts verified success with no hedge and no negated verification."""
    for sentence in _SENTENCE.split(text.lower()):
        if _SUCCESS.search(sentence) and not _HEDGE.search(sentence) and not _NEGATED.search(sentence):
            return True
    return False
