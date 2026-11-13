"""Gradio demo: ask a question, see the base and fine-tuned model side by side."""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import gradio as gr

from ..eval.client import ChatClient
from .core import Backend, Outcome, compare
from .databases import CustomSchemaError, Preset, load_custom, load_presets
from .warmup import WarmupState, start_in_background

ROOT = Path(__file__).resolve().parents[3]
CUSTOM = "custom"
MAX_QUESTION = 500
log = logging.getLogger("app")


@dataclass
class Settings:
    base_url: str
    ft_url: str
    base_model: str
    ft_model: str
    sequential: bool
    max_rows: int
    timeout_s: float
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            base_url=e("LLM_BASE_URL", "http://127.0.0.1:8081/v1"),
            ft_url=e("LLM_FT_URL", "http://127.0.0.1:8082/v1"),
            base_model=e("LLM_BASE_MODEL", "base"),
            ft_model=e("LLM_FT_MODEL", "finetuned"),
            sequential=e("APP_SEQUENTIAL", "0") == "1",
            max_rows=int(e("APP_MAX_ROWS", "50")),
            timeout_s=float(e("REQUEST_TIMEOUT_S", "60")),
            host=e("APP_HOST", "127.0.0.1"),
            port=int(e("APP_PORT", "7860")),
        )


def render(o: Outcome) -> str:
    if not o.available:
        return "**Model unavailable.** Is its server running?"
    sql = f"```sql\n{o.sql}\n```\n" if o.sql else ""
    if o.error:
        return f"{sql}\n❌ {o.error}  \n_{o.latency_s:.1f}s_"
    rows = f"{o.n_rows}{'+' if o.truncated else ''} row{'s' if o.n_rows != 1 else ''}"
    badge = ""
    if o.matches is not None:
        badge = (
            "\n\n✅ matches the reference answer"
            if o.matches
            else "\n\n⚠️ differs from the reference"
        )
    return f"{sql}\n✅ executed · {rows} · {o.latency_s:.1f}s{badge}"


