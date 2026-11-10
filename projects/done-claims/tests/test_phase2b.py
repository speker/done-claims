import csv
import tempfile
import unittest
from pathlib import Path

from doneclaims.harbor import FIELDS
from doneclaims.phase2b import analyse, load, stage2_issues, unverified_share
from doneclaims.power import choose_k, simulate, summarise
from doneclaims.power import load as load_power


def row(trial: str, issue: str, category: str, resolved: bool, status: str = "completed") -> dict:
    values = dict.fromkeys(FIELDS, "")
    values.update(
        trial=trial,
        instance_id=issue,
        status=status,
        target=str(resolved),
        category=category,
        claims_success="False",
        tests_after_edit="0",
        remote_fetches="0",
        last_outcome="unknown",
    )
    return values


def write(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


class Phase2bTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        stage1 = [
            row("a1", "a", "unverified", False),
            row("a2", "a", "ran_passing", True),
            row("a3", "a", "ran_failing", True),
            row("b1", "b", "ran_passing", True),
            row("b2", "b", "ran_passing", False),
            row("b3", "b", "no_product_change", False),
            row("c1", "c", "unverified", True),
            row("c2", "c", "ran_passing", False),
            row("c3", "c", "ran_passing", False, status="exception:AgentTimeoutError"),
        ]
        stage2 = [
            row("a4", "a", "unverified", False),
            row("a5", "a", "ran_passing", True),
            row("c4", "c", "unverified", False),
            row("c5", "c", "ran_passing", True),
            row("b4", "b", "unverified", False),
        ]
        self.stage1 = write(base / "s1.csv", stage1)
        self.stage2 = write(base / "s2.csv", stage2)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stage1_gate_and_issue_set(self):
        rows = load(self.stage1, 1)
        self.assertEqual(len(rows), 8)
        self.assertAlmostEqual(unverified_share(rows), 2 / 7)
        self.assertEqual(stage2_issues(rows), ["a", "c"])

    def test_pooled_h1_uses_only_stage2_issues(self):
        report = analyse(load(self.stage1, 1), load(self.stage2, 2))
        self.assertTrue(report["gate"]["stage2_runs"])
        self.assertEqual(report["pooled"]["issues"], 2)
        self.assertEqual(report["stage2_issues_outside_set"], ["b"])
        self.assertEqual(report["h1"]["informative_issues"], 2)
        self.assertLess(report["h1"]["odds_ratio"], 1)

    def test_power_simulation_is_seeded(self):
        issues = load_power(self.stage1)
        first = simulate(issues, 4, 0.68, 20, seed=1)
        self.assertEqual(first, simulate(issues, 4, 0.68, 20, seed=1))
        summary = summarise(first)
        self.assertGreaterEqual(summary["within_target"], 0.0)
        self.assertLessEqual(summary["within_target"], 1.0)

    def test_choose_k_falls_back_to_the_cap(self):
        table = {k: {"within_target": 0.5} for k in (2, 4, 6, 8, 10, 12)}
        self.assertEqual(choose_k(table), 12)
        table[6]["within_target"] = 0.95
        self.assertEqual(choose_k(table), 6)


if __name__ == "__main__":
    unittest.main()
