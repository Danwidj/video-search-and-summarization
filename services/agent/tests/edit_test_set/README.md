# Edit and Clip Request Test Set & Scorer (Item 1D)

This package contains the fixed set of 20 realistic edit and clip requests with expected tools and arguments, plus an offline scorer that runs completely without hosted models.

## Background & Origin

Derived from the scout evaluation reported in `data/vss-agent-tool-loop/report.md` (section 3) as part of Plan B Phase 1:
- **10 Investigator clip requests (`I1`–`I10`)**: cover report-only retrieval, evidence crop search, time window clips, action vs entity differentiation, multi-source queries, domain refusals (weather, audio), exact argument precision, parameter binding across videos, and out-of-range recovery.
- **10 Editor edit requests (`E1`–`E10`)**: cover entity renaming, time range updates, composite removals and additions, summary rewrites, capability limits (severity), out-of-scope refusals (France capital), non-existent target rejection, ambiguous physical dimension refusals, batch operations, and unauthorized actions (direct publishing).

## Structure

```
services/agent/tests/edit_test_set/
├── cases.json        # Canonical 20-case test definitions (JSON)
├── cases.py          # Pydantic data models & test set loader
├── scorer.py         # Offline evaluation engine & metric reporter
├── __main__.py       # CLI runner
├── fixtures/         # Golden trace fixtures from the scout evaluation
└── README.md         # This document
```

## Running the Scorer

### Via Python API
```python
from tests.edit_test_set import Scorer, ExecutionTrace, load_default_test_set

scorer = Scorer()
trace = ExecutionTrace(
    case_id="E1",
    steps=[
        {"tool": "propose_edit", "args": {"item_id": "E1", "field": "label", "new_value": "delivery van"}},
    ],
    answer="Proposed renaming E1 to delivery van."
)
score = scorer.score_trace(trace)
print(f"Passed: {score.passed}, Score: {score.total_score}")
```

### Via CLI
```bash
python -m tests.edit_test_set --input tests/edit_test_set/fixtures/battery_editor_1.jsonl
```

### Via Pytest
```bash
uv run pytest tests/unit_test/test_edit_test_set.py -v
```
