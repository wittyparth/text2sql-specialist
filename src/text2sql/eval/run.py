"""Run one model over one frozen eval set (see --help)."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..prompt import build_messages, extract_sql
from ..schema import canonicalize, load_context
from ..sqlexec import QueryResult, results_match, results_match_strict, run_select, safe_connect
from .client import ChatClient
from .errors import classify
from .score import summarize


class EvalError(RuntimeError):
    pass


def load_config(path: str | Path) -> dict:
    return yaml.safe_load(os.path.expandvars(Path(path).read_text()))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_items(set_cfg: dict) -> list[dict]:
    path = Path(set_cfg["path"])
    if sha256_file(path) != set_cfg["sha256"]:
        raise EvalError(
            f"{path} no longer matches the sha256 in configs/eval.yaml; the eval set is frozen"
        )
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def git_sha() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "unknown"


def score_item(item: dict, completion_text: str, conn, gold: QueryResult) -> dict:
    sql = extract_sql(completion_text)
    pred = run_select(conn, sql) if sql else None
    ordered = bool(item.get("order_matters"))
    executed = bool(pred and pred.ok)
    ok = executed and gold.ok and results_match(pred.rows, gold.rows, ordered)
    strict = executed and gold.ok and results_match_strict(pred.rows, gold.rows, ordered)
    return {
        "sql": sql,
        "executed": executed,
        "ok": bool(ok),
        "ok_strict": bool(strict),
        "failure": None if ok else classify(sql, pred, gold, ordered),
        "error_class": pred.error_class if pred and not pred.ok else None,
        "error": pred.message if pred and not pred.ok else None,
        "n_rows": len(pred.rows) if executed else None,
        "pred_rows": [list(r) for r in pred.rows[:20]] if executed else None,
    }


def evaluate(client: ChatClient, items: list[dict], set_cfg: dict, gen: dict, limit=None):
    shared_conn = shared_schema = None
    if set_cfg["db"] != "per_item":
        shared_conn = safe_connect(set_cfg["db"])
        shared_schema = canonicalize(shared_conn)
    rows = []
    for i, item in enumerate(items[:limit]):
        if shared_conn:
            conn, schema = shared_conn, shared_schema
        else:
            conn, schema = load_context(item["context_sqlite"]), item["schema_canonical"]
        gold = run_select(conn, item["sql"])
        if not gold.ok:
            raise EvalError(f"reference SQL fails for {item['id']}: {gold.message}")
        comp = client.complete(
            build_messages(schema, item["question"]),
            max_tokens=gen["max_tokens"],
            temperature=gen["temperature"],
            seed=gen.get("seed"),
        )
        base = {
            "id": item["id"],
            "difficulty": item["difficulty"],
            "question": item["question"],
            "gold_sql": item["sql"],
            "gold_rows": len(gold.rows),
            "raw": comp.text,
            "latency_s": comp.latency_s,
            "prompt_tokens": comp.prompt_tokens,
            "completion_tokens": comp.completion_tokens,
        }
        if comp.error:
            rows.append(base | {"status": "endpoint_error", "error": comp.error, "ok": False})
        else:
            rows.append(base | {"status": "scored"} | score_item(item, comp.text, conn, gold))
        if not shared_conn:
            conn.close()
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(items[:limit])}", flush=True)
    return rows


def run_eval(
    cfg: dict, model: str, set_name: str, limit: int | None = None, out_root: Path = Path("runs")
) -> tuple[Path, dict]:
    mcfg, scfg = cfg["models"][model], cfg["sets"][set_name]
    items = load_items(scfg)
    key = os.environ.get(mcfg["key_env"]) if mcfg.get("key_env") else None
    if mcfg.get("key_env") and not key:
        raise EvalError(f"{model} needs {mcfg['key_env']} in the environment")
    client = ChatClient(mcfg["url"], mcfg["model"], key, cfg.get("timeout_s", 120))
    if not client.healthy():
        raise EvalError(f"no server answering at {mcfg['url']} (is the model started?)")
    started = time.monotonic()
    rows = evaluate(client, items, scfg, cfg["generation"], limit)
    summary = summarize(rows) | {"wall_s": round(time.monotonic() - started, 1)}
    run_dir = out_root / f"{datetime.now(UTC):%Y%m%d-%H%M%S}_{model}_{set_name}"
    run_dir.mkdir(parents=True)
    (run_dir / "predictions.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "model": model,
                "model_cfg": {k: v for k, v in mcfg.items() if k != "key_env"},
                "set": set_name,
                "eval_sha256": scfg["sha256"],
                "generation": cfg["generation"],
                "parallel": cfg.get("parallel", 1),
                "limit": limit,
                "git_sha": git_sha(),
                "platform": platform.platform(),
                "finished_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )
    return run_dir, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m text2sql.eval.run", description=__doc__)
    ap.add_argument("--config", default="configs/eval.yaml")
    ap.add_argument("--model", required=True)
    ap.add_argument("--set", dest="set_name", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--allow-endpoint-errors", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if cfg.get("parallel", 1) != 1:
        print("warning: parallel != 1 breaks determinism; results won't compare", file=sys.stderr)
    try:
        run_dir, s = run_eval(cfg, args.model, args.set_name, args.limit)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    lo, hi = s["ex_ci"]
    print(
        f"{args.model} on {args.set_name}: EX {s['ex']:.1%} [{lo:.1%}, {hi:.1%}] n={s['n']}, "
        f"valid SQL {s['valid_sql_rate']:.1%}, p50 {s['latency_p50_s']:.2f}s -> {run_dir}"
    )
    if s["endpoint_errors"] and not args.allow_endpoint_errors:
        print(
            f"error: {s['endpoint_errors']} requests failed; scores exclude them", file=sys.stderr
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
