#!/usr/bin/env python3
"""Read-only diagnostic of C3 timestamp and severity scoring. Standard library only; no model or network call.

Run:  nice -n 19 python3 -I /home/hengz/evalv2-data/v2/diagnostics/timestamps_severity.py
Reads the scored rows, the run stores, the frozen GT, the manifest and the chart CSV. Writes only the generated
block of timestamps-severity.md (between the markers) in this directory. Every number is recomputed from raw rows;
nothing is imported from the eval package, so it is an independent check of the scorer.
"""
import collections, csv, json, math, random, re, statistics as st, sys
from pathlib import Path

ROOT = Path('/home/hengz/evalv2-data')
RUNS = ROOT / 'v2/runs'
EVAL = Path('/home/hengz/vss-wt-c3a5/deploy/docker/developer-profiles/dev-profile-incident/eval')
CSV = Path('/home/hengz/vss-wt-c3e/deploy/docker/developer-profiles/dev-profile-incident/eval/methodology/presentation/data/d1_incident_extraction.csv')
REPORT = Path(__file__).resolve().parent / 'timestamps-severity.md'
SCORE = 'scoring/evalv2-score-stage-v3/primary/'
SW = ['c3-track-a-switchyard', 'c3-track-a-switchyard-recovery', 'c3-track-a-switchyard-recovery-a5a']
OR = ['c3-track-a-openrouter']
OUTPUT = {'scored', 'contract_invalid', 'parse_failure'}
SUBJECTS = ['nano-direct', 'super-direct', 'omni-direct', 'gemma4-31b-openrouter', 'qwen35-9b-openrouter']
SHORT = {'nano-direct': 'Nano', 'super-direct': 'Super', 'omni-direct': 'Omni', 'gemma4-31b-openrouter': 'Gemma',
         'qwen35-9b-openrouter': 'Qwen', 'nano-pipeline-nanoground': 'NanoPipe'}
COMPLETE = ['nano-direct', 'omni-direct', 'gemma4-31b-openrouter', 'qwen35-9b-openrouter']
BOOT, SEED, TOL = 2000, 20261027, 5
OUT = []


def say(*a): OUT.append(' '.join(str(x) for x in a))
def h(t, lvl=3): say(''); say('#' * lvl + ' ' + t); say('')
def table(head, rows):
    say('| ' + ' | '.join(str(x) for x in head) + ' |'); say('|' + '---|' * len(head))
    for r in rows: say('| ' + ' | '.join(fmt(x) for x in r) + ' |')
    say('')
def fmt(x):
    if x is None: return '-'
    if isinstance(x, float): return f'{x:.3f}'.rstrip('0').rstrip('.') if abs(x) < 1000 else f'{x:.0f}'
    return str(x)
def mean(v): return sum(v) / len(v) if v else None
def med(v): return st.median(v) if v else None
def q(v, p):
    if not v: return None
    s = sorted(v); i = p * (len(s) - 1); a = int(i); b = min(a + 1, len(s) - 1)
    return s[a] + (s[b] - s[a]) * (i - a)
def rate(a, b): return a / b if b else None


