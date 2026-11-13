import sqlite3, sys, collections, pyarrow.parquet as pq
rows = pq.read_table(sys.argv[1]).to_pylist()
ok=0; ctx_fail=0; sql_fail=0; empty=0; reasons=collections.Counter(); bycx=collections.defaultdict(lambda:[0,0])
for r in rows:
    db=sqlite3.connect(":memory:")
    try: db.executescript(r["sql_context"])
    except Exception as e: ctx_fail+=1; reasons["ctx: "+str(e).split(":")[0][:40]]+=1; continue
    bycx[r["sql_complexity"]][1]+=1
    try:
        res=db.execute(r["sql"]).fetchall()
        ok+=1; bycx[r["sql_complexity"]][0]+=1
        if not res: empty+=1
    except Exception as e: sql_fail+=1; reasons["sql: "+str(e).split(":")[0][:40]]+=1
n=len(rows); print(f"rows={n} ok={ok} ({ok/n:.1%}) ctx_fail={ctx_fail} sql_fail={sql_fail} ok_but_empty_result={empty}")
for k,v in reasons.most_common(8): print(" ",v,k)
for k,(a,b) in sorted(bycx.items()): print(f"  {k:28s} {a}/{b} pass")
