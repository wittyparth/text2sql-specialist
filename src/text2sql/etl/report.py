"""Builds reports/data_quality.{json,md} (and figures) from the final records. Never hand-edited."""

import hashlib
import json
import platform
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from .manifest import atomic_write
from .records import Record

# drop reasons grouped by the stage that produces them, in funnel order
STAGE_REASONS = {
    "mapped": {"EMPTY_FIELD"},
    "in scope (SELECT)": {"NOT_SELECT", "MULTI_STATEMENT"},
    "context loaded": {"CTX_LOAD_FAILED"},
    "executes": {
        "SQL_NO_SUCH_COLUMN",
        "SQL_NO_SUCH_TABLE",
        "SQL_NO_SUCH_FUNCTION",
        "SQL_AMBIGUOUS",
        "SQL_SYNTAX",
        "SQL_OTHER",
        "TIMEOUT",
    },
    "passes filters": {"QUESTION_LENGTH", "SQL_LENGTH", "TOKEN_BUDGET", "TIME_RELATIVE_HARDCODED"},
    "after dedup": {"DUP_EXACT", "DUP_CONFLICTING_LABEL", "DUP_CROSS_SOURCE"},
    "after leakage guard": {"LEAKAGE_OVERLAP"},
}


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def funnel(records: list[Record], source: str) -> dict[str, int]:
    recs = [r for r in records if r.source == source]
    reasons = Counter(r.drop_reason for r in recs if r.status == "dropped")
    out = {"extracted": len(recs)}
    left = len(recs)
    for stage, codes in STAGE_REASONS.items():
        if stage == "executes":
            # rec.sql is only set once execution succeeded, so it marks the rows that ran
            ran = [r for r in recs if r.sql]
            out["executes (raw)"] = sum(1 for r in ran if not r.repaired)
            out["executes (repaired)"] = sum(1 for r in ran if r.repaired)
            left = len(ran)
            continue
        left -= sum(reasons[c] for c in codes)
        out[stage] = left
    return out


def drop_reason_table(records: list[Record], total: int) -> list[dict]:
    by_code = defaultdict(list)
    for r in sorted(records, key=lambda r: r.id):
        if r.status == "dropped":
            by_code[r.drop_reason].append(r)
    rows = []
    for code, recs in sorted(by_code.items(), key=lambda kv: -len(kv[1])):
        rows.append(
            {
                "code": code,
                "count": len(recs),
                "pct": round(100 * len(recs) / total, 2),
                "examples": [
                    {"question": r.question[:140], "sql": r.sql_raw[:200], "detail": r.drop_detail}
                    for r in recs[:3]
                ],
            }
        )
    return rows


def repair_stats(records: list[Record]) -> dict:
    fixed = [r for r in records if r.repaired and r.sql]
    by_dialect = Counter(r.repair_dialect or "unknown" for r in fixed)
    funcs: Counter = Counter()
    call = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    for r in fixed:
        if r.sql != r.sql_raw:
            before = Counter(m.lower() for m in call.findall(r.sql_raw))
            after = Counter(m.lower() for m in call.findall(r.sql))
            for name in before:
                if name not in after:
                    funcs[name] += 1
    return {
        "recovered": len(fixed),
        "by_dialect": dict(by_dialect),
        "top_rewritten_functions": funcs.most_common(10),
    }


def distributions(records: list[Record]) -> dict:
    kept = [r for r in records if r.status == "kept"]
    cx = defaultdict(Counter)
    for r in kept:
        cx[r.split or "none"][r.complexity_derived] += 1
    dom = Counter(r.domain for r in kept if r.source == "gretel")
    bins = [0, 100, 200, 300, 500, 800, 1200, 1500, 1800, 10**9]
    hist = Counter()
    for r in records:
        if r.sampled and r.split == "train":
            for lo, hi in zip(bins, bins[1:], strict=False):
                if lo <= r.n_tokens < hi:
                    hist[f"{lo}-{hi if hi < 10**9 else 'inf'}"] += 1
    return {
        "complexity_by_split": {k: dict(v) for k, v in cx.items()},
        "rows_per_domain": dict(sorted(dom.items())),
        "train_token_histogram": dict(hist),
    }


