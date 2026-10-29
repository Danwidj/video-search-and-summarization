# Stage 2 registered prompts (V1–V8)

> Registered 2026-10-28 in [`contracts/experiments/registry.json`](../../../contracts/experiments/registry.json) (append-only; status `candidate`). Each is `p1-v4-base` plus one change drawn from `annotation-guidelines-v1.0`. No few-shot example, no video-specific or ground-truth wording. None is assumed to help: each is a hypothesis tested against the concurrent baseline under D9 v2, and every version is reported whatever its result.

## Shared settings

| Item | Value |
|---|---|
| Model | `nvidia/cosmos-3-super-reasoner` (Switchyard), the same for every version |
| P1 request | `{"temperature": 0.0, "max_tokens": 16384, "media_io_kwargs": {"video": {"num_frames": 64}}}` from `contracts/inference.json`; strict `response_format` with the `incident-contract-v4` schema. Super ignores `num_frames` (gateway samples about 24 frames) |
| Pipeline | Local experiment agent (`experiments/agent/start-experiment-agent.sh`), `experiment_prompt_id`, `skip_rp1: true`, `skip_crops: true`, no Supabase or R2 |
| Retries | `retry-v2` |
| Scoring | evaluation-methodology-v1.2 |

## Versions

### V1 severity calibration: `p1-v4-e01-severity`

- **SHA-256:** `004746ea7d193fbba4af4c411c8baa2c7a1c9acfdd9d81fdaee19838024c4138`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e01-severity.txt`](../../../contracts/experiments/p1/p1-v4-e01-severity.txt) (2878 words, +205 on the base).
- **Hypothesis:** Severity is over-rated on dev (ground-truth level 3 predicted 4 or 5 in 24 of 38 Stage 1 outputs). Stating the guidelines' severity decision rules (annotation-guidelines-v1.0 §2.3: observed harm and demonstrated danger, visible indicators per level, property alone, the evidence-conditional tie-break) improves severity exact accuracy without lowering other scores.
- **Targeted fields:** severity_level (exact, within one, signed error); severity confusion.
- **Potential regressions (watched by G2):** Under-rating real level-4/5 incidents if the visible-indicator requirement is applied too strictly; longer SEVERITY_REASON; type or timestamps should be unaffected (watch G2).
- **Exact change:**

```diff
@@ -138,6 +138,28 @@
 Do not infer injuries, fatalities, or damage that are not visually
 supported by the video.
 
+How to apply the rubric:
+1. Assess two things, both from the video: the harm actually shown
+   (injury, damage, disruption) and the danger to people actually shown
+   (for example a weapon held towards a person, people inside a blast
+   area, a vehicle striking a pedestrian). The level is the one that the
+   more serious of the two supports.
+2. Danger counts only when the video shows both the means of harm and
+   people exposed to it. A dangerous-looking scene with no one exposed is
+   not danger to people.
+3. Each level needs its own indicators to be visible. Levels 4 and 5 need
+   severe, major or fatal harm, or two or more people visibly harmed or
+   exposed to the danger. A dramatic-looking scene alone does not meet
+   them, and a clearly visible indicator of a level must not be
+   downgraded.
+4. Property damage alone rarely exceeds level 3; destruction that is major
+   or massive in the sense of the rubric is needed for level 4 or 5.
+5. Only when the evidence fits two adjacent levels equally well, choose
+   the lower level unless an indicator named in the higher level's
+   definition is visible.
+6. SEVERITY_REASON must name the decisive visible evidence for the chosen
+   level.
+
 SEVERITY_REASON
 - One or two sentences explaining which observable evidence places the
   incident at the chosen SEVERITY_LEVEL under the rubric above.