# ---------- load ----------
gt_file = json.loads((ROOT / 'ground_truth/ground-truth-v1.0/ground_truth.json').read_text())
GT = {(r.get('Incident_ID (P_key)')): r for r in gt_file['sheets']['gt_incidents']}
SPLIT = json.loads((ROOT / 'ground_truth/ground-truth-v1.0/split-v2.json').read_text())
MAN = {c['incident_id']: c for c in json.loads((EVAL / 'eval_reproducibility/dataset-manifest-v1.json').read_text())['clips']}
TEST, DEV = SPLIT['test'], SPLIT['dev']
CAT = {c: cat for cat, hv in SPLIT['by_category'].items() for half in ('dev', 'test') for c in hv[half]}
D = {c: MAN[c]['duration_seconds'] for c in MAN}
sd = sorted(TEST, key=lambda c: D[c])
T1, T2 = D[sd[len(sd) // 3 - 1]], D[sd[2 * len(sd) // 3 - 1]]
def tert(c): return 'short' if D[c] <= T1 else ('mid' if D[c] <= T2 else 'long')


def lines(p): return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]
def score_path(run):
    live = RUNS / run / SCORE / 'live-videos.jsonl'
    return live if live.exists() else RUNS / run / SCORE / 'offline-videos.jsonl'
def obj(run, ref):
    k, x = ref.split(':'); return json.loads((RUNS / run / 'store/objects' / k / x[:2] / f'{x}.json').read_text())['payload']


def store_extras(run):
    """(subject, clip, repeat) -> raw reply fields from the run store (read-only)."""
    att = {}
    for a in lines(RUNS / run / 'attempts.jsonl'): att[a.get('work_key')] = a
    ex = {}
    for c in lines(RUNS / run / 'checkpoint.jsonl'):
        k = (c['subject'], c['item_id'], c['repeat']); e = {'run': run}
        a = att.get(c['key']) or {}
        e['prompt_tokens'] = (a.get('tokens') or {}).get('prompt')
        if a.get('response_ref'):
            try: e['provider'] = obj(run, a['response_ref']).get('provider')
            except FileNotFoundError: pass
        if c.get('prediction_ref'):
            p = obj(run, c['prediction_ref'])
            e['finish'] = p.get('finish_reason'); e['raw'] = p.get('raw')
            v = p.get('validation') or {}
            e['codes'] = sorted({x.get('code') for x in v.get('core_violations') or []})
        ex[k] = e
    return ex


def salvage(raw):
    """Start, end, severity from a reply that failed the contract. Diagnostic only; never a score."""
    if not raw: return None, None, None, None
    try:
        i = json.loads(raw)['incident']; return i.get('start_timestamp'), i.get('end_timestamp'), i.get('severity_level'), 'json'
    except Exception:
        g = lambda n: (lambda m: int(m.group(1)) if m and len(m.group(1)) < 7 else None)(re.search(rf'"{n}"\s*:\s*(\d+)', raw))
        return g('start_timestamp'), g('end_timestamp'), g('severity_level'), 'regex'


def merged(runs, stage='p1'):
    best = {}; ex = {}
    for run in runs:
        for r in lines(score_path(run)):
            if r.get('stage', 'p1') != stage: continue
            k = (r['subject'], r['incident_id'], r['repeat'])
            if k not in best or best[k]['outcome'] not in OUTPUT: best[k] = {**r, '_run': run}
        if stage == 'p1' and (RUNS / run / 'attempts.jsonl').exists() and not run.startswith('c3-track-b'):
            for k, v in store_extras(run).items():
                if k not in ex or ex[k].get('raw') is None: ex[k] = v
        a = RUNS / run / 'amendment-a1-records.jsonl'
        if a.exists() and stage == 'p1':
            for x in lines(a):
                k = (x['subject'], x['item_id'], x['repeat'])
                best.setdefault(k, {'subject': x['subject'], 'incident_id': x['item_id'], 'repeat': x['repeat'],
                                    'outcome': x['outcome'], 'amendment': 'A1', 'incident_field_scores': {}, '_run': run})
    return best, ex


def norm(r, e):
    f = r.get('incident_field_scores') or {}; c = r['incident_id']; g = GT[c]
    s = lambda n, k: (f.get(n) or {}).get(k)
    rs, re_, rv, how = salvage((e or {}).get('raw'))
    return {'subject': r['subject'], 'clip': c, 'rep': r['repeat'], 'outcome': r['outcome'], 'valid': r['outcome'] == 'scored',
            'gs': int(g['Start_Timestamp']), 'ge': int(g['End_Timestamp']), 'gv': int(g['Severity_Level']), 'D': D[c],
            'cat': CAT[c], 'tert': tert(c), 'ps': s('start_timestamp', 'predicted'), 'pe': s('end_timestamp', 'predicted'),
            'pv': s('severity_level', 'predicted'), 'pass_s': s('start_timestamp', 'pass'), 'pass_e': s('end_timestamp', 'pass'),
            'pass_v': s('severity_level', 'pass'), 'row_gs': s('start_timestamp', 'expected'), 'row_ge': s('end_timestamp', 'expected'),
            'row_gv': s('severity_level', 'expected'), 'pred_incident': (r.get('prediction') or {}).get('incident') or {},
            'rs': rs, 're': re_, 'rv': rv, 'how': how, 'codes': (e or {}).get('codes') or [], 'finish': (e or {}).get('finish'),
            'tok': (e or {}).get('prompt_tokens'), 'provider': (e or {}).get('provider'), 'run': r['_run'], 'amend': r.get('amendment')}


b1, e1 = merged(SW); b2, e2 = merged(OR)
ROWS = [norm(r, {**e1, **e2}.get(k)) for k, r in {**b1, **b2}.items()]
BY = collections.defaultdict(list)
for r in ROWS: BY[r['subject']].append(r)
cb, _ = merged(['c3-track-b-contingency-nano-grounding'], 'p1'); cf, _ = merged(['c3-track-b-contingency-nano-grounding'], 'final')
CONT = {'p1': [norm(r, None) for r in cb.values()], 'final': [norm(r, None) for r in cf.values()]}
CSVROWS = {(r['subject'], r['stage']): r for r in csv.DictReader(CSV.open()) if r['split'] == 'test-55'}
def V(s): return [r for r in BY[s] if r['valid']]

# ---------- 0. integrity ----------
h('G0. Integrity checks (row against frozen GT, manifest and raw reply)')
bad = collections.Counter()
for r in ROWS + CONT['p1'] + CONT['final']:
    if r['amend']: continue
    if r['row_gs'] != r['gs']: bad['row GT start != frozen GT'] += 1
    if r['row_ge'] != r['ge']: bad['row GT end != frozen GT'] += 1
    if r['row_gv'] != r['gv']: bad['row GT severity != frozen GT'] += 1
    if r['ps'] is not None and r['pass_s'] != (abs(r['ps'] - r['gs']) <= TOL): bad['start pass != |e|<=5'] += 1
    if r['pe'] is not None and r['pass_e'] != (abs(r['pe'] - r['ge']) <= TOL): bad['end pass != |e|<=5'] += 1
    if r['ps'] is None and r['pass_s']: bad['missing start passed'] += 1
    if r['pv'] is not None and bool(r['pass_v']) != (r['pv'] == r['gv']): bad['severity pass != exact'] += 1
    i = r['pred_incident']
    if r['valid']:
        if i.get('start_timestamp') != r['ps'] or i.get('end_timestamp') != r['pe'] or i.get('severity_level') != r['pv']:
            bad['scored value != prediction.incident'] += 1
        if r['ps'] is None or r['pe'] is None or r['pv'] is None: bad['valid row missing a field'] += 1
        if not all(isinstance(x, int) for x in (r['ps'], r['pe'], r['pv'])): bad['non-integer predicted'] += 1
        if not (0 <= r['ps'] < r['D'] + 1 and 0 <= r['pe'] < r['D'] + 1): bad['valid row outside video bound'] += 1
        if r['pe'] < r['ps']: bad['valid row end<start'] += 1
    elif r['ps'] is not None or r['pv'] is not None: bad['invalid row carries a scored value'] += 1
say('Mismatches:', dict(bad) or 'none', f"(over {len(ROWS)} Track A rows and {len(CONT['p1']) + len(CONT['final'])} contingency stage rows)")
say('')
g = gt_file['sheets']['gt_incidents']
ids = [r['Incident_ID (P_key)'] for r in g]
say(f"GT rows {len(g)}, unique ids {len(set(ids))} (one incident per clip). Non-integer start/end/severity: "
    f"{sum(1 for r in g for k in ('Start_Timestamp', 'End_Timestamp', 'Severity_Level') if float(r[k]) != int(r[k]))}. "
    f"Duration != end-start: {sum(1 for r in g if r['Duration'] != r['End_Timestamp'] - r['Start_Timestamp'])}. "
    f"GT end > manifest duration + 1: {[c for c in ids if GT[c]['End_Timestamp'] >= D[c] + 1]}. GT end > duration: "
    f"{[(c, GT[c]['End_Timestamp'], D[c]) for c in TEST if GT[c]['End_Timestamp'] > D[c]]}.")
fn = collections.Counter()
for c in ids:
    a = GT[c]['Filename'] or ''; b = MAN[c]['r2_key']
    fn[('demo' in a, 'demo' in b)] += 1
say(''); say(f"GT Filename demo flag vs manifest r2_key demo flag (gt, key): {dict(fn)}; mismatched clips: "
    f"{[c for c in ids if ('demo' in (GT[c]['Filename'] or '')) != ('demo' in MAN[c]['r2_key'])]}")
say(''); say(f"Zero-length GT windows on test: {[c for c in TEST if GT[c]['End_Timestamp'] == GT[c]['Start_Timestamp']]}. "
    f"Duration tertile cuts on the 55 test clips: short <= {T1:.1f} s, mid <= {T2:.1f} s; max {max(D[c] for c in TEST):.1f} s; median {med([D[c] for c in TEST]):.1f} s.")

# ---------- A1 denominators ----------
h('A1. Denominators and reconciliation with the chart CSV (start and end, ±5 s)')
head = ['model', 'planned', 'rows', 'valid', 'contract_invalid', 'parse_failure', 'http_error', 'not run', 'start pass', 'CSV n', 'pass/CSV n', 'CSV acc', 'pass/valid', 'pass/planned', 'start MAE', 'CSV MAE', 'start med', 'CSV med', 'end pass', 'end pass/CSV n', 'CSV end acc', 'end pass/valid', 'end pass/planned', 'end MAE', 'CSV end MAE']
tb = []
for s in SUBJECTS:
    rows = BY[s]; oc = collections.Counter(r['outcome'] for r in rows); v = V(s); c = CSVROWS[(s, 'p1')]
    n_out = sum(1 for r in rows if r['outcome'] in OUTPUT)
    ps = sum(1 for r in rows if r['pass_s']); pe = sum(1 for r in rows if r['pass_e'])
    es = [abs(r['ps'] - r['gs']) for r in v]; ee = [abs(r['pe'] - r['ge']) for r in v]
    tb.append([SHORT[s], 110, len(rows), oc['scored'], oc['contract_invalid'], oc['parse_failure'], oc['http_error'], 110 - len(rows),
               ps, int(c['start_timestamp_n']), rate(ps, n_out), float(c['start_timestamp_acc']), rate(ps, len(v)), ps / 110, mean(es), float(c['start_mae_s']), med(es), float(c['start_median_s']),
               pe, rate(pe, n_out), float(c['end_timestamp_acc']), rate(pe, len(v)), pe / 110, mean(ee), float(c['end_mae_s'])])
table(head, tb)
say('Super rows by run:', dict(collections.Counter(r['run'] for r in BY['super-direct'])), '; Super clips:', len({r['clip'] for r in BY['super-direct']}), 'with both repeats:', sum(1 for c, n in collections.Counter(r['clip'] for r in BY['super-direct']).items() if n == 2))
say('')
sc = collections.Counter(CAT[r['clip']] for r in BY['super-direct'])
say('Super rows by category:', dict(sc), f"; median duration of Super clips {med([r['D'] for r in BY['super-direct']]):.1f} s vs all test {med([D[c] for c in TEST]):.1f} s.")

# ---------- A2 signed error ----------
def errstats(rows, p, g):
    e = [r[p] - r[g] for r in rows]; a = [abs(x) for x in e]
    return [len(e), mean(e), med(e), q(e, .1), q(e, .25), q(e, .75), q(e, .9), mean(a), med(a), q(a, .9), max(a) if a else None,
            rate(sum(x <= 2 for x in a), len(a)), rate(sum(x <= 5 for x in a), len(a)), sum(x == 5 for x in a), rate(sum(x < 5 for x in a), len(a)), rate(sum(x <= 10 for x in a), len(a))]
HEAD = ['n', 'mean', 'median', 'q10', 'q25', 'q75', 'q90', 'MAE', 'medAE', 'p90 AE', 'max AE', '≤2', '≤5', '=5 exactly', '<5', '≤10']
for nm, p, gg in (('start', 'ps', 'gs'), ('end', 'pe', 'ge')):
    h(f'A2. {nm}: signed error (pred - GT, s) on contract-valid rows')
    table(['model'] + HEAD, [[SHORT[s]] + errstats(V(s), p, gg) for s in SUBJECTS] + [[f'NanoPipe {k}'] + errstats([r for r in CONT[k] if r['ps'] is not None], p, gg) for k in ('p1', 'final')])
    h(f'A3. {nm}: by category (n, mean signed, median signed, MAE, medAE, ≤5)')
    cats = sorted(SPLIT['by_category'])
    table(['model'] + cats, [[SHORT[s]] + [(lambda x: f"{x[0]}; {x[1]:+.1f}; {x[2]:+.1f}; {x[7]:.1f}; {x[8]:.1f}; {x[12]:.2f}" if x[0] else '-')(errstats([r for r in V(s) if r['cat'] == c], p, gg)) for c in cats] for s in SUBJECTS])
    h(f'A3. {nm}: by duration tertile (same fields)')
    table(['model', 'short', 'mid', 'long'], [[SHORT[s]] + [(lambda x: f"{x[0]}; {x[1]:+.1f}; {x[2]:+.1f}; {x[7]:.1f}; {x[8]:.1f}; {x[12]:.2f}" if x[0] else '-')(errstats([r for r in V(s) if r['tert'] == t], p, gg)) for t in ('short', 'mid', 'long')] for s in SUBJECTS])

# ---------- A4 boundary effects ----------
h('A4. Clip-boundary effects (valid rows)')
fl = lambda r: math.floor(r['D'])
gs0 = [c for c in TEST if GT[c]['Start_Timestamp'] == 0]; gend = [c for c in TEST if GT[c]['End_Timestamp'] >= math.floor(D[c])]
say(f'GT on 55 test clips: start=0 on {len(gs0)}, end at the last whole second or later on {len(gend)}; GT window/duration median {med([(GT[c]["End_Timestamp"] - GT[c]["Start_Timestamp"]) / D[c] for c in TEST]):.2f}; GT start/duration median {med([GT[c]["Start_Timestamp"] / D[c] for c in TEST]):.2f}; GT end/duration median {med([GT[c]["End_Timestamp"] / D[c] for c in TEST]):.2f}.')
say('')
tb = []
for s in SUBJECTS:
    v = V(s)
    p0 = [r for r in v if r['ps'] == 0]; pe = [r for r in v if r['pe'] >= fl(r)]
    tb.append([SHORT[s], len(v), rate(len(p0), len(v)), rate(sum(r['gs'] == 0 for r in v), len(v)), mean([abs(r['ps'] - r['gs']) for r in p0]), mean([abs(r['ps'] - r['gs']) for r in v if r['ps'] != 0]),
               rate(len(pe), len(v)), rate(sum(r['ge'] >= fl(r) for r in v), len(v)), mean([r['pe'] - r['ge'] for r in pe]), mean([abs(r['pe'] - r['ge']) for r in pe]), mean([abs(r['pe'] - r['ge']) for r in v if r['pe'] < fl(r)]),
               rate(sum(r['pe'] == r['ps'] for r in v), len(v)), med([(r['pe'] - r['ps']) / r['D'] for r in v]), med([(r['ge'] - r['gs']) / r['D'] for r in v])])
table(['model', 'n', 'pred start=0', 'GT start=0 (same rows)', 'MAE when pred=0', 'MAE otherwise', 'pred end≥floor(D)', 'GT end≥floor(D)', 'signed err when pred end≥floor(D)', 'MAE then', 'MAE otherwise', 'pred zero-length', 'pred window/D median', 'GT window/D median'], tb)

# ---------- A5 outliers ----------
h('A5. Outliers: how far a few rows and long clips drive the MAE (valid rows)')
tb = []
for s in SUBJECTS:
    v = V(s); row = [SHORT[s]]
    for p, gg in (('ps', 'gs'), ('pe', 'ge')):
        a = sorted((abs(r[p] - r[gg]) for r in v), reverse=True); k = max(1, round(len(a) * .05))
        row += [mean(a), med(a), sum(a[:k]) / sum(a) if sum(a) else None, mean(a[k:]), mean([abs(r[p] - r[gg]) for r in v if r['D'] <= 60]), mean([abs(r[p] - r[gg]) for r in v if r['D'] > 60]), sum(1 for r in v if r['D'] > 60)]
    tb.append(row)
table(['model', 'start MAE', 'start med', 'top 5% share of error', 'MAE without top 5%', 'MAE D≤60', 'MAE D>60', 'rows D>60', 'end MAE', 'end med', 'top 5% share', 'MAE without top 5%', 'MAE D≤60', 'MAE D>60', 'rows D>60'], tb)
worst = sorted((r for s in SUBJECTS for r in V(s)), key=lambda r: -max(abs(r['ps'] - r['gs']), abs(r['pe'] - r['ge'])))[:15]
table(['model', 'clip', 'rep', 'D', 'GT', 'pred'], [[SHORT[r['subject']], r['clip'], r['rep'], r['D'], f"{r['gs']}-{r['ge']}", f"{r['ps']}-{r['pe']}"] for r in worst])

# ---------- A6 common clips ----------
def clipmean(rows, f):
    d = collections.defaultdict(list)
    for r in rows: d[r['clip']].append(f(r))
    return {c: mean(x) for c, x in d.items()}
vc = {s: {r['clip'] for r in V(s)} for s in SUBJECTS}
C4 = sorted(set.intersection(*[vc[s] for s in COMPLETE])); C5 = sorted(set(C4) & vc['super-direct'])
I4 = set.intersection(*[{(r['clip'], r['rep']) for r in V(s)} for s in COMPLETE])
h('A6. Valid-only timestamps on common clips')
say(f'Clips with at least one valid output in each of Nano, Omni, Gemma, Qwen: {len(C4)} of 55; also Super: {len(C5)}. (clip, repeat) items valid for all four: {len(I4)}. Clip-weighted (mean of a clip\'s valid repeats).')
say('')
say('C4 composition:', dict(collections.Counter(CAT[c] for c in C4)), f'median D {med([D[c] for c in C4]):.1f} s (all test {med([D[c] for c in TEST]):.1f} s); median GT severity {med([GT[c]["Severity_Level"] for c in C4])}.')
say('')
def boot(vals):
    if not vals: return None
    rnd = random.Random(SEED); n = len(vals); m = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
    return [m[int(.025 * BOOT)], m[int(.975 * BOOT) - 1]]
def ci(v): b = boot(v); return f'{mean(v):.3f} [{b[0]:.2f}, {b[1]:.2f}]' if v else '-'
tb = []
for name, cl in (('C4 (4 complete models)', C4), ('C5 (plus Super)', C5)):
    for s in (COMPLETE if name.startswith('C4') else SUBJECTS):
        v = [r for r in V(s) if r['clip'] in cl]
        sp = list(clipmean(v, lambda r: float(abs(r['ps'] - r['gs']) <= TOL)).values()); ep = list(clipmean(v, lambda r: float(abs(r['pe'] - r['ge']) <= TOL)).values())
        sm = list(clipmean(v, lambda r: abs(r['ps'] - r['gs'])).values()); em = list(clipmean(v, lambda r: abs(r['pe'] - r['ge'])).values())
        tb.append([name, SHORT[s], len(v), ci(sp), ci(ep), ci(sm), med(sm), ci(em), med(em)])
table(['set', 'model', 'rows', 'start ≤5 [95% CI]', 'end ≤5', 'start MAE', 'start med (clip means)', 'end MAE', 'end med'], tb)
tb = []
for s in COMPLETE:
    v = [r for r in V(s) if (r['clip'], r['rep']) in I4]
    tb.append([SHORT[s], len(v), rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in v), len(v)), rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in v), len(v)), mean([abs(r['ps'] - r['gs']) for r in v]), mean([abs(r['pe'] - r['ge']) for r in v]), mean([abs(r['pv'] - r['gv']) for r in v])])
