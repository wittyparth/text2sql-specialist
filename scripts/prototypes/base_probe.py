import sqlite3, sys, json, re, random, time, collections, urllib.request, pyarrow.parquet as pq
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, __import__("os").path.dirname(__file__)); from canon import canon
SYSTEM="You are a SQLite expert. Given a database schema and a question, write one SQLite SELECT query that answers the question. Output only the SQL query."
def ask(schema,q,url="http://127.0.0.1:8081/v1/chat/completions"):
    body=json.dumps({"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":f"Schema:\n{schema}\n\nQuestion: {q}"}],"temperature":0,"max_tokens":256}).encode()
    t=time.time(); r=json.load(urllib.request.urlopen(urllib.request.Request(url,body,{"Content-Type":"application/json"})))
    return r["choices"][0]["message"]["content"], time.time()-t, r["usage"]
def extract(txt):
    m=re.search(r"```(?:sql|sqlite)?\s*(.*?)```",txt,re.S|re.I); s=m.group(1) if m else txt
    return s.strip().split(";")[0].strip()
def norm(rows): return collections.Counter(tuple(sorted((repr(round(v,4) if isinstance(v,float) else v) for v in r))) for r in rows)
if __name__=='__main__':
    rows=[r for r in pq.read_table(sys.argv[1]).to_pylist() if r["sql_task_type"] in("analytics and reporting","data retrieval")]
    random.seed(1); random.shuffle(rows); items=[]
    for r in rows:
        db=sqlite3.connect(":memory:")
        try: db.executescript(r["sql_context"]); gold=db.execute(r["sql"]).fetchall()
        except Exception: continue
        if gold: items.append((r,canon(db),gold))
        if len(items)==200: break
    def run(it):
        r,schema,gold=it; out,lat,usage=ask(schema,r["sql_prompt"]); sql=extract(out)
        db=sqlite3.connect(":memory:"); db.executescript(r["sql_context"])
        try: pred=db.execute(sql).fetchall(); err=None
        except Exception as e: pred=None; err=str(e)
        return dict(timedep=bool(re.search(r"\b(now|current_date|curdate|getdate|sysdate|last|past|recent|this year|this month)\b",r["sql_prompt"]+" "+r["sql"],re.I)),cx=r["sql_complexity"],fenced="```" in out,ok=pred is not None and norm(pred)==norm(gold),err=err,lat=lat,ptok=usage["prompt_tokens"],ctok=usage["completion_tokens"],out=out,gold=r["sql"])
    t=time.time()
    with ThreadPoolExecutor(4) as ex: res=list(ex.map(run,items))
    n=len(res); print(f"n={n} wall={time.time()-t:.0f}s EX={sum(r['ok'] for r in res)/n:.1%} exec_errors={sum(r['err'] is not None for r in res)} fenced_outputs={sum(r['fenced'] for r in res)}")
    lat=sorted(r["lat"] for r in res); print(f"latency p50={lat[n//2]:.2f}s p95={lat[int(n*.95)]:.2f}s  prompt_tok p50={sorted(r['ptok'] for r in res)[n//2]} compl_tok p50={sorted(r['ctok'] for r in res)[n//2]}")
    print("errors:",collections.Counter(re.sub(r":.*","",r["err"]) for r in res if r["err"]).most_common(6))
    by=collections.defaultdict(list); [by[r["cx"]].append(r["ok"]) for r in res]
    for k,v in sorted(by.items()): print(f"  {k:22s} {sum(v)}/{len(v)}")
    for r in [r for r in res if not r["ok"]][:4]: print("---\nPRED:",r["out"][:250],"\nGOLD:",r["gold"][:250],"\nERR:",r["err"])
    td=[r for r in res if r["timedep"]]; nt=[r for r in res if not r["timedep"]]
    print(f"time-dependent items={len(td)} EX={sum(r['ok'] for r in td)/max(1,len(td)):.1%} | non-time-dependent items={len(nt)} EX={sum(r['ok'] for r in nt)/len(nt):.1%}")