def table(o: Outcome) -> dict:
    return gr.update(value=[list(r) for r in o.rows] if o.ok else [], headers=o.columns or None)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def build_ui(s: Settings, presets: dict[str, Preset], backends: list[Backend], warm: WarmupState):
    labels = {k: p.label for k, p in presets.items()} | {CUSTOM: "Paste your own schema"}
    first = next(iter(presets))

    def banner() -> str:
        return (
            ""
            if warm.ready.is_set()
            else f"⏳ Models warming up ({warm.detail}). Answers work, the first ones are slower."
        )

    def pick_db(key: str):
        if key == CUSTOM:
            return (
                gr.update(value="", visible=False),
                gr.update(visible=True),
                gr.update(choices=[], value=None),
                "",
            )
        p = presets[key]
        note = "" if not p.unseen else "A domain the model never saw during training. "
        return (
            gr.update(value=p.schema, visible=True),
            gr.update(visible=False),
            gr.update(choices=[e["question"] for e in p.examples], value=None),
            note,
        )

    def pick_example(q: str | None):
        return gr.update(value=q) if q else gr.update()

    def run(key: str, question: str, ddl: str):
        question = (question or "").strip()
        empty = ("", [], "", [], "", gr.update(visible=False))
        if not question:
            return ("Type a question first.", *empty[1:])
        if len(question) > MAX_QUESTION:
            return (f"Questions are limited to {MAX_QUESTION} characters.", *empty[1:])
        reference = ordered = None
        try:
            if key == CUSTOM:
                conn, schema = load_custom(ddl)
            else:
                p = presets[key]
                conn, schema = p.connect(), p.schema
                ex = next((e for e in p.examples if e["question"] == question), None)
                reference, ordered = (ex["sql"], ex["order_matters"]) if ex else (None, False)
            outs = compare(
                backends, schema, question, conn, reference, bool(ordered), s.sequential, s.max_rows
            )
            conn.close()
        except CustomSchemaError as exc:
            return (f"⚠️ {exc}", *empty[1:])
        base, ft = outs
        ref_box = gr.update(
            visible=bool(reference), value=f"```sql\n{reference}\n```" if reference else ""
        )
        return "", render(base), table(base), render(ft), table(ft), ref_box

    def results_md() -> str:
        p = ROOT / "reports" / "eval_results.md"
        return p.read_text() if p.exists() else "No evaluation report yet. Run `make eval-all`."

    def funnel_rows() -> list[list]:
        rep = read_json(ROOT / "reports" / "data_quality.json")
        if not rep:
            return []
        steps = list(next(iter(rep["funnel"].values())))
        return [
            [st] + [f"{rep['funnel'][src].get(st, 0):,}" for src in rep["funnel"]] for st in steps
        ]

    def drop_examples(code: str | None) -> str:
        rep = read_json(ROOT / "reports" / "data_quality.json")
        row = next((d for d in (rep or {}).get("drop_reasons", []) if d["code"] == code), None)
        if not row:
            return "Pick a drop reason."
        lines = [f"**{row['code']}**: {row['count']:,} rows"]
        for ex in row["examples"]:
            err = f"\n  - SQLite said: `{ex['detail']}`" if ex["detail"] else ""
            lines.append(f"- {ex['question']}\n  - `{ex['sql']}`{err}")
        return "\n".join(lines)

    with gr.Blocks(title="Text-to-SQL Specialist") as demo:
        gr.Markdown(
            "# Text-to-SQL Specialist\nBase vs fine-tuned Qwen2.5-Coder-1.5B, running on CPU."
        )
        status = gr.Markdown(banner())
        gr.Timer(3).tick(banner, outputs=status)
        with gr.Tabs():
            with gr.Tab("Try it"):
                db = gr.Radio([(v, k) for k, v in labels.items()], value=first, label="Database")
                note = gr.Markdown("")
                schema_box = gr.Code(
                    value=presets[first].schema, language="sql", label="Schema", interactive=False
                )
                ddl = gr.Textbox(
                    lines=8,
                    label="CREATE TABLE / INSERT statements",
                    visible=False,
                    info="First query on a new schema is slower (no prompt cache yet).",
                )
                example = gr.Dropdown(
                    [e["question"] for e in presets[first].examples],
                    label="Example questions (these have a reference answer)",
                )
                question = gr.Textbox(label="Question", max_length=MAX_QUESTION)
                go = gr.Button("Generate & run", variant="primary")
                msg = gr.Markdown("")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### Base model")
                        base_md, base_df = gr.Markdown(), gr.Dataframe(interactive=False)
                    with gr.Column():
                        gr.Markdown("### Fine-tuned (ours)")
                        ft_md, ft_df = gr.Markdown(), gr.Dataframe(interactive=False)
                ref = gr.Markdown(visible=False)
                db.change(pick_db, db, [schema_box, ddl, example, note])
                example.change(pick_example, example, question)
                go.click(run, [db, question, ddl], [msg, base_md, base_df, ft_md, ft_df, ref])
                question.submit(
                    run, [db, question, ddl], [msg, base_md, base_df, ft_md, ft_df, ref]
                )
            with gr.Tab("Results"):
                gr.Markdown(results_md())
                for img in sorted((ROOT / "reports" / "figures").glob("difficulty_*.png")):
                    gr.Image(str(img), show_label=False)
            with gr.Tab("Data pipeline"):
                gr.Markdown("How many raw rows survive each step of the ETL.")
                rep = read_json(ROOT / "reports" / "data_quality.json") or {}
                gr.Dataframe(
                    funnel_rows(), headers=["Stage", *rep.get("funnel", {})], interactive=False
                )
                codes = [d["code"] for d in rep.get("drop_reasons", [])]
                pick = gr.Dropdown(codes, label="Why rows were dropped (browse real examples)")
                shown = gr.Markdown()
                pick.change(drop_examples, pick, shown)
            with gr.Tab("About"):
                gr.Markdown((ROOT / "src/text2sql/app/about.md").read_text())
    return demo


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    s = Settings.from_env()
    presets = load_presets(ROOT / "data" / "demo")
    backends = [
        Backend("base", ChatClient(s.base_url, s.base_model, timeout_s=s.timeout_s)),
        Backend("finetuned", ChatClient(s.ft_url, s.ft_model, timeout_s=s.timeout_s)),
    ]
    warm = WarmupState()
    start_in_background(backends, presets, warm)
    demo = build_ui(s, presets, backends, warm)
    demo.queue(default_concurrency_limit=2).launch(server_name=s.host, server_port=s.port)


if __name__ == "__main__":
    main()
