import unittest

from doneclaims.trajectory import open_file_marker, parse, split_action

from .fixtures import ai, obs, trajectory


class SplitActionTest(unittest.TestCase):
    def test_command_is_last_fenced_block(self):
        text = "DISCUSSION\nThe bug is here:\n```python\nrow[-1]\n```\nOpen it.\n```\nopen pkg/core.py\n```"
        discussion, command = split_action(text)
        self.assertEqual(command, "open pkg/core.py")
        self.assertIn("row[-1]", discussion)

    def test_language_tag_is_ignored(self):
        self.assertEqual(split_action("```bash\nls -la\n```")[1], "ls -la")

    def test_edit_body_with_inner_fences_is_one_command(self):
        text = (
            "DISCUSSION\nAdd a docstring example.\n```\nedit 10:12\n    doc = '''\n"
            "```python\nx = 1\n```\n'''\nend_of_edit\n```"
        )
        command = split_action(text)[1]
        self.assertTrue(command.startswith("edit 10:12"))
        self.assertTrue(command.endswith("end_of_edit"))

    def test_example_edit_in_discussion_does_not_hide_the_real_command(self):
        text = (
            "Earlier I ran:\n```\nedit 1:1\nx\nend_of_edit\n```\nNow run it.\n```\npython reproduce.py\n```"
        )
        self.assertEqual(split_action(text)[1], "python reproduce.py")

    def test_text_without_block_has_no_command(self):
        discussion, command = split_action("I think we are done.")
        self.assertIsNone(command)
        self.assertEqual(discussion, "I think we are done.")


class OpenFileTest(unittest.TestCase):
    def test_marker_values(self):
        self.assertEqual(open_file_marker("x\n(Open file: /repo/a.py)\n"), "/repo/a.py")
        self.assertEqual(open_file_marker("(Open file: n/a)"), "")
        self.assertIsNone(open_file_marker("no marker here"))

    def test_action_sees_file_opened_by_previous_observation(self):
        steps = parse(
            trajectory(
                ai("open pkg/core.py"),
                obs("[File: /repo/pkg/core.py (40 lines total)]", "/repo/pkg/core.py"),
                ai("edit 3:3\n    return row\nend_of_edit"),
                obs("File updated.", "/repo/pkg/core.py"),
            )
        )
        self.assertEqual([s.open_file for s in steps], [None, "/repo/pkg/core.py"])

    def test_na_marker_clears_open_file(self):
        steps = parse(
            trajectory(
                ai("open a.py"),
                obs("ok", "/repo/a.py"),
                ai("rm a.py"),
                obs("removed"),
                ai("ls"),
                obs("b.py"),
            )
        )
        self.assertEqual([s.open_file for s in steps], [None, "/repo/a.py", None])

    def test_trailing_action_without_observation_is_kept(self):
        steps = parse(trajectory(ai("ls"), obs("a.py"), ai("submit")))
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[-1].command, "submit")
        self.assertEqual(steps[-1].observation, "")


if __name__ == "__main__":
    unittest.main()
