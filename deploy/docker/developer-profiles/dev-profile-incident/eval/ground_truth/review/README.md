# Ground-truth review (PR 3 → PR 4 → PR 5)

This folder holds the **proposed** corrections to the human-labelled ground truth. They follow [`annotation-guidelines-v1.0`](../annotation-guidelines-v1.0.md) and are **not final ground truth**:
- PR 4 reviews each proposal (AI-assisted and human), setting it to Approved or Rejected;
- PR 5 freezes the approved version as `ground-truth-v1.0`.

| File | In git | What |
|---|---|---|
| `Ground Truth Review v0.1.xlsx` | **no** (see Storage) | The editable working workbook: the source's sheets with the proposed values written in, plus `Review Summary` and `Change Log` |
| [`audit-v0.1.md`](audit-v0.1.md) | yes | The audit report: findings by rule, with ids and counts only and no annotation text |
| [`review-v0.1-manifest.json`](review-v0.1-manifest.json) | yes | Source SHA-256, output SHA-256, change-log digest, counts and inventory facts |

## Source

`Complete Ground Truth Labelling.xlsx` (profile root, gitignored) is never modified. The build opens it twice, once for values and once for formulas, saves only the new file, and fails if the source's SHA-256 changes. The v0.1 source SHA-256 is:

`7c3f1fcc186e2608887ea31fc9eda06178522c4525763f69d7e2b46032cc2a5c`

## Rebuild

From `eval/`:

```bash
uv run python scripts/gt_review_build.py                 # source: ../Complete Ground Truth Labelling.xlsx, version v0.1
uv run python scripts/gt_review_build.py --version v0.2  # a new version; never overwrite one under review
```

The same source, dataset manifest and generator always give the same change-log digest (recorded in the manifest). The `.xlsx` bytes differ between builds because the file embeds its save time, so compare digests, not file hashes.

## The working workbook

- **`Review Summary`** (first sheet): progress, entries by class and by rule, and the affected videos. All counts are formulas over the `Change Log`, so they update as reviewers work.
- **`Change Log`:** one row per finding, with these columns:
  - change id, incident and record id, sheet, row and field;
  - original and proposed values;
  - class, rule, guideline reference and reason;
  - **supporting video evidence** (the clip, its local copy and the incident window to watch);
  - confidence and **review status** (Pending / Approved / Rejected dropdown), reviewer and notes.
- **Data sheets** (`gt_incidents`, `gt_entities`, `gt_instruments`, `gt_assets`): the source columns, rows, ids and formulas, with proposed values written in.
  - **Colours:** green marks verified corrections, yellow rule-based proposals, orange cells needing video review.
  - **Cell comments** give the change id and the original value.
  - **Two review columns** follow the documented ones: `review_flags` and `change_ids`.
  - **Removals:** rows proposed for removal are struck through and flagged, not deleted.
  - **Additions:** new records are appended with the next free id, and nothing is renumbered.
- **Classes:**
  - `verified_correction`: provable without video, from the workbook or the dataset manifest;
  - `rule_based_proposal`: an approved guideline rule applied to what the annotator recorded;
  - `needs_video_review`: only the video can answer, so **no value is proposed**;
  - `informational`: recorded, no change.
- **Out of taxonomy:** possible out-of-taxonomy clips carry the `OUT_OF_TAXONOMY_CANDIDATE` review flag. Their type stays one of the five categories.

## Storage

The working workbook is **not committed**. `eval/.gitignore` lists it on purpose, with this README as the reason:
- the source workbook has never been committed (`eval/eval_data/` is ignored as real annotation data);
- the workbook carries annotator names (`Labelled_By`);
- where the frozen ground truth will live (plan decision D7) is not yet decided.

**Persistence today:** the file is at `eval/ground_truth/review/Ground Truth Review v0.1.xlsx` on the build machine. Its SHA-256 at build time is in `review-v0.1-manifest.json`, and it can be rebuilt with the same change-log digest from the source, the tracked dataset manifest and the generator.

**Proposed durable location (needs approval; a write to shared storage):** the private R2 bucket under `ground-truth/review/<version>/`, holding the workbook, the manifest and the source's SHA-256. R2 already holds the dataset and is backed up with it. Each reviewed state is uploaded as a new object (`…-reviewed-<date>.xlsx`), never overwritten. A team drive would also work; R2 keeps it next to the videos and under the same access control.
