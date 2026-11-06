"""Description scoring audit: read-only. python3 /home/hengz/evalv2-data/v2/diagnostics/description_audit.py"""
import json, os, collections, statistics as st, glob, re, sys
R='/home/hengz/evalv2-data/v2/runs/'
TAIL='scoring/evalv2-score-stage-v3/primary/%s-videos.jsonl'
MO=('scored','contract_invalid','parse_failure')
def rows(run):
    p=R+run+'/'+TAIL%'live'
    if not os.path.exists(p): p=R+run+'/'+TAIL%'offline'
    return [json.loads(l) for l in open(p)]
A={}
for run in ('c3-track-a-switchyard','c3-track-a-switchyard-recovery','c3-track-a-switchyard-recovery-a5a','c3-track-a-openrouter'):
    for r in rows(run):
        if r.get('stage','p1')!='p1': continue
        k=(r['subject'],r['incident_id'],r['repeat'])
        if k not in A or A[k]['outcome'] not in MO: A[k]=r; r['_run']=run
for r in rows('c3-track-b-contingency-nano-grounding'):
    if r.get('stage')=='final': A[(r['subject'],r['incident_id'],r['repeat'])]=r; r['_run']='contingency'
man=json.load(open('/home/hengz/vss-wt-c3a5/deploy/docker/developer-profiles/dev-profile-incident/eval/eval_reproducibility/dataset-manifest-v1.json'))
dur={c['incident_id']:float(c['duration_seconds']) for c in man['clips']}
cat={c['incident_id']:c.get('category') for c in man['clips']}
subs=['nano-direct','omni-direct','gemma4-31b-openrouter','qwen35-9b-openrouter','super-direct','nano-pipeline-nanoground']
def q(x,p):
    x=sorted(x); return x[min(len(x)-1,int(p*(len(x)-1)+.5))] if x else None
out={}
for s in subs:
    R_=[r for k,r in A.items() if k[0]==s]
    oc=collections.Counter(r['outcome'] for r in R_)
    D=[(r,r['incident_field_scores'].get('description') or {}) for r in R_ if r.get('incident_field_scores')]
    sc=[d['score'] for r,d in D if d.get('score') is not None and d.get('judged')]
    scored=[(r,d) for r,d in D if r['outcome']=='scored']
    judged=[d for r,d in scored if d.get('judged') and d.get('score') is not None]
    inval=[(r,d) for r,d in D if r['outcome']!='scored']
    print(s,'rows',len(R_),dict(oc),'| field rows',len(D),'| invalid with field',len(inval),'judged',sum(1 for r,d in inval if d.get('judged')),'pass',sum(1 for r,d in inval if d.get('pass')))
    ps=sum(1 for d in judged if d['pass'])
    v=[d['score'] for d in judged]
    print('   VALID judged',len(judged),'unjudged',len(scored)-len(judged),'pass',ps,round(ps/len(judged),4),'mean',round(st.mean(v),3),'median',q(v,.5),'q',[q(v,x) for x in(.1,.25,.75,.9)],'dist',sorted(collections.Counter(round(x,2) for x in v).items()))
    print('   all rows with verdict pass',sum(1 for r,d in D if d.get('pass')),'/',sum(1 for r,d in D if d.get('pass') is not None),'errors',sum(1 for r,d in D if d.get('error')))
    th={t:round(sum(1 for x in v if x>=t)/len(v),3) for t in (.3,.4,.5,.6,.7)}
    print('   thresholds (exploratory)',th)
    tp=[d['pass'] for r,d in scored if d.get('score') is not None and (r['incident_field_scores'].get('type') or {}).get('pass')]
    tf=[d['pass'] for r,d in scored if d.get('score') is not None and not (r['incident_field_scores'].get('type') or {}).get('pass')]
    print('   pass | type correct',sum(tp),len(tp),'| type wrong',sum(tf),len(tf))
    L=[(len((d.get('predicted') or '').split()),d['score']) for r,d in scored if d.get('score') is not None]
    print('   predicted words median',q([a for a,b in L],.5),'score corr',round(st.correlation([a for a,b in L],[b for a,b in L]),3))
    json.dump(None,open(os.devnull,'w'))
    out[s]=scored
# by category / duration, pooled complete models
allv=[(k,r,d) for s in subs for k,r in A.items() if k[0]==s and r['outcome']=='scored' for d in [r['incident_field_scores'].get('description') or {}] if d.get('score') is not None]
c=collections.defaultdict(lambda:[0,0]); dd=collections.defaultdict(lambda:[0,0])
ds=sorted(dur.values()); t1,t2=q(ds,1/3),q(ds,2/3)
for k,r,d in allv:
    if k[0]=='nano-pipeline-nanoground': continue
    x=c[(k[0],cat.get(k[1]))]; x[0]+=d['pass']; x[1]+=1
    b='short' if dur[k[1]]<=t1 else 'mid' if dur[k[1]]<=t2 else 'long'
    y=dd[(k[0],b)]; y[0]+=d['pass']; y[1]+=1
print('terciles',t1,t2)
for s in subs[:5]:
    print(s,'cat',{kk[1]:f'{v[0]}/{v[1]}' for kk,v in c.items() if kk[0]==s}); print(s,'dur',{kk[1]:f'{v[0]}/{v[1]}' for kk,v in dd.items() if kk[0]==s})
gl=[len(d['expected'].split()) for k,r,d in allv]; print('GT desc words',q(gl,.1),q(gl,.5),q(gl,.9))
# per-clip pass count across complete models
pc=collections.defaultdict(list)
for k,r,d in allv: pc[k[1]].append(d['pass'])
print('clips with any pass',sum(any(v) for v in pc.values()),'of',len(pc),'; clips never passing',sorted(c for c,v in pc.items() if not any(v))[:12])
# pairing check
bad=0
for k,r in A.items():
    d=(r.get('incident_field_scores') or {}).get('description') or {}
    if d.get('expected') and r.get('ground_truth') and d['expected']!=r['ground_truth']['incident'].get('description'): bad+=1
print('GT pairing mismatches',bad)
