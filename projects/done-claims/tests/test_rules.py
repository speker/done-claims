import unittest

from doneclaims.rules import (
    Action,
    Kind,
    Outcome,
    claims_success,
    classify,
    file_role,
    outcome,
    patch_files,
    targets_file,
    write_applied,
)

from .fixtures import EDIT_OK, EDIT_REJECTED, PYTEST_FAIL, PYTEST_PASS, SCRIPT_OK, SCRIPT_TRACEBACK, patch


class ClassifyTest(unittest.TestCase):
    def assertKind(self, command, kind, writes=()):
        action = classify(command, "/repo/pkg/core.py")
        self.assertEqual((action.kind, action.writes), (kind, tuple(writes)), command)

    def test_agent_tools(self):
        self.assertEqual(classify("submit", None), Action(Kind.SUBMIT))
        self.assertEqual(
            classify("edit 3:3\n    return row\nend_of_edit", "/repo/a.py"),
            Action(Kind.EDIT, ("/repo/a.py",), via_tool=True),
        )
        self.assertEqual(classify("edit 3:3\nx\nend_of_edit", None).writes, ())
        self.assertEqual(classify("create reproduce.py", None), Action(Kind.CREATE, ("reproduce.py",), True))
        self.assertKind("search_dir parse", Kind.OTHER)
        self.assertKind("open pkg/core.py", Kind.OTHER)

    def test_test_runners(self):
        for command in (
            "pytest -x tests/test_core.py",
            "python -m pytest -q",
            "cd /repo && python -m unittest tests.test_core",
            "timeout 120 python -m pytest tests",
            "python setup.py test",
            "python tests/runtests.py basic",
            "./runtests.py",
            "make test",
            "tox -e py39",
            "PYTHONPATH=. pytest tests",
        ):
            self.assertKind(command, Kind.TEST_RUN)

    def test_script_runs(self):
        for command in (
            "python reproduce.py",
            "python3 -c 'import pkg'",
            "python -m pkg.cli --help",
            "bash run.sh",
        ):
            self.assertKind(command, Kind.SCRIPT_RUN)
        self.assertKind("python", Kind.OTHER)

    def test_scripts_called_by_path(self):
        self.assertKind("chmod +x /tmp/check.py && /tmp/check.py", Kind.SCRIPT_RUN)
        self.assertKind("../tools/run.sh", Kind.SCRIPT_RUN)
        self.assertKind("/testbed/tests/runtests.py basic", Kind.TEST_RUN)
        self.assertKind("/usr/bin/env", Kind.OTHER)

    def test_shell_wrappers_are_unwrapped(self):
        self.assertKind('bash -lc "python /testbed/tests/runtests.py --verbosity 2"', Kind.TEST_RUN)
        self.assertKind("sh -c 'python reproduce.py'", Kind.SCRIPT_RUN)
        self.assertKind("bash -c 'echo x > pkg/core.py'", Kind.EDIT, ["pkg/core.py"])
        self.assertKind("bash -lc 'ls -la'", Kind.OTHER)
        self.assertKind("bash run.sh", Kind.SCRIPT_RUN)

    def test_installing_and_building_are_not_runs(self):
        for command in (
            "python -m pip install pytz",
            "python3 -m pip install -e . --quiet",
            "python -m venv .venv",
            "python setup.py build",
            "python setup.py develop",
            "pip install sqlparse",
        ):
            self.assertKind(command, Kind.OTHER)
        self.assertKind("python -m pip install pytz && python reproduce.py", Kind.SCRIPT_RUN)

    def test_static_checks_are_not_runs(self):
        self.assertKind("mypy pkg", Kind.STATIC_CHECK)
        self.assertKind("python -m flake8 pkg", Kind.STATIC_CHECK)

    def test_redirects_are_writes_but_keep_the_run(self):
        self.assertKind("python reproduce.py > out.txt 2>&1", Kind.SCRIPT_RUN, ["out.txt"])
        self.assertKind("pytest tests | tail -5", Kind.TEST_RUN)
        self.assertKind('python -c "print(1 > 0)"', Kind.SCRIPT_RUN)
        self.assertKind("echo 'x = 1' >> pkg/core.py", Kind.EDIT, ["pkg/core.py"])

    def test_sed_in_place_targets(self):
        self.assertKind("sed -i 's/a/b/' pkg/core.py", Kind.EDIT, ["pkg/core.py"])
        self.assertKind(
            "sed -i.bak -e 's/a/b/' pkg/core.py pkg/util.py", Kind.EDIT, ["pkg/core.py", "pkg/util.py"]
        )
        self.assertKind("sed 's/a/b/' pkg/core.py", Kind.OTHER)
        self.assertKind("sed -i 's/a/b/' pkg/core.py && python -m pytest -q", Kind.TEST_RUN, ["pkg/core.py"])

    def test_move_and_copy_destinations_are_writes(self):
        self.assertKind("mv pkg/old.py pkg/new.py", Kind.EDIT, ["pkg/new.py"])
        self.assertKind("cp -r template pkg/data", Kind.EDIT, ["pkg/data"])
        self.assertKind("git mv pkg/a.py pkg/_a.py", Kind.EDIT, ["pkg/_a.py"])
        self.assertKind("mv", Kind.OTHER)

    def test_deletions_are_writes(self):
        self.assertKind("rm pkg/ast/int.py", Kind.EDIT, ["pkg/ast/int.py"])
        self.assertKind("rm -f reproduce.py out.txt", Kind.EDIT, ["reproduce.py", "out.txt"])
        self.assertEqual(classify("rm -rf build && echo x > log.txt", None).deletes, ("build",))
        self.assertEqual(classify("echo x > log.txt", None).deletes, ())

    def test_navigation_and_unknown_shell(self):
        self.assertKind("ls -la", Kind.OTHER)
        self.assertKind("grep -rn 'def parse' .", Kind.OTHER)
        self.assertKind("", Kind.OTHER)


