"""Build reports/eval_results.{md,json} and figures from the latest full run of each model/set."""

import argparse
import json
from pathlib import Path

from .errors import shift_table
from .run import git_sha
from .score import mcnemar_exact, paired_bootstrap

MODEL_ORDER = ["base-q4", "ft-q4", "ft-q8", "ft-f16", "base-f16", "frontier"]
LABELS = {
    "base-q4": "Qwen2.5-Coder-1.5B base, Q4_K_M",
    "ft-q4": "**Fine-tuned, Q4_K_M** (shipped)",
    "ft-q8": "Fine-tuned, Q8_0",
    "ft-f16": "Fine-tuned, F16",
    "base-f16": "Base, F16",
    "frontier": "Frontier API (OpenRouter)",
}
SETS = {"gretel_heldout": "Gretel held-out domains", "chinook": "Chinook (11 tables)"}


def load_runs(runs_dir: Path) -> dict[tuple[str, str], dict]:
    """Latest complete (no --limit) run per (model, set); directory names sort by timestamp."""
    found = {}
    for d in sorted(runs_dir.glob("*_*_*")):
        try:
            cfg = json.loads((d / "config.json").read_text())
            summary = json.loads((d / "summary.json").read_text())
        except (OSError, ValueError):
            continue
        if cfg.get("limit") is None:
            rows = [json.loads(x) for x in (d / "predictions.jsonl").read_text().splitlines()]
            found[(cfg["model"], cfg["set"])] = {
                "dir": d.name,
                "cfg": cfg,
                "s": summary,
                "rows": rows,
            }
    return found


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def ex_cell(s: dict) -> str:
    lo, hi = s["ex_ci"]
    return f"{pct(s['ex'])} [{pct(lo)}, {pct(hi)}] (n={s['n']})"


def headline(runs: dict) -> list[str]:
    models = [m for m in MODEL_ORDER if any((m, s) in runs for s in SETS)]
    head = "| Model | " + " | ".join(f"{t} EX" for t in SETS.values())
    head += " | Valid SQL (Chinook) | Dialect errors (Chinook) | p50 latency (Metal) |"
    lines = [head, "|" + "---|" * (len(SETS) + 4)]
    for m in models:
        cells = [ex_cell(runs[(m, s)]["s"]) if (m, s) in runs else "n/a" for s in SETS]
        ck = runs.get((m, "chinook"))
        extra = (
            [
                pct(ck["s"]["valid_sql_rate"]),
                pct(ck["s"]["dialect_error_rate"]),
                f"{ck['s']['latency_p50_s']:.2f} s",
            ]
            if ck
            else ["n/a"] * 3
        )
        lines.append(f"| {LABELS[m]} | " + " | ".join(cells + extra) + " |")
    return lines


def paired(runs: dict, base: str, tuned: str) -> tuple[list[str], dict]:
    lines = [
        "| Set | Δ EX | 95% CI | McNemar p | base ✓ / tuned ✗ | base ✗ / tuned ✓ |",
        "|---|---|---|---|---|---|",
    ]
    out = {}
    for sname, title in SETS.items():
        if (base, sname) not in runs or (tuned, sname) not in runs:
            continue
        a = {r["id"]: r["ok"] for r in runs[(base, sname)]["rows"] if r["status"] == "scored"}
        b = {r["id"]: r["ok"] for r in runs[(tuned, sname)]["rows"] if r["status"] == "scored"}
        ids = sorted(set(a) & set(b))
        av, bv = [a[i] for i in ids], [b[i] for i in ids]
        diff, lo, hi = paired_bootstrap(av, bv)
        only_a = sum(x and not y for x, y in zip(av, bv, strict=True))
        only_b = sum(y and not x for x, y in zip(av, bv, strict=True))
        p = mcnemar_exact(only_a, only_b)
        out[sname] = {
            "diff": diff,
            "ci": [lo, hi],
            "p": p,
            "base_only": only_a,
            "tuned_only": only_b,
        }
        lines.append(
            f"| {title} (n={len(ids)}) | {100 * diff:+.1f} pts | "
            f"[{100 * lo:+.1f}, {100 * hi:+.1f}] | {p:.4f} | {only_a} | {only_b} |"
        )
    return lines, out


def per_difficulty(runs: dict, base: str, tuned: str) -> list[str]:
    lines = []
    for sname, title in SETS.items():
        if (base, sname) not in runs or (tuned, sname) not in runs:
            continue
        bd, td = (
            runs[(base, sname)]["s"]["by_difficulty"],
            runs[(tuned, sname)]["s"]["by_difficulty"],
        )
        lines += [f"**{title}**", "", "| Difficulty | n | Base | Fine-tuned |", "|---|---|---|---|"]
        lines += [
            f"| {k} | {bd[k]['n']} | {pct(bd[k]['ex'])} | {pct(td[k]['ex'])} |"
            for k in bd
            if k in td
        ]
        lines.append("")
    return lines


def _failures(runs: dict, model: str, sname: str) -> list[str]:
    return [r["failure"] for r in runs[(model, sname)]["rows"] if r.get("failure")]


def error_shift(runs: dict, base: str, tuned: str) -> list[str]:
    lines = [
        "| Failure class | " + " | ".join(f"{t} (base → tuned)" for t in SETS.values()) + " |",
        "|---|" + "---|" * len(SETS),
    ]
    tables = {}
    for sname in SETS:
        if (base, sname) in runs and (tuned, sname) in runs:
            tables[sname] = shift_table(_failures(runs, base, sname), _failures(runs, tuned, sname))
    for c in sorted({c for t in tables.values() for c in t}):
        cells = [
            f"{tables[s][c][0]} → {tables[s][c][1]}" if s in tables and c in tables[s] else "0 → 0"
            for s in SETS
        ]
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    return lines


