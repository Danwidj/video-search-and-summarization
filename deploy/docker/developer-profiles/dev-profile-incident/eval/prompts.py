# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""P1 (incident extraction) and RP1 (report generation) prompts.

P1 runs directly against video through a VLM and produces the structured
incident JSON that is the common interface across extraction, GT evaluation
(``matching.py``/``eval_gt.py``), DB storage, and RP1. RP1 takes P1's JSON as
its sole input (no video) and produces a human-readable report; it does not
re-analyze the video itself, so it is a plain text prompt, not a VLM prompt.

Additive to the existing NVIDIA prompts in this repo (``alert_type_config.json``,
``video_report_gen.vlm_prompt``, ``incident_report_gen``) - never a replacement
for them.
"""

from __future__ import annotations

P1_PROMPT_VERSION = "P1-v1"
RP1_PROMPT_VERSION = "RP1-v1"

P1_INCIDENT_EXTRACTION_PROMPT = """UNIFIED VLM INCIDENT EXTRACTION PROMPT — P1

You are analysing a surveillance video for structured incident extraction.

Analyse the video and identify the ONE primary incident shown in the video.
This system assumes one primary incident per video.

Extract only information that can be reasonably established from the
visual evidence. Do not invent or speculate about identities, motives,
relationships, causes, injuries, outcomes, object ownership, or other
details that cannot be established from the video.

Return the result using ONLY the structured output schema specified at
the end of this prompt.

==================================================
1. INCIDENT
==================================================

Extract the following fields:

TYPE
Classify the primary incident using exactly one of the following values:

- road accident
- burglary
- explosion
- assault
- animal attack

Use only these permitted values.

START_TIMESTAMP
- Integer number of seconds from the beginning of the video at which
  the primary incident begins.
- Identify the earliest observable moment at which the abnormal or harmful
  event itself begins.
- Do not include unrelated activity or normal activity that occurs before
  the incident.
- Base the start timestamp only on observable visual evidence. Do not infer
  that the incident began before it becomes observable in the video.

END_TIMESTAMP
- Integer number of seconds from the beginning of the video at which
  the primary incident ends.
- Identify the earliest observable moment at which the abnormal or harmful
  event has clearly ceased or reached a stable post-incident state.
- Include continuing consequences that remain part of the active incident.
  Do not end the incident merely because the initial triggering event has
  finished.

  Examples:
  - If a vehicle ignites and continues burning, the incident remains active
    while the fire is visibly burning. The incident ends when the fire has
    been extinguished or has otherwise clearly ceased.
  - If an assault occurs, the incident remains active while aggressive
    physical interaction continues. It ends when the aggressive interaction
    has clearly ceased and does not immediately resume.
  - If a vehicle collision occurs, do not end the incident at the instant of
    impact. Include the immediate collision sequence until the involved
    vehicles and people have reached a stable post-collision state.

- If the incident is still visibly ongoing when the video ends, use the
  final observable second of the video as End_Timestamp.
- Do not infer when an incident ends beyond the available video.

DURATION
- Duration of the observable incident in seconds.
- Calculate as:
  End_Timestamp - Start_Timestamp

DESCRIPTION
- Provide a short, objective description of the incident based only on
  observable events in the video.
- Describe the main event, the relevant entities and their actions, and
  relevant instruments or assets where appropriate.
- Focus on information necessary to understand what occurred.
- Do not speculate about identities, motives, relationships, causes,
  injuries, or outcomes that cannot be visually established.
- Keep the description concise, normally 1–3 sentences.
- Do not include irrelevant background activity.

SEVERITY_LEVEL
Assign an integer from 1 to 5 according to the following rubric.

1 — Minimal / Very Low
Little to no harm or danger. No injuries, negligible property damage,
and negligible disruption.

Examples:
- minor verbal disagreement
- harmless animal presence
- minor incident with no injury or meaningful damage

2 — Low
Minor harm or limited danger. May involve minor injuries, limited
property damage, or temporary disruption, but the situation is not
seriously threatening.

Examples:
- minor physical altercation
- minor road accident
- limited property damage
- minor injury not requiring urgent intervention

3 — Moderate
Significant harm or clear public-safety risk. May involve significant
injuries, substantial property damage, or behaviour that could
reasonably escalate into serious harm.

Examples:
- physical fight causing injury
- substantial vehicle collision
- burglary with property damage
- dangerous animal threatening a person

4 — High
Severe harm or major danger. May involve severe injuries, major
property damage, or significant danger to multiple people.

