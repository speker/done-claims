"""Claude Code trajectories in Harbor's ATIF format (agent/trajectory.json) as evidence events."""

import json
import re
from dataclasses import dataclass

from . import rules
from .evidence import Assessment, Event, classify_events

_EDIT_TOOLS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}
_SHELL_TOOLS = {"Bash"}
_TOOL_ERROR = "<tool_use_error>"
_CREATED = "File created successfully"
_METADATA = re.compile(r"^\[metadata\] (\{.*\})\s*$", re.M)
_REMOTE = re.compile(r"https?://|\b(curl|wget)\b|\bgit\s+(clone|fetch|pull|ls-remote)\b")


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(content_text(part) for part in content)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def repository_roots(document: dict) -> tuple[str, ...]:
    """Working directories Harbor recorded for the session; the repository lives there."""
    extra = (document.get("agent") or {}).get("extra") or {}
    return tuple(root.rstrip("/") for root in extra.get("cwds") or [] if root and root != "/")


def relative_to_roots(path: str, roots: tuple[str, ...]) -> str:
    """Paths inside a root become repository-relative; paths outside stay absolute."""
    path = path.replace("\\", "/")
    for root in roots:
        if path.startswith(root + "/"):
            return path[len(root) + 1 :]
    return path.removeprefix("./")


def inside_repository(path: str, roots: tuple[str, ...]) -> bool:
    return not roots or not path.startswith(("/", "~"))


def _results_by_call(step: dict) -> dict[str, dict]:
    observation = step.get("observation") or {}
    return {r.get("source_call_id"): r for r in observation.get("results") or [] if r.get("source_call_id")}


def _is_error(result: dict | None) -> bool:
    if result is None:
        return False
    extra = result.get("extra") or {}
    return extra.get("tool_result_is_error") is True or _TOOL_ERROR in content_text(result.get("content"))


def _agent_steps(document: dict):
    for step in document.get("steps") or []:
        if step.get("source") == "agent":
            yield step


@dataclass(frozen=True)
class ToolCall:
    index: int
    name: str
    arguments: dict
    output: str
    failed: bool


def tool_calls(document: dict) -> list[ToolCall]:
    """Every tool call of the agent in order, with its result text and whether the tool reported an error."""
    calls: list[ToolCall] = []
    for step in _agent_steps(document):
        results = _results_by_call(step)
        for call in step.get("tool_calls") or []:
            arguments = call.get("arguments")
            result = results.get(call.get("tool_call_id"))
            calls.append(
                ToolCall(
                    index=len(calls),
                    name=call.get("function_name") or "",
                    arguments=arguments if isinstance(arguments, dict) else {},
                    output=content_text(result.get("content")) if result else "",
                    failed=_is_error(result),
                )
            )
    return calls


def closing_message(document: dict) -> str:
    closing = ""
    for step in _agent_steps(document):
        message = content_text(step.get("message"))
        if message.strip():
            closing = message
    return closing


def metadata(call: ToolCall) -> dict:
    """Fields Harbor copies from Claude Code's tool result into `[metadata] {...}` lines."""
    fields: dict = {}
    for match in _METADATA.finditer(call.output):
        try:
            found = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(found, dict):
            fields.update(found)
    return fields


def edited_path(call: ToolCall) -> str | None:
    """The file an edit tool changed: Claude Code's own report first, then the arguments.

    gpt-oss sometimes passes `path` instead of `file_path`, and Claude Code applies the edit anyway.
    """
    reported = metadata(call).get("filePath")
    if isinstance(reported, str) and reported:
        return reported
    for key in (_EDIT_TOOLS.get(call.name), "file_path", "notebook_path", "path"):
        value = call.arguments.get(key) if key else None
        if isinstance(value, str) and value:
            return value
    return None


def to_event(call: ToolCall, roots: tuple[str, ...]) -> Event:
    if call.name in _EDIT_TOOLS:
        path = edited_path(call)
        writes = (relative_to_roots(path, roots),) if path else ()
        action = rules.Action(rules.Kind.EDIT, writes, via_tool=True)
        return Event(call.index, action, bool(writes) and not call.failed, None)
    if call.name in _SHELL_TOOLS:
        command = call.arguments.get("command")
        # Claude Code rejects a non-string command at input validation, so nothing ran.
        if not isinstance(command, str):
            return Event(call.index, rules.Action(rules.Kind.OTHER), False, None)
        action = rules.classify(command, None)
        action = rules.Action(
            action.kind,
            tuple(relative_to_roots(w, roots) for w in action.writes),
            action.via_tool,
            tuple(relative_to_roots(d, roots) for d in action.deletes),
        )
        outcome = None
        if action.kind in rules.RUN_KINDS:
            outcome = rules.outcome(action.kind, call.output)
            if call.failed and outcome is rules.Outcome.UNKNOWN:
                outcome = rules.Outcome.FAIL
            # Claude Code moves a command to the background when it hits the Bash time limit; the run
            # did not finish, which phase 1 counts as a failure ("EXECUTION TIMED OUT").
            if metadata(call).get("timedOutAfterMs"):
                outcome = rules.Outcome.FAIL
        return Event(call.index, action, not call.failed, outcome)
    return Event(call.index, rules.Action(rules.Kind.OTHER), False, None)


def events_from_atif(document: dict) -> tuple[list[Event], str, int]:
    """Events in call order, the last agent message, and the number of tool calls."""
    roots = repository_roots(document)
    calls = tool_calls(document)
    return [to_event(c, roots) for c in calls], closing_message(document), len(calls)


def remote_fetches(document: dict) -> int:
    """Shell commands that reach a URL or a git remote; the agent could pull an upstream fix this way."""
    return sum(
        1
        for c in tool_calls(document)
        if c.name in _SHELL_TOOLS
        and isinstance(c.arguments.get("command"), str)
        and _REMOTE.search(c.arguments["command"])
    )


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip("/") + "/")


def transient_files(calls: list[ToolCall], events: list[Event]) -> set[str]:
    """Files the agent created with Write and later removed, and the removals that took them away.

    They are not in the final repository, so neither creating nor deleting them changes the product.
    """
    created = {
        e.action.writes[0]
        for c, e in zip(calls, events, strict=True)
        if c.name == "Write" and e.applied and e.action.writes and _CREATED in c.output
    }
    deleted = {d for e in events if e.applied for d in e.action.deletes}
    gone = {p for p in created if any(_under(p, d) for d in deleted)}
    return gone | {d for d in deleted if any(_under(p, d) for p in gone)}


def assess_atif(document: dict, patch: str | None = None) -> Assessment:
    """Without a patch, product files are the files inside the repository that applied edits touched,
    leaving out files the agent created and deleted again."""
    roots = repository_roots(document)
    calls = tool_calls(document)
    events = [to_event(c, roots) for c in calls]
    if patch is not None:
        files = rules.patch_files(patch)
    else:
        touched = {t for e in events if e.applied for t in e.action.writes if inside_repository(t, roots)}
        files = sorted(touched - transient_files(calls, events))
    return classify_events(events, files, closing_message(document), len(calls))
