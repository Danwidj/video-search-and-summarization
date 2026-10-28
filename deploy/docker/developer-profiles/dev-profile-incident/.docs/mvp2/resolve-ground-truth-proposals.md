I do not have time to manually review all 98 Pending ground-truth proposals. I authorise an AI-assisted adjudication process to resolve them, subject to the safeguards below.

The goal is to produce a defensible, consistent and visually grounded ground-truth candidate for our FYP evaluation, while minimising unnecessary manual work.

### 1. Decision framework

For each of the 98 entries, independently evaluate the original value, AI proposal, annotation guidelines and available video evidence.

Choose one of:

- ACCEPT: Apply the AI proposal because it corrects an error or meaningfully improves annotation quality.
- REJECT: Keep the original because it is correct, sufficiently clear or more informative.
- MODIFY: Apply a better custom value that follows the annotation guidelines.
- VERIFY VIDEO: Inspect the relevant video before choosing ACCEPT, REJECT or MODIFY.

Do not simply reproduce the original AI recommendation. Reassess each case independently.

### 2. Automatic application

I authorise you to automatically apply ACCEPT, REJECT and MODIFY recommendations to a **new AI-adjudicated review workbook**, without requiring me to approve each row.

For VERIFY VIDEO:
- Locate the relevant development or test video and cited timestamps.
- Inspect the video or extract relevant frames using the project's existing tools.
- Make a final decision based on visible evidence.
- If the evidence remains inconclusive, retain an explicit unresolved status rather than guessing.

Do not treat a text-only assessment as video verification.

### 3. Annotation standards

Follow the existing annotation guidelines, especially Pronoun Policy P1.

For gender and pronoun changes:
- Do not automatically replace all gendered references with neutral alternatives.
- Preserve visually supported information, using qualified descriptions where required.
- Use neutral descriptions where gender is uncertain.
- Ensure pronoun consistency.
- Prefer minimal corrections rather than unnecessarily rewriting descriptions.

For factual changes:
- Prioritise accuracy over fluency.
- Verify changes to incident type, severity, threat level, timestamps, entity identity/count, instruments, assets and taxonomy classifications against video evidence.
- Preserve meaningful details.
- Avoid unsupported assumptions, inferred motivations and invented events.

For stylistic changes:
- Reject changes that merely rephrase an already accurate annotation.
- Do not optimise wording for Cosmos 3 Super or the LLM-as-judge.
- Apply the same standards consistently across all incident categories.

### 4. Risk-based verification

Classify every decision as low, medium or high impact based on its potential effect on evaluation.

Low impact:
- Pronoun consistency.
- Grammar.
- Minor wording changes that preserve meaning.

Medium impact:
- Entity descriptions.
- Object descriptions.
- Changes to event wording that might affect semantic similarity.

High impact:
- Incident type or taxonomy.
- Severity or threat level.
- Start/end timestamps.
- Entity counts or identities.
- Instrument/asset identification.
- Substantive changes to the event sequence.

Inspect source videos for all high-impact decisions.

Do not rely on the AI confidence column as proof of correctness.

### 5. Preserve traceability

Create a separate AI-adjudicated workbook and audit report.

For each of the 98 entries, record:
- Change Log ID.
- Original value.
- AI proposal.
- Final decision.
- Final accepted value.
- Justification.
- Evidence source, including video ID and timestamps if inspected.
- Whether video verification was actually performed.
- Whether the decision remains uncertain.
- Decision provenance: AI-assisted, not human-reviewed.

Do not overwrite the original review package, source ground truth or existing candidates.

Ensure paired reclassifications remain consistent.

### 6. Build a new candidate

After adjudication:
1. Validate all decisions against the annotation schema and guidelines.
2. Generate a new candidate using the existing candidate-building workflow, or a clearly documented AI-adjudication variant if required.
3. Run all available offline validation tests.
4. Produce a summary of accepted, rejected, modified and unresolved changes.
5. Identify any changes that materially affect evaluation labels or scoring denominators.

Do not fabricate human approvals or populate the human Reviewer field with my identity.

If existing scripts require human approval, do not bypass that requirement. Instead, prepare the AI-adjudicated candidate and explain precisely what is needed to finalise it.

### 7. Evaluation integrity

Do not inspect model predictions, Stage 0 outputs or benchmark scores when adjudicating annotations.

Do not tune the ground truth to favour either direct VLM or VSS.

Do not modify the evaluation methodology, scoring thresholds or model prompts.

Keep an immutable record of the original ground truth and every change.

### 8. Final report

After processing the 98 entries, report:

- ACCEPT / REJECT / MODIFY counts.
- Number of videos actually inspected.
- Number of unresolved cases.
- Changes affecting incident fields, entities, instruments, assets or taxonomy.
- Any changes to scoring eligibility.
- Validation results.
- Whether the candidate is ready for final approval.

Only escalate cases where the video evidence is genuinely ambiguous, inaccessible or contradictory.

Do not freeze ground-truth-v1.0 or execute Stage 1 yet. I will review the final summary and explicitly approve the AI-assisted ground-truth candidate before freezing.