Examples:
- serious assault
- major vehicle collision with severe injuries
- large explosion causing major damage
- armed confrontation posing immediate danger

5 — Critical
Extreme or catastrophic harm. Involves fatalities, imminent risk of
multiple deaths, massive destruction, or widespread danger.

Examples:
- fatal incident
- major explosion threatening many people
- catastrophic collision with multiple casualties
- event posing immediate lethal danger to a large group

Do not infer injuries, fatalities, or damage that are not visually
supported by the video.

CONFIDENCE_SCORE
- Do NOT invent or self-report a subjective confidence score.
- Return null unless the underlying model/API provides a native,
  meaningful confidence measure.
- If no such native confidence measure is available, return null.

==================================================
2. ENTITIES
==================================================

DEFINITION

An entity is a living being (human or animal) that is directly relevant
to the incident through participation, causation, victimization,
material impact, or active response.

INCLUDE living beings that:
- cause or participate in the incident;
- are targeted, injured, threatened, attacked, or otherwise materially
  affected by the incident; or
- actively respond to the incident, such as by intervening, assisting
  a victim, confronting a participant, or taking another observable
  action directly related to the incident.

EXCLUDE incidental or background living beings whose presence does not
materially affect the incident.

Mere visibility, proximity, observation, or passing through the scene
is NOT sufficient for inclusion.

For example:
- attacker → include
- victim → include
- person physically intervening → include
- person visibly assisting a victim → include
- unrelated passer-by → exclude
- distant person merely watching → exclude
- unrelated background crowd → exclude

If there is insufficient visual evidence that a living being is directly
relevant to the incident, do not include it.

For every qualifying entity, return:

ENTITY_ID
- Assign sequentially within the incident: E1, E2, E3, ...

TYPE
Use exactly one of:
- human
- animal
- unknown

DESCRIPTION
- Provide a short, objective description.
- Include useful distinguishing visual appearance, observable actions,
  and/or role in the incident.
- Do not infer identity, occupation, relationship, motive, or other
  attributes that cannot be visually established.

If no qualifying entities are observed, return an empty array.

==================================================
3. INSTRUMENTS
==================================================

DEFINITION

An instrument is a non-living physical object that satisfies BOTH
conditions:

1. It is visibly HELD IN THE HAND of a qualifying entity; AND
2. It is relevant to the incident.

An instrument does NOT have to be a weapon.

Examples may include:
- firearm
- knife
- bottle
- stick
- tool
- phone
- wallet
- bag
- another relevant hand-held object

An object is NOT an instrument merely because it belongs to, is near,
is attached to, or is worn by an entity.

The object must be visibly held in the hand.

Do not infer ownership. Associate an instrument with an entity only when
the video provides sufficient visual evidence that the entity is
holding it.

Exclude hand-held objects that have no meaningful relevance to the
incident.

If there is insufficient visual evidence that an object is being held
in the hand, do not classify it as an instrument.

For every qualifying instrument, return:

INSTRUMENT_ID
- Assign sequentially within the incident: I1, I2, I3, ...

ENTITY_ID
- ID of the qualifying entity visibly holding the instrument.
- This must reference an entity in the Entities array.
- Return null only when the holder cannot be reliably determined.

NAME
- Concise name for the object.
- Use a lowercase noun where possible.
- Do not identify an object more specifically than the visual evidence
  supports.

DESCRIPTION
- Provide a short, objective description of the instrument and its
  observable relevance to the incident.

THREAT_LEVEL
Assign an integer from 1 to 5.

Threat level represents the instrument's POTENTIAL TO CAUSE HARM given
both its inherent characteristics and the observed context.

Threat level does NOT represent the amount of harm that actually
occurred.

1 — Minimal / Very Low
The instrument presents little to no realistic capacity for harm in
the observed context.

Examples:
- wallet
- phone
- harmless everyday object

2 — Low
The instrument could cause minor harm but is not normally capable of
causing serious injury in the observed context.

Examples:
- small lightweight object used aggressively
- object capable of causing minor injury

3 — Moderate
The instrument could reasonably cause significant injury or is being
used in a threatening manner.

Examples:
- heavy blunt object
- stick used aggressively
- object being wielded as an improvised weapon

4 — High
The instrument is capable of causing severe injury or death and presents
a clear immediate threat in the observed context.

Examples:
- knife or other dangerous weapon being brandished
- heavy weapon being used to attack another person