table(['model (same clip+repeat items)', 'n', 'start ≤5', 'end ≤5', 'start MAE', 'end MAE', 'severity MAE'], tb)

# ---------- A7 baselines ----------
h('A7. Model-free timestamp baselines on each model\'s own valid rows')
fr_s = med([GT[c]['Start_Timestamp'] / D[c] for c in DEV]); fr_e = med([GT[c]['End_Timestamp'] / D[c] for c in DEV])
say(f'Fitted on the 25 dev clips: start = {fr_s:.3f} x D, end = {fr_e:.3f} x D (rounded). "Whole clip" = start 0, end floor(D).')
say('')
def iou(a, b, c, d):
    ov = max(0, min(b, d) - max(a, c)); un = max(b, d) - min(a, c); return ov / un if un else 0.0
tb = []
for s in SUBJECTS:
    v = V(s); w = [r for r in v if r['ge'] > r['gs']]
    tb.append([SHORT[s], len(v), rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in v), len(v)), rate(sum(r['gs'] <= TOL for r in v), len(v)), rate(sum(abs(round(fr_s * r['D']) - r['gs']) <= TOL for r in v), len(v)), mean([abs(round(fr_s * r['D']) - r['gs']) for r in v]), mean([abs(r['ps'] - r['gs']) for r in v]),
               rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in v), len(v)), rate(sum(abs(fl(r) - r['ge']) <= TOL for r in v), len(v)), rate(sum(abs(round(fr_e * r['D']) - r['ge']) <= TOL for r in v), len(v)), mean([abs(round(fr_e * r['D']) - r['ge']) for r in v]), mean([abs(r['pe'] - r['ge']) for r in v]),
               mean([iou(r['gs'], r['ge'], r['ps'], r['pe']) for r in w]), mean([iou(r['gs'], r['ge'], 0, fl(r)) for r in w]), mean([iou(r['gs'], r['ge'], round(fr_s * r['D']), round(fr_e * r['D'])) for r in w])])