def build_report(
    records: list[Record],
    *,
    run_id: str,
    config: dict,
    manifest: dict,
    split_info: dict,
    stage_stats: list[dict],
    incremental: dict,
    eval_counts: dict,
    aug_stats: dict,
    mix_counts: dict,
    chinook_tokens: int | None,
) -> dict:
    import pyarrow
    import sqlglot

    total = len(records)
    sources = sorted({r.source for r in records})
    f = {s: funnel(records, s) for s in sources}
    for s in sources:
        srcrecs = [r for r in records if r.source == s]
        for split in ("train", "val", "test_heldout"):
            f[s][f"split: {split}"] = sum(1 for r in srcrecs if r.split == split)
        f[s]["sampled"] = sum(1 for r in srcrecs if r.sampled and r.split == "train")
    attempted = aug_stats.get("attempted", 0)
    train_n = mix_counts.get("train", 0)
    return {
        "header": {
            "run_id": run_id,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "python": platform.python_version(),
            "sqlglot": sqlglot.__version__,
            "pyarrow": pyarrow.__version__,
            "config_sha": hashlib.sha256(
                json.dumps(config, sort_keys=True, default=str).encode()
            ).hexdigest()[:12],
        },
        "revisions": {n: s["revision"] for n, s in config["sources"].items()},
        "files": manifest.get("files", {}),
        "funnel": f,
        "drop_reasons": drop_reason_table(records, total),
        "repair": repair_stats(records),
        "split": split_info,
        "distributions": distributions(records),
        "eval": eval_counts,
        "augment": {
            **aug_stats,
            "share_pct": round(100 * aug_stats.get("augmented", 0) / train_n, 1) if train_n else 0,
            "attempted_share_pct": round(100 * attempted / train_n, 1) if train_n else 0,
        },
        "mix": mix_counts,
        "chinook_prompt_tokens": chinook_tokens,
        "stages": stage_stats,
        "incremental": incremental,
    }


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(rep: dict) -> str:
    h = rep["header"]
    lines = [
        "# Data quality report",
        "",
        "_Generated by `python -m text2sql.etl.pipeline`; do not edit by hand._",
        "",
        f"- run `{h['run_id']}` at {h['generated_at']}, git `{h['git_sha']}`, "
        f"config `{h['config_sha']}`",
        f"- python {h['python']}, sqlglot {h['sqlglot']}, pyarrow {h['pyarrow']}",
        "- source revisions: "
        + ", ".join(f"{k} `{str(v)[:12]}`" for k, v in rep["revisions"].items()),
        "",
        "## 1. Funnel",
        "",
    ]
    f = rep["funnel"]
    sources = list(f)
    steps = list(f[sources[0]])
    rows = []
    for step in steps:
        row = [step]
        for s in sources:
            n = f[s].get(step, 0)
            base = f[s]["extracted"] or 1
            row.append(f"{n:,} ({100 * n / base:.1f}%)")
        rows.append(row)
    lines += [_table(["Stage"] + sources, rows), "", "Percentages are of rows extracted.", ""]
    lines += ["## 2. Drop reasons", ""]
    lines += [
        _table(
            ["Code", "Rows", "% of extracted"],
            [[d["code"], f"{d['count']:,}", f"{d['pct']}%"] for d in rep["drop_reasons"]],
        )
    ]
    lines += ["", "Three real examples per code:", ""]
    for d in rep["drop_reasons"]:
        lines.append(f"**{d['code']}**")
        for ex in d["examples"]:
            detail = f" -> `{ex['detail']}`" if ex["detail"] else ""
            lines.append(f"- {ex['question']}  \n  `{ex['sql']}`{detail}")
        lines.append("")
    r = rep["repair"]
    lines += [
        "## 3. Repairs",
        "",
        f"Rows recovered by sqlglot dialect repair: **{r['recovered']:,}** "
        f"({', '.join(f'{k}: {v:,}' for k, v in r['by_dialect'].items())}).",
        "",
        "Most frequently rewritten functions: "
        + ", ".join(f"`{n}` ({c})" for n, c in r["top_rewritten_functions"]),
        "",
    ]
    s = rep["split"]
    lines += [
        "## 4. Split integrity",
        "",
        f"- test_heldout domains ({len(s['domains']['test_heldout'])}): "
        + ", ".join(s["domains"]["test_heldout"]),
        f"- val domains ({len(s['domains']['val'])}): " + ", ".join(s["domains"]["val"]),
        f"- train domains: {len(s['domains']['train'])}",
        "- domain overlap between splits: **none** (asserted in code)",
        f"- leakage guard: **{s['leakage_removed']}** train/val rows removed",
        "",
    ]
    e = rep["eval"]
    lines += ["## 5. Eval and training sets", ""]
    lines += [
        _table(
            ["Set", "n", "By class"],
            [
                [k, v["n"], ", ".join(f"{c}: {n}" for c, n in sorted(v["by_class"].items()))]
                for k, v in e.items()
            ],
        ),
        "",
    ]
    a = rep["augment"]
    lines += [
        f"Training mix: {rep['mix']}. Distractor augmentation: {a.get('augmented', 0):,} rows "
        f"augmented ({a['share_pct']}% of the training mix), {a.get('AUG_FAILED', 0)} failed "
        "re-execution and were kept un-augmented.",
        "",
    ]
    if rep.get("chinook_prompt_tokens"):
        lines += [
            f"Chinook prompt size for comparison: {rep['chinook_prompt_tokens']:,} tokens.",
            "",
        ]
    lines += ["## 6. Stages", ""]
    lines += [
        _table(
            ["Stage", "in", "out", "seconds"],
            [[x["name"], x["n_in"], x["n_out"], x["seconds"]] for x in rep["stages"]],
        )
    ]
    inc = rep["incremental"]
    lines += ["", f"Incremental: new={inc['new']}, skipped={inc['skipped']}", ""]
    lines += [
        "## 7. Figures",
        "",
        "![complexity](figures/complexity_by_split.png)",
        "![tokens](figures/token_lengths.png)",
        "![domains](figures/rows_per_domain.png)",
        "",
    ]
    return "\n".join(lines)


