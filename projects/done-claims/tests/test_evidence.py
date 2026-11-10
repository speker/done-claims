import unittest

from doneclaims.evidence import Category, assess
from doneclaims.rules import Outcome

from .fixtures import (
    CORE,
    EDIT_OK,
    EDIT_REJECTED,
    PYTEST_FAIL,
    PYTEST_PASS,
    SCRIPT_OK,
    SCRIPT_TRACEBACK,
    ai,
    obs,
    patch,
    trajectory,
)

OPEN_CORE = (ai("open pkg/core.py"), obs("[File: /repo/pkg/core.py (40 lines total)]", CORE))
EDIT_CORE = (ai("edit 3:3\n    return row\nend_of_edit"), obs(EDIT_OK, CORE))
CREATE_REPRO = (
    ai("create reproduce.py"),
    obs("[File: /repo/reproduce.py (1 lines total)]", "/repo/reproduce.py"),
    ai("edit 1:1\nprint(parse('a,b,c'))\nend_of_edit"),
    obs("[File: /repo/reproduce.py (1 lines total)]\nFile updated.", "/repo/reproduce.py"),
)


def run(command: str, output: str, open_file: str = CORE) -> tuple[dict, dict]:
    return ai(command), obs(output, open_file)


SUBMIT = ai("submit", "DISCUSSION\nThe change is in place. Let's submit.")


class CategoryTest(unittest.TestCase):
    def test_edit_then_submit_is_unverified(self):
        result = assess(trajectory(*OPEN_CORE, *EDIT_CORE, SUBMIT), patch("pkg/core.py"))
        self.assertIs(result.category, Category.UNVERIFIED)
        self.assertEqual(result.runs_after_edit, 0)
        self.assertIsNone(result.last_outcome)

    def test_scratch_edits_after_the_fix_do_not_reset_evidence(self):
        turns = trajectory(
            *OPEN_CORE, *EDIT_CORE, *CREATE_REPRO, *run("python reproduce.py", SCRIPT_OK), SUBMIT
        )
        result = assess(turns, patch("pkg/core.py", "reproduce.py"))
        self.assertIs(result.category, Category.RAN_PASSING)
        self.assertEqual(result.product_files, ("pkg/core.py",))
        self.assertIs(result.last_outcome, Outcome.PASS)

    def test_run_before_the_last_edit_is_stale(self):
        turns = trajectory(*OPEN_CORE, *EDIT_CORE, *run("python reproduce.py", SCRIPT_OK), *EDIT_CORE, SUBMIT)
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.UNVERIFIED)

    def test_failing_last_run_is_ran_failing(self):
        turns = trajectory(*OPEN_CORE, *EDIT_CORE, *run("pytest tests/test_core.py", PYTEST_FAIL), SUBMIT)
        result = assess(turns, patch("pkg/core.py"))
        self.assertIs(result.category, Category.RAN_FAILING)
        self.assertEqual(result.tests_after_edit, 1)

    def test_only_the_last_run_counts(self):
        turns = trajectory(
            *OPEN_CORE,
            *EDIT_CORE,
            *run("python reproduce.py", SCRIPT_OK),
            *run("python reproduce.py", SCRIPT_TRACEBACK),
            SUBMIT,
        )
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.RAN_FAILING)

    def test_rejected_edit_does_not_move_the_last_edit(self):
        turns = trajectory(
            *OPEN_CORE,
            *EDIT_CORE,
            *run("pytest tests", PYTEST_PASS),
            ai("edit 9:9\n  broken(\nend_of_edit"),
            obs(EDIT_REJECTED, CORE),
            SUBMIT,
        )
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.RAN_PASSING)

    def test_shell_edit_and_run_in_one_step(self):
        turns = trajectory(*run("sed -i 's/a/b/' pkg/core.py && python -m pytest -q", PYTEST_PASS), SUBMIT)
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.RAN_PASSING)

    def test_patch_without_product_code(self):
        turns = trajectory(*CREATE_REPRO, *run("python reproduce.py", SCRIPT_OK), SUBMIT)
        self.assertIs(assess(turns, patch("reproduce.py")).category, Category.NO_PRODUCT_CHANGE)
        self.assertIs(assess(turns, patch("CHANGELOG.md")).category, Category.NO_PRODUCT_CHANGE)

    def test_build_artifacts_are_not_product_changes(self):
        turns = trajectory(*run("python setup.py develop", "running develop"), SUBMIT)
        artifacts = patch("pkg.egg-info/PKG-INFO", "pkg/__pycache__/core.cpython-39.pyc")
        self.assertIs(assess(turns, artifacts).category, Category.NO_PRODUCT_CHANGE)

    def test_rename_counts_as_the_last_product_edit(self):
        turns = trajectory(*run("mv pkg/parse.py pkg/_parse.py", ""), SUBMIT)
        self.assertIs(assess(turns, patch("pkg/_parse.py")).category, Category.UNVERIFIED)

    def test_deleting_a_product_file_is_a_product_edit(self):
        turns = trajectory(
            *run("rm pkg/ast/int.py", ""), *run("python -c 'import pkg'", SCRIPT_TRACEBACK), SUBMIT
        )
        self.assertIs(assess(turns, patch("pkg/ast/int.py")).category, Category.RAN_FAILING)

    def test_removing_scratch_files_after_a_run_keeps_the_evidence(self):
        turns = trajectory(
            *OPEN_CORE,
            *EDIT_CORE,
            *run("python reproduce.py", SCRIPT_OK),
            *run("rm reproduce.py", ""),
            SUBMIT,
        )
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.RAN_PASSING)

    def test_patch_edit_not_seen_in_trajectory(self):
        turns = trajectory(*OPEN_CORE, *run("python reproduce.py", SCRIPT_OK), SUBMIT)
        self.assertIs(assess(turns, patch("pkg/core.py")).category, Category.UNDETERMINED)

    def test_touched_tests_flag(self):
        result = assess(
            trajectory(*OPEN_CORE, *EDIT_CORE, SUBMIT), patch("pkg/core.py", "tests/test_core.py")
        )
        self.assertTrue(result.touched_tests)


class ClosingClaimTest(unittest.TestCase):
    def test_claim_comes_from_the_submit_step(self):
        claim = ai("submit", "DISCUSSION\nThe tests pass now. Submitting.")
        self.assertTrue(
            assess(trajectory(*OPEN_CORE, *EDIT_CORE, claim), patch("pkg/core.py")).claims_success
        )

    def test_hedged_claim(self):
        claim = ai("submit", "DISCUSSION\nThis should resolve the issue.")
        self.assertFalse(
            assess(trajectory(*OPEN_CORE, *EDIT_CORE, claim), patch("pkg/core.py")).claims_success
        )

    def test_empty_submit_discussion_falls_back_to_previous_step(self):
        turns = trajectory(
            *OPEN_CORE,
            ai("edit 3:3\n    return row\nend_of_edit", "DISCUSSION\nThe issue has been fixed."),
            obs(EDIT_OK, CORE),
            {"role": "ai", "text": "```\nsubmit\n```"},
        )
        self.assertTrue(assess(turns, patch("pkg/core.py")).claims_success)


if __name__ == "__main__":
    unittest.main()
