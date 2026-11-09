# Ask for a chart: three example chips (2026-11-09)

Desktop 1440 px captures of the dashboard's "Ask for a chart" panel, taken on the local console (port 3210) against the live agent and database, read-only.

Final chips (`chips-row-1440.png` shows them): chip 1 is unchanged; chips 2 and 3 are the chosen candidates 1 and 2.

| File | Prompt | Drawn as | Verdict |
|---|---|---|---|
| `chip-1-october-severity-stacked-1440.png` | Break down each incident type by severity throughout October | Stacked bar by severity (view) | Chip 1, kept |
| `chip-2-share-incident-types-october-1440.png` | Share of each incident type throughout October | Donut | Chip 2 |
| `chip-3-severity-mix-assault-90d-1440.png` | Severity mix of assault incidents in the last 90 days | Donut | Chip 3 |
| `candidate-01-share-incident-types-october-1440.png` | Share of each incident type throughout October | Donut, 5 slices | Best, chosen |
| `candidate-02-severity-mix-assault-90d-1440.png` | Severity mix of assault incidents in the last 90 days | Donut, 3 slices | Good, chosen |
| `candidate-03-ai-or-human-reviewers-october-1440.png` | Who wrote the reports in October: AI or human reviewers | Donut, 2 slices (2 vs 62) | Lopsided, not chosen |
| `candidate-04-official-status-30d-1440.png` | Official and not official reports in the last 30 days | Donut, 2 slices (5 vs 76) | Lopsided, repeats the totals card |
| `candidate-05-analysis-outcomes-all-runs-1440.png` | Share of analysis outcomes across all runs | Donut, 5 slices | Pipeline data, one slice dominates, "Earlier" label |
| `candidate-06-road-accident-severity-october-1440.png` | Severity mix of road accidents throughout October | Stacked bar by severity (view), one bar | One bar, not a chart worth a chip |
| `candidate-07-official-share-october-1440.png` | Share of October reports that are official | Donut, 2 slices (0 vs 64) | Empty slice, not chosen |
