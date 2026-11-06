"""Stratified description samples joined to the judge's stored reasoning. Run with the eval venv from the A5 eval dir:
uv run --frozen python /home/hengz/evalv2-data/v2/diagnostics/description_samples.py"""
import json, os, random, sys, glob, collections
sys.path.insert(0,'.')
from evalv2.tasks.judging import JudgeCache, JudgeIdentity
import hashlib
src=open('evalv2/tasks/judging.py').read()
exec(open('/home/hengz/evalv2-data/v2/diagnostics/description_audit.py').read().split("man=json.load")[0])
# cache: raw by key across runs
raw={}
for run in ('c3-track-a-switchyard','c3-track-a-switchyard-recovery','c3-track-a-switchyard-recovery-a5a','c3-track-a-openrouter','c3-track-b-contingency-nano-grounding'):
    for p in glob.glob(R+run+'/scoring/judge-cache/*.incident.jsonl'):
        for l in open(p):
            e=json.loads(l); raw.setdefault(e['key'],[]).append((run,e))
print('cache entries',len(raw))
bad=0;noreason=0
for es in raw.values():
  for _,e in es:
    try:
        j=json.loads(e['raw'])
        if abs(float(j['score'])-e['score'])>1e-9: bad+=1
    except Exception: noreason+=1
multi={k:v for k,v in raw.items() if len({r for r,_ in v})>1}
dis=[(k,[(r,e['score']) for r,e in v]) for k,v in multi.items() if len({e['score'] for _,e in v})>1]
flip=[d for d in dis if len({s_>=.5 for _,s_ in d[1]})>1]
print('pairs judged in >1 run',len(multi),'score differs',len(dis),'pass flips',len(flip),'max gap',max([max(s_ for _,s_ in d[1])-min(s_ for _,s_ in d[1]) for d in dis] or [0]))
print('examples',[d[1] for d in dis[:6]])
print('raw score != stored',bad,'unparsable raw (regex fallback)',noreason)

from evalv2.tasks.judges import load_judges
import evalv2.tasks.judges as jm
reg=load_judges(); spec=[j for j in (reg.judges.values() if hasattr(reg,'judges') else reg) if j.id=='openrouter-gpt-oss-20b-c3-v1'][0]
ident=jm.judge_identity(spec,'incident') if hasattr(jm,'judge_identity') else None
print('identity',ident.model,ident.prompt_sha256[:10],dict(ident.settings))
hit=miss=0; S=collections.defaultdict(list)
for k_,r in A.items():
    if r['outcome']!='scored': continue
    d=r['incident_field_scores']['description']
    if d.get('score') is None: continue
    es=raw.get(ident.key(d['expected'],d['predicted']))
    if es is None: miss+=1; continue
    e=[x for _,x in es if abs(x['score']-d['score'])<1e-9]
    if not e: print('NO MATCHING VERDICT',k_); continue
    hit+=1
    S[k_[0]].append((k_,d,json.loads(e[0]['raw']).get('reasoning')))
print('joined',hit,'unjoined',miss)
rnd=random.Random(20261105)
out=[]
for s in ('nano-direct','omni-direct','gemma4-31b-openrouter','qwen35-9b-openrouter','super-direct'):
    x=sorted(S[s],key=lambda t:(t[0][1],t[0][2]))
    z=[t for t in x if t[1]['score']==0]; lo=[t for t in x if 0<t[1]['score']<.5]; hi=[t for t in x if t[1]['score']>=.5]
    pick=rnd.sample(z,2)+rnd.sample(lo,2)+rnd.sample(hi,1)
    out+=pick
for i,(k_,d,why) in enumerate(out,1):
    print(f"#{i} {k_[0]} {k_[1]} r{k_[2]} score={d['score']} pass={d['pass']}\n GT: {d['expected'][:430]}\n PRED: {d['predicted'][:330]}\n WHY: {why[:260]}")
json.dump([{'n':i+1,'subject':k_[0],'clip':k_[1],'repeat':k_[2],'score':d['score'],'pass':d['pass'],'gt':d['expected'],'pred':d['predicted'],'why':why} for i,(k_,d,why) in enumerate(out)],open('/home/hengz/evalv2-data/v2/diagnostics/description_samples.json','w'),indent=1)
