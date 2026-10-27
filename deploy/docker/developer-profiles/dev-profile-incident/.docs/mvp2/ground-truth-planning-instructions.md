# Task: Plan a Multi-PR Ground Truth Refinement and VSS Prompt Engineering Workstream

## Objective

Investigate the current VSS repository, datasets, annotation contracts, evaluation framework, and infrastructure, then produce a detailed, implementation-ready plan for:

1. Finalising shared annotation guidelines and evaluation scoring rules.
2. Downloading the relevant surveillance videos from Cloudflare R2.
3. Auditing the existing human-labelled ground-truth Excel workbook.
4. Using AI to review, correct and standardise the human annotations.
5. Validating and freezing the revised ground truth.
6. Conducting controlled VSS prompt-engineering experiments.
7. Evaluating and documenting performance across prompt versions.

The work should be divided into several focused PRs rather than one large PR.

**This is a planning request only. Do not implement the workstream, download the full dataset, modify annotations, run model experiments, or create implementation PRs yet.**

The main scientific objective is to determine whether specific prompt-engineering techniques improve VSS extraction accuracy against a fixed, independently established reference dataset.

Improvement is a hypothesis to test, not an outcome to guarantee.

---

## 1. Investigate the current repository

Before proposing implementation, inspect the actual repository.

Locate and review:

- The `Contracts` folder and all relevant VLM/VSS prompts.
- The current incident JSON contracts, including `incident-contract-v4` where applicable.
- Existing VLM/VSS extraction code.
- Existing evaluation scripts, metrics and matching logic.
- Ground-truth loading and validation code.
- Cloudflare R2 configuration and video access.
- Dataset manifests and video identifiers.
- Relevant developer profile configurations.
- `.docs/mvp2/eval.md`
- `.docs/status.md`
- `.docs/decisions.md`
- Database documentation and Excel workbooks.
- Existing tests, CI workflows and evaluation outputs.

Establish:

- What currently exists.
- What is already implemented.
- What is incomplete.
- What can be reused.
- What requires modification.
- Which assumptions require verification.

Do not introduce a parallel evaluation framework when the existing one can be extended.

Do not modify Supabase or execute legacy database initialisation.

---

# Proposed Multi-PR Roadmap

## PR 1 — Shared Annotation Guidelines and Evaluation Methodology

**This PR must be completed and approved before any AI-assisted ground-truth correction begins.**

Its purpose is to establish the authoritative definitions of correct annotations and exactly how predictions will be scored.

### A. Shared annotation guidelines

Create a version-controlled, standalone annotation guideline document.

Suggested version:

`annotation-guidelines-v1.0`

This document must be separate from:

- Ground-truth AI correction prompts.
- VLM extraction prompts.
- VSS extraction prompts.
- Experimental prompt versions.

Both ground-truth correction and VSS extraction must follow the same definitions.

However, they should not necessarily use the same complete prompt.

### B. Incident definitions

Finalise:

- Permitted incident categories.
- Incident start timestamp.
- Incident end timestamp.
- Severity levels 1–5.
- Severity reasoning.
- Incident descriptions.
- Observable evidence requirements.
- Uncertainty handling.

For severity, provide explicit decision rules and examples distinguishing levels 1, 2, 3, 4 and 5.

Clarify how to distinguish actual observed harm from potential danger.

Do not infer injuries, fatalities or damage unsupported by video evidence.

### C. Entity definitions

Finalise:

- What constitutes a significant entity.
- Inclusion and exclusion criteria.
- Active participants.
- Victims.
- Responders and interveners.
- Bystanders.
- Background individuals.
- Entity descriptions.
- Entity identifiers and relationships.
- Temporal fields.

Mere visibility or proximity must not automatically establish significance.

### D. Instrument definitions

Finalise:

- What constitutes an instrument.
- Requirements for visible hand-held interaction.
- Incident relevance.
- Instrument-holder relationships.
- Threat levels 1–5.
- Potential harm versus actual harm.
- Instrument descriptions.
- Classification ambiguity.

Provide examples distinguishing instruments from assets.

### E. Asset definitions

Finalise:

- What constitutes an asset.
- Incident significance.
- Interaction, damage or targeting.
- Background-object exclusion.
- Asset descriptions.
- Asset/instrument classification rules.

### F. Description standardisation

Define a consistent format for:

- Incident descriptions.
- Entity descriptions.
- Instrument descriptions.
- Asset descriptions.

Descriptions should be objective, concise and sufficiently informative.

They should preserve meaningful visual details without introducing speculation.

Define how to handle uncertain attributes and partially visible objects.