```

### V2 significant entities: `p1-v4-e02-entities`

- **SHA-256:** `19ce9a01c9a6867d5d275c312ef68cef342eb2fe169296a6f2617917c6d1c31a`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e02-entities.txt`](../../../contracts/experiments/p1/p1-v4-e02-entities.txt) (2789 words, +116 on the base).
- **Hypothesis:** Entities are over-listed on dev (85-102 predicted against 55-72 ground-truth entities in Stage 1). Applying the guidelines' role test (annotation-guidelines-v1.0 §3) raises entity precision without lowering recall.
- **Targeted fields:** entity precision, recall, F1; entity type and description on matched pairs.
- **Potential regressions (watched by G2):** Dropping real victims or responders who act briefly (entity recall); fewer holder targets for instruments (instrument holder).
- **Exact change:**

```diff
@@ -193,6 +193,22 @@
 If there is insufficient visual evidence that a living being is directly
 relevant to the incident, do not include it.
 
+Decide each candidate by its role in the incident, not by how visible it
+is:
+- participant (causes or takes part: attacker, intruder, a driver seen
+  controlling the vehicle) → include;
+- victim or target (attacked, struck, threatened, chased or otherwise
+  materially affected) → include;
+- responder (takes an observable action related to the incident:
+  separates fighters, assists a victim, confronts a participant, fights a
+  fire) → include;
+- bystander (watches, walks past or stays nearby without affecting or
+  being affected by the incident) → exclude;
+- background person or animal → exclude.
+Record each individually distinguishable participant, victim or responder
+as a separate entity. A vehicle occupant is an entity only when visible
+and relevant.
+
 For every qualifying entity, return:
 
 ENTITY_ID
```

### V3 instrument classification: `p1-v4-e03-instruments`

- **SHA-256:** `fe6adc566ad135513899e77c86ae773ad1289932a2f78958c5e7b778fa3b9d90`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e03-instruments.txt`](../../../contracts/experiments/p1/p1-v4-e03-instruments.txt) (2776 words, +103 on the base).
- **Hypothesis:** Instruments are under-reported on dev (9 predicted against 18-25 ground-truth instruments in Stage 1). Applying the existing instrument definition explicitly to each entity (annotation-guidelines-v1.0 §4, §6) raises instrument recall without adding non-instruments.
- **Targeted fields:** instrument recall, F1, threat level, holder.
- **Potential regressions (watched by G2):** Listing worn or background objects as instruments (instrument precision); objects moving from asset to instrument (asset recall).
- **Exact change:**

```diff
@@ -276,6 +276,16 @@
 If there is insufficient visual evidence that an object is being held
 in the hand, do not classify it as an instrument.
 
+Apply the definition to every participant, victim and responder: check
+what each holds in the hand during the incident. An object that is held
+and used as part of the incident (to strike, threaten, force an entry,
+carry stolen goods, or respond, for example a stick, bottle, crowbar, bag
+of stolen goods or fire extinguisher) is an instrument even when it is not
+a weapon. Objects that are worn (helmet, mask), attached to the body,
+never seen in a hand, or vehicles are never instruments.
+Rate THREAT_LEVEL by the object's capacity to harm in the observed
+context, whether or not anyone was hurt.
+
 For every qualifying instrument, return:
 
 INSTRUMENT_ID
```

### V4 asset relevance: `p1-v4-e04-assets`

- **SHA-256:** `58f8840431c77d678cb8eb11290575aa0a7d0594fcec3b1cb6445609f3a02f86`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e04-assets.txt`](../../../contracts/experiments/p1/p1-v4-e04-assets.txt) (2745 words, +72 on the base).
- **Hypothesis:** Assets are over-listed on dev (about 105 predicted against 41 ground-truth assets in Stage 1). Requiring a visible role for each asset (annotation-guidelines-v1.0 §5) raises asset precision without lowering recall.
- **Targeted fields:** asset precision, F1; asset name and description on matched pairs.
- **Potential regressions (watched by G2):** Dropping relevant but briefly involved objects (asset recall), for example the second vehicle in a collision.
- **Exact change:**

