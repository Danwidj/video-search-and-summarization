# Verification log

Date 2026-11-05. "Replayed" means recomputed from raw rows, separately from the chart path.

| Check | Result |
|---|---|
| Final comparison type, raw recount | VSS 78/110 = 0.709; direct 74/110 = 0.673. Matches |
| Severity both-valid, raw recount | 91 pairs, 0.714 and 0.813. Matches |
| Frozen analysis rehearsal on contingency | Reproduced the known both-valid numbers before any final data |
| D1 pass rates and MAE | All reproduce from raw rows (timestamps and severity audit); 466 Track A and 105 contingency rows match GT |
| D2 counts | Replay 976 of 977 pairs, the one a tie; chart cells reproduce; τ sweep 0 mismatches over 2,118 blocks |
| Dashboard | 57/60, 72/75 from summary |
| Chat | Snapshot hashes match; 119 references recount cleanly; stored exact verdicts reproduce |
| C3-E | Classes replay on dev and test; coverage script reproduces the dev table; freeze `34dd7755…` verified |
| Old-deck figures | 10 of 10 reproduce, from the dev pilot |
| Description | 1,043 cached replies parse; 363 rows join to verdicts; 0 GT pairing mismatches |
| Tests | Eval suite: 1,575 passed, 20 skipped, 1 failed |

**The one test failure.** `test_reference_tooling_imports_no_model_client_task_or_v1_module`: frozen `evalv2/references/c3e_score.py` imports `evalv2.tasks.crops`. Present since that scorer landed. It is an architectural guard, not a wrong result; the file is pinned by the C3-E freeze, so it was not changed. Fix after the study by moving the scorer or adjusting the guard, in a new version.

**Denominator corrections made:** description and ±5 s rates; D2 object scores (mixed view replaced); contingency failed runs kept where stated. CSV `*_ci_lo/hi` for field rates in `d1_incident_extraction.csv` are row-level, about 1.24–1.40× too narrow: use the `views()` columns.

**AI versus human:** no reference or label in this package is human-verified. All sample labels in the audits are one AI reader.
