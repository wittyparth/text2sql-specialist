"""Drive the running demo in Chrome and check each feature. Needs playwright and Chrome:

    uv run --with playwright python scripts/ui_smoke.py [http://localhost:7860]

Start the app first (`docker compose up`, `./run.sh` or `make app`). Screenshots go to docs/.
"""

import sys

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7860"
OUT = "docs"
log = []


def ok(name, cond, detail=""):
    log.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name, detail[:160])


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1400, "height": 1100})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(URL)
    pg.get_by_role("tab", name="Try it").wait_for(timeout=30000)
    pg.wait_for_timeout(1500)
    ok(
        "page loads, 4 tabs",
        all(
            pg.get_by_role("tab", name=n).count()
            for n in ["Try it", "Results", "Data pipeline", "About"]
        ),
    )

    # 1. a curated Chinook example with a reference answer (first option: the regression case)
    pg.get_by_label("Example questions (these have a reference answer)").click()
    pg.get_by_role("option").first.click()
    pg.wait_for_timeout(2000)
    filled = pg.get_by_label("Question", exact=True).input_value()
    ok("first example fills the question box", filled.strip(), filled[:60])
    pg.get_by_role("button", name="Generate & run").click()
    pg.wait_for_function(
        "document.body.innerText.includes('executed') || document.body.innerText.includes('❌')",
        timeout=180000,
    )
    pg.wait_for_function(
        "(document.body.innerText.match(/executed|❌/g) || []).length >= 2", timeout=180000
    )
    pg.wait_for_timeout(1000)
    body = pg.inner_text("body")
    ok(
        "both models answered",
        body.count("executed") + body.count("❌") >= 2,
        f"executed={body.count('executed')} err={body.count('❌')}",
    )
    ok(
        "match badge shown",
        "matches the reference answer" in body or "differs from the reference" in body,
        f"match={body.count('matches the reference')} differ={body.count('differs from')}",
    )
    ok("reference SQL shown", "ORDER BY" in body.upper())
    pg.screenshot(path=f"{OUT}/demo.png", full_page=True)

    # 2. custom schema: a malicious one is rejected with a readable message
    pg.get_by_text("Paste your own schema").click()
    pg.wait_for_timeout(800)
    pg.get_by_label("CREATE TABLE / INSERT statements").fill(
        "DROP TABLE users; CREATE TABLE t (a INT);"
    )
    pg.get_by_label("Question", exact=True).fill("how many rows?")
    pg.get_by_role("button", name="Generate & run").click()
    pg.wait_for_timeout(4000)
    body = pg.inner_text("body")
    ok(
        "DROP in custom schema is rejected politely",
        "⚠️" in body or "not allowed" in body.lower() or "only" in body.lower(),
        body[body.find("⚠️") :][:120] if "⚠️" in body else "",
    )
    ok("no stack trace shown", "Traceback" not in body)

    # 3. custom schema that is fine
    pg.get_by_label("CREATE TABLE / INSERT statements").fill(
        "CREATE TABLE pets (id INT, name TEXT, age INT);"
        " INSERT INTO pets VALUES (1,'Rex',3),(2,'Tom',5);"
    )
    pg.get_by_label("Question", exact=True).fill("What is the name of the oldest pet?")
    pg.get_by_role("button", name="Generate & run").click()
    pg.wait_for_function(
        "!document.body.innerText.includes('Only CREATE TABLE')"
        " && (document.body.innerText.match(/executed|❌/g) || []).length >= 2",
        timeout=180000,
    )
    pg.wait_for_timeout(800)
    body = pg.inner_text("body")
    ok(
        "custom schema answers (Tom)",
        "Tom" in body and "executed" in body,
        "executed" if "executed" in body else body[:80],
    )

    # 4. other tabs
    pg.get_by_role("tab", name="Results").click()
    pg.wait_for_timeout(1200)
    t = pg.inner_text("body")
    ok(
        "Results tab shows the headline table",
        "Execution" in t or "Headline" in t or "62.4%" in t,
        "62.4%" if "62.4%" in t else "",
    )
    pg.get_by_role("tab", name="Data pipeline").click()
    pg.wait_for_timeout(1200)
    t = pg.inner_text("body")
    ok("Data pipeline shows the funnel", "105,851" in t)
    pg.get_by_label("Why rows were dropped (browse real examples)").click()
    pg.get_by_role("option", name="NOT_SELECT").click()
    pg.wait_for_timeout(800)
    ok(
        "drop-reason examples render",
        "NOT_SELECT" in pg.inner_text("body") and "rows" in pg.inner_text("body"),
    )
    pg.get_by_role("tab", name="About").click()
    pg.wait_for_timeout(800)
    ok("About tab renders", len(pg.inner_text("body")) > 400)
    ok("no JS page errors", not errors, "; ".join(errors)[:160])
    b.close()

bad = [n for n, c, _ in log if not c]
print("\nFAILED:" if bad else "\nALL PASSED", bad)
sys.exit(1 if bad else 0)