```diff
@@ -408,6 +408,13 @@
 Exclude irrelevant scenery, furniture, vehicles, or other background
 objects merely because they are visible.
 
+Before listing an object as an asset, identify its role from the video:
+involved (for example a vehicle in the collision), affected or damaged,
+targeted (the ATM being forced, the door broken open), or interacted with
+during the incident. If no such role can be identified, do not list it.
+Parked vehicles, buildings, signs, furniture and road features that play
+no part in the incident are background, even when they are prominent.
+
 If an object's relevance cannot be reasonably established from the
 video, do not include it.
 
```

### V5 description completeness and consistency: `p1-v4-e05-descriptions`

- **SHA-256:** `416b6790b230d9113f0f008d28e4a74c2d3b0073c6871868ae0b8f01174fe8b0`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e05-descriptions.txt`](../../../contracts/experiments/p1/p1-v4-e05-descriptions.txt) (2753 words, +80 on the base).
- **Hypothesis:** The incident description passes the judge in 27-47% of dev outputs in Stage 1 and is unstable between repeats. Stating the guidelines' general description principles (annotation-guidelines-v1.0 §2.4, §7: event, who, key action, observable outcome; observable verbs; completeness and consistency with the structured fields) improves description scores. It contains no example sentence and no ground-truth wording.
- **Targeted fields:** incident description (judge); secondary: entity and item descriptions.
- **Potential regressions (watched by G2):** Longer descriptions that add unsupported detail; no direct effect expected on items or timestamps.
- **Exact change:**

```diff
@@ -79,6 +79,14 @@
 - Do not speculate about identities, motives, relationships, causes,
   injuries, or outcomes that cannot be visually established.
 - Keep the description concise, normally 1–3 sentences.
+- Write it in this order: the event; who was involved, by role and
+  visible appearance; the key action or actions; the observable outcome.
+- Use observable verbs ("strikes", "falls", "lies motionless"), not
+  conclusions ("kills", "is unconscious").
+- Be complete and consistent: include each of these elements that the
+  video shows, leave out any that it does not show rather than guessing,
+  and make every statement agree with TYPE, SEVERITY_LEVEL, the
+  timestamps and the entities, instruments and assets you return.
 - Do not include irrelevant background activity.
 
 SEVERITY_LEVEL
```

### V6 incident start and end: `p1-v4-e06-boundaries`

- **SHA-256:** `4b498b0d75e400b26c8f8602652b8ecb31ca68be483af44525ca4239a802a160`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e06-boundaries.txt`](../../../contracts/experiments/p1/p1-v4-e06-boundaries.txt) (2744 words, +71 on the base).
- **Hypothesis:** End timestamps (47-50% within 5 s) and duration (32-38%) are the weakest timing fields on dev in Stage 1. Stating how to locate the boundaries (annotation-guidelines-v1.0 §2.2) improves end and duration accuracy without lowering start accuracy.
- **Targeted fields:** end_timestamp, duration; start_timestamp must not fall.
- **Potential regressions (watched by G2):** Ends moved too early (before consequences finish) or too late; start shifts if the 'already under way' rule over-fires.
- **Exact change:**

```diff
@@ -40,6 +40,7 @@
   the incident.
 - Base the start timestamp only on observable visual evidence. Do not infer
   that the incident began before it becomes observable in the video.
+- If the incident is already under way in the first frame, use 0.
 
 END_TIMESTAMP
 - Integer number of seconds from the beginning of the video at which
@@ -64,6 +65,12 @@
 - If the incident is still visibly ongoing when the video ends, use the
   final observable second of the video as End_Timestamp.
 - Do not infer when an incident ends beyond the available video.
+- To find the end, locate the last observable second of the harmful
+  action or its active consequence (the last blow, the moment the vehicles
+  come to rest, the fire stops burning, the animal leaves the person), then
+  apply the rules above.
+- Round each timestamp to the nearest whole second at which the change is
+  visible.
 
 TITLE
 - A short, neutral headline for the incident, normally 4-10 words.
```

### V7 structured self-check: `p1-v4-e07-checklist`

