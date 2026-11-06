import sys,json,glob,collections,statistics
sys.dont_write_bytecode=True
E_="/home/hengz/vss-wt-c3e/deploy/docker/developer-profiles/dev-profile-incident/eval"
sys.path.insert(0,E_)
import numpy as np
from evalv2 import cluster_bootstrap as cb
RUNS="/home/hengz/evalv2-data/v2/runs/"
SC="/scoring/evalv2-score-stage-v3/primary/%s-videos.jsonl"
def rows(run,mode='live'):
    return [json.loads(l) for l in open(RUNS+run+SC%mode)]
def trackA(mode):
    best={}
    for run in ('c1a','c1a-recovery'):
        for r in rows(run,mode):
            k=(r['subject'],r['incident_id'],r['repeat']); o=best.get(k)
            if o is None or o['outcome'] not in('scored','contract_invalid','parse_failure'): best[k]=r
    return best
def art(run='c1b'):
    out={}
    for l in open(RUNS+run+'/checkpoint.jsonl'):
        c=json.loads(l)
        ref=c.get('prediction_ref')
        p=None
        if ref:
            h=ref.split(':')[1]; p=json.load(open(glob.glob(RUNS+run+f'/store/objects/pipeline-prediction/{h[:2]}/{h}*')[0]))['payload']
        out[(c['subject'],c['item_id'],c['repeat'])]=(c['outcome'],p)
    return out
MODE=sys.argv[1] if len(sys.argv)>1 else 'live'
A=trackA(MODE); B=rows('c1b',MODE); ART=art()
print('A rows',collections.Counter((k[0],k[2],r['outcome']) for k,r in A.items()))
print('B rows',collections.Counter((r['subject'],r['stage'],r['outcome']) for r in B))
print('art outcomes',collections.Counter((k[0],v[0]) for k,v in ART.items()))
ret={k for k,v in ART.items() if v[1] and v[1].get('p1_retried')}
DUR={}
for f in glob.glob(RUNS+'c1b/store/objects/vss-request/*/*'):
    q=json.load(open(f))['payload']; DUR[q['incident_id']]=q['body'].get('video_duration_seconds')
CTX={}
for l in open(RUNS+'c1b/attempts.jsonl'):
    a=json.loads(l)
    if a['outcome']=='answered':
        h=a['response_ref'].split(':')[1]
        b=json.load(open(glob.glob(RUNS+f'c1b/store/objects/vss-response/{h[:2]}/{h}*')[0]))['payload']['body']
        CTX[(a['subject'],a['item_id'])]=bool(b['experiment']['caption'].get('context_sent'))
print('ctx sent',{s:sorted(c for (x,c),v in CTX.items() if x==s and v) for s in('nano-pipeline','super-pipeline')})
cap={k:(v[1]['caption_pass'] if v[1] else None) for k,v in ART.items()}
print('retried',sorted(ret))
for k,v in list(ART.items())[:0]: pass
print('caption ran',collections.Counter((k[0],bool(c and c.get('ran'))) for k,c in cap.items()), 'none',[k for k,c in cap.items() if c is None])
print('caption calls',{s:sum((c or {}).get('calls',0) for k,c in cap.items() if k[0]==s) for s in('nano-pipeline','super-pipeline')})
# duration per clip
dur={}
for k,v in ART.items():
    if v[1]:
        dur[k[1]]=None
def counts(r,kinds):
    tp=fp=fn=0
    for kd in kinds:
        b=r.get(kd) or {}
        tp+=len(b.get('matches') or []);fp+=len(b.get('unmatched_model') or []);fn+=len(b.get('unmatched_gt') or [])
    return tp,fp,fn
def f1(t):
    tp,fp,fn=t
    d=2*tp+fp+fn
    return 2*tp/d if d else np.nan
def extra(ra,rb,seed=20261027,n=10000):
    """pooled instruments, assets, object(instr+assets), object_score; description judged pass; both-valid keys"""
    a={(r['incident_id'],r['repeat']):r for r in ra if r['outcome']=='scored'}
    b={(r['incident_id'],r['repeat']):r for r in rb if r['outcome']=='scored'}
    ks=sorted(set(a)&set(b)); clips=sorted({r['incident_id'] for r in ra}&{r['incident_id'] for r in rb})
    idx=cb._resample_index(len(clips),n,seed)
    ci={c:i for i,c in enumerate(clips)}
    T=np.zeros((2,len(clips),4,3)) # side, clip, kind(ent,ins,ast,obj), tp fp fn
    D=np.zeros((2,len(clips),2))
    for k in ks:
        for s,R in enumerate((a,b)):
            r=R[k]; i=ci[k[0]]
            for j,kd in enumerate((('entities',),('instruments',),('assets',),('instruments','assets'))):
                T[s,i,j]+=counts(r,kd)
            d=(r['incident_field_scores'].get('description') or {}).get('pass')
        pa=(a[k]['incident_field_scores'].get('description') or {}).get('pass'); pb=(b[k]['incident_field_scores'].get('description') or {}).get('pass')
        if pa is not None and pb is not None:
            D[0,ci[k[0]]]+= (bool(pa),1); D[1,ci[k[0]]]+=(bool(pb),1)
    def F(arr):
        tp,fp,fn=arr[...,0],arr[...,1],arr[...,2]
        den=2*tp+fp+fn
        with np.errstate(all='ignore'): return np.where(den>0,2*tp/den,np.nan)
    pa=F(T[0].sum(0)); pb=F(T[1].sum(0))
    ba=F(T[0][idx].sum(1)); bb=F(T[1][idx].sum(1))  # (n,4)
    res={}
    names=['entities_f1p','instruments_f1','assets_f1','object_f1']
    for j,nm in enumerate(names):
        d=ba[:,j]-bb[:,j]; d=d[~np.isnan(d)]
        res[nm]=dict(a=round(float(pa[j]),4),b=round(float(pb[j]),4),diff=round(float(pa[j]-pb[j]),4),ci=[round(float(x),4) for x in np.percentile(d,[2.5,97.5])],p=round(min(1,2*min((d<=0).mean(),(d>=0).mean())),4))
    sa=(pa[0]+pa[3])/2; sb=(pb[0]+pb[3])/2; d=((ba[:,0]+ba[:,3])/2-(bb[:,0]+bb[:,3])/2); d=d[~np.isnan(d)]
    res['object_score']=dict(a=round(float(sa),4),b=round(float(sb),4),diff=round(float(sa-sb),4),ci=[round(float(x),4) for x in np.percentile(d,[2.5,97.5])],p=round(min(1,2*min((d<=0).mean(),(d>=0).mean())),4))
    n_=D[0,:,1].sum()
    if n_:
        ra_=D[0,:,0].sum()/n_; rb_=D[1,:,0].sum()/n_
        xa=D[0][idx].sum(1); xb=D[1][idx].sum(1)
        with np.errstate(all='ignore'): d=xa[:,0]/xa[:,1]-xb[:,0]/xb[:,1]
        d=d[~np.isnan(d)]
        res['description_pass']=dict(n=int(n_),a=round(float(ra_),4),b=round(float(rb_),4),diff=round(float(ra_-rb_),4),ci=[round(float(x),4) for x in np.percentile(d,[2.5,97.5])],p=round(min(1,2*min((d<=0).mean(),(d>=0).mean())),4))
    return res