### G. Visual grounding rules

Review the current `TIMESTAMP_SECONDS`, `LABEL`, `image`, and `bounding_box` fields.

The current intended approach is to select a representative frame where the item is clearly visible, preferably during its significant involvement in the incident.

Do not require the first appearance or first moment of significance if that produces a poor frame.

For ground-truth labelling:

- Empty image fields are intentional.
- Do not require manual screenshots.
- Do not require manually annotated bounding boxes.
- Do not treat empty image fields as invalid labels.
- Do not score image or bounding-box accuracy unless explicitly approved as an additional evaluation objective.

### H. Finalise evaluation scoring rules

This is a critical deliverable of PR 1.

Before AI modifies the ground truth, define exactly how each field will be evaluated.

Inspect the current evaluation code and preserve the existing methodology where appropriate.

Propose and document:

**Incident**
- Type accuracy.
- Severity accuracy.
- Start timestamp accuracy.
- End timestamp accuracy.
- Description semantic similarity.

**Entities**
- Item matching methodology.
- True positives, false positives and false negatives.
- Precision, Recall and F1.
- Description matching.
- Handling multiple similar entities.

**Instruments**
- Item matching.
- Precision, Recall and F1.
- Threat-level accuracy.
- Holder-entity relationship correctness.
- Handling ambiguous objects.

**Assets**
- Item matching.
- Precision, Recall and F1.
- Description matching.
- Handling multiple similar assets.

Investigate whether the current evaluation uses embedding similarity, Hungarian matching, or other methods.

Define:

- Matching thresholds.
- One-to-one matching rules.
- Treatment of unmatched predictions.
- Treatment of unmatched ground-truth items.
- Treatment of empty arrays.
- Treatment of null fields.
- Treatment of invalid outputs.
- Treatment of model/API failures.
- Field-level aggregation.
- Video-level aggregation.
- Overall score calculation, if applicable.

Ensure that matching and scoring rules are fixed before ground-truth correction and prompt experiments.

Avoid using a changing LLM judge or changing semantic-similarity thresholds across prompt versions.

### PR 1 deliverables

- Versioned annotation guidelines.
- Versioned evaluation methodology.
- Field-level scoring specification.
- Matching and aggregation rules.
- Examples of correct and incorrect annotations.
- Explicit list of fields excluded from scoring.
- Decisions requiring approval.
- Tests or reference fixtures demonstrating scoring behaviour.

**Acceptance criterion:** The project has one authoritative definition of correct annotations and one fixed, reproducible evaluation methodology.

---

## PR 2 — Cloudflare R2 Dataset Preparation

Plan a dedicated PR for reproducible video retrieval and preparation.

### Source

Cloudflare R2:

`anomaly_detection_dataset/anomaly/`

Download videos from:

- `demo`
- `animal_attacks`
- `assault`
- `burglary`
- `explosion`
- `road_accidents`

Exclude:

- `shooting`

### Requirements

Investigate the existing Cloudflare configuration and determine the appropriate download method.

Plan for:

- Object inventory.
- File counts.
- Total download size.
- File formats.
- Video durations.
- Available storage.
- Resumable downloads.
- Retry handling.
- File integrity verification.
- Duplicate detection.
- Missing or corrupted video detection.
- Exact filename preservation.
- Dataset manifest generation.
- Gitignore rules.
- Reproducible setup instructions.

Do not commit large video files to Git.

Do not expose Cloudflare credentials.

Preserve original filenames for ground-truth matching.

Investigate whether all videos must be downloaded locally or whether existing cached copies can be reused.

### PR 2 deliverables

- Reproducible download script.
- Dataset manifest generator.
- Integrity validation.
- Setup documentation.
- Tests for dataset preparation utilities.

---

## PR 3 — Human Ground Truth Audit

Locate the workbook:

`Complete Ground Truth Labelling`

The workbook contains:

- `gt_incidents`
- `gt_entities`
- `gt_instruments`
- `gt_assets`

These sheets are intended to contain human annotations for all relevant Cloudflare videos.

The filenames should match the video dataset exactly.

### Audit requirements

Plan validation for:

- Filename matching.
- Missing videos.
- Missing annotations.
- Duplicate annotations.
- Invalid identifiers.
- Broken references.
- Invalid categories.
- Severity values.
- Threat-level values.
- Timestamp consistency.
- Missing descriptions.
- Description formatting.
- Entity significance.
- Instrument significance.
- Asset significance.
- Instrument-holder relationships.
- Contradictions across sheets.
- Ambiguous classifications.

Use the approved annotation guidelines and scoring rules from PR 1.

Do not modify the original workbook.

