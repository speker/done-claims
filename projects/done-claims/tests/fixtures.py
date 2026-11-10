"""Hand-written trajectories in the SWE-agent format; none of this text comes from the dataset."""

PROMPT = "ISSUE:\nparse() drops the last field.\n\n(Open file: n/a)\n(Current directory: /repo)\nbash-$"


def ai(command: str, discussion: str = "DISCUSSION\nNext step.") -> dict:
    return {"role": "ai", "text": f"{discussion}\n```\n{command}\n```"}


def obs(body: str, open_file: str = "n/a") -> dict:
    return {"role": "user", "text": f"{body}\n(Open file: {open_file})\n(Current directory: /repo)\nbash-$"}


def trajectory(*turns: dict) -> list[dict]:
    return [{"role": "system", "text": ""}, {"role": "user", "text": PROMPT}, *turns]


def patch(*paths: str) -> str:
    return "\n".join(
        f"diff --git a/{p} b/{p}\nindex 1111111..2222222 100644\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b"
        for p in paths
    )


CORE = "/repo/pkg/core.py"
EDIT_OK = "[File: /repo/pkg/core.py (40 lines total)]\n1:def parse(row):\nFile updated."
EDIT_REJECTED = (
    "Your proposed edit has introduced new syntax error(s). Please read this error message carefully.\n"
    "Your changes have NOT been applied."
)
SCRIPT_OK = "['a', 'b', 'c']\nScript completed successfully, no errors."
SCRIPT_TRACEBACK = (
    'Traceback (most recent call last):\n  File "reproduce.py", line 3\nIndexError: list index out of range'
)
PYTEST_FAIL = (
    "collected 4 items\n\ntests/test_core.py ..F.\n\n========= 1 failed, 3 passed in 0.21s ========="
)
PYTEST_PASS = "collected 4 items\n\ntests/test_core.py ....\n\n========= 4 passed in 0.19s ========="