class WriteAppliedTest(unittest.TestCase):
    def test_tool_edit(self):
        edit = Action(Kind.EDIT, ("/repo/pkg/core.py",), via_tool=True)
        self.assertTrue(write_applied(edit, EDIT_OK))
        self.assertFalse(write_applied(edit, EDIT_REJECTED))
        self.assertFalse(write_applied(edit, "No file open. Use the `open` command first."))
        self.assertFalse(write_applied(Action(Kind.EDIT, (), via_tool=True), EDIT_OK))

    def test_tool_create(self):
        create = Action(Kind.CREATE, ("reproduce.py",), via_tool=True)
        self.assertTrue(write_applied(create, "[File: /repo/reproduce.py (1 lines total)]"))
        self.assertFalse(write_applied(create, "Error: File 'reproduce.py' already exists."))

    def test_shell_write(self):
        sed = Action(Kind.EDIT, ("pkg/core.py",))
        self.assertTrue(write_applied(sed, "Your command ran successfully and did not produce any output."))
        self.assertFalse(write_applied(sed, "sed: can't read pkg/core.py: No such file or directory"))

    def test_tool_edit_ignores_shell_error_text_inside_file_listing(self):
        edit = Action(Kind.EDIT, ("/repo/pkg/io.py",), via_tool=True)
        listing = "[File: /repo/pkg/io.py (9 lines total)]\n4:    raise OSError('No such file or directory')"
        self.assertTrue(write_applied(edit, listing))