table(['model', 'n', 'start ≤5 model', 'start=0 ≤5', 'start frac ≤5', 'start frac MAE', 'start model MAE', 'end ≤5 model', 'end=D ≤5', 'end frac ≤5', 'end frac MAE', 'end model MAE', 'IoU model', 'IoU whole clip', 'IoU frac'], tb)
h('A7b. Paired clip-level difference, model minus dev-fitted fractional baseline (common C4 clips, 95% CI; negative = model better on MAE)')
tb = []
for s in COMPLETE:
    v = [r for r in V(s) if r['clip'] in C4]
    a = clipmean(v, lambda r: abs(r['ps'] - r['gs']) - abs(round(fr_s * r['D']) - r['gs'])); b = clipmean(v, lambda r: abs(r['pe'] - r['ge']) - abs(round(fr_e * r['D']) - r['ge']))
    tb.append([SHORT[s], len(a), ci(list(a.values())), ci(list(b.values()))])
table(['model', 'clips', 'start MAE diff', 'end MAE diff'], tb)

# ---------- A8 survivorship ----------
h('A8. Selection: what the contract removes, and raw timestamps of invalid replies (diagnostic, never a score)')
tb = []
for s in SUBJECTS:
    rows = [r for r in BY[s] if not r['valid'] and r['outcome'] in OUTPUT]
    codes = collections.Counter(c for r in rows for c in (r['codes'] or ['(none)']))
    fin = collections.Counter(r['finish'] for r in rows)
    tb.append([SHORT[s], len(rows), dict(codes), dict(fin), sum(r['rs'] is not None for r in rows), sum(r['rv'] is not None for r in rows), sum(r['how'] == 'json' for r in rows)])
table(['model', 'invalid outputs', 'core codes (per reply, once each)', 'finish_reason', 'start salvageable', 'severity salvageable', 'full JSON'], tb)
tb = []
for s in SUBJECTS:
    v = V(s); inv = [r for r in BY[s] if not r['valid'] and r['rs'] is not None and r['re'] is not None]
    allp = [(r['ps'], r['pe'], r) for r in v] + [(r['rs'], r['re'], r) for r in inv]
    beyond = [r for r in inv if r['re'] >= r['D'] + 1 or r['rs'] >= r['D'] + 1]
    tb.append([SHORT[s], len(inv), len(beyond), rate(sum(abs(r['rs'] - r['gs']) <= TOL for r in inv), len(inv)), rate(sum(abs(r['re'] - r['ge']) <= TOL for r in inv), len(inv)), mean([abs(r['rs'] - r['gs']) for r in inv]), mean([abs(r['re'] - r['ge']) for r in inv]),
               rate(sum(abs(a - r['gs']) <= TOL for a, b, r in allp), len(allp)), rate(sum(abs(b - r['ge']) <= TOL for a, b, r in allp), len(allp)), mean([abs(a - r['gs']) for a, b, r in allp]), mean([abs(b - r['ge']) for a, b, r in allp]), mean([r['D'] for r in inv]), mean([r['D'] for r in v])])
table(['model', 'invalid with raw start+end', 'of which beyond video', 'raw start ≤5', 'raw end ≤5', 'raw start MAE', 'raw end MAE', 'valid+raw start ≤5', 'valid+raw end ≤5', 'valid+raw start MAE', 'valid+raw end MAE', 'mean D invalid', 'mean D valid'], tb)

# ---------- A9 scale ----------
h('A9. Time scale: units, offset and scale (all replies with raw start and end)')
def ols(x, y):
    n = len(x); mx, my = mean(x), mean(y); sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx; sxy = sum((a - mx) * (c - my) for a, c in zip(x, y)); syy = sum((c - my) ** 2 for c in y)
    return b, my - b * mx, (sxy / math.sqrt(sxx * syy)) if syy and sxx else None
def rk(v):
    s = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]: j += 1
        for k in range(i, j + 1): r[s[k]] = (i + j) / 2
        i = j + 1
    return r
def allrows(s):
    return [(r['ps'], r['pe'], r) if r['valid'] else (r['rs'], r['re'], r) for r in BY[s] if (r['valid'] or (r['rs'] is not None and r['re'] is not None))]
tb = []
for s in SUBJECTS:
    a = allrows(s); e = [x[1] for x in a]; ge = [x[2]['ge'] for x in a]; dd = [x[2]['D'] for x in a]; sv = [x[0] for x in a]; gs = [x[2]['gs'] for x in a]
    v = V(s)
    b, i0, c = ols(ge, e); b2_, i2, c2 = ols(gs, sv)
    tb.append([SHORT[s], len(a), b2_, i2, c2, b, i0, c, ols(rk(dd), rk(e))[2], q(e, .5), q(e, .95), max(e), rate(sum(x / y > 1 for x, y in zip(e, dd)), len(e)), med([x / y for x, y in zip(e, dd)]), max(x / y for x, y in zip(e, dd))])
table(['model', 'n', 'start slope on GT', 'intercept', 'r', 'end slope on GT', 'intercept', 'r', 'Spearman(end, D)', 'end median', 'end p95', 'end max', 'end>D share', 'end/D median', 'end/D max'], tb)
buckets = [(0, 15), (15, 30), (30, 60), (60, 120), (120, 1e9)]
h('A9b. Predicted end (raw) by clip duration: median [max], and prompt tokens median [min-max]', 4)
tb = []
for s in SUBJECTS:
    a = allrows(s); row = [SHORT[s]]
    for lo, hi in buckets:
        x = [y[1] for y in a if lo < y[2]['D'] <= hi]; t = [r['tok'] for r in BY[s] if lo < r['D'] <= hi and r['tok']]
        row.append(f"{len(x)}: {med(x)} [{max(x) if x else '-'}]; tok {med(t)} [{min(t) if t else '-'}-{max(t) if t else '-'}]")
    tb.append(row)
table(['model'] + [f'D {lo}-{hi if hi < 1e9 else "max"}' for lo, hi in buckets], tb)
tb = []
for s in SUBJECTS:
    t = [(r['D'], r['tok']) for r in BY[s] if r['tok'] and r['outcome'] in OUTPUT]
    bb, ii, cc = ols([x[0] for x in t], [x[1] for x in t])
    tb.append([SHORT[s], len(t), len({x[1] for x in t}), min(x[1] for x in t), max(x[1] for x in t), bb, ii, cc, dict(collections.Counter(r['provider'] for r in BY[s]))])
table(['model', 'n', 'distinct prompt_tokens', 'min', 'max', 'tokens per clip second', 'intercept', 'r', 'provider'], tb)
tb = []
for s in SUBJECTS:
    a = allrows(s); best = None
    for K in range(5, 201):
        err = mean([abs(x[1] * x[2]['D'] / K - x[2]['ge']) for x in a])
        if best is None or err < best[1]: best = (K, err)
    tb.append([SHORT[s], best[0], best[1], mean([abs(x[1] - x[2]['ge']) for x in a])])
table(['model', 'in-sample best K in true=pred×D/K (end)', 'end MAE under K', 'end MAE unscaled (same rows)'], tb)

# ---------- A10 repeats ----------
h('A10. Repeat stability at temperature 0 (clips with two valid repeats)')
tb = []
for s in SUBJECTS:
    d = collections.defaultdict(dict)
    for r in V(s): d[r['clip']][r['rep']] = r
    p = [x for x in d.values() if len(x) == 2]
    ds = [abs(x[1]['ps'] - x[2]['ps']) for x in p]; de = [abs(x[1]['pe'] - x[2]['pe']) for x in p]; dv = [abs(x[1]['pv'] - x[2]['pv']) for x in p]
    fl_ = sum((abs(x[1]['ps'] - x[1]['gs']) <= TOL) != (abs(x[2]['ps'] - x[2]['gs']) <= TOL) for x in p)
    tb.append([SHORT[s], len(p), mean(ds), med(ds), max(ds) if ds else None, mean(de), med(de), rate(fl_, len(p)), mean(dv), rate(sum(x == 0 for x in dv), len(dv))])
table(['model', 'clips', 'start |r1-r2| mean', 'median', 'max', 'end |r1-r2| mean', 'median', 'start ±5 verdict flips', 'severity |r1-r2| mean', 'severity identical'], tb)

