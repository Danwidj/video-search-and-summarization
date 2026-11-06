"""Contract validity decomposition, read-only. uv run --frozen python ... from the A5 eval dir."""
import json, glob, collections, os, re, sys
R='/home/hengz/evalv2-data/v2/runs/'
RUNS=['c3-track-a-switchyard','c3-track-a-switchyard-recovery','c3-track-a-switchyard-recovery-a5a','c3-track-a-openrouter']
def obj(run,ref):
    k,h=ref.split(':'); p=glob.glob(R+run+f'/store/objects/{k}/{h[:2]}/{h}*')
    return json.load(open(p[0]))['payload'] if p else None
final={}; att=collections.defaultdict(list)
for run in RUNS:
    for l in open(R+run+'/attempts.jsonl'):
        a=json.loads(l); a['_run']=run; att[(a['subject'],a['item_id'],a['repeat'])].append(a)
    for l in open(R+run+'/checkpoint.jsonl'):
        c=json.loads(l); c['_run']=run; k=(c['subject'],c['item_id'],c['repeat'])
        final[k]=c
subs=['nano-direct','omni-direct','gemma4-31b-openrouter','qwen35-9b-openrouter','super-direct']
if len(sys.argv)>1 and sys.argv[1]=='peek':
    k=[k for k,c in final.items() if c['outcome']=='parse_failure'][0]; c=final[k]
    print(k,json.dumps(obj(c['_run'],c['prediction_ref']))[:1500] if c.get('prediction_ref') else c)
    a=att[k][-1]; print(a.get('response_ref')); r=obj(a['_run'],a['response_ref']); print(json.dumps(r)[:900])
    k=[k for k,c in final.items() if c['outcome']=='contract_invalid'][0]; c=final[k]; print(k,json.dumps(obj(c['_run'],c['prediction_ref']))[:1800])
    for k,c in final.items():
        if c['outcome']=='http_error':
            a=att[k][-1]; print(k,a.get('status'),a.get('failure_kind'),str(obj(a['_run'],a['response_ref']) if a.get('response_ref') else a)[:400]); break
if len(sys.argv)==1:
    # planned items: 55 clips x 2
    clips=sorted({k[1] for k in final if k[0]=='nano-direct'})
    planned=[(c,r) for c in clips for r in (1,2)]
    a1=[json.loads(l) for l in open(R+'c3-track-a-switchyard/amendment-a1-records.jsonl')] if os.path.exists(R+'c3-track-a-switchyard/amendment-a1-records.jsonl') else []
    print('A1 records',[(x['subject'],x['item_id'],x['repeat'],x['outcome']) for x in a1])
    tot={}
    for s in subs:
        C=collections.Counter(); V=collections.Counter(); FR=collections.Counter(); http=collections.Counter()
        ex=collections.defaultdict(list)
        for c,r in planned:
            k=(s,c,r); f=final.get(k); A=att.get(k,[])
            if f is None:
                ok=[x for x in A]
                if any(x['subject']==s and x['item_id']==c and x['repeat']==r for x in a1): C['A1 crash record (model replied; huge-integer output)']+=1; continue
                if not A: C['no attempt yet (never sent: open/queued)']+=1
                else: C['no final row: last attempt '+A[-1]['outcome']]+=1
                continue
            o=f['outcome']
            if o=='scored': C['valid']+=1; continue
            if o in('contract_invalid','parse_failure'):
                p=obj(f['_run'],f['prediction_ref']); val=p['validation']; fr=p.get('finish_reason'); FR[(o,fr)]+=1
                codes=sorted({v['code'] for v in val.get('core_violations',[])})
                for v in val.get('core_violations',[]): V[v['code']]+=1
                C[f'{o}: '+'+'.join(codes[:3])+(f' (finish {fr})' if fr!='stop' else '')]+=1
                if len(ex[o])<2: ex[o].append((c,r,[ (v['code'],v.get('path'),v.get('message','')[:90]) for v in val.get('core_violations',[])][:3]))
                continue
            la=A[-1] if A else {}
            C[f'infra final: {o} status {la.get("status")}']+=1
        print('\n==',s); 
        for k_,v in C.most_common(): print('  ',v,k_)
        print('   finish',dict(FR)); print('   violation counts',V.most_common(10)); print('   ex',dict(ex))
    for k_,c in final.items():
        if c['outcome']=='http_error':
            a=att[k_][-1]
            r=obj(a['_run'],a['response_ref']) if a.get('response_ref') else None
            print('HTTP',k_,a.get('status'),str(r)[:220]) 
