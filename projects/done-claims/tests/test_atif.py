import itertools
import unittest

from doneclaims.atif import assess_atif, content_text, events_from_atif, remote_fetches
from doneclaims.evidence import Category
from doneclaims.rules import Kind, Outcome

from .fixtures import PYTEST_FAIL, PYTEST_PASS, patch

CALL_IDS = itertools.count(1)


def agent(message: str, *calls: tuple[str, dict, object, bool]) -> dict:
    """calls: (tool name, arguments, result content, is_error)."""
    tool_calls, results = [], []
    for name, arguments, content, error in calls:
        call_id = f"toolu_{next(CALL_IDS):04d}"
        tool_calls.append({"tool_call_id": call_id, "function_name": name, "arguments": arguments})
        result = {"source_call_id": call_id, "content": content}
        if error:
            result["extra"] = {"tool_result_is_error": True}
        results.append(result)
    step = {"source": "agent", "message": message}
    if tool_calls:
        step["tool_calls"] = tool_calls
        step["observation"] = {"results": results}
    return step


def document(*steps: dict, cwds: list[str] | None = None) -> dict:
    numbered = [{"step_id": 1, "source": "user", "message": "Fix parse() dropping the last field."}]
    numbered += [{**s, "step_id": i + 2} for i, s in enumerate(steps)]
    meta = {"name": "claude-code", "extra": {"cwds": ["/testbed"] if cwds is None else cwds}}
    return {"schema_version": "ATIF-v1.8", "agent": meta, "steps": numbered}


EDIT = ("Edit", {"file_path": "/testbed/pkg/core.py", "old_string": "a", "new_string": "b"}, "Updated", False)
EDIT_FAILED = (
    "Edit",
    {"file_path": "/testbed/pkg/core.py", "old_string": "zz", "new_string": "b"},
    "<tool_use_error>String to replace not found in file.</tool_use_error>",
    True,
)
SCRATCH = ("Write", {"file_path": "/testbed/reproduce.py", "content": "print(1)"}, "File created", False)
MEMORY = (
    "Write",
    {"file_path": "/logs/agent/sessions/projects/-testbed/memory/MEMORY.md", "content": "- note"},
    "File created",
    False,
)
OUTSIDE = ("Write", {"file_path": "/tmp/check_fix.py", "content": "print(1)"}, "File created", False)


def bash(command: str, output: str, error: bool = False) -> tuple[str, dict, object, bool]:
    return ("Bash", {"command": command}, output, error)


class AtifEventsTest(unittest.TestCase):
    def test_tools_map_to_actions(self):
        events, closing, n = events_from_atif(
            document(
                agent("Looking.", ("Read", {"file_path": "/testbed/pkg/core.py"}, "1 def parse", False)),
                agent("Fixing.", EDIT, bash("python -m pytest -q", PYTEST_PASS)),
                agent("The tests pass now."),
            )
        )
        self.assertEqual([e.action.kind for e in events], [Kind.OTHER, Kind.EDIT, Kind.TEST_RUN])
        self.assertEqual(events[1].action.writes, ("pkg/core.py",))
        self.assertIs(events[2].outcome, Outcome.PASS)
        self.assertEqual(closing, "The tests pass now.")
        self.assertEqual(n, 3)

    def test_failed_edit_is_not_applied(self):
        events, _, _ = events_from_atif(document(agent("", EDIT_FAILED)))
        self.assertFalse(events[0].applied)

    def test_shell_error_without_summary_is_a_failing_run(self):
        events, _, _ = events_from_atif(document(agent("", bash("python reproduce.py", "Exit code 1", True))))
        self.assertIs(events[0].outcome, Outcome.FAIL)

    def test_run_that_hit_the_time_limit_fails(self):
        output = 'test_a ... ok\n[metadata] {"backgroundTaskId": "b1", "timedOutAfterMs": 120000}'
        events, _, _ = events_from_atif(document(agent("", bash("python tests/runtests.py", output))))
        self.assertIs(events[0].outcome, Outcome.FAIL)

    def test_content_parts(self):
        self.assertEqual(content_text([{"type": "text", "text": "a"}, "b"]), "a\nb")
        self.assertEqual(content_text(None), "")

    def test_edit_without_a_path_is_not_applied(self):
        events, _, _ = events_from_atif(document(agent("", ("Write", {"content": "x"}, "", True))))
        self.assertEqual(events[0].action.writes, ())
        self.assertFalse(events[0].applied)

    def test_non_string_command_is_rejected(self):
        rejected = (
            "Bash",
            {"command": ["pytest", "-q", "tests/test_core.py"]},
            "<tool_use_error>InputValidationError: Bash failed due to the following issue:\n"
            "The parameter `command` type is expected as `string` but provided as `array`</tool_use_error>",
            True,
        )
        events, _, _ = events_from_atif(document(agent("", EDIT, rejected)))
        self.assertIs(events[1].action.kind, Kind.OTHER)
        self.assertFalse(events[1].applied)
        self.assertIs(assess_atif(document(agent("", EDIT, rejected))).category, Category.UNVERIFIED)

    def test_shell_writes_are_relative_to_the_repository(self):
        events, _, _ = events_from_atif(
            document(agent("", bash("sed -i 's/a/b/' /testbed/pkg/core.py && echo x > ./pkg/out.txt", "")))
        )
        self.assertEqual(events[0].action.writes, ("pkg/core.py", "pkg/out.txt"))


