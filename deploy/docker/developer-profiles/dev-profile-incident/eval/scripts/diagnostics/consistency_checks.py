"""Parser/policy consistency and valid-only views. python3 ... read-only."""
exec(open('/home/hengz/evalv2-data/v2/diagnostics/description_audit.py').read().split("subs=[")[0])
import collections, glob, json
subs=['nano-direct','omni-direct','gemma4-31b-openrouter','qwen35-9b-openrouter','super-direct']
print('response_format / settings / prompt per subject')
for run in ('c3-track-a-switchyard','c3-track-a-switchyard-recovery-a5a','c3-track-a-openrouter'):
    seen=collections.Counter()
    for l in open(R+run+'/checkpoint.jsonl'):
        c=json.loads(l); k,h=c['ref'].split(':'); p=glob.glob(R+run+f'/store/objects/{k}/{h[:2]}/{h}*')[0]
        s=(json.load(open(p))['payload'].get('provenance') or {}).get('stages',{}).get('p1')
        if not s: continue
        seen[(c['subject'],s['prompt_sha256'][:8],s['response_format_sha256'][:8],s['settings_sha256'][:8],s['contract_version'])]+=1
    print(run,seen)
print('valid outputs with a window beyond the clip duration (should be 0 if one policy applied):')
for s in subs:
    n=0;t=0
    for k,r in A.items():
        if k[0]!=s or r['outcome']!='scored': continue
        t+=1; f=r['incident_field_scores']; e=f['end_timestamp'].get('predicted'); st_=f['start_timestamp'].get('predicted')
        if (e is not None and e>dur[k[1]]+1) or (st_ is not None and st_>dur[k[1]]+1): n+=1
    print(' ',s,n,'of',t)
pre=lambda c: re.match(r'[A-Za-z]+',c).group(0)
print('valid-only rates: description, start5, end5; end-to-end of 110')
for s in subs:
    V=[r for k,r in A.items() if k[0]==s and r['outcome']=='scored']
    f=lambda name:sum(1 for r in V if (r['incident_field_scores'].get(name) or {}).get('pass'))
    n=len(V); print(' ',s,n,{x:(f(x),round(f(x)/n,3),round(f(x)/110,3)) for x in('description','start_timestamp','end_timestamp','type')})
    c=collections.defaultdict(lambda:[0,0])
    for k,r in A.items():
        if k[0]==s and r['outcome']=='scored':
            d=r['incident_field_scores']['description']
            if d.get('pass') is not None: c[pre(k[1])][0]+=d['pass']; c[pre(k[1])][1]+=1
    print('    by category',{a:f'{b[0]}/{b[1]}' for a,b in sorted(c.items())})
common=[(c,rp) for c in sorted({k[1] for k in A}) for rp in (1,2) if all(A.get((s,c,rp),{}).get('outcome')=='scored' for s in subs[:4])]
print('clip-repeats valid for all four complete models',len(common),'clips',len({c for c,_ in common}))
for s in subs[:4]:
    P=[A[(s,c,rp)]['incident_field_scores'] for c,rp in common]
    g=lambda n:sum(1 for x in P if (x.get(n) or {}).get('pass'))
    print(' ',s,{n:round(g(n)/len(P),3) for n in('description','type','start_timestamp','end_timestamp')})
# description by predicted length tertile pooled, and mean GT length vs pass
rows=[(len(r['incident_field_scores']['description']['expected'].split()),r['incident_field_scores']['description']['pass']) for k,r in A.items() if k[0] in subs[:4] and r['outcome']=='scored' and r['incident_field_scores']['description'].get('pass') is not None]
rows.sort(); n=len(rows)
for a,b,lab in ((0,n//3,'short GT'),(n//3,2*n//3,'mid GT'),(2*n//3,n,'long GT')):
    x=rows[a:b]; print(lab,x[0][0],'-',x[-1][0],'words',sum(p for _,p in x),len(x),round(sum(p for _,p in x)/len(x),3))
