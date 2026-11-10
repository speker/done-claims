"""SWE-agent trajectories as a list of (discussion, command, observation) steps."""

import re
from dataclasses import dataclass

_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_EDIT_BLOCK = re.compile(r"```[^\n`]*\n((?:edit|insert|append)\b[^\n]*\n.*?\nend_of_edit)[ \t]*\n```", re.S)
_OPEN_FILE = re.compile(r"\(Open file: ([^)\n]*)\)")


@dataclass(frozen=True)
class Step:
    index: int
    discussion: str
    command: str | None
    observation: str
    open_file: str | None


def split_action(text: str) -> tuple[str, str | None]:
    """The command is the last fenced block; everything before it is discussion.

    An edit body may itself contain fences, so an edit block that runs to end_of_edit and ends
    at or after the last plain fence wins over the plain match.
    """
    blocks = list(_FENCE.finditer(text))
    if not blocks:
        return text.strip(), None
    last = blocks[-1]
    edits = list(_EDIT_BLOCK.finditer(text))
    if edits and edits[-1].end() >= last.end():
        last = edits[-1]
    return text[: last.start()].strip(), last.group(1).strip()


def open_file_marker(observation: str) -> str | None:
    """None when the observation has no marker, "" when it reports no open file."""
    found = _OPEN_FILE.findall(observation)
    if not found:
        return None
    value = found[-1].strip()
    return "" if value == "n/a" else value


def parse(trajectory: list[dict]) -> list[Step]:
    steps: list[Step] = []
    open_file: str | None = None
    pending: tuple[str, str | None, str | None] | None = None

    for turn in trajectory:
        role = turn.get("role")
        text = turn.get("text") or ""
        if role == "ai":
            if pending is not None:
                steps.append(Step(len(steps), pending[0], pending[1], "", pending[2]))
            discussion, command = split_action(text)
            pending = (discussion, command, open_file)
        elif role == "user":
            if pending is not None:
                steps.append(Step(len(steps), pending[0], pending[1], text, pending[2]))
                pending = None
            marker = open_file_marker(text)
            if marker is not None:
                open_file = marker or None

    if pending is not None:
        steps.append(Step(len(steps), pending[0], pending[1], "", pending[2]))
    return steps