- **SHA-256:** `1f2734d82f2e76c83106e6927e76b800b94d447e9b5dca84d8690b38bf0ef0cb`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e07-checklist.txt`](../../../contracts/experiments/p1/p1-v4-e07-checklist.txt) (2794 words, +121 on the base).
- **Hypothesis:** Two outputs were contract-invalid in Stage 1 (VSS arm) and cross-field consistency is not checked by the model. An explicit final consistency check (annotation-guidelines-v1.0 §6, §8; prompt §8) raises the valid-output rate and consistency without lowering any score.
- **Targeted fields:** valid-output rate (G1), consistency; all eight scores as guards.
- **Potential regressions (watched by G2):** Longer outputs and latency; the model may drop items to satisfy the checks (item recall).
- **Exact change:**

```diff
@@ -552,3 +552,21 @@
 boxes are generated downstream by the detector stage on the frame extracted at
 TIMESTAMP_SECONDS, guided by your LABEL.
 
+==================================================
+10. FINAL CONSISTENCY CHECK
+==================================================
+
+Before returning the JSON, check each point and correct the output:
+1. Every instrument's ENTITY_ID names an entity in ENTITIES, or is null
+   when the holder cannot be seen.
+2. No object appears both as an instrument and as an asset at the same
+   observed time.
+3. Every entity, instrument and asset has a role in the incident; remove
+   bystanders and background objects.
+4. START_TIMESTAMP <= every timeline event <= END_TIMESTAMP, all within the
+   video.
+5. SEVERITY_LEVEL and each THREAT_LEVEL follow their rubrics for the
+   visible evidence, as stated in SEVERITY_REASON.
+6. TITLE and DESCRIPTION agree with TYPE and the structured fields.
+7. Anything that could not be established is stated in UNCERTAINTIES,
+   not guessed.
```

## V8 combination rule (fixed before any Stage 2 output)

- **Built after Stage 2a**, as `p1-v4-e08-combined` (parent `p1-v4-base`). It applies, unchanged and in section order, the inserted block of every V1–V7 version whose D9 v2 comparison against `s2-vss-baseline` (merged, `original+recovery-v1`) has **`ΔI` > 0 and no G2 problem** (and passes G1 and G3).
- **Fewer than two qualifying versions:** V8 is not built. A single qualifying version is already its own candidate.
- **Selection:** V8 is then a candidate like the others: `select_d9` over every version that ran. `ΔI ≥ +0.02` is needed to beat `p1-v4-base`.
- **Disclosure:** V8 is chosen from dev results and scored on the same dev clips. Stage 3 is the held-out check.

### V8 combined: `p1-v4-e08-combined` (registered 2026-10-29)

- **SHA-256:** `9c21fc60f39ca46c5c226c02f17e4e60360cbbd543092c54ebdc7dfb21de7323`. **Parent:** `p1-v4-base`. **Full text:** [`contracts/experiments/p1/p1-v4-e08-combined.txt`](../../../contracts/experiments/p1/p1-v4-e08-combined.txt) (3,441 words, +768 on the base; 23,030 bytes). The diff is [`stage2-drafts/p1-v4-e08-combined.diff`](../../experiments/stage2-drafts/p1-v4-e08-combined.diff).
- **Built by the rule above**, with no editing. All seven of V1–V7 qualified ([Stage 2a §7](stage2a-results.md#7-v8-qualification)).
  - Every block is inserted unchanged at its base position, in section order (V6, V5, V1, V2, V3, V4, then V7 as a new section 10).
  - Removing any one variant's blocks gives that variant again.
- **Pre-registration checks (owner-requested):**
  - no contradictory instructions (V7 item 2 settles the V3/V4 instrument-versus-asset overlap);
  - no new or conflicting output fields; `incident-contract-v4` unchanged;
  - inference settings unchanged;
  - about +1,063 prompt tokens, so the worst case stays under the 35,000-token per-attempt ceiling.
- **Result** ([Stage 2b](stage2b-results.md)):
  - ΔI +0.022 [−0.025, +0.071] against `s2-vss-baseline-b`. It qualifies (≥ +0.02, guardrails pass) but is not selected: V1 has the higher ΔI.

