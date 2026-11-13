#!/usr/bin/env python3
"""Validate the Chinook text-to-SQL eval set.

Usage:
    python3 validate_chinook_eval.py <db_path> <jsonl_path> [--write-counts] [--show]

Checks per item:
  * required fields / allowed difficulty values / unique ids, questions and SQL
  * SQL is a single read-only SELECT (or WITH ... SELECT) statement
  * executes without error (DB opened read-only) and returns a non-empty result
  * "tables" field matches the tables referenced in the SQL
  * determinism: appending every output column as an extra ORDER BY key, once
    ascending and once descending, must not change the result (as a list when
    order_matters, as a multiset otherwise). Catches ORDER BY + LIMIT that does
    not pin down which rows/what order are returned.
  * top-N cutoff ties: for queries ending in ORDER BY ... LIMIT N, the ranking
    keys (all ORDER BY terms except the last one, which is treated as the
    tie-breaker; or the single term if only one) must not tie between row N
    and row N+1.
  * expected_row_count matches the actual row count (or is filled in with
    --write-counts).
"""
import argparse
import collections
import json
import re
import sqlite3
import sys

TABLES = ["Album", "Artist", "Customer", "Employee", "Genre", "Invoice",
          "InvoiceLine", "MediaType", "Playlist", "PlaylistTrack", "Track"]
DIFFICULTIES = ["easy", "medium", "hard", "sqlite_specific"]
REQUIRED = ["id", "question", "sql", "difficulty", "tags", "tables",
            "order_matters", "expected_row_count"]
FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b", re.I)


