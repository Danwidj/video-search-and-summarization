# Baseline-to-final system evolution

Slide-sized summary. Full citations are in `evidence/system-evolution-evidence.md`. "Measured" means an experiment isolated the change. "Level" means a score with no before and after. "Not measured" is architectural intent only.

Evidence grades: **A** pre-registered, paired, 55 test clips (previously exposed). **B** dev split. **C** scout or small pilot. **D** cost or diagnostic.

| Area | What changed | Why | Measured improvement | Architectural only, no direct evidence |
|---|---|---|---|---|
| Stock VSS to incident VSS | Added incident routes, report tool, contract, console, Supabase, eval. Dropped VST, NIM, stock UI | Reviewable, versioned reports, not a general video agent | None. Parity: [A] VSS − direct ΔI −0.007 [−0.036, +0.024] | Traceability, review workflow, mergeability |
| Model hosting | On-prem NIM to remote OpenAI-compatible endpoints, keys server-side | Free-tier hangs, `_type: nim` failures, GPU contention | None; no local-vs-remote test. C3 shows the cost of dependence: Super 64 timeouts and 27 rate limits in 117 attempts | Freed GPU, ~2 s restarts |
| Extraction pipeline | Contract v1 to v4, strict validation, ID-only repair, append-only revisions | Benchmark did not measure production; JSONB replaced single-version design | None across versions. [C] `core-scored-v1` accepted answers 6 to 13 of 15; counts acceptance, not accuracy | One contract, immutable attempt record, official pointer |
| Captions | 20 s windows for clips over 30 s, added as context to P1 | Sparse sampling missed short events | None isolated. Exploratory contingency split on 25 clips: severity MAE −0.20 [−0.44, 0.00], unadjusted, confounded by clip length | Long-clip recall |
| Grounding and evidence | Remote-VLM grounding, whole-frame evidence, zoom, tracking (VM), first-seen image, box tool | VLM boxes in P1 failed; small crops misnamed items | Zoom only: dev Super entity F1 +0.026 (no CI), Nano about 0; C3 contingency object score −0.0065 [−0.0213, +0.0079]. See D3 for levels | Tracking accuracy, frame over crop, reviewer correction |
| Prompt engineering | Few-shot removed, registry with pinned hashes, V1–V8 prompt experiments | Few-shot leaked labels; severity over-rating | **Held out: not confirmed.** V1 +0.051 [+0.013, +0.089] on dev, +0.019 [−0.015, +0.055] on test. V1 not adopted | Prompt registry as change control |
| Object identification | Entities, instruments, assets; zoom naming; τ 0.40 | Thumbnail resolution misnames items; τ 0.75 was a floor | [B] V1 object F1 +0.047 [+0.014, +0.084] on dev only. Zoom as above | Reviewer trust in names |
| Chatbot | Template chat kept as default; grounded chat merged, off, not deployed | Template listed ids regardless of the question | None: template was never scored. Levels in D4 | Code-composed counts, id checks, refusal |
| Dashboard | Fixed displays; Ask for a chart with closed `ChartSpec`; severity normalisation | Real figures only; text-to-SQL rejected | [B] severity words 0.88 to 0.92, +0.04 [−0.03, +0.11], p 0.45, not significant. Level [A]: 57/60, 72/75 | Allowlist as a safety boundary |
| Operational efficiency | Native agent, no VST upload, batch and background jobs, tracker limits, box describe tuning | Slow rebuilds, double uploads, stalls | [C] box describe 60–125 s to 1–3 s; detector tail 10–65 s to at most 8.6 s. Scouts only | Full-stack latency with tracking is not measured |

## Reading for the slide

- Later components do not count as improvements unless an experiment isolated them. Only zoom and prompts were isolated, and neither shows a held-out gain.
- Features that are off or removed must not be demoed as current: grounded chat is off, set-of-marks is off, privacy blur was removed by #453, and the chart feature needed a VM pull and restart when last recorded.
- Use "AI-assisted ground truth", not "human ground truth".
- Do not quote a frame-sampling count: three project documents disagree (`evidence/system-evolution-evidence.md` §13).
