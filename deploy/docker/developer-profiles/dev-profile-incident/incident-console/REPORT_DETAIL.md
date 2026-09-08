# Incident Reports and Dashboard

Run .venv/bin/streamlit run app.py. The app registers exactly two pages:
Incident Reports and Analytics Dashboard. Details are an internal view of
Incident Reports, selected by the report query parameter. Older catalog and
evaluation source files remain in the repository but are not registered pages.

Incident Reports and Dashboard both read fixtures/data/*.csv through
fixtures/dashboard_seed.py. local_reports.py is a thin view model over the
same rows; it does not create a second session copy. Edits to the Incident
fields are written atomically back to fixtures/data/incidents.csv, so they
survive refreshes and are immediately visible to the Dashboard.

R2 footage is listed read-only and mapped once per Incident_ID. Existing
filename matches win; when synthetic filenames do not exist in R2, the next
unused category clip is used, then an unused bucket clip as a last resort.
These clips are explicitly labeled as demo footage, not evidence for the sample event.
The local environment needs R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY and
R2_BUCKET. Credentials stay server-side; playback uses one-hour signed URLs.
No report metadata is read from or written to R2. Do not commit local environment files.

Edit fields switches the displayed report fields into inputs in place. Save
validates timestamps and confidence; Cancel discards the draft. Video selection,
playback and jump controls sit together beside the report and verification form.

The detail view shows only the supplied Incident fields and unchanged seed
descriptions. Missing confidence stays missing. Playback seeks to
the incident start; jump buttons seek to either bound. The video range marker
appears only if an actual video duration is supplied (none is invented for a
manually linked video). Entity, Instrument and Asset UI are out of scope.

Full severity rubric text is not available in this checkout; the tooltip says so.
Status, location, reviewer and audit fields are not rendered because they are
not present in fixtures/data/incidents.csv. Dashboard retains its database
notice and reads the same CSV preview data when no database is configured.