5 — Critical
The instrument presents an immediate and extreme lethal threat,
particularly to multiple people or over a wide area.

Examples:
- weapon being actively used with clear lethal potential
- explosive device posing immediate danger to multiple people

IMPORTANT:
Evaluate potential threat, not actual outcome.

For example, a dangerous weapon does not receive a low threat level
merely because nobody was visibly injured.

If no qualifying instruments are observed, return an empty array.

==================================================
4. ASSETS
==================================================

DEFINITION

An asset is a non-living physical object that satisfies BOTH conditions:

1. It is relevant to understanding the incident; AND
2. It is NOT held in the hand of any entity.

Assets can be of any physical size.

Examples include:

Small:
- relevant objects lying on a table or ground
- relevant personal property not currently held

Medium:
- table
- chair
- bicycle

Large:
- motorcycle
- car
- other vehicle
- relevant structural object

Include an object only when it is materially relevant to understanding
the incident.

An asset may be relevant because it is:
- involved in the incident;
- affected or damaged by the incident;
- targeted during the incident;
- interacted with during the incident; or
- otherwise important for understanding what occurred.

Do NOT list every visible object.

Exclude irrelevant scenery, furniture, vehicles, or other background
objects merely because they are visible.

If an object's relevance cannot be reasonably established from the
video, do not include it.

For every qualifying asset, return:

ASSET_ID
- Assign sequentially within the incident: A1, A2, A3, ...

NAME
- Concise name for the object.
- Use a lowercase noun where possible.

DESCRIPTION
- Provide a short, objective description explaining the object's
  observable characteristics and/or relevance to the incident.
- Do not speculate about ownership or other unsupported attributes.

If no qualifying assets are observed, return an empty array.

==================================================
5. ENTITY / INSTRUMENT / ASSET CLASSIFICATION RULE
==================================================

Apply the following rule consistently:

LIVING BEING
+ directly relevant to incident
→ ENTITY

NON-LIVING OBJECT
+ relevant to incident
+ visibly held in an entity's hand
→ INSTRUMENT

NON-LIVING OBJECT
+ relevant to incident
+ NOT held in an entity's hand
→ ASSET

IRRELEVANT OR BACKGROUND PERSON / ANIMAL / OBJECT
→ DO NOT RECORD

The same physical object must not simultaneously be classified as both
an instrument and an asset at the same observed point in time.

When uncertain whether something qualifies, prefer omission over an
unsupported classification.

==================================================
6. GENERAL EXTRACTION RULES
==================================================

- Analyse only the primary incident in the video.
- Base all fields on observable video evidence.
- Do not invent missing information.
- Do not infer identities, motives, relationships, ownership, causes,
  injuries, fatalities, or outcomes without sufficient visual evidence.
- Do not include incidental people, animals, or objects.
- Use empty arrays when no qualifying entities, instruments, or assets
  are identified.
- Preserve consistency between fields.

For example:
- an Instrument.Entity_ID must correspond to an Entity_ID returned in
  the Entities array;
- Duration must equal End_Timestamp - Start_Timestamp;
- descriptions must not contradict the structured fields;
- severity and threat level must follow the supplied rubrics.

==================================================
7. OUTPUT FORMAT
==================================================

Return ONLY valid JSON.

Do not include:
- Markdown
- code fences
- explanatory text before or after the JSON
- comments
- additional fields outside the specified schema

Use the following structure:

{
  "incident": {
    "type": "road accident | burglary | explosion | assault | animal attack",
    "start_timestamp": 0,
    "end_timestamp": 0,
    "duration": 0,
    "description": "Short objective incident description.",
    "severity_level": 1,
    "confidence_score": null
  },
  "entities": [
    {
      "entity_id": "E1",
      "type": "human | animal | unknown",
      "description": "Objective description of the entity."
    }
  ],
  "instruments": [
    {
      "instrument_id": "I1",
      "entity_id": "E1",
      "name": "object name",
      "description": "Objective description of the instrument.",
      "threat_level": 1
    }
  ],
  "assets": [
    {
      "asset_id": "A1",
      "name": "object name",
      "description": "Objective description of the asset."
    }
  ]
}

If a category contains no qualifying items, return an empty array.

Example:

"entities": [],
"instruments": [],
"assets": []

Do not fabricate an item merely to avoid returning an empty array."""

RP1_REPORT_GENERATION_PROMPT = """REPORT GENERATION PROMPT — RP1

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

{structured_incident_json}"""
