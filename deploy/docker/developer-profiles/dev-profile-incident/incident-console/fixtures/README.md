# Dashboard seed preview

`dashboard_seed.py` no longer hardcodes a synthetic incident list. `load_seed()`
now parses four committed CSV files under `data/` with the Python stdlib `csv`
module (no new dependencies) and returns the same dict shape as before:
`{"Incident": [...], "Entity": [...], "Instrument": [...], "Asset": [...],
"Report": [], "Video": [...], "Query": []}`. Every consumer
(`pages/3_Dashboard.py`, `dashboard_view.py`, `pages/2_Report_Review.py`,
`report_detail.py`, `local_reports.py`) keeps working unchanged. No database
seeding or writes occur.

## The four data files

| File | Rows | Real (`synthetic=false`) | Synthetic (`synthetic=true`) |
|---|---|---|---|
| `data/incidents.csv` | 72 | 36 | 36 |
| `data/entities.csv` | 133 | 52 | 81 |
| `data/instruments.csv` | 37 | 17 | 20 |
| `data/assets.csv` | 40 | 8 | 32 |

`data/incidents.csv` keeps the ground-truth column names
(`Start_Timestamp_sec`, `End_Timestamp_sec`, `Duration_sec`, `Severity_Level`,
`Confidence_Score`); the parser maps them onto the dict keys the consumers expect
(`Start_Timestamp` / `End_Timestamp` as `"HH:MM:SS"` strings, `Duration` as int
seconds, `Severity`, and `Confidence_Score` omitted entirely when blank). Every
row in every file carries a `synthetic` column (`false` / `true`) — this is the
load-bearing separator the graders and the eval flow filter on. `Video` rows are
still generated in code, one per incident (`ID=V<n>`), because the sheet provides
no Video data. Each generated row carries the matching `Incident_ID` and
`Filename`; the report view resolves that filename to one distinct Cloudflare
R2 object at runtime. Exact filename matches win, and unused category clips are
assigned to synthetic rows when the bucket has fewer clips than the fixture.
`Report` and `Query` stay empty lists.

These are plain CSV data files, so they carry no SPDX/licence header (the repo
only applies that header to source, not to data fixtures).

## Real vs synthetic split

**Real half (36 incidents)** — the capstone group's ground-truth sheets,
transcribed verbatim from `groundtruth/` (descriptions lightly copy-edited for
spelling only, lowercased):

- 7 `burglary`, 9 `explosion`, 5 `road accident`, 15 `animal`. IDs are the
  sheet's own (`Burglary001`, `Explosion001`, `RoadAccidents001`, `Animal001`, …).
- All real `Severity_Level` values for `burglary` and `road accident` are blank
  in the sheet and are carried through as `None`.
- Every real `Confidence_Score` is blank → the key is omitted on every real row.
- Every real `Image` is blank → `Image` is `None` on all entities/instruments/assets.

**Synthetic half (36 incidents)** — generated to fill the gaps the real data
lacks. IDs use the `SYN-<Type><NNN>` scheme (`SYN-Fighting001`,
`SYN-Explosion001`, …); entity/instrument/asset IDs stay `E1` / `I1` / `A1`
scoped to their synthetic incident.

- 12 `fighting` (the enum has the type; the real data has zero fighting incidents).
- 9 `explosion`, each with linked entities, instruments **and** assets (the real
  data has explosion incidents but no linked rows of any kind for them).
- 5 `burglary`, 5 `road accident`, 5 `animal` to round out the spread.
- A wide `Confidence_Score` spread (the real data has none): several scores below
  0.7 and several deliberately missing, so the dashboard's Low-Confidence Review
  Queue widget has content. Across the whole seed, 44 incidents have no score and
  14 score below 0.7.
- Broader instrument/asset variety across all types, with `Threat_Level` per the
  same rubric the real data uses (firearm/IED-class 5, blade/machete 4,
  bat/pipe/vehicle 3, screwdriver/bottle/bolt-cutter 2, trolley/bag 1;
  road-accident vehicles left blank, matching the real rows).
- Every synthetic incident has 1–4 linked entities (human / animal / unknown mix)
  and, where it fits the scenario, instruments (with `Entity_ID` and
  `Threat_Level`) and assets. Descriptions match the real style: short, objective,
  lowercase.

## Known ground-truth gaps (carried through as-is, not invented)

Reproduced from `groundtruth/NOTES.md`; these affect only the **real** rows:

1. Descriptions were copy-edited for spelling/grammar only and lowercased;
   meaning unchanged. Raw originals can be restored as a quick follow-up.
2. Blank `Severity_Level` on every real `burglary` and `road accident` incident →
   carried as `None`. These incidents do not appear in severity-filtered
   dashboard views or the "Critical Alerts (Sev 4–5)" KPI, and show "Not
   supplied" in report detail. Do **not** invent values.
3. `Confidence_Score` blank for every real row → key omitted (never `None`/`0`).
4. `Image` blank for every real entity/instrument/asset → `None`.
5. Empty incident rows `Burglary005`, `Burglary006`, `Explosion007` have no
   type/timestamps/description in the sheet. They are emitted with `Type=None`
   and null fields. (`load_seed()` still returns them; `pages/2_Report_Review.py`
   got a two-line null-guard so the card list tolerates the missing type — see
   the PR description.)
6. `RoadAccidents006` appears in `entities.csv` (one entity, `E2` only) with **no**
   row in `incidents.csv`. The stray entity is carried as-is; it links to no
   incident and is excluded from every dashboard join.
7. Road-accident instruments have no `Threat_Level` in the sheet → `None`.
8. `Burglary007` instrument `I2` (truck) has no `Entity_ID` → `None`.
9. `RoadAccidents005` instrument `I2` points at entity `E2`, but that entity row
   was filed under the stray `RoadAccidents006` (gap 6), so `RoadAccidents005`
   itself only has `E1`. Carried through unchanged; flagged for the group.
10. Instrument names like `suv` / `truck` / `bus` / `car` / `van` are vehicles the
    group recorded as "instruments" (the means used); kept as-is. The synthetic
    rows follow the same convention.
11. No real `explosion` entities/instruments/assets and no real `fighting`
    incidents were provided — the synthetic half supplies both.

## Dashboard behaviour notes (unchanged)

When the database helper returns no handle, the Analytics Dashboard shows a
labelled *Preview mock / seed data* toggle, enabled by default. Disable it to
review empty states. Field names match the supplied model. Duration is seconds;
timestamps are video-relative `HH:MM:SS`. The trend groups `Start_Timestamp` into
30-second clip-offset buckets, not calendar dates. Entity/instrument/asset IDs
are scoped to `Incident_ID`. All URL fields are opaque placeholder strings on
`example.invalid`, with no storage-provider parsing.

Location and Status are not in this schema and display as "Not supplied". Active
Under Review is unavailable rather than inferred from confidence. The confidence
queue prioritises missing scores, then scores below 70%, with descending severity
breaking ties. Missing scores are excluded from averages.

Live mode preserves `list_reports(status="verified")`. The display adapter in
`dashboard_view.py` handles that legacy response without changing production
reads. It contains no linked entities/instruments, so those widgets explain that
gap.

To remove the preview, delete this `fixtures/` directory and the preview branch
in `pages/3_Dashboard.py`. No database or storage configuration changes are
required.
