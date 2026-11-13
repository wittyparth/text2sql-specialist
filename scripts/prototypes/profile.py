import sqlite3, sys, collections, json, re, time, pyarrow.parquet as pq, sqlglot
D=sys.argv[1]
def run(ctx, sql):
    db=sqlite3.connect(":memory:")
    try: db.executescript(ctx)
    except Exception as e: return "ctx", str(e)
    try: return "ok", db.execute(sql).fetchall()
    except Exception as e: return "sql", str(e)
def tr(s, read):
    try: return ";\n".join(sqlglot.transpile(s, read=read, write="sqlite"))
    except Exception: return None
t=time.time()
rows=pq.read_table(f"{D}/train.parquet").to_pylist()
st=collections.Counter(); cx=collections.Counter(); dom=collections.Counter(); tt=collections.Counter(); qlen=[]; L=[]
for r in rows:
    dom[r["domain"]]+=1; tt[r["sql_task_type"]]+=1
    s,res=run(r["sql_context"], r["sql"])
    if s=="ok":
        st["ok_raw"]+=1; st["ok_empty" if not res else "ok_nonempty"]+=1
    else:
        ctx2=r["sql_context"] if s=="sql" else tr(r["sql_context"],"mysql")
        sql2=tr(r["sql"],"mysql") or tr(r["sql"],"postgres")
        if ctx2 and sql2:
            s2,res2=run(ctx2,sql2)
            if s2=="ok": st["recovered_transpile"]+=1; st["ok_empty" if not res2 else "ok_nonempty"]+=1; continue
        st["fail_"+s]+=1
    L.append(len(r["sql_context"])+len(r["sql_prompt"])+len(r["sql"]))
print(f"gretel train rows={len(rows)} secs={time.time()-t:.0f}")
for k,v in sorted(st.items()): print(f"  {k}: {v} ({v/len(rows):.1%})")
print("  unique domains:",len(dom)," min/max per domain:",min(dom.values()),max(dom.values()))
print("  task types:",dict(tt))
L.sort(); print("  chars ctx+q+sql p50/p90/p99/max:",L[len(L)//2],L[int(len(L)*.9)],L[int(len(L)*.99)],L[-1])
# dup questions
qs=collections.Counter(re.sub(r"\W+"," ",r["sql_prompt"].lower()).strip() for r in rows); print("  dup normalized questions:",sum(v-1 for v in qs.values() if v>1))
# sql-create-context
cc=json.load(open(f"{D}/sqlcc.json")); st=collections.Counter()
for r in cc:
    s,_=run(r["context"].replace(", ",", ") if True else "", r["answer"])
    st[s]+=1
print(f"sql-create-context rows={len(cc)}", dict(st))
qs2=collections.Counter(re.sub(r"\W+"," ",r["question"].lower()).strip() for r in cc); print("  dup normalized questions:",sum(v-1 for v in qs2.values() if v>1))
print("  overlap questions w/ gretel:", len(set(qs)&set(qs2)))
