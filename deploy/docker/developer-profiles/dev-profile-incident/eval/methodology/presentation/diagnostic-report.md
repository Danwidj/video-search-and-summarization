# Consolidated diagnostic report

**Conclusion:** the poor scores mainly reflect genuine limits and reporting choices. No defect in the core scoring invalidates the benchmark. GT text and examples are private: `/home/hengz/evalv2-data/v2/diagnostics/` (`timestamps-severity.md`, `objects-crops.md`, `chat-attribution.md`, `description_samples.json`).

| Issue | Affected metric | Root cause | Evidence | Class | Confidence | Action | Slides |
|---|---|---|---|---|---|---|---|
| Mixed denominators | Description, ±5 s, object scores | My use of the continuity view | Object order changes | A reporting | High | Corrected | Done |
| D2 final rows dropped failed runs | Contingency object metrics | `with_failed_runs` not applied to items | Recall 0.705 to 0.627 | A | High | Correction v1, both shown | Done |
| Chat list plurals, m:ss windows | Chat exact | Scorer | Oracle 63/79 to 65/79, gap widens; window latent | A | High | `corrections_v1.py`; originals kept | Footnote |
| Judges got id list | 9 library verdicts | Scorer input | 6 oracle, 3 system | A | High | Note; re-judge only if approved | Footnote |
| Row-level CIs in CSV fields | D1 field CIs | Not clip-cluster | 1.24–1.40× too narrow | A reporting | High | Use `views()` | Avoid those columns |
| Judge unstable near cutoff | Description | Non-deterministic at temperature 0 | 4 of 31 flips | C | High | Caveat; repeat study | Caveat |
| Strict on brief correct text | Description | No anchors | 4 of 10 in 0.1–0.4 | C | Medium | Blind review | Provisional |
| 16,384-token cap | Yield | Reasoning budget | Nano 15, Omni 23, Qwen 40 | C and D | High | Explain | Done |
| Assign before threshold | Object F1 vs τ | Design | F1 cannot fall as τ falls | C | High | Show τ curve | Annex |
| τ does not separate objects | Object F1 | 96.7% of GT pairs clear 0.40; false TPs Nano 30%, Gemma 3% | Audit | C | Medium | Keep 0.40; human calibration | Caveat |
| Strong trivial baselines | ±5 s | start=0 passes 0.44, end=clip end 0.55 on Nano rows | Audit | C | High | Note | Caveat |
| Valid subsets differ | All conditional metrics | Failures vary by clip | 17 clips common to four | C | High | Show both views | Done |
| Chat scored against GT on partial corpus | Library chat | By design, implied | Agent report | C | High | Disclose | Caveat |
| Wrong-event descriptions | Description | Genuine | 10 of 10 zero scores | D | High | Report | Keep |
| Nano severity | MAE | Miscalibration; QWK 0.61 | No better than always 3 | D | High | Report | Keep |
| Nano precision | Object | Repeats, background | 75% of sampled FPs real | D | Medium | Report | Keep |
| Chat on pipeline reports | Exact 0.19 | 36 of 50 losses report-side; answer generation 0 | Trace | D | High | Report | Keep |
| 251 of 367 evidence entries unmatched | Crops | Mostly background or duplicates | Sample of 40 | D and C | Medium | Report | Keep |
| Gemma out-of-clip times | Yield, timing | Possibly provider video handling | Windows do not track clip | F, likely E | Medium | Unresolved | Footnote |
| HTTP 400 not retried | Gemma, Qwen yield | Provider download | 8 runs | E | High | Infra | Footnote |
| Super outage | Super rows | 524 and 429 | Attempt logs | E | High | Mark incomplete | Keep |
| GT candidates | Various | Naming conflicts, for example RoadAccidents039 | 12 clips proposed | B | Medium | Human review; GT unchanged | No |

**VSS subgroups:** no subgroup survives correction (`data/final_subgroups.csv`).

**Recommended next:** blind human review of 77 description pairs and τ pairs; repeat-judge test; separately versioned chat re-judge; production-path run with person tracking and Super if VM and Super become available.