def strip_strings(sql):
    """Replace string literal contents with spaces so keyword scanning ignores them."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            out.append(ch + " " * (j - i - 1) + (ch if j < n else ""))
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def top_level_positions(masked, pattern):
    """Positions of regex matches that are at parenthesis depth 0."""
    depth_at = []
    d = 0
    for ch in masked:
        if ch == "(":
            d += 1
        depth_at.append(d)
        if ch == ")":
            d -= 1
    return [m for m in re.finditer(pattern, masked, re.I) if depth_at[m.start()] == 0]


def split_top_level_commas(s):
    parts, d, cur = [], 0, []
    for ch in s:
        if ch == "(":
            d += 1
        elif ch == ")":
            d -= 1
        if ch == "," and d == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def parse_final_order_limit(sql):
    """Return (head_sql, order_terms, limit_int_or_None) for the outermost query."""
    sql = sql.strip().rstrip(";").strip()
    masked = strip_strings(sql)
    obs = top_level_positions(masked, r"\bORDER\s+BY\b")
    lims = top_level_positions(masked, r"\bLIMIT\b")
    limit = None
    lim_start = len(sql)
    if lims:
        m = lims[-1]
        lim_start = m.start()
        lm = re.match(r"LIMIT\s+(\d+)\s*$", sql[m.start():], re.I)
        if not lm:
            raise ValueError("unsupported LIMIT clause (use plain LIMIT N)")
        limit = int(lm.group(1))
    if not obs or obs[-1].start() > lim_start:
        return sql[:lim_start].strip(), [], limit
    ob = obs[-1]
    terms = split_top_level_commas(sql[ob.end():lim_start])
    return sql[:ob.start()].strip(), terms, limit


def build(head, terms, limit=None):
    s = head
    if terms:
        s += " ORDER BY " + ", ".join(terms)
    if limit is not None:
        s += f" LIMIT {limit}"
    return s


def norm(rows):
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in r) for r in rows]


def check_item(conn, item):
    errs, warns = [], []
    sql = item["sql"]
    masked = strip_strings(sql)
    stripped = masked.strip().rstrip(";")
    if ";" in stripped:
        errs.append("multiple statements")
    if not re.match(r"\s*(SELECT|WITH)\b", masked, re.I):
        errs.append("not a SELECT/WITH statement")
    if FORBIDDEN.search(masked):
        errs.append("forbidden keyword in SQL")

    used = {t for t in TABLES if re.search(r"\b" + t + r"\b", masked)}
    if used != set(item["tables"]):
        errs.append(f"tables field {sorted(item['tables'])} != tables in SQL {sorted(used)}")

    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        ncols = len(cur.description)
    except sqlite3.Error as e:
        return [f"execution error: {e}"], warns, None
    if not rows:
        errs.append("empty result")
        return errs, warns, 0

    try:
        head, terms, limit = parse_final_order_limit(sql)
    except ValueError as e:
        errs.append(str(e))
        return errs, warns, len(rows)

    if limit is not None and not terms:
        errs.append("LIMIT without ORDER BY")
    if item["order_matters"] and not terms:
        errs.append("order_matters=true but no final ORDER BY")

    # Determinism: extra tie-breakers on all output columns, asc vs desc.
    if terms or limit is not None:
        cols = [str(i) for i in range(1, ncols + 1)]
        try:
            a = norm(conn.execute(build(head, terms + cols, limit)).fetchall())
            b = norm(conn.execute(build(head, terms + [c + " DESC" for c in cols], limit)).fetchall())
        except sqlite3.Error as e:
            errs.append(f"determinism probe failed to run: {e}")
        else:
            base = norm(rows)
            if item["order_matters"]:
                if not (a == base == b):
                    errs.append("ORDER BY does not fully determine row order")
            else:
                if not (collections.Counter(a) == collections.Counter(base) == collections.Counter(b)):
                    errs.append("ORDER BY/LIMIT does not determine the returned row set")

    # Top-N cutoff tie check on ranking keys.
    if limit is not None and terms:
        keys = terms[:-1] if len(terms) > 1 else terms
        key_exprs = [re.sub(r"\s+(ASC|DESC)\s*$", "", k, flags=re.I) for k in keys]
        # Ordinal keys refer to output columns; evaluate them from the row itself.
        if all(re.fullmatch(r"\d+", k) for k in key_exprs):
            full = conn.execute(build(head, keys, limit + 1)).fetchall()
            if len(full) > limit:
                idx = [int(k) - 1 for k in key_exprs]
                if [full[limit - 1][i] for i in idx] == [full[limit][i] for i in idx]:
                    errs.append(f"tie at top-{limit} cutoff on {keys}")
        else:
            # Re-run ordered by the ranking keys only, with the key expressions appended as
            # extra output columns, and compare the key values of rows N and N+1.
            # Attempt 1: inject them into the outermost SELECT list (works when keys use
            # table columns). Attempt 2: wrap the query (works when keys use output aliases).
            nk = len(key_exprs)
            extra = ", ".join(f"({k}) AS __k{i}" for i, k in enumerate(key_exprs))
            full, last_err = None, None
            try:
                masked_head = strip_strings(head)
                sel = top_level_positions(masked_head, r"\bSELECT\b")[-1]
                frm = [m for m in top_level_positions(masked_head, r"\bFROM\b") if m.start() > sel.start()]
                if not frm:
                    raise ValueError("no FROM")
                f0 = frm[0].start()
                aug_head = head[:f0].rstrip() + ", " + extra + " " + head[f0:]
                full = conn.execute(build(aug_head, keys, limit + 1)).fetchall()
            except (sqlite3.Error, ValueError, IndexError) as e:
                last_err = e
                try:
                    wrapped = f"SELECT __q.*, {extra} FROM ({head}) AS __q"
                    full = conn.execute(build(wrapped, keys, limit + 1)).fetchall()
                except sqlite3.Error as e2:
                    last_err = e2
            if full is None:
                warns.append(f"could not run cutoff tie check: {last_err}")
            elif len(full) > limit:
                if norm([full[limit - 1][-nk:]]) == norm([full[limit][-nk:]]):
                    errs.append(f"tie at top-{limit} cutoff on {keys}")

    # Within-result ties on ranking keys for ordered questions (question must state the tie-break).
    if item["order_matters"] and len(terms) > 1:
        keys = terms[:-1]
        cols = [str(i) for i in range(1, ncols + 1)]
        try:
            a = conn.execute(build(head, keys + cols, limit)).fetchall()
            b = conn.execute(build(head, keys + [c + " DESC" for c in cols], limit)).fetchall()
            if norm(a) != norm(b):
                warns.append("rows tie on ranking keys; question must state the final tie-break")
        except sqlite3.Error:
            pass

    if isinstance(item.get("expected_row_count"), int) and item["expected_row_count"] != len(rows):
        errs.append(f"expected_row_count {item['expected_row_count']} != actual {len(rows)}")
    return errs, warns, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("jsonl")
    ap.add_argument("--write-counts", action="store_true",
                    help="rewrite expected_row_count in the jsonl from actual results")
    ap.add_argument("--show", action="store_true", help="print first rows of every result")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    items = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]

    failures, warnings = {}, {}
    seen_ids, seen_q, seen_sql = set(), set(), set()
    per_diff = collections.Counter()
    pass_diff = collections.Counter()
    tables_cov = collections.Counter()

    for item in items:
        errs = []
        missing = [k for k in REQUIRED if k not in item]
        if missing:
            errs.append(f"missing fields {missing}")
            failures[item.get("id", "?")] = errs
            continue
        if item["difficulty"] not in DIFFICULTIES:
            errs.append(f"bad difficulty {item['difficulty']}")
        for key, seen in (("id", seen_ids), ("question", seen_q), ("sql", seen_sql)):
            v = re.sub(r"\s+", " ", item[key].strip().lower())
            if v in seen:
                errs.append(f"duplicate {key}")
            seen.add(v)
        e, w, n = check_item(conn, item)
        errs += e
        if args.write_counts and n is not None:
            item["expected_row_count"] = n
            errs = [x for x in errs if not x.startswith("expected_row_count")]
        per_diff[item["difficulty"]] += 1
        tables_cov.update(item["tables"])
        if errs:
            failures[item["id"]] = errs
        else:
            pass_diff[item["difficulty"]] += 1
        if w:
            warnings[item["id"]] = w
        if args.show and n:
            rows = conn.execute(item["sql"]).fetchall()
            print(f"--- {item['id']} [{item['difficulty']}] rows={n} order={item['order_matters']}\n    Q: {item['question']}\n    {rows[:6]}")

    if args.write_counts:
        with open(args.jsonl, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("=" * 60)
    for iid, errs in failures.items():
        for e in errs:
            print(f"FAIL {iid}: {e}")
    for iid, ws in warnings.items():
        for w in ws:
            print(f"WARN {iid}: {w}")
    total = len(items)
    passed = total - len(failures)
    print(f"Items: {total}  Passed: {passed}  Failed: {len(failures)}  Warnings: {len(warnings)}")
    for d in DIFFICULTIES:
        print(f"  {d:16s} {pass_diff[d]:3d}/{per_diff[d]:3d} passed")
    uncovered = [t for t in TABLES if tables_cov[t] == 0]
    print("Table coverage:", ", ".join(f"{t}={tables_cov[t]}" for t in TABLES))
    if uncovered:
        print("FAIL: tables never used:", uncovered)
    sys.exit(0 if not failures and not uncovered else 1)


if __name__ == "__main__":
    main()