### Image fields

The image fields are intentionally empty.

Do not flag them as missing data.

Do not generate manual screenshots or bounding-box labels.

### PR 3 deliverables

- Workbook validation script.
- Video-to-workbook matching report.
- Annotation consistency report.
- List of potentially incorrect annotations.
- List of ambiguous annotations.
- Reproducible audit procedure.

**Acceptance criterion:** The existing human-labelled dataset has been audited, and all issues requiring correction have been identified or flagged.

---

## PR 4 — AI-Assisted Ground Truth Correction

Plan an AI-assisted correction pipeline using the approved annotation guidelines.

### Inputs

- Original human-labelled workbook.
- Shared annotation guidelines.
- Source videos.
- Existing annotation contracts.

### AI correction responsibilities

For each annotated video:

1. Read the existing human annotations.
2. Review the relevant video evidence.
3. Check annotations against the shared guidelines.
4. Identify unsupported claims.
5. Correct inconsistent descriptions.
6. Reassess incident severity.
7. Reassess instrument threat levels.
8. Identify omitted significant entities.
9. Identify incorrectly included incidental entities.
10. Identify omitted or misclassified instruments.
11. Identify omitted or misclassified assets.
12. Verify relationships and timestamps.
13. Standardise descriptions.
14. Explain proposed changes.

### Video understanding

Investigate the actual AI model and video-processing capabilities.

Do not assume a text-only model can analyse videos.

Specify whether correction requires:

- Full-video input.
- Video clips.
- Sampled frames.
- Existing VLM infrastructure.
- Additional video-processing utilities.

Explain how the system will handle long videos and temporal events.

### Correction traceability

Every proposed correction must preserve:

- Original value.
- Proposed value.
- Video filename.
- Worksheet.
- Record identifier.
- Field name.
- Explanation.
- Supporting visual evidence or timestamp.
- AI model.
- Correction prompt version.
- Annotation guideline version.
- Review status.
- Accepted final value.

Never silently overwrite original human annotations.

### Independence from VSS

The correction AI must not receive:

- VSS predictions.
- Experimental VSS prompts.
- VSS accuracy scores.
- Information about which labels VSS gets wrong.

The correction process must be independent of the system being evaluated.

### Human validation

Plan a review process prioritising:

- Incident type changes.
- Severity changes.
- Threat-level changes.
- Added or removed entities.
- Added or removed instruments.
- Added or removed assets.
- Changed relationships.
- Ambiguous classifications.
- Unsupported descriptions.

Also sample unchanged annotations to detect missed errors.

If some annotations remain uncertain, record that uncertainty rather than forcing unsupported answers.

### PR 4 deliverables

- Versioned AI correction prompt.
- Correction pipeline.
- Proposed corrected workbook.
- Field-level change log.
- Review workflow.
- Validation results.
- Reproducibility documentation.

**Acceptance criterion:** Corrections are traceable, independently justified and ready for approval before freezing.

---

## PR 5 — Freeze the Ground Truth

Plan a dedicated PR to produce a reproducible, versioned reference dataset.

Suggested version:

`ground-truth-v1.0`

### Required artifacts

- Original human-labelled workbook.
- Corrected reference workbook.
- Approved annotation guideline version.
- Evaluation methodology version.
- Correction log.
- Dataset manifest.
- Validation report.
- Review record.
- Dataset checksum/hash.

### Freezing rules

After freezing:

- Do not change labels to improve VSS scores.
- Do not change annotation definitions during an experiment.
- Do not expose reference answers to VSS.
- Do not silently replace the frozen workbook.
- Genuine errors must be corrected through a documented new dataset version.
- If the reference dataset changes, rerun all compared prompt versions against the same updated dataset.

### Dataset split

Investigate the existing development and held-out test split.

Propose a defensible split for prompt engineering.

Requirements:

- Development videos may be used to design and refine prompts.
- Held-out test videos must not be used to select prompt changes.
- Final test evaluation should occur only after selecting the candidate prompt.
- Avoid near-duplicate or related videos leaking across splits.
- Keep the split fixed and reproducible.

If the dataset is too small, propose an alternative such as grouped cross-validation or a limited development/test split, explaining the trade-offs.

The final held-out set should remain unseen during prompt selection.

### PR 5 deliverables

- Frozen ground-truth dataset.
- Dataset version manifest.
- Fixed development/test split.
- Dataset integrity checks.
- Reproducible loading instructions.
- Approval record.

**Acceptance criterion:** A stable reference dataset exists before VSS prompt experimentation begins.

---

## PR 6 — VSS Prompt Experimentation Infrastructure

