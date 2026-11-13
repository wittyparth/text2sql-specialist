import sqlite3, sys, pyarrow.parquet as pq, random
def canon(db, sample_rows=2):
    out=[]
    for (t,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
        cols=db.execute(f'pragma table_info("{t}")').fetchall()
        fks={r[3]:(r[2],r[4]) for r in db.execute(f'pragma foreign_key_list("{t}")')}
        parts=[]
        for c in cols:
            s=f"{c[1]} {c[2] or 'TEXT'}".strip()
            if c[5]: s+=" PRIMARY KEY"
            if c[1] in fks: s+=f" REFERENCES {fks[c[1]][0]}({fks[c[1]][1]})"
            parts.append(s)
        out.append(f"CREATE TABLE {t} ({', '.join(parts)});")
        if sample_rows:
            rows=db.execute(f'select * from "{t}" limit {sample_rows}').fetchall()
            for r in rows: out.append("-- " + ", ".join(str(v)[:30] for v in r))
    return "\n".join(out)
if __name__=='__main__':
    db=sqlite3.connect(sys.argv[1]+"/chinook.sqlite")
    c=canon(db); print("chinook canonical chars:",len(c)); print(c[:700])
    rows=pq.read_table(sys.argv[1]+"/train.parquet").to_pylist(); random.seed(0); L=[]
    for r in random.sample(rows,3000):
        m=sqlite3.connect(":memory:")
        try: m.executescript(r["sql_context"])
        except Exception: continue
        L.append(len(canon(m))+len(r["sql_prompt"])+len(r["sql"]))
    L.sort(); print("gretel canonical ctx+q+sql chars p50/p90/p99/max",L[len(L)//2],L[int(len(L)*.9)],L[int(len(L)*.99)],L[-1])