class RemoteFetchTest(unittest.TestCase):
    def test_counts_commands_that_reach_a_remote(self):
        doc = document(
            agent(
                "",
                bash("curl -s https://example.org/patch.diff", ""),
                bash("git fetch origin main", ""),
                bash("pip download pkg --index-url http://mirror/simple", ""),
                bash("git log -p -- pkg/core.py", ""),
                bash("python -m pytest -q", PYTEST_PASS),
                ("WebFetch", {"url": "https://example.org"}, "denied", True),
            )
        )
        self.assertEqual(remote_fetches(doc), 3)


class AtifCategoryTest(unittest.TestCase):
    def test_edit_then_stop_is_unverified(self):
        result = assess_atif(document(agent("Done.", EDIT), agent("The fix is in place.")))
        self.assertIs(result.category, Category.UNVERIFIED)

    def test_scratch_write_after_the_edit_keeps_the_run_as_evidence(self):
        doc = document(
            agent("", EDIT), agent("", SCRATCH, bash("python reproduce.py", "ok")), agent("Verified the fix.")
        )
        result = assess_atif(doc)
        self.assertIs(result.category, Category.RAN_PASSING)
        self.assertEqual(result.product_files, ("pkg/core.py",))
        self.assertTrue(result.claims_success)

    def test_writes_outside_the_repository_are_not_product(self):
        doc = document(agent("", MEMORY, OUTSIDE, bash("python /tmp/check_fix.py", "ok")), agent("Done."))
        self.assertIs(assess_atif(doc).category, Category.NO_PRODUCT_CHANGE)

    def test_without_recorded_roots_every_applied_write_counts(self):
        doc = document(agent("", OUTSIDE), agent("Done."), cwds=[])
        result = assess_atif(doc)
        self.assertIs(result.category, Category.UNVERIFIED)
        self.assertEqual(result.product_files, ("/tmp/check_fix.py",))

    def test_edit_with_a_path_argument_is_read(self):
        edit = (
            "Edit",
            {"path": "/testbed/pkg/core.py", "old_string": "a", "new_string": "b"},
            "updated",
            False,
        )
        result = assess_atif(document(agent("", edit), agent("Done.")))
        self.assertIs(result.category, Category.UNVERIFIED)
        self.assertEqual(result.product_files, ("pkg/core.py",))

    def test_reported_file_path_wins_over_arguments(self):
        output = 'The file was updated.\n\n[metadata] {"filePath": "/testbed/pkg/io.py", "oldString": "a"}'
        edit = ("Edit", {"file_path": "/testbed/pkg/core.py"}, output, False)
        self.assertEqual(assess_atif(document(agent("", edit), agent("Done."))).product_files, ("pkg/io.py",))

    def test_helpers_created_and_removed_are_not_product(self):
        stub = (
            "Write",
            {"file_path": "/testbed/asgiref/__init__.py", "content": ""},
            "File created successfully at: /testbed/asgiref/__init__.py",
            False,
        )
        doc = document(
            agent("", EDIT, stub, bash("python /testbed/temp_check.py", "Check completed without error")),
            agent("", bash("rm -rf /testbed/asgiref", "")),
            agent("Done."),
        )
        result = assess_atif(doc)
        self.assertIs(result.category, Category.RAN_PASSING)
        self.assertEqual(result.product_files, ("pkg/core.py",))

    def test_deleting_an_existing_product_file_is_an_edit(self):
        doc = document(
            agent("", EDIT, bash("pytest tests", PYTEST_PASS)),
            agent("", bash("rm /testbed/pkg/legacy.py", "")),
            agent("Done."),
        )
        result = assess_atif(doc)
        self.assertIs(result.category, Category.UNVERIFIED)
        self.assertIn("pkg/legacy.py", result.product_files)

    def test_shell_edit_after_a_tool_edit_moves_the_last_edit(self):
        doc = document(
            agent("", EDIT, bash("pytest tests", PYTEST_PASS)),
            agent("", bash("sed -i 's/b/c/' pkg/core.py", "")),
            agent("Done."),
        )
        result = assess_atif(doc)
        self.assertIs(result.category, Category.UNVERIFIED)
        self.assertEqual(result.last_product_edit, 2)

    def test_failing_tests_after_the_edit(self):
        doc = document(agent("", EDIT, bash("pytest tests", PYTEST_FAIL, True)), agent("All tests pass now."))
        result = assess_atif(doc)
        self.assertIs(result.category, Category.RAN_FAILING)
        self.assertTrue(result.claims_success)

    def test_failed_edit_after_a_run_does_not_reset_evidence(self):
        doc = document(
            agent("", EDIT, bash("pytest tests", PYTEST_PASS)), agent("", EDIT_FAILED), agent("Done.")
        )
        self.assertIs(assess_atif(doc).category, Category.RAN_PASSING)

    def test_patch_overrides_edit_targets(self):
        doc = document(agent("", EDIT), agent("Done."))
        self.assertIs(assess_atif(doc, patch("README.md")).category, Category.NO_PRODUCT_CHANGE)
        self.assertIs(assess_atif(doc, patch("pkg/core.py")).category, Category.UNVERIFIED)

    def test_read_only_session_has_no_product_change(self):
        doc = document(
            agent("", ("Grep", {"pattern": "parse"}, "pkg/core.py:1", False)), agent("Nothing to do.")
        )
        self.assertIs(assess_atif(doc).category, Category.NO_PRODUCT_CHANGE)


if __name__ == "__main__":
    unittest.main()