class OutcomeTest(unittest.TestCase):
    def test_pytest_summaries(self):
        self.assertIs(outcome(Kind.TEST_RUN, PYTEST_PASS), Outcome.PASS)
        self.assertIs(outcome(Kind.TEST_RUN, PYTEST_FAIL), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "===== 1 error in 0.10s ====="), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "===== no tests ran in 0.01s ====="), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "== 2 passed, 1 warning in 0.50s =="), Outcome.PASS)
        self.assertIs(outcome(Kind.TEST_RUN, "== 5 passed in 61.20s (0:01:01) =="), Outcome.PASS)

    def test_quiet_pytest_summaries_without_bars(self):
        self.assertIs(outcome(Kind.TEST_RUN, "....\n44 passed, 32 warnings in 1.01s"), Outcome.PASS)
        self.assertIs(outcome(Kind.TEST_RUN, "F..\n1 failed, 2 passed in 0.50s"), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "s\n1 skipped in 0.01s"), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "Ran 4 tests in 0.01s\n\nOK"), Outcome.PASS)

    def test_last_pytest_summary_wins(self):
        text = PYTEST_FAIL + "\n\nrerun\n" + PYTEST_PASS
        self.assertIs(outcome(Kind.TEST_RUN, text), Outcome.PASS)

    def test_unittest_summaries(self):
        self.assertIs(outcome(Kind.TEST_RUN, "...\nRan 3 tests in 0.001s\n\nOK"), Outcome.PASS)
        self.assertIs(outcome(Kind.TEST_RUN, "Ran 3 tests in 0.002s\n\nFAILED (failures=1)"), Outcome.FAIL)
        self.assertIs(outcome(Kind.TEST_RUN, "Ran 0 tests in 0.000s\n\nOK"), Outcome.FAIL)

    def test_collection_error_without_summary(self):
        self.assertIs(
            outcome(Kind.TEST_RUN, "ImportError while loading conftest\n" + SCRIPT_TRACEBACK), Outcome.FAIL
        )

    def test_script_runs(self):
        self.assertIs(outcome(Kind.SCRIPT_RUN, SCRIPT_OK), Outcome.PASS)
        self.assertIs(outcome(Kind.SCRIPT_RUN, SCRIPT_TRACEBACK), Outcome.FAIL)
        self.assertIs(outcome(Kind.SCRIPT_RUN, "EXECUTION TIMED OUT"), Outcome.FAIL)
        self.assertIs(outcome(Kind.SCRIPT_RUN, "python: can't open file 'x.py'"), Outcome.FAIL)
        self.assertIs(outcome(Kind.SCRIPT_RUN, "['a', 'b']"), Outcome.UNKNOWN)
        silent = "Your command ran successfully and did not produce any output."
        self.assertIs(outcome(Kind.SCRIPT_RUN, silent), Outcome.UNKNOWN)


class PatchTest(unittest.TestCase):
    def test_patch_files(self):
        self.assertEqual(patch_files(patch("pkg/core.py", "reproduce.py")), ["pkg/core.py", "reproduce.py"])
        self.assertEqual(patch_files(""), [])
        self.assertEqual(patch_files(None), [])

    def test_file_roles(self):
        cases = {
            "reproduce.py": "scratch",
            "repro_issue_12.py": "scratch",
            "tests/test_core.py": "test",
            "pkg/tests/helpers.py": "test",
            "test_issue.py": "test",
            "pkg/core_test.py": "test",
            "conftest.py": "test",
            "docs/index.rst": "docs",
            "CHANGELOG.md": "docs",
            "pkg/core.py": "product",
            "setup.py": "product",
            "pkg.egg-info/PKG-INFO": "artifact",
            ".eggs/babel-2.16.0-py3.9.egg/babel/core.py": "artifact",
            "pkg/__pycache__/core.cpython-39.pyc": "artifact",
            "pkg/core.pyc": "artifact",
            "eggs/recipes.py": "product",
            "=3.6.0": "artifact",
            "tmp_myapp/models.py": "scratch",
            "tmpapp/models.py": "scratch",
            "sandbox2/run.py": "scratch",
            "temp/check.py": "scratch",
            "dvc/repo/reproduce.py": "product",
            "django/views/debug.py": "product",
            "sphinx/util/template.py": "product",
            "templates/base.py": "product",
            "tests/issue_322/reproduce.py": "test",
            "docs/source/debug.rst": "docs",
        }
        for path, role in cases.items():
            self.assertEqual(file_role(path), role, path)

    def test_targets_file_respects_path_boundaries(self):
        self.assertTrue(targets_file("/repo/pkg/core.py", "pkg/core.py"))
        self.assertTrue(targets_file("pkg/core.py", "pkg/core.py"))
        self.assertFalse(targets_file("/repo/xpkg/core.py", "pkg/core.py"))
        self.assertFalse(targets_file("/repo/pkg/core.pyc", "pkg/core.py"))


class ClaimsTest(unittest.TestCase):
    def test_asserted_success(self):
        for text in (
            "The output confirms the fix works. Let's submit.",
            "The issue has been fixed.",
            "The tests pass now, so I will submit.",
            "The script no longer raises an error, confirming the fix.",
        ):
            self.assertTrue(claims_success(text), text)

    def test_hedged_negated_or_absent(self):
        for text in (
            "This should fix the issue. Let's submit.",
            "This suggests the bug has been fixed.",
            "We have not verified the fix, but the change is small.",
            "I am unable to run the tests here; submitting the change.",
            "Let's submit the changes.",
            "",
        ):
            self.assertFalse(claims_success(text), text)

    def test_one_unhedged_sentence_is_enough(self):
        self.assertTrue(claims_success("It might be slow. The tests pass now."))


if __name__ == "__main__":
    unittest.main()