Plan a dedicated PR for reproducible prompt experiments.

All relevant VSS extraction prompts should remain under the existing `Contracts` folder.

Inspect the current prompt organisation and reuse its naming conventions.

### Prompt versioning

Every prompt version must be saved immutably.

Suggested versions:

- `vss-prompt-v1`
- `vss-prompt-v2`
- `vss-prompt-v3`
- `vss-prompt-v4`

Or the equivalent existing project convention.

Each experiment must record:

- Prompt version.
- Complete prompt text.
- Shared annotation guideline version.
- Evaluation methodology version.
- Contract/schema version.
- Model and model version.
- Model parameters.
- Ground-truth version.
- Dataset split.
- Video identifiers.
- Execution date.
- Raw model output.
- Parsed output.
- Processing latency.
- Token usage.
- API cost, where available.
- Errors and failures.
- Evaluation results.

Keep prompts and experiment configurations reproducible.

### Prompt-engineering experiments

Propose controlled experiments targeting:

**Severity**
- More precise severity decision rules.
- Observed harm versus potential danger.
- Severity overestimation and underestimation.

**Entities**
- Significant versus incidental entities.
- Participant and bystander distinctions.
- Omitted or duplicated entities.

**Instruments**
- Hand-held object classification.
- Instrument versus asset confusion.
- Threat-level assignment.

**Assets**
- Incident relevance.
- Background-object exclusion.
- Asset descriptions.

**Descriptions**
- Consistent structure.
- Factual completeness.
- Reduced hallucination.
- Clearer relationships between items.

**General**
- Few-shot examples.
- Field-specific instructions.
- Explicit exclusion rules.
- Structured consistency checks.
- Uncertainty handling.

Each experiment should have a documented hypothesis.

Prefer changing one coherent prompt component at a time so the effect can be interpreted.

### Critical experimental requirement

**Do not require prompt performance to improve monotonically.**

The goal is to determine which changes improve extraction accuracy.

A new prompt may:

- Improve some fields.
- Worsen other fields.
- Have no measurable effect.
- Improve accuracy but increase latency.
- Reduce hallucinations but omit valid items.

All outcomes are valid experimental findings.

Preserve every tested prompt version, including unsuccessful versions.

Do not silently discard regressions.

Do not repeatedly tune prompts against the held-out test set.

### PR 6 deliverables

- Prompt registry/versioning structure.
- Experiment configuration format.
- Reproducible experiment runner.
- Result storage conventions.
- Development-set evaluation workflow.
- Experiment tracking documentation.
- Tests for prompt loading and experiment execution.

---

## PR 7 — Execute Experiments and Analyse Results

Plan the final experimental PR or series of smaller experiment/reporting PRs.

### Experimental workflow

1. Establish the baseline VSS prompt.
2. Run the baseline on the development set.
3. Evaluate using the frozen scoring methodology.
4. Analyse field-level errors.
5. Formulate a specific prompt improvement hypothesis.
6. Create a new immutable prompt version.
7. Run it on the same development set.
8. Compare results using the same ground truth and metrics.
9. Record improvements, regressions and trade-offs.
10. Repeat for the planned experiments.
11. Select the best candidate using predefined development-set criteria.
12. Run the selected candidate and baseline on the held-out test set.
13. Report the final comparison without further test-driven prompt changes.

### Evaluation dimensions

**Incident**
- Type accuracy.
- Severity accuracy.
- Timestamp accuracy.
- Description similarity.

**Entities**
- Precision.
- Recall.
- F1.
- Description correctness.

**Instruments**
- Precision.
- Recall.
- F1.
- Threat-level accuracy.
- Holder relationship correctness.

**Assets**
- Precision.
- Recall.
- F1.
- Description correctness.

Use the approved evaluation methodology from PR 1.

### Analysis

Produce:

- Overall results.
- Per-field results.
- Per-category results.
- Severity confusion matrices.
- Threat-level error analysis.
- Entity/instrument/asset false positives and false negatives.
- Prompt-version comparisons.
- Processing latency comparisons.
- Model/API failure analysis.
- Qualitative examples of improvements and regressions.

Use paired comparisons because the same videos are evaluated across prompt versions.

Report confidence intervals where appropriate.

Do not mix model failures with extraction errors without documenting the scoring convention.

### Reporting requirements

Every experiment must be retained.

Report:

- Successful improvements.
- Unsuccessful prompt changes.
- Accuracy/latency trade-offs.
- Remaining systematic errors.
- Limitations.
- Final selected prompt.
- Reasons for selecting it.

Avoid claiming that prompt engineering guarantees improvement.