def pd(ra,rb):
    x=cb.paired_difference(ra,rb)
    m=x['metrics']
    out={'clips':x['clips'],'both_valid':x['both_valid_runs']}
    for k,v in m.items():
        out[k]={'a':v['a'],'b':v['b'],'diff':v['difference'],'ci':v['ci95'],'ex0':v['excludes_zero']}
    out.update(extra(ra,rb))
    return out
def A_rows(subject,rep): return [dict(r,repeat=1) for k,r in A.items() if k[0]==subject and k[2]==rep]
def B_rows(subject,stage): return [r for r in B if r['subject']==subject and r['stage']==stage]
res={}
# validate: Track A Nano-Super
na=[r for k,r in A.items() if k[0]=='nano-direct']; su=[r for k,r in A.items() if k[0]=='super-direct']
res['VALIDATE TrackA Nano-Super']=pd(na,su)
res['TrackB Nano-Super p1']=pd(B_rows('nano-pipeline','p1'),B_rows('super-pipeline','p1'))
res['TrackB Nano-Super final']=pd(B_rows('nano-pipeline','final')+[r for r in B_rows('nano-pipeline','p1') if r['outcome']!='scored'],B_rows('super-pipeline','final')+[r for r in B_rows('super-pipeline','p1') if r['outcome']!='scored'])
for m,(sa,sb) in {'Nano':('nano-direct','nano-pipeline'),'Super':('super-direct','super-pipeline')}.items():
    keep=lambda rows,sub: [r for r in rows if sub=='all' or (sub=='cap' and CTX.get((sb,r['incident_id']))) or (sub=='nocap' and DUR[r['incident_id']]<=30)]
    noret=lambda rows:[r for r in rows if (sb,r['incident_id'],1) not in ret]
    capclips={k[1] for k,c in cap.items() if k[0]==sb and c and c.get('ran')}
    for sub in ('all','cap','nocap'):
        for rep in (1,2):
            a=noret(keep(A_rows(sa,rep),sub))
            p=noret(keep(B_rows(sb,'p1'),sub))
            failed=[r for r in p if r['outcome']!='scored']
            f=noret(keep(B_rows(sb,'final'),sub))+failed
            res[f'{m} B.p1 - A.rep{rep} [{sub}]']=pd(p,a)
            res[f'{m} B.final - A.rep{rep} [{sub}]']=pd(f,a)
    for sub in ('all','cap','nocap'):
        a1=keep(A_rows(sa,1),sub); a2=keep(A_rows(sa,2),sub)
        res[f'{m} A.rep2 - A.rep1 [{sub}] (noise floor)']=pd(a2,a1)
    res[f'{m} ALLRUNS B.p1 - A.rep1 (no exclusions)']=pd(B_rows(sb,'p1'),A_rows(sa,1))
    res[f'{m} ALLRUNS B.p1 - A.rep2 (no exclusions)']=pd(B_rows(sb,'p1'),A_rows(sa,2))
    # zoom pooled
    failed=[r for r in B_rows(sb,'p1') if r['outcome']!='scored']
    res[f'{m} B.final - B.p1_agent (zoom)']=pd(B_rows(sb,'final')+failed,B_rows(sb,'p1_agent')+failed)
json.dump(res,open(sys.argv[2],'w'),indent=0)
def fm(v):
    if not isinstance(v,dict): return str(v)
    return f"{v.get('a')}|{v.get('b')} d={v.get('diff')} ci={v.get('ci')}"+(f" p={v['p']}" if 'p' in v else '')+(f" n={v['n']}" if 'n' in v else '')
for k,v in res.items():
    print('##',k,'clips',v['clips'],'both',v['both_valid'])
    for m in ('contract_valid','type_accuracy','severity_mae','severity_exact','severity_qwk','start_mae_s','end_mae_s','entities_f1','instruments_f1','assets_f1','object_f1','object_score','description_pass'):
        if m in v: print('  ',m,fm(v[m]))
