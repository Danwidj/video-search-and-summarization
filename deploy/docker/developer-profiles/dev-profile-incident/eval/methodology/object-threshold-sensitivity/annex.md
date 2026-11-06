# Annex: object-matching threshold

**Methodology.** Objects are matched per clip and kind by one-to-one Hungarian assignment on MiniLM cosine similarity, and an assigned pair counts at τ = 0.40 or above. τ was set on 2026-10-28 from 132 AI-labelled, AI-audited dev pairs under a stated rule, before any object scoring of the evaluation clips. It is dev calibration, not post-evaluation selection. It is not human-validated, its source is one model's outputs, and it followed an earlier provisional result of 0.30. As a post-hoc check we replayed every stored score exactly, swept τ from 0.20 to 0.60 on dev first, labelled 140 sampled dev pairs (one AI reader, texts only), and fixed a decision rule and its result before computing evaluation-half figures. The evaluation clips are not unseen: they appeared in earlier benchmarks and audits.

**Findings.**
- **τ = 0.40 stays primary.** No lower common threshold met the rule fixed in advance.
- **Lower τ raises F1 by construction.** The assignment comes first, so wrong pairs raise measured F1 too. Evaluation-half object scores rise by 0.05 to 0.10 at τ = 0.30.
- **Those added pairs are often not the same object.** On dev, an estimated 28% of pairs in [0.30, 0.35) and 41% in [0.35, 0.40) are the same object, with many undecidable from text.
- **0.40 is not a sharp boundary.** Pairs just above it are only about half confirmed, and quality falls clearly only below 0.35.
- **The top of the ranking depends on τ.** Gemma leads at 0.40 and above, Nano at 0.35 and below, and intervals overlap. Omni is last throughout.
- **Future evaluations:** one common τ fixed on dev before evaluation, always shown with its τ curve, ideally from human-labelled pairs covering every model.
