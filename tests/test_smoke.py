"""Smoke test on a tiny synthetic fixture. No API calls."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


def run(*args):
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


class Smoke(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = run("period_end_check.report", str(FIX), "--title", "fixture", "--out-dir", d)
            self.assertIn("lower in 3/3", out)
            self.assertTrue((Path(d) / "report.html").read_text().startswith("<!doctype html>"))
            self.assertIn("API cost of both arms: $0.01", (Path(d) / "report.md").read_text())

    def test_drift_from_corner_shop(self):
        with tempfile.TemporaryDirectory() as d:
            for arm in ("seen", "hidden"):
                rows = run("period_end_check.drift", "--from-corner-shop", str(FIX / f"out_{arm}"))
                (Path(d) / f"{arm}.jsonl").write_text(rows)
                first = json.loads(rows.splitlines()[0])
                self.assertEqual(first["n_steps"], 13)
            single = run("period_end_check.drift", str(Path(d) / "seen.jsonl"), "--k", "3")
            self.assertIn("| purchase_order | 3 | 3 (100%)", single)
            cmp_ = run("period_end_check.drift", "--compare", str(Path(d) / "hidden.jsonl"),
                       str(Path(d) / "seen.jsonl"), "--labels", "hidden", "seen")
            self.assertIn("| purchase_order | 0/3 (0%) | 3/3 (100%) | +100 pts", cmp_)

    def test_drift_k_frac(self):
        rows = [{"episode_id": "e", "step": s, "n_steps": 100, "action_type": "post_entry"} for s in range(90)]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in rows))
            out = run("period_end_check.drift", str(p), "--k-frac", "0.1")
            self.assertIn("| post_entry | 1 | 1 (100%)", out)


if __name__ == "__main__":
    unittest.main()