The final conclusion should be supported by measured results.

### PR 7 deliverables

- Complete experiment results.
- Prompt comparison tables.
- Error analysis.
- Visualisations.
- Final evaluation report.
- Selected prompt version.
- Reproduction instructions.

---

## 8. Documentation requirements

Every implementation PR must update the affected documentation.

Inspect:

- `.docs/status.md`
- `.docs/decisions.md`
- `.docs/mvp2/eval.md`
- Contracts documentation.
- Evaluation READMEs.
- Ground-truth documentation.
- Dataset preparation documentation.
- Experiment documentation.
- Database design documentation and Excel workbooks, where relevant.

The documentation should clearly distinguish:

1. Annotation guidelines.
2. Ground-truth correction prompts.
3. Frozen ground-truth datasets.
4. Experimental VSS prompts.
5. Evaluation scoring methodology.
6. Experimental results.

Do not conflate these artifacts.

Do not modify the Supabase database schema merely to support offline evaluation.

---

## 9. Produce a Detailed Multi-PR Implementation Plan

Use the seven PRs above as the proposed starting structure.

Adjust the decomposition if the repository architecture warrants it.

For each PR, provide:

1. Proposed PR title.
2. Objective.
3. Files and directories expected to change.
4. Existing code to reuse.
5. New modules or scripts required.
6. Implementation tasks.
7. Dependencies.
8. Tests and validation.
9. Acceptance criteria.
10. Risks.
11. Decisions requiring approval.
12. Estimated complexity.
13. Expected deliverables.

Identify which PRs can proceed independently and which must wait for earlier approvals.

In particular, enforce these dependencies:

- Annotation guidelines and evaluation scoring rules must be approved before ground-truth correction.
- Dataset integrity must be established before correction.
- Ground-truth correction must be reviewed before freezing.
- Ground truth must be frozen before formal prompt experiments.
- Final held-out evaluation must occur after prompt selection.

---

## 10. Decisions Requiring My Approval

Identify any unresolved methodological decisions.

At minimum, investigate:

- Severity definitions.
- Threat-level definitions.
- Entity/instrument/asset significance rules.
- Description standardisation format.
- Evaluation matching thresholds.
- Metric aggregation.
- Ground-truth AI model selection.
- Video-processing approach.
- Human-review requirements.
- Dataset split.
- Prompt selection criteria.
- Experiment budget and API limits.
- Storage and versioning conventions.

For each decision, provide:

- Available options.
- Advantages and disadvantages.
- Recommended choice.
- Consequences for implementation.

Separate blocking decisions from optional refinements.

Do not silently make major methodological decisions.

---

## 11. Final Planning Deliverable

Create a detailed planning document at an appropriate repository location, such as:

`.docs/mvp2/ground-truth-and-prompt-experiments-plan.md`

Include:

### A. Current-State Audit
Existing implementation, reusable components, missing functionality and risks.

### B. Annotation and Evaluation Specification
How annotation guidelines and evaluation scoring will be finalised together.

### C. Dataset Preparation
Cloudflare R2 download and integrity strategy.

### D. Ground-Truth Correction
AI-assisted review, traceability, human validation and independence.

### E. Ground-Truth Freezing
Versioning, checksums, approval and dataset splits.

### F. Prompt Experimentation
Versioning, controlled experiments, development-set selection and held-out evaluation.

### G. Multi-PR Roadmap
PR-by-PR tasks, dependencies, tests and acceptance criteria.

### H. Risks and Open Decisions
Methodological, infrastructure, cost and reproducibility concerns.

### I. Recommended Next Steps
The exact order of implementation and the first PR to undertake.

## Final Constraints

- Planning only.
- Do not start implementation.
- Do not download the full Cloudflare dataset.
- Do not modify the original workbook.
- Do not modify current VSS prompts.
- Do not run expensive model experiments.
- Do not modify Supabase.
- Do not create implementation PRs.
- Do not assume unverified repository details.
- Reuse existing evaluation infrastructure where possible.
- Keep annotation guidelines separate from experimental prompts.
- Finalise scoring rules before AI-assisted correction.
- Preserve original human annotations.
- Preserve unsuccessful prompt versions.
- Do not guarantee monotonic improvement.
- Prevent ground-truth leakage into VSS.
- Do not optimise prompts against the final held-out test set.
- Do not merge anything without approval.

Once the planning document is complete, provide:

1. A concise current-state summary.
2. The proposed PR sequence.
3. The critical dependencies.
4. Recommended methodological choices.
5. Blocking decisions requiring approval.
6. The recommended first PR.

**Wait for my approval before implementation begins.**
