# Public archive notes

Branch `archive/eval-v2-final-results` is a single clean commit on top of `main`, made on 2026-11-06 from the unpublished local branch `eval/v2-c3e-evidence` (tip `5127e9569`). It does not carry that branch's history. It is an archive, not a merge target. Results are unchanged: only the items below differ.

## Sanitised

| File | Change |
|---|---|
| `methodology/c3e-dev-results-v1.md` | §5 per-item GT discrepancy table replaced by a summary, because it quoted private GT content. Scores and denominators unchanged |
| `methodology/description-threshold-sensitivity/README.md` | Two example cells reworded generically |
| `methodology/presentation/README.md` | Archive pointer added; `RESUME.md` row removed |

## Omitted

| Item | Reason | Kept in |
|---|---|---|
| `scripts/diagnostics/chat_attribution.py` | Hand labels embed GT names and paraphrases, and cannot be separated without losing the attribution method | Local branch |
| `scripts/diagnostics/objects_crops.py` | Embeds GT names in its labels | Local branch |
| `methodology/presentation/RESUME.md` | Operating notes for a finished run | Local branch |
| Local `.docs/` edits | Live project docs; `main` is left as it is | Local branch |

## Never in Git

Ground-truth text, incident videos and frames, raw model replies, judge caches, AI reference annotations and private audit reports stay in private evaluation storage (`evalv2-data`, `eval/eval_data`). Reproducing results needs that data, so most scripts here will not run from this branch alone. Absolute paths in scripts refer to that private layout.

Related archive branches: `eval/v2-c3-amendment-a5` (amendment A5) and `eval/v2-final-comparison` (frozen final plan, analysis, profile and config).

## Reading the results

- Super is incomplete: 50 of 110 valid at the deadline; original Track B and chat-a4 were not completed.
- The final VLM-vs-VSS run is Nano-only with person tracking off. It is separately frozen, not original C3, and not production.
- References are AI-generated or AI-assisted; nothing is human-verified.
- Evaluation clips were held out from prompt selection but were previously exposed.