def write_figures(rep: dict, out_dir: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    d = rep["distributions"]

    fig, ax = plt.subplots(figsize=(7, 3.5))
    classes = sorted({c for v in d["complexity_by_split"].values() for c in v})
    splits = [s for s in ("train", "val", "test_heldout") if s in d["complexity_by_split"]]
    width = 0.8 / max(len(splits), 1)
    for i, sp in enumerate(splits):
        tot = sum(d["complexity_by_split"][sp].values()) or 1
        ax.bar(
            [x + i * width for x in range(len(classes))],
            [100 * d["complexity_by_split"][sp].get(c, 0) / tot for c in classes],
            width,
            label=sp,
        )
    ax.set_xticks([x + width for x in range(len(classes))], classes, rotation=30, ha="right")
    ax.set_ylabel("% of split")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "complexity_by_split.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.5))
    hist = d["train_token_histogram"]
    ax.bar(list(hist), list(hist.values()))
    ax.set_xlabel("prompt + answer tokens (training mix)")
    ax.set_ylabel("rows")
    if rep.get("chinook_prompt_tokens"):
        ax.set_title(f"Chinook prompt: {rep['chinook_prompt_tokens']:,} tokens")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(out_dir / "token_lengths.png", dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.hist(list(d["rows_per_domain"].values()), bins=15)
    ax.set_xlabel("kept rows per Gretel domain")
    ax.set_ylabel("domains")
    fig.tight_layout()
    fig.savefig(out_dir / "rows_per_domain.png", dpi=130)
    plt.close(fig)
    return True


def write_report(rep: dict, reports_dir: Path) -> None:
    atomic_write(reports_dir / "data_quality.json", json.dumps(rep, indent=2, default=str))
    write_figures(rep, reports_dir / "figures")
    atomic_write(reports_dir / "data_quality.md", render_markdown(rep))
