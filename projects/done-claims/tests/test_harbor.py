import json
import tempfile
import unittest
from pathlib import Path

from doneclaims.harbor import COMPLETED, job_meta, read_job, summarise

from .fixtures import PYTEST_PASS
from .test_atif import EDIT, MEMORY, agent, bash, document

STARTED = "2026-11-05T09:10:00Z"


def result(trial: str, task: str, reward: float | None, exception: str | None = None) -> dict:
    data = {
        "task_name": f"swe-bench/{task}",
        "trial_name": trial,
        "trial_uri": f"file:///jobs/smoke/{trial}",
        "task_id": {"org": "swe-bench", "name": task},
        "agent_info": {"name": "claude-code", "version": "2.1.318", "model_info": {"name": "gpt-oss-120b"}},
        "agent_result": {"n_input_tokens": 1200, "n_output_tokens": 300},
        "verifier_result": None if reward is None else {"rewards": {"reward": reward}},
        "exception_info": None,
        "agent_execution": {"started_at": STARTED, "finished_at": "2026-11-05T09:12:30Z"},
    }
    if exception:
        data["exception_info"] = {
            "exception_type": exception,
            "exception_message": "",
            "exception_traceback": "",
        }
    return data


def write_trial(job: Path, trial: str, data: dict, trajectory: dict | None) -> None:
    folder = job / trial
    (folder / "agent").mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps(data), encoding="utf-8")
    if trajectory is not None:
        (folder / "agent" / "trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")


class HarborJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.job = Path(self.tmp.name) / "smoke"
        self.job.mkdir()
        config = {
            "job_name": "smoke",
            "agents": [
                {
                    "name": "claude-code",
                    "model_name": "gpt-oss-120b",
                    "base_url": "http://model-server.invalid:8300",
                    "model_api_key_name": "ANTHROPIC_AUTH_TOKEN",
                    "model_api_format": "anthropic_messages",
                    "kwargs": {"version": "2.1.318"},
                    "env": {"ANTHROPIC_MODEL": "gpt-oss-120b"},
                }
            ],
            "datasets": [{"name": "swe-bench/swe-bench-verified", "ref": "sha256:abc", "n_tasks": 3}],
        }
        (self.job / "config.json").write_text(json.dumps(config), encoding="utf-8")
        verified = document(agent("", EDIT, bash("python -m pytest -q", PYTEST_PASS)), agent("Tests pass."))
        unverified = document(agent("", EDIT), agent("", bash("curl -s https://example.org/fix.diff", "")))
        memory_only = document(agent("", MEMORY), agent("This is not a bug."))
        write_trial(self.job, "task-a__1", result("task-a__1", "task-a", 1.0), verified)
        write_trial(self.job, "task-a__2", result("task-a__2", "task-a", 0.0), unverified)
        write_trial(self.job, "task-b__1", result("task-b__1", "task-b", 0.0), memory_only)
        write_trial(self.job, "task-c__1", result("task-c__1", "task-c", None, "AgentTimeoutError"), None)
        (self.job / "task-d__1").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows(self):
        rows = {r["trial"]: r for r in read_job(self.job)}
        self.assertEqual(sorted(rows), ["task-a__1", "task-a__2", "task-b__1", "task-c__1"])
        self.assertEqual(rows["task-a__1"]["category"], "ran_passing")
        self.assertTrue(rows["task-a__1"]["target"])
        self.assertEqual(rows["task-a__1"]["agent_seconds"], 150.0)
        self.assertEqual(rows["task-a__2"]["category"], "unverified")
        self.assertEqual(rows["task-a__2"]["remote_fetches"], 1)
        self.assertEqual(rows["task-b__1"]["category"], "no_product_change")
        self.assertEqual(rows["task-c__1"]["status"], "exception:AgentTimeoutError")
        self.assertEqual(rows["task-c__1"]["category"], "")
        self.assertEqual(rows["task-a__1"]["instance_id"], "task-a")

    def test_summary(self):
        summary = summarise(read_job(self.job), {})
        self.assertEqual(summary["status_counts"], {COMPLETED: 3, "exception:AgentTimeoutError": 1})
        done = summary["completed"]
        self.assertEqual(done["all"]["n"], 3)
        self.assertEqual(done["trials_with_remote_fetch"], 1)
        self.assertEqual(done["by_category"]["ran_passing"]["resolved"], 1)
        first = done["stratified_odds_ratios"]["within_instance"][0]
        self.assertEqual(first["comparison"], "unverified vs ran_passing")
        self.assertIsNone(first["odds_ratio"])
        self.assertEqual(
            done["sensitivity_without_remote_fetch"]["within_instance"][0]["informative_strata"], 0
        )

    def test_meta_leaves_out_endpoint_and_key_name(self):
        text = json.dumps(job_meta(self.job))
        self.assertNotIn("model-server.invalid", text)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", text)
        self.assertIn("2.1.318", text)


if __name__ == "__main__":
    unittest.main()