# ---------- A11 consensus ----------
h('A11. Clip-level consensus: where models agree with each other but not with GT (GT review candidates)')
def cons(p, gk, pk):
    out = []
    for c in TEST:
        v = {s: clipmean([r for r in V(s) if r['clip'] == c], lambda r: r[pk]).get(c) for s in SUBJECTS}
        v = {k: x for k, x in v.items() if x is not None}
        if len(v) < 3: continue
        g = GT[c][p]; vals = sorted(v.values()); m = med(vals)
        same = all((x - g) > TOL for x in vals) or all((g - x) > TOL for x in vals)
        most = sum(abs(x - m) <= TOL for x in vals)
        out.append((c, g, m, len(vals), same, most, vals))
    return out
for p, gk, pk in (('Start_Timestamp', 'gs', 'ps'), ('End_Timestamp', 'ge', 'pe')):
    o = cons(p, gk, pk); hit = [x for x in o if x[4]]; agree = [x for x in hit if x[6][-1] - x[6][0] <= 2 * TOL]
    say(f'{p}: clips with ≥3 models: {len(o)}; every model misses ±5 on the same side: {len(hit)}; of these models within 10 s of each other: {len(agree)}.')
    say('')
    table(['clip', 'cat', 'D', 'GT', 'model median', 'models', 'range', 'all same side'], [[x[0], CAT[x[0]], D[x[0]], x[1], x[2], x[3], f'{x[6][0]:.0f}..{x[6][-1]:.0f}', 'yes'] for x in sorted(hit, key=lambda x: -abs(x[2] - x[1]))])
mm = []
for c in TEST:
    t = re.findall(r'(\d+(?:\.\d+)?)\s*(?:s\b|sec|seconds)', GT[c]['Description'] or '')
    t = [float(x) for x in t]
    if t: mm.append((c, GT[c]['Start_Timestamp'], GT[c]['End_Timestamp'], D[c], min(t), max(t)))
far = [x for x in mm if abs(x[4] - x[1]) > 3 or x[5] > x[2] + 3]
say(f'GT descriptions naming times: {len(mm)} of 55 test clips. Earliest named time more than 3 s from GT start, or latest more than 3 s past GT end: {len(far)}.')
say('')
table(['clip', 'GT start', 'GT end', 'D', 'earliest time in GT text', 'latest time in GT text'], far)
tb = []
ann = collections.defaultdict(list)
for s in COMPLETE:
    for r in V(s): ann[GT[r['clip']]['Labelled_By']].append(r)
for a, v in sorted(ann.items(), key=lambda x: str(x[0])):
    tb.append([a, len({r['clip'] for r in v}), len(v), mean([r['ps'] - r['gs'] for r in v]), mean([r['pe'] - r['ge'] for r in v]), rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in v), len(v)), mean([r['gv'] for r in v]), mean([r['pv'] - r['gv'] for r in v]), mean([abs(r['pv'] - r['gv']) for r in v])])
h('A12. By GT annotator (4 complete models pooled; annotator confounded with category)', 4)
table(['Labelled_By', 'test clips', 'rows', 'start signed', 'end signed', 'start ≤5', 'GT severity mean', 'severity signed', 'severity MAE'], tb)
say('Annotator by category on test clips:', {str(k): dict(collections.Counter(CAT[c] for c in TEST if GT[c]['Labelled_By'] == k)) for k in sorted({GT[c]['Labelled_By'] for c in TEST}, key=str)})

# ---------- B ----------
h('B1. GT severity distribution', 3)
say('Test 55:', dict(sorted(collections.Counter(int(GT[c]['Severity_Level']) for c in TEST).items())), '; dev 25:', dict(sorted(collections.Counter(int(GT[c]['Severity_Level']) for c in DEV).items())))
say('')
table(['category', 'n', '1', '2', '3', '4', '5', 'median'], [[c, len(x)] + [x.count(k) for k in range(1, 6)] + [med(x)] for c in sorted(SPLIT['by_category']) for x in [[int(GT[i]['Severity_Level']) for i in TEST if CAT[i] == c]]])
def qwk(p):
    if not p: return None
    n = len(p); O = [[0] * 5 for _ in range(5)]
    for g, x in p: O[g - 1][x - 1] += 1
    a = [sum(O[i]) for i in range(5)]; b = [sum(O[i][j] for i in range(5)) for j in range(5)]
    num = sum((i - j) ** 2 * O[i][j] for i in range(5) for j in range(5)); den = sum((i - j) ** 2 * a[i] * b[j] / n for i in range(5) for j in range(5))
    return 1 - num / den if den else None
h('B2. Severity on contract-valid rows, against CSV')
tb = []
for s in SUBJECTS:
    v = V(s); e = [r['pv'] - r['gv'] for r in v]; c = CSVROWS[(s, 'p1')]
    tb.append([SHORT[s], len(v), mean([abs(x) for x in e]), float(c['severity_mae_valid']), float(c['severity_mae_valid2']), rate(sum(x == 0 for x in e), len(e)), float(c['severity_exact_valid']), float(c['severity_level_acc']), rate(sum(abs(x) <= 1 for x in e), len(e)), mean(e), sum(x > 0 for x in e), sum(x < 0 for x in e), sum(x == 0 for x in e), qwk([(r['gv'], r['pv']) for r in v]), dict(sorted(collections.Counter(r['pv'] for r in v).items()))])
table(['model', 'n', 'MAE', 'CSV MAE', 'CSV MAE2', 'exact', 'CSV exact', 'CSV severity acc (invalid as miss)', 'within 1', 'mean signed', 'over', 'under', 'exact n', 'QWK', 'predicted levels'], tb)
for s in SUBJECTS + ['NanoPipe final']:
    v = V(s) if s in SUBJECTS else [r for r in CONT['final'] if r['pv'] is not None]
    M = collections.Counter((r['gv'], r['pv']) for r in v)
    h(f'B3. Confusion {SHORT.get(s, s)} (rows GT, columns predicted; n={len(v)}; MAE {mean([abs(r["pv"] - r["gv"]) for r in v]):.3f})', 4)
    table(['GT\\pred', 1, 2, 3, 4, 5, 'row n', 'row MAE', 'row signed'], [[g] + [M[(g, p)] for p in range(1, 6)] + [sum(M[(g, p)] for p in range(1, 6)), mean([abs(r['pv'] - r['gv']) for r in v if r['gv'] == g]), mean([r['pv'] - r['gv'] for r in v if r['gv'] == g])] for g in range(1, 6)])
h('B4. Severity by category on valid rows (n; MAE; signed)')
cats = sorted(SPLIT['by_category'])
table(['model'] + cats, [[SHORT[s]] + [(lambda v: f"{len(v)}; {mean([abs(r['pv'] - r['gv']) for r in v]):.2f}; {mean([r['pv'] - r['gv'] for r in v]):+.2f}" if v else '-')([r for r in V(s) if r['cat'] == c]) for c in cats] for s in SUBJECTS])
h('B5. Baselines on the same rows per model')
dev_med = med([GT[c]['Severity_Level'] for c in DEV]); dev_cat = {c: med([GT[i]['Severity_Level'] for i in DEV if CAT[i] == c]) for c in cats}
test_cat = {c: med([GT[i]['Severity_Level'] for i in TEST if CAT[i] == c]) for c in cats}
say(f'Dev-fitted constant median {dev_med}; dev per-category medians {dev_cat} (fair: no test label). Test per-category medians {test_cat}. "Rows median/mode" and "category oracle" are fitted on the evaluated rows and know the true category, so they are optimistic.')
say('')
def blrow(name, v):
    g = [r['gv'] for r in v]; md = st.median_low(g); mo = collections.Counter(g).most_common(1)[0][0]
    cm = {c: st.median_low([r['gv'] for r in v if r['cat'] == c]) for c in {r['cat'] for r in v}}
    mae = lambda f: mean([abs(f(r) - r['gv']) for r in v])
    ex = lambda f: rate(sum(f(r) == r['gv'] for r in v), len(v))
    return [name, len(v), mae(lambda r: r['pv']), ex(lambda r: r['pv']), mae(lambda r: dev_med), ex(lambda r: dev_med), f'{md}: {mae(lambda r: md):.3f}', f'{mo}: {mae(lambda r: mo):.3f}', mae(lambda r: 2), mae(lambda r: 3), mae(lambda r: dev_cat[r['cat']]), mae(lambda r: cm[r['cat']]), ex(lambda r: cm[r['cat']])]
