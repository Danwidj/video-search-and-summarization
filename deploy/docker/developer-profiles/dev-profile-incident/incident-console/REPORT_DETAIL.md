# Incident Reports and Dashboard

Run .venv/bin/streamlit run app.py. The app registers exactly two pages:
Incident Reports and Analytics Dashboard. Details are an internal view of
Incident Reports, selected by the report query parameter. Older catalog and
evaluation source files remain in the repository but are not registered pages.

Incident Reports uses the incidents from fixtures/dashboard_seed.py (the
capstone group's real ground truth plus a clearly-flagged synthetic half; see
fixtures/README.md for the split and counts). local_reports.py adapts those rows
without changing the fixture or dashboard.
Review status starts Unreviewed as local workflow state. Edits, verification and
video mappings last only for the current Streamlit session; they do not update
the fixture, Dashboard, Postgres, or Cloudflare R2.

R2 footage is listed read-only and matched by category for demo playback. These
clips are explicitly labeled as demo footage, not evidence for the sample event.
The local environment needs R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY and
R2_BUCKET. Credentials stay server-side; playback uses one-hour signed URLs.
No report metadata is read from or written to R2. A manual URL override remains
available inside the video panel. Do not commit local environment files.

Edit fields switches the displayed report fields into inputs in place. Save
validates timestamps and confidence; Cancel discards the draft. Video selection,
playback and jump controls sit together beside the report and verification form.

The detail view shows all eight incident fields, unchanged seed descriptions,
and a pending AI Summary. Missing confidence stays missing. Playback seeks to
the incident start; jump buttons seek to either bound. The video range marker
appears only if an actual video duration is supplied (none is invented for a
manually linked video). Entity, Instrument and Asset UI are out of scope.

Full severity rubric text is not available in this checkout; the tooltip says so.
The legacy database review adapter remains available for future live integration,
but Incident Reports does not connect to it. Dashboard retains its existing
behavior, including its existing database notice and optional seed preview.