def examples(runs: dict, base: str, tuned: str, n_win: int = 10, n_loss: int = 5) -> list[str]:
    out = []
    for sname, title in SETS.items():
        if (base, sname) not in runs or (tuned, sname) not in runs:
            continue
        b = {r["id"]: r for r in runs[(base, sname)]["rows"] if r["status"] == "scored"}
        t = {r["id"]: r for r in runs[(tuned, sname)]["rows"] if r["status"] == "scored"}
        wins = [i for i in sorted(b) if i in t and not b[i]["ok"] and t[i]["ok"]]
        losses = [i for i in sorted(b) if i in t and b[i]["ok"] and not t[i]["ok"]]
        for label, ids in (
            ("fine-tuned fixed", wins[:n_win]),
            ("fine-tuned broke", losses[:n_loss]),
        ):
            out += [
                f"**{title}: {label}** ({len(wins) if 'fixed' in label else len(losses)} total)",
                "",
            ]
            for i in ids:
                out += [
                    f"- _{b[i]['question']}_",
                    f"  - reference: `{b[i]['gold_sql']}`",
                    f"  - base: `{b[i]['sql']}`",
                    f"  - tuned: `{t[i]['sql']}`",
                ]
            out.append("")
    return out


def quantization(runs: dict) -> list[str]:
    lines = [
        "| Variant | " + " | ".join(f"{t} EX" for t in SETS.values()) + " |",
        "|---|" + "---|" * len(SETS),
    ]
    for m in ("ft-f16", "ft-q8", "ft-q4"):
        if any((m, s) in runs for s in SETS):
            lines.append(
                f"| {LABELS[m]} | "
                + " | ".join(ex_cell(runs[(m, s)]["s"]) if (m, s) in runs else "n/a" for s in SETS)
                + " |"
            )
    return lines if len(lines) > 2 else []


def figures(runs: dict, base: str, tuned: str, out_dir: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    for sname, title in SETS.items():
        if (base, sname) not in runs or (tuned, sname) not in runs:
            continue
        bd, td = (
            runs[(base, sname)]["s"]["by_difficulty"],
            runs[(tuned, sname)]["s"]["by_difficulty"],
        )
        keys = [k for k in bd if k in td]
        fig, ax = plt.subplots(figsize=(7, 3.5))
        xs = range(len(keys))
        ax.bar([x - 0.2 for x in xs], [100 * bd[k]["ex"] for k in keys], 0.4, label="base")
        ax.bar([x + 0.2 for x in xs], [100 * td[k]["ex"] for k in keys], 0.4, label="fine-tuned")
        ax.set_xticks(list(xs), [f"{k}\nn={bd[k]['n']}" for k in keys])
        ax.set_ylabel("execution accuracy (%)")
        ax.set_title(title)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / f"difficulty_{sname}.png", dpi=130)
        plt.close(fig)


def build(runs_dir: Path, out_dir: Path, base: str = "base-q4", tuned: str = "ft-q4") -> None:
    runs = load_runs(runs_dir)
    if not runs:
        raise SystemExit(f"no complete runs in {runs_dir}")
    pair_lines, pair_json = paired(runs, base, tuned)
    md = [
        "# Evaluation results",
        "",
        "_Generated by `python -m text2sql.eval.compare`; do not edit by hand._",
        "",
        f"git `{git_sha()}`. Every model was reached through the same OpenAI-compatible client, "
        "one "
        "request at a time, greedy decoding, same prompt builder and SQL extractor. Runs: "
        + ", ".join(f"`{v['dir']}`" for v in runs.values()),
        "",
        "## Headline",
        "",
        *headline(runs),
        "",
        "EX = execution accuracy (normalized result match), with a 95% bootstrap interval.",
        "",
        f"## Paired comparison: {tuned} vs {base}",
        "",
        *pair_lines,
        "",
        "## Per difficulty",
        "",
        *per_difficulty(runs, base, tuned),
    ]
    q = quantization(runs)
    if q:
        md += ["## Quantization cost", "", *q, ""]
    md += [
        "## Error-class shift",
        "",
        *error_shift(runs, base, tuned),
        "",
        "## Qualitative examples",
        "",
        *examples(runs, base, tuned),
        "## Limitations",
        "",
        "- Training and Gretel evaluation data are synthetic; Chinook (n=100) has wide intervals.",
        "- SQLite SELECT only, single turn, no clarifying questions.",
        "- Latency here is Apple-silicon Metal; the CPU-only numbers are in the README.",
        "",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval_results.md").write_text("\n".join(md))
    (out_dir / "eval_results.json").write_text(
        json.dumps(
            {
                "runs": {
                    f"{m}/{s}": {"dir": v["dir"], "summary": v["s"]} for (m, s), v in runs.items()
                },
                "paired": pair_json,
            },
            indent=2,
        )
    )
    figures(runs, base, tuned, out_dir / "figures")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--base", default="base-q4")
    ap.add_argument("--tuned", default="ft-q4")
    a = ap.parse_args()
    build(Path(a.runs), Path(a.out), a.base, a.tuned)
    print(f"wrote {a.out}/eval_results.md")


if __name__ == "__main__":
    main()