HB = ['set', 'n', 'model MAE', 'model exact', 'dev median MAE', 'dev median exact', 'rows median', 'rows mode', 'always 2', 'always 3', 'dev cat median', 'cat oracle MAE', 'cat oracle exact']
table(HB, [blrow(SHORT[s], V(s)) for s in SUBJECTS])
table(HB, [blrow(f'{SHORT[s]} on C4', [r for r in V(s) if r['clip'] in C4]) for s in COMPLETE] + [blrow(f'{SHORT[s]} on C5', [r for r in V(s) if r['clip'] in C5]) for s in SUBJECTS])
h('B6. MAE on clips valid for all complete models, clip-weighted, 95% CI, and paired difference to baselines (negative = model better)')
tb = []
for s in COMPLETE:
    v = [r for r in V(s) if r['clip'] in C4]
    a = clipmean(v, lambda r: abs(r['pv'] - r['gv'])); sg = clipmean(v, lambda r: r['pv'] - r['gv'])
    d1 = clipmean(v, lambda r: abs(r['pv'] - r['gv']) - abs(dev_med - r['gv'])); d2 = clipmean(v, lambda r: abs(r['pv'] - r['gv']) - abs(dev_cat[r['cat']] - r['gv']))
    tb.append([SHORT[s], len(a), ci(list(a.values())), ci(list(sg.values())), ci(list(d1.values())), ci(list(d2.values()))])
table(['model', 'clips', 'MAE', 'signed', 'minus dev median', 'minus dev category median'], tb)
tb = []
for s in SUBJECTS:
    v = V(s); d1 = clipmean(v, lambda r: abs(r['pv'] - r['gv']) - abs(dev_med - r['gv'])); d2 = clipmean(v, lambda r: abs(r['pv'] - r['gv']) - abs(dev_cat[r['cat']] - r['gv']))
    tb.append([SHORT[s], len(d1), ci(list(d1.values())), ci(list(d2.values()))])
table(['model (own valid clips)', 'clips', 'minus dev median', 'minus dev category median'], tb)
h('B7. Paired Nano against each model on common clips (clip means, model minus Nano; 95% CI)')
tb = []
for s in ['super-direct', 'omni-direct', 'gemma4-31b-openrouter', 'qwen35-9b-openrouter']:
    a = clipmean(V(s), lambda r: abs(r['pv'] - r['gv'])); b = clipmean(V('nano-direct'), lambda r: abs(r['pv'] - r['gv']))
    k = sorted(set(a) & set(b)); tb.append([SHORT[s], len(k), mean([b[c] for c in k]), mean([a[c] for c in k]), ci([a[c] - b[c] for c in k])])
table(['model', 'shared clips', 'Nano MAE', 'model MAE', 'difference'], tb)
h('B8. Severity of invalid replies (raw, diagnostic only)')
tb = []
for s in SUBJECTS:
    inv = [r for r in BY[s] if not r['valid'] and isinstance(r['rv'], int) and 1 <= r['rv'] <= 5]; v = V(s)
    both = [(r['rv'], r['gv']) for r in inv] + [(r['pv'], r['gv']) for r in v]
    tb.append([SHORT[s], len(inv), mean([abs(r['rv'] - r['gv']) for r in inv]), mean([r['rv'] - r['gv'] for r in inv]), mean([r['gv'] for r in inv]), mean([r['gv'] for r in v]), mean([abs(a - b) for a, b in both]), len(both)])
table(['model', 'invalid with raw severity', 'raw MAE', 'raw signed', 'GT mean on invalid', 'GT mean on valid', 'valid+raw MAE', 'n'], tb)
say(f"GT severity mean of clips by coverage: clips in C4 {mean([GT[c]['Severity_Level'] for c in C4]):.2f}; clips outside C4 {mean([GT[c]['Severity_Level'] for c in TEST if c not in C4]):.2f}.")
h('B9. Clips where the four complete models all err the same way by at least 1 (GT review candidates)')
tb = []
for c in TEST:
    m = {s: clipmean([r for r in V(s) if r['clip'] == c], lambda r: r['pv']).get(c) for s in SUBJECTS}
    m = {k: x for k, x in m.items() if x is not None}
    g = GT[c]['Severity_Level']
    if len(m) >= 3 and (all(x - g >= 1 for x in m.values()) or all(g - x >= 1 for x in m.values())):
        tb.append([c, CAT[c], int(g), len(m), ', '.join(f'{SHORT[k]} {x:g}' for k, x in m.items()), (GT[c]['Description'] or '')[:170].replace('|', '/')])
say(f'{len(tb)} of 55 test clips.')
say('')
table(['clip', 'cat', 'GT', 'models', 'clip-mean predictions', 'GT description (start)'], sorted(tb, key=lambda x: x[1]))
h('B10. Nano: largest over-predictions (GT, predicted, stated reason)')
v = sorted(V('nano-direct'), key=lambda r: -(r['pv'] - r['gv']))[:12]
table(['clip', 'rep', 'GT', 'pred', 'severity_reason'], [[r['clip'], r['rep'], r['gv'], r['pv'], str(r['pred_incident'].get('severity_reason'))[:170].replace('|', '/')] for r in v])
h('B11. Contingency Nano pipeline (55 single runs; not Track A)')
tb = []
for k in ('p1', 'final'):
    v = [r for r in CONT[k] if r['pv'] is not None]; c = CSVROWS.get(('nano-pipeline-nanoground', k)) or {}
    tb.append([k, len(CONT[k]), len(v), mean([abs(r['pv'] - r['gv']) for r in v]), c.get('severity_mae_valid'), mean([r['pv'] - r['gv'] for r in v]), rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in v), len(v)), c.get('start_timestamp_acc'), c.get('start_timestamp_n'), mean([abs(r['ps'] - r['gs']) for r in v]), c.get('start_mae_s'), rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in v), len(v))])
table(['stage', 'rows', 'with values', 'severity MAE', 'CSV', 'signed', 'start ≤5 valid', 'CSV acc', 'CSV n', 'start MAE', 'CSV', 'end ≤5 valid'], tb)


# ---------- extra checks ----------
h('X1. Provider split inside the OpenRouter subjects (same model, routed by availability)')
tb = []
for s in ('gemma4-31b-openrouter', 'qwen35-9b-openrouter'):
    for pv in sorted({r['provider'] for r in BY[s]}, key=str):
        rows = [r for r in BY[s] if r['provider'] == pv]; v = [r for r in rows if r['valid']]
        tb.append([SHORT[s], pv, len(rows), len(v), rate(len(v), len(rows)), mean([r['D'] for r in rows]), med([r['tok'] for r in rows if r['tok']]), rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in v), len(v)), rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in v), len(v)), mean([abs(r['pv'] - r['gv']) for r in v])])
table(['model', 'provider', 'rows', 'valid', 'valid rate', 'mean D', 'median tokens', 'start ≤5 valid', 'end ≤5 valid', 'severity MAE'], tb)
h('X2. Coverage: contract-valid share of planned, by duration tertile and category (the valid sets are not alike)')
ng = {t: sum(tert(c) == t for c in TEST) * 2 for t in ('short', 'mid', 'long')}; cats = sorted(SPLIT['by_category'])
nc = {c: sum(CAT[i] == c for i in TEST) * 2 for c in cats}
table(['model'] + [f'{t} ({ng[t]})' for t in ng] + [f'{c} ({nc[c]})' for c in cats] + ['mean D valid', 'mean GT severity valid'],
      [[SHORT[s]] + [f"{sum(r['tert'] == t for r in V(s))} ({sum(r['tert'] == t for r in V(s)) / ng[t]:.2f})" for t in ng] + [f"{sum(r['cat'] == c for r in V(s))} ({sum(r['cat'] == c for r in V(s)) / nc[c]:.2f})" for c in cats] + [mean([r['D'] for r in V(s)]), mean([r['gv'] for r in V(s)])] for s in SUBJECTS])
h('X3. Invalid windows: how far past the clip, and clock-like values')
tb = []
for s in ('omni-direct', 'gemma4-31b-openrouter'):
    b = [r for r in BY[s] if not r['valid'] and r['re'] is not None and 'WINDOW_BEYOND_VIDEO' in r['codes']]
    m = [max(r['re'], r['rs']) - r['D'] for r in b]
    tb.append([SHORT[s], len(b), med(m), sum(x < 2 for x in m), sum(x < 10 for x in m), sum(x > 1000 for x in m), med([max(r['re'], r['rs']) / r['D'] for r in b]), dict(collections.Counter(r['tert'] for r in b))])
