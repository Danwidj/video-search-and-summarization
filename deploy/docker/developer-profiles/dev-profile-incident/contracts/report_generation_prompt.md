REPORT GENERATION PROMPT - RP1 (incident-contract-v2)

Generate a concise, objective incident report using ONLY the structured
incident information provided below.

The report must accurately reflect the supplied structured data.
Do not invent, infer, or assume identities, motives, relationships,
causes, injuries, weapons, actions, outcomes, or other details that are
not supported by the supplied data.

Do not independently reinterpret or reanalyse the source video. The
structured incident data is the sole source of information for this report.

==================================================
INCIDENT REPORT
==================================================

Incident Type: <type>
Severity: <severity_level>/5
Incident Time: <start_timestamp>–<end_timestamp>
Duration: <duration> seconds

SUMMARY

Provide a concise overview of the incident.

Summarise:
- what happened;
- the directly relevant entities involved;
- the most important actions or interactions; and
- the main observable outcome, if available.

Aim for approximately 40–60 words, but use fewer words when the incident
is simple.

==================================================
INCIDENT DETAILS
==================================================

Provide an objective, chronological account of the incident based on the
supplied structured data.

Focus on the sequence of important observable events and interactions.
Mention relevant instruments and assets where they contribute to
understanding what occurred.

Do not speculate about intent, motivation, relationships, causation, or
events that are not represented in the supplied data.

Aim for approximately 60–100 words, but use fewer words when sufficient.

==================================================
ENTITIES INVOLVED
==================================================

List each supplied entity separately.

For each entity, provide:
- Entity_ID
- Type
- Description
- relevant role/actions, if available from the supplied data

Example:
E1 — Human: Person wearing a dark shirt who approached E2 and initiated
the physical confrontation.

Do not add people or animals that are not present in the structured data.

If there are no entities, write:
"None identified."

==================================================
INSTRUMENTS
==================================================

List each supplied instrument separately.

For each instrument, provide:
- Instrument_ID
- Name
- Description
- Entity_ID of the entity holding it, if available
- Threat Level: <level>/5

Example:
I1 — Knife — Held by E1 — Threat Level: 4/5

Threat level represents the instrument's potential to cause harm in the
observed context, not the amount of harm actually caused.

Do not add instruments that are not present in the structured data.

If there are no instruments, write:
"None identified."

==================================================
ASSETS
==================================================

List each supplied asset separately.

For each asset, provide:
- Asset_ID
- Name
- Description

Mention its relevance to the incident only when that information is
supported by the supplied data.

Do not add assets that are not present in the structured data.

If there are no assets, write:
"None identified."

==================================================
OBSERVATIONS / LIMITATIONS
==================================================

Briefly state any material uncertainty or missing information explicitly
present in the supplied data that affects interpretation of the incident.

Do not create uncertainties merely to populate this section.

If there are no material limitations represented in the supplied data,
write:
"No material limitations identified from the supplied incident data."

==================================================
LENGTH AND STYLE
==================================================

- Keep the report concise and proportional to the complexity of the incident.
- Most reports should be approximately 150–250 words.
- Simple incidents may be shorter than 150 words.
- Never exceed 300 words.
- Do NOT add unnecessary information to reach a target word count.
- Use neutral, factual, professional language.
- Avoid dramatic, emotive, or speculative language.
- Do not repeat the same information unnecessarily across sections.
- Preserve the supplied Entity_ID, Instrument_ID, and Asset_ID values.
- Do not introduce facts that are absent from the structured incident data.

Return only the completed incident report. Do not include commentary about
how the report was generated.

==================================================
STRUCTURED INCIDENT DATA
==================================================

{structured_incident_json}
