# Incident Reports and Dashboard

Run .venv/bin/streamlit run app.py. The app registers exactly two pages:
Incident Reports and Analytics Dashboard. Details are an internal view of
Incident Reports, selected by the report query parameter.

Both pages are database-backed. With no `INCIDENT_DB_DSN` configured they render
the visible "database not configured" state and stop; there is no offline mode.
With a DSN set, Incident Reports and Dashboard read and write incidents through
`db.py` (`IncidentDB`) via the `db_reports.py` view model. Edits to the Incident
fields round-trip through Supabase Postgres, so they survive refreshes and are
immediately visible to the Dashboard.

R2 footage is listed read-only and mapped once per Incident_ID. Existing
filename matches win; when an incident filename does not exist in R2, the next
unused category clip is used, then an unused bucket clip as a last resort.
These clips are explicitly labeled as demo footage, not evidence for the sample event.
The local environment needs R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY and
R2_BUCKET. Credentials stay server-side; playback uses one-hour signed URLs.
No report metadata is read from or written to R2. Do not commit local environment files.

Edit fields switches the displayed report fields into inputs in place. Save
validates timestamps and confidence; Cancel discards the draft. Video selection,
playback and jump controls sit together beside the report and verification form.

The detail view shows only the supplied Incident fields. Missing confidence
stays missing. Playback seeks to the incident start; jump buttons seek to either
bound. The video range marker appears only if an actual video duration is
supplied (none is invented for a manually linked video). Entity, Instrument and
Asset UI are read-only sections below the fields.

Full severity rubric text is not available in this checkout; the tooltip says so.
The review-status control renders a "Verified by" / "Last edited by" attribution
caption from the persisted verified_by / edited_by columns, so a saved reviewer
name survives navigating away and back.
