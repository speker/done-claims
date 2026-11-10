"""Classify a finished trajectory by the evidence that follows its last product-code edit."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from . import rules
from .trajectory import Step, parse


class Category(StrEnum):
    NO_PRODUCT_CHANGE = "no_product_change"
    UNDETERMINED = "undetermined"
    UNVERIFIED = "unverified"
    RAN_FAILING = "ran_failing"
    RAN_PASSING = "ran_passing"


@dataclass(frozen=True)
class Event:
    """One agent action with what it wrote, whether the write took effect, and how a run ended."""

    index: int
    action: rules.Action
    applied: bool
    outcome: rules.Outcome | None


@dataclass(frozen=True)
class Assessment:
    category: Category
    n_steps: int
    product_files: tuple[str, ...]
    touched_tests: bool
    last_product_edit: int | None
    runs_after_edit: int
    tests_after_edit: int
    last_outcome: rules.Outcome | None
    claims_success: bool


def classify_events(events: Iterable[Event], files: list[str], closing: str, n_steps: int) -> Assessment:
    product = tuple(f for f in files if rules.file_role(f) == "product")
    touched_tests = any(rules.file_role(f) == "test" for f in files)

    last_edit: int | None = None
    runs: list[tuple[int, rules.Kind, rules.Outcome]] = []
    for event in events:
        writes_product = any(rules.targets_file(t, p) for t in event.action.writes for p in product)
        if writes_product and event.applied:
            last_edit = event.index
        if event.action.kind in rules.RUN_KINDS and event.outcome is not None:
            runs.append((event.index, event.action.kind, event.outcome))

    after = [r for r in runs if last_edit is not None and r[0] >= last_edit]
    last_outcome = after[-1][2] if after else None
    if not product:
        category = Category.NO_PRODUCT_CHANGE
    elif last_edit is None:
        category = Category.UNDETERMINED
    elif not after:
        category = Category.UNVERIFIED
    elif last_outcome is rules.Outcome.FAIL:
        category = Category.RAN_FAILING
    else:
        category = Category.RAN_PASSING

    return Assessment(
        category=category,
        n_steps=n_steps,
        product_files=product,
        touched_tests=touched_tests,
        last_product_edit=last_edit,
        runs_after_edit=len(after),
        tests_after_edit=sum(1 for r in after if r[1] is rules.Kind.TEST_RUN),
        last_outcome=last_outcome,
        claims_success=rules.claims_success(closing),
    )


def closing_text(steps: list[Step]) -> str:
    for step in reversed(steps):
        if rules.classify(step.command, step.open_file).kind is rules.Kind.SUBMIT:
            if step.discussion:
                return step.discussion
            earlier = [s.discussion for s in steps[: step.index] if s.discussion]
            return earlier[-1] if earlier else ""
    return ""


def swe_agent_events(steps: list[Step]) -> list[Event]:
    events = []
    for step in steps:
        action = rules.classify(step.command, step.open_file)
        outcome = rules.outcome(action.kind, step.observation) if action.kind in rules.RUN_KINDS else None
        events.append(Event(step.index, action, rules.write_applied(action, step.observation), outcome))
    return events


def assess(trajectory: list[dict], patch: str | None) -> Assessment:
    steps = parse(trajectory)
    return classify_events(swe_agent_events(steps), rules.patch_files(patch), closing_text(steps), len(steps))
