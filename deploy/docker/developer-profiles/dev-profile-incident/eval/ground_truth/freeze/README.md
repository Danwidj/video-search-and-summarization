# Ground-truth freeze (PR 5)

`ground-truth-v1.0` is built from the unchanged source workbook plus the review decisions in the latest reviewed candidate workbook (`../review/Ground Truth Candidate <version>.xlsx`). It is **frozen only when you approve it**. Until then the output is a `candidate`, which the loader refuses for reported results.

| File | In git | What |
|---|---|---|
| [`ground-truth-v1.0-readiness.md`](ground-truth-v1.0-readiness.md) | yes | Status, blocking issues and validation (ids and counts only) |
| `ground-truth-v1.0-approval.json` | written by the approver | The approval record (below). Not created by any tool |
| `eval_data/ground_truth/ground-truth-v1.0/` | **no** | `ground_truth.json` (records), `split-v2.json`, `MANIFEST.json` (SHA-256 of every output and input, versions, git SHA, status, blocking reasons) |
| [`../../eval_reproducibility/split-v2.json`](../../eval_reproducibility/split-v2.json) | yes | `split-v2`: dev = the 25 former few-shot clips, test = the 55 evaluation clips. Membership is unchanged from the seeded `split_<category>.json` |

## Build

From `eval/`:

```bash
uv run python scripts/gt_freeze.py --candidate "ground_truth/review/Ground Truth Candidate v0.2.xlsx"
uv run python scripts/gt_freeze.py --candidate … --approval ground_truth/freeze/ground-truth-v1.0-approval.json
```

## What blocks a freeze

- **Any entry still `Pending`.** A Pending entry is never treated as Approved. Review it in the candidate workbook, then build the next candidate version.
- **Linked entries decided apart:** a reclassification approved on one side only.
- **An approved entry whose AI proposal is invalid** and that has no accepted value.
- **Schema problems:**
  - a type outside the five;
  - severity or threat outside 1-5;
  - an id that is not exactly `E#`/`I#`/`A#`, or a duplicate id;
  - an instrument holder that is not an entity of the incident;
  - start not before end, an end past the clip, or a duration that is not end - start;
  - an empty description;
  - a filename that is not a `dataset-manifest-v1` clip, or a clip with no incident.
- **Split problems:**
  - not 25/55 (unless exclusions are approved);
  - a clip in both halves;
  - split and ground truth differ;
  - the split's category differs from the ground-truth type.
- **No approval record, or one that does not name exactly this candidate.**

## The approval record

Written by the person approving the final annotations and exclusions, after reading the readiness report:

```json
{
  "version": "ground-truth-v1.0",
  "candidate_workbook_sha256": "<the candidate workbook's SHA-256, from the readiness report>",
  "records_sha256": "<the records digest, from the readiness report>",
  "exclusions": [],
  "unresolved_keep_original": [],
  "approved_by": "<name or role>",
  "approved_at": "<ISO date>"
}
```

`unresolved_keep_original` lists AI-unresolved entries whose original value the owner keeps (otherwise they block). For an AI-Adjudicated Candidate, pass `--adjudication <file>` to `gt_freeze.py`.

`exclusions` lists incident ids to leave out of the ground truth and both split halves. Any exclusion changes the 25/55 split, so it needs this explicit approval. If any value differs from the candidate, the output stays a `candidate`.

## After freezing

- **Loading:** `eval_gt_schema.load_frozen_gt_index(<dir>)` verifies every file against `MANIFEST.json` and refuses an altered file or a candidate. `allow_candidate=True` is for plumbing tests only, never for reported results.
- **Never overwritten:** a frozen directory is refused as a target. A genuine error found later becomes `v1.1`, and every compared prompt version is rerun.
- **Storage:** frozen ground truth is local and gitignored until plan decision D7 (committed JSON vs R2) and the annotation-text privacy question are decided.