table(['model', 'beyond-video replies', 'median overshoot s', 'overshoot <2 s', '<10 s', '>1000 s', 'median end/D', 'tertile'], tb)
table(['model', 'clip', 'rep', 'D', 'raw start', 'raw end', 'as HH:MM:SS digits', 'as seconds of day'], [[SHORT[r['subject']], r['clip'], r['rep'], r['D'], r['rs'], r['re'], f"{r['re'] // 10000:02d}:{r['re'] // 100 % 100:02d}:{r['re'] % 100:02d}", f"{r['re'] // 3600:02d}:{r['re'] // 60 % 60:02d}:{r['re'] % 60:02d}"] for r in ROWS if r['re'] is not None and r['re'] > 1000])
gv = collections.Counter(x[1] for x in allrows('gemma4-31b-openrouter')); gs_ = collections.Counter(x[0] for x in allrows('gemma4-31b-openrouter'))
say('Gemma raw end, most frequent values:', gv.most_common(12), '; raw start:', gs_.most_common(8))
say('')
for s in SUBJECTS:
    e = [x[1] for x in allrows(s)]; say(f"{SHORT[s]}: share of raw ends ending in 0, 1 or 5: {sum(x % 10 in (0, 1, 5) for x in e) / len(e):.2f}; ending in 1: {sum(x % 10 == 1 for x in e) / len(e):.2f}; n={len(e)}"); say('')
h('X4. Severity: where the errors sit (category, GT to predicted; top cells) and leave-one-clip-out calibration')
for s in SUBJECTS:
    c = collections.Counter((r['cat'], r['gv'], r['pv']) for r in V(s) if r['gv'] != r['pv'])
    say(f"{SHORT[s]}:", '; '.join(f'{k[0]} {k[1]}→{k[2]} ×{n}' for k, n in c.most_common(9))); say('')
tb = []
for s in SUBJECTS:
    v = V(s); e = []
    for r in v:
        tr = [x for x in v if x['clip'] != r['clip']]
        same = [x['gv'] for x in tr if x['pv'] == r['pv']]
        e.append(abs((st.median_low(same) if same else r['pv']) - r['gv']))
    mp = {p: st.median_low([x['gv'] for x in v if x['pv'] == p]) for p in sorted({x['pv'] for x in v})}
    g = [r['gv'] for r in v]; pr = [r['pv'] for r in v]
    cm = {c: st.median_low([x['gv'] for x in v if x['cat'] == c]) for c in {x['cat'] for x in v}}
    tb.append([SHORT[s], len(v), mean([abs(a - b) for a, b in zip(g, pr)]), mean(e), str(mp), ols(rk(g), rk(pr))[2], qwk([(r['gv'], r['pv']) for r in v]), qwk([(r['gv'], cm[r['cat']]) for r in v]), qwk([(r['gv'], int(dev_cat[r['cat']])) for r in v])])
table(['model', 'n', 'MAE', 'MAE after remap (leave-one-clip-out, per-predicted-level median)', 'in-sample map pred→GT', 'Spearman', 'QWK', 'QWK of category oracle', 'QWK of dev category median'], tb)
h('X5. GT text of review candidates and road-accident annotators')
for c in ('Animal007', 'Animal006', 'Explosion004', 'RoadAccidents008', 'Explosion027', 'Assault020', 'Animal013', 'RoadAccidents039', 'Burglary005', 'RoadAccidents024'):
    g = GT[c]; say(f"- **{c}** D {D[c]:.1f}, GT {int(g['Start_Timestamp'])}-{int(g['End_Timestamp'])}, severity {int(g['Severity_Level'])}, by {g['Labelled_By']}: {g['Description']}"); say('')
    say('  Models: ' + '; '.join(f"{SHORT[s]} {r['ps']}-{r['pe']}" for s in SUBJECTS for r in V(s) if r['clip'] == c and r['rep'] == min(x['rep'] for x in V(s) if x['clip'] == c))); say('')
tb = []
for who in sorted({GT[c]['Labelled_By'] for c in TEST if CAT[c] == 'Road Accident'}):
    v = [r for s in COMPLETE for r in V(s) if r['cat'] == 'Road Accident' and GT[r['clip']]['Labelled_By'] == who]
    tb.append([who, len({r['clip'] for r in v}), len(v), med([r['pe'] - r['ge'] for r in v]), mean([r['pe'] - r['ge'] for r in v]), med([(GT[c]['End_Timestamp'] - GT[c]['Start_Timestamp']) / D[c] for c in TEST if CAT[c] == 'Road Accident' and GT[c]['Labelled_By'] == who]), rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in v), len(v)), mean([r['pv'] - r['gv'] for r in v])])
table(['Road Accident annotator', 'clips', 'rows', 'end signed median', 'end signed mean', 'GT window/D median', 'end ≤5', 'severity signed'], tb)
h('X6. What ±5 s means on these clips')
hw = [10 / D[c] for c in TEST]
say(f"A ±5 s band spans 10 s. Share of the clip it covers: median {med(hw):.2f}; clips where it covers ≥50%: {sum(x >= .5 for x in hw)} of 55; ≥25%: {sum(x >= .25 for x in hw)}. Clips where D/64 > 5 s: {sum(D[c] / 64 > 5 for c in TEST)}; D/28 > 5 s (Gemma's self-reported budget): {sum(D[c] / 28 > 5 for c in TEST)} {[c for c in TEST if D[c] / 28 > 5]}.")
say('')
tb = []
for s in SUBJECTS:
    v = V(s)
    row = [SHORT[s], len(v)]
    for p, gg in (('ps', 'gs'), ('pe', 'ge')):
        row += [rate(sum(abs(r[p] - r[gg]) <= 2 for r in v), len(v)), rate(sum(abs(r[p] - r[gg]) <= TOL for r in v), len(v)), rate(sum(abs(r[p] - r[gg]) <= max(1, .05 * r['D']) for r in v), len(v)), rate(sum(abs(r[p] - r[gg]) <= max(1, .1 * r['D']) for r in v), len(v))]
    row += [rate(sum(iou(r['gs'], r['ge'], r['ps'], r['pe']) >= .5 for r in v), len(v))]
    tb.append(row)
table(['model', 'n', 'start ≤2', 'start ≤5', 'start ≤5% D', 'start ≤10% D', 'end ≤2', 'end ≤5', 'end ≤5% D', 'end ≤10% D', 'IoU≥0.5'], tb)
h('X7. All models on the 26 clips Super answered (valid rows, clip-weighted)')
S26 = sorted({r['clip'] for r in BY['super-direct']}); tb = []
for s in SUBJECTS:
    v = [r for r in V(s) if r['clip'] in S26]; a = clipmean(v, lambda r: float(abs(r['ps'] - r['gs']) <= TOL)); b = clipmean(v, lambda r: float(abs(r['pe'] - r['ge']) <= TOL)); c = clipmean(v, lambda r: abs(r['pv'] - r['gv'])); d = clipmean(v, lambda r: abs(r['ps'] - r['gs']))
    tb.append([SHORT[s], len(a), mean(list(a.values())), mean(list(b.values())), mean(list(d.values())), mean(list(c.values()))])
table(['model', 'clips (of 26) with a valid output', 'start ≤5', 'end ≤5', 'start MAE', 'severity MAE'], tb)
say('Super repeats present:', dict(collections.Counter(r['rep'] for r in BY['super-direct'])))
h('X8. Contingency denominators: same predictions, two CSV accuracies')
a = {(r['clip'], r['rep']): r for r in CONT['p1'] if r['valid']}; b = {(r['clip'], r['rep']): r for r in CONT['final']}
same = sum(1 for k in a if k in b and (a[k]['ps'], a[k]['pe'], a[k]['pv']) == (b[k]['ps'], b[k]['pe'], b[k]['pv']))
say(f"p1 scored {len(a)}, final {len(b)}, identical start/end/severity on {same}. p1 outcomes: {dict(collections.Counter(r['outcome'] for r in CONT['p1']))}.")
say('')
tb = []
for f, p in (('start_timestamp', 'pass_s'), ('end_timestamp', 'pass_e'), ('severity_level', 'pass_v')):
    c1 = CSVROWS[('nano-pipeline-nanoground', 'p1')]; c2 = CSVROWS[('nano-pipeline-nanoground', 'final')]
    n1 = sum(1 for r in CONT['p1'] if r[p]); n2 = sum(1 for r in CONT['final'] if r[p])
    tb.append([f, n1, c1[f + '_n'], c1[f + '_acc'], n2, c2[f + '_n'], c2[f + '_acc']])
