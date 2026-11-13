import json

from text2sql.eval.compare import build, load_runs
from text2sql.eval.score import summarize


def fake_run(root, ts, model, sname, oks, limit=None):
    rows = [
        {
            "id": f"i{k}",
            "status": "scored",
            "difficulty": "easy" if k % 2 else "hard",
            "ok": ok,
            "ok_strict": ok,
            "executed": True,
            "failure": None if ok else "WRONG_VALUES",
            "latency_s": 0.4,
            "completion_tokens": 10,
            "question": f"q{k}",
            "gold_sql": "SELECT 1",
            "sql": "SELECT 1" if ok else "SELECT 2",
        }
        for k, ok in enumerate(oks)
    ]
    d = root / f"{ts}_{model}_{sname}"
    d.mkdir()
    (d / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "summary.json").write_text(json.dumps(summarize(rows)))
    (d / "config.json").write_text(json.dumps({"model": model, "set": sname, "limit": limit}))


def test_report_contains_paired_stats_and_skips_partial_runs(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "out"
    runs.mkdir()
    base = [True] * 20 + [False] * 20
    tuned = [True] * 30 + [False] * 10
    for sname in ("chinook", "gretel_heldout"):
        fake_run(runs, "20260101-000000", "base-q4", sname, base)
        fake_run(runs, "20260101-000001", "ft-q4", sname, tuned)
    fake_run(runs, "20260102-000000", "ft-q4", "chinook", [True] * 5, limit=5)  # ignored
    assert load_runs(runs)[("ft-q4", "chinook")]["s"]["n"] == 40
    build(runs, out)
    md = (out / "eval_results.md").read_text()
    assert "(n=40)" in md and "McNemar" in md and "+25.0 pts" in md
    assert "WRONG_VALUES | 20 → 10" in md
    data = json.loads((out / "eval_results.json").read_text())
    assert (
        data["paired"]["chinook"]["tuned_only"] == 10
        and data["paired"]["chinook"]["base_only"] == 0
    )
