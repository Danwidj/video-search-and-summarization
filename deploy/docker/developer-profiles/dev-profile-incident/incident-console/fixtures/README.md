# Dashboard seed preview

The dashboard_seed.py fixture contains 18 synthetic incidents based on the supplied
sheet examples, linked entities, four instruments, two assets and 18 videos.
Report and Query collections are intentionally empty; these widgets do not need them.
No database seeding or writes occur.

When the database helper returns no handle, the Analytics Dashboard shows a labeled
Preview mock / seed data toggle, enabled by default. Disable it to review empty
states. The existing database notice remains visible.

Field names match the supplied model. Confidence is optional and uses 0–1 values.
Duration is seconds; timestamps are video-relative HH:MM:SS. The trend groups
Start_Timestamp into 30-second clip-offset buckets, not calendar dates.
Entity/instrument/asset IDs are scoped to Incident_ID. All URL fields are opaque
placeholder strings on example.invalid, with no storage-provider parsing.

Location and Status are not in this schema and display as Not supplied.
Active Under Review is unavailable rather than inferred from confidence.
The separate confidence queue prioritizes missing scores, then scores below 70%,
with descending severity breaking ties. Missing scores are excluded from averages.

Live mode preserves list_reports(status="verified"). The display adapter in
dashboard_view.py handles that legacy response without changing production reads.
It contains no linked entities/instruments, so those widgets explain that gap.

To remove the preview, delete this fixtures directory and the preview branch in
pages/3_Dashboard.py. No database or storage configuration changes are required.
