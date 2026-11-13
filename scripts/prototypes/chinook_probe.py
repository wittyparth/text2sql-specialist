import sqlite3, sys, json, re, time, collections
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, sys.argv[3]); from canon import canon; from base_probe import ask, extract
def cell(v):
    if isinstance(v,str):
        s=v.strip(); s=re.sub(r"^(\d{4}-\d{2}-\d{2}) 00:00:00$",r"\1",s)
        try: return round(float(s),2)
        except ValueError: return s
    if isinstance(v,(int,float)): return round(float(v),2)
    return v
def norm(rows, ordered):
    rr=[tuple(sorted(map(repr,map(cell,r)))) for r in rows]
    return rr if ordered else collections.Counter(rr)
db=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True,check_same_thread=False); schema=canon(db)
items=[json.loads(l) for l in open(sys.argv[2])]
def run(it):
    out,lat,u=ask(schema,it["question"]); sql=extract(out)
    c=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
    gold=c.execute(it["sql"]).fetchall()
    try: pred=c.execute(sql).fetchall(); err=None
    except Exception as e: pred=None; err=str(e)
    ok=pred is not None and norm(pred,it["order_matters"])==norm(gold,it["order_matters"])
    return dict(d=it["difficulty"],ok=ok,err=err,lat=lat,ptok=u["prompt_tokens"],sql=sql,q=it["question"])
import base_probe
with ThreadPoolExecutor(4) as ex: res=list(ex.map(run,items))
n=len(res); print(f"chinook n={n} EX={sum(r['ok'] for r in res)/n:.1%} exec_errors={sum(r['err'] is not None for r in res)} prompt_tok={res[0]['ptok']} lat_p50={sorted(r['lat'] for r in res)[n//2]:.2f}s")
by=collections.defaultdict(list); [by[r["d"]].append(r["ok"]) for r in res]
for k,v in by.items(): print(f"  {k:16s} {sum(v)}/{len(v)}")
print("errors:",collections.Counter(re.sub(r":.*","",r["err"]) for r in res if r["err"]).most_common(6))
for r in [r for r in res if r["err"] and "function" in r["err"]][:3]: print("DIALECT:",r["sql"][:160],"|",r["err"])
for r in [r for r in res if r["err"]][:6]: print("Q:",r["q"][:90],"\n  SQL:",r["sql"][:170].replace("\n"," "),"\n  ERR:",r["err"])