table(['field', 'p1 passes', 'p1 CSV n', 'p1 CSV acc', 'final passes', 'final CSV n', 'final CSV acc'], tb)
h('X9. High prompt-token clips (tokens are constant within a clip, so a clip property, not a retry)')
hi = sorted({r['clip'] for r in BY['super-direct'] if (r['tok'] or 0) > 12000})
tb = []
for c in sorted({r['clip'] for r in ROWS if r['subject'] in ('super-direct', 'nano-direct', 'qwen35-9b-openrouter') and (r['tok'] or 0) > 12000 and r['D'] < 60}):
    tk = lambda s: max([r['tok'] or 0 for r in BY[s] if r['clip'] == c] or [0]) or None
    tb.append([c, D[c], MAN[c]['size_bytes'], MAN[c]['r2_folder'], tk('nano-direct'), tk('super-direct'), tk('omni-direct'), tk('gemma4-31b-openrouter'), tk('qwen35-9b-openrouter')])
table(['clip', 'D', 'bytes', 'folder', 'Nano', 'Super', 'Omni', 'Gemma', 'Qwen'], tb)


h('X10. Why a ±5 s check fails (share of failing valid rows)')
tb = []
for s in SUBJECTS:
    v = V(s); fs = [r for r in v if abs(r['ps'] - r['gs']) > TOL]; fe = [r for r in v if abs(r['pe'] - r['ge']) > TOL]
    tb.append([SHORT[s], len(fs), sum(r['ps'] == 0 for r in fs), sum(r['ps'] < r['gs'] and r['ps'] != 0 for r in fs), sum(r['ps'] > r['gs'] for r in fs), len(fe), sum(r['pe'] >= fl(r) - 1 for r in fe), sum(r['pe'] > r['ge'] and r['pe'] < fl(r) - 1 for r in fe), sum(r['pe'] < r['ge'] for r in fe)])
table(['model', 'start fails', 'pred 0', 'other early', 'late', 'end fails', 'runs to clip end', 'other late', 'early'], tb)
h('X11. Duration-standardised ±5 s (valid rows; equal weight to the three tertiles, removes the coverage mix)')
tb = []
for s in SUBJECTS:
    a = [rate(sum(abs(r['ps'] - r['gs']) <= TOL for r in V(s) if r['tert'] == t), sum(r['tert'] == t for r in V(s))) for t in ng]
    b = [rate(sum(abs(r['pe'] - r['ge']) <= TOL for r in V(s) if r['tert'] == t), sum(r['tert'] == t for r in V(s))) for t in ng]
    c = [mean([abs(r['pv'] - r['gv']) for r in V(s) if r['tert'] == t]) for t in ng]
    tb.append([SHORT[s], *a, mean(a), *b, mean(b), *c, mean(c)])
table(['model', 'start short', 'mid', 'long', 'start std', 'end short', 'mid', 'long', 'end std', 'sev short', 'mid', 'long', 'sev std'], tb)
h('X12. Intervals: row-level (CSV columns) against clip-cluster, same point estimate')
def cl_ci(rows, f):
    per = collections.defaultdict(list)
    for r in rows: per[r['clip']].append(f(r))
    keys = sorted(per); rnd = random.Random(SEED); out = []
    for _ in range(BOOT):
        a = b = 0
        for _ in keys:
            x = per[keys[rnd.randrange(len(keys))]]; a += sum(x); b += len(x)
        out.append(a / b)
    out.sort(); return [out[int(.025 * BOOT)], out[int(.975 * BOOT) - 1]]
tb = []
for s in SUBJECTS:
    rows = [r for r in BY[s] if r['outcome'] in OUTPUT]; c = CSVROWS[(s, 'p1')]
    for f, k in (('start_timestamp', 'pass_s'), ('end_timestamp', 'pass_e')):
        z = cl_ci(rows, lambda r: 1.0 if r[k] else 0.0); lo, hi = float(c[f + '_ci_lo']), float(c[f + '_ci_hi'])
        tb.append([SHORT[s], f, float(c[f + '_acc']), f'{lo:.3f}-{hi:.3f}', hi - lo, f'{z[0]:.3f}-{z[1]:.3f}', z[1] - z[0], (z[1] - z[0]) / (hi - lo)])
table(['model', 'field', 'acc', 'CSV CI', 'width', 'clip-cluster CI', 'width', 'ratio'], tb)
c = CSVROWS[('nano-direct', 'p1')]
say(f"Same CSV row, Nano type: type_acc {c['type_acc']} CI {c['type_ci_lo']}-{c['type_ci_hi']}; e2e_type_of_planned {c['e2e_type_of_planned']} CI {c['e2e_type_of_planned_ci_lo']}-{c['e2e_type_of_planned_ci_hi']}.")
h('X13. Gemma raw windows by clip (rep 1), and Qwen tokens by provider')
g = sorted([x for x in allrows('gemma4-31b-openrouter') if x[2]['rep'] == 1], key=lambda x: x[2]['D'])
say('D: GT -> raw (v=valid): ' + '; '.join(f"{x[2]['D']:.0f}: {x[2]['gs']}-{x[2]['ge']} -> {x[0]}-{x[1]}{'v' if x[2]['valid'] else ''}" for x in g))
say('')
qq = collections.defaultdict(dict)
for r in BY['qwen35-9b-openrouter']:
    if r['tok']: qq[r['clip']][r['rep']] = (r['provider'], r['tok'])
both = [(c, x) for c, x in qq.items() if len(x) == 2 and x[1][0] != x[2][0]]
say(f"Qwen clips with both repeats answered: {sum(len(x) == 2 for x in qq.values())}; served by different providers: {len(both)}; prompt tokens on those: {[(c, x[1][0][:4], x[1][1], x[2][0][:4], x[2][1]) for c, x in both][:12]}")
say('')
hiq = collections.Counter((r['provider'], (r['tok'] or 0) > 9000, r['D'] < 60) for r in BY['qwen35-9b-openrouter'] if r['tok'])
say('Qwen (provider, tokens>9000, D<60):', dict(hiq))
h('X14. Severity: signal beyond category, and rubric-boundary cells')
tb = []
RB = lambda r: (r['cat'] == 'Burglary' and r['gv'] == 2 and r['pv'] in (1, 3)) or (r['cat'] == 'Animal Attack' and r['gv'] <= 2 and r['pv'] == r['gv'] + 1) or (r['cat'] == 'Explosion' and r['gv'] == 4 and r['pv'] == 5)
for s in SUBJECTS:
    v = V(s); gm = {c: mean([r['gv'] for r in v if r['cat'] == c]) for c in {r['cat'] for r in v}}; pm = {c: mean([r['pv'] for r in v if r['cat'] == c]) for c in {r['cat'] for r in v}}
    x = [r['gv'] - gm[r['cat']] for r in v]; y = [r['pv'] - pm[r['cat']] for r in v]
    e = sum(abs(r['pv'] - r['gv']) for r in v); rb = sum(abs(r['pv'] - r['gv']) for r in v if RB(r))
    tb.append([SHORT[s], len(v), ols(x, y)[2], ols(rk(x), rk(y))[2], e, rb, rb / e, mean([abs(r['pv'] - r['gv']) if not RB(r) else 0 for r in v])])
table(['model', 'n', 'within-category Pearson', 'within-category Spearman', 'total abs error', 'error in the 3 rubric-boundary cell groups', 'share', 'MAE if those cells were forgiven (illustration only)'], tb)
say('Cell groups: Burglary GT 2 predicted 1 or 3; Animal Attack predicted one above a GT of 1 or 2; Explosion GT 4 predicted 5. These are where the guideline adds rules the prompt does not carry.')


h('X15. Concentration of run-to-clip-end misses')
ce = collections.Counter(r['clip'] for s in SUBJECTS for r in {(x['clip']): x for x in V(s) if abs(x['pe'] - x['ge']) > TOL and x['pe'] >= fl(x) - 1 and x['pe'] > x['ge']}.values())
say(f"Clips with at least one model running to the clip end and missing ±5: {len(ce)} of 55; two or more models: {sum(v >= 2 for v in ce.values())}; three or more: {sum(v >= 3 for v in ce.values())}: {sorted(c for c, v in ce.items() if v >= 3)}.")

# ---------- write ----------
body = '\n'.join(OUT)
B, E = '<!-- BEGIN GENERATED -->', '<!-- END GENERATED -->'
old = REPORT.read_text() if REPORT.exists() else f'# Timestamps and severity diagnostic\n\n{B}\n{E}\n'
REPORT.write_text(old.split(B)[0] + B + '\n' + body + '\n' + E + old.split(E)[1])
print('wrote', REPORT, len(body))
