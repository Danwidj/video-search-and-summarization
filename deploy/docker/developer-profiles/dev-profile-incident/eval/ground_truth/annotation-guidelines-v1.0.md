# Annotation Guidelines v1.0

> **Status: draft for approval (2026-10-27).** Version id `annotation-guidelines-v1.0`. Approved decisions D1 and D2 of the [ground-truth plan](../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) apply: the severity and threat scales are unchanged, and this document adds decision rules, tie-breaks, category examples, significance and classification rules, uncertainty handling and description standards. Items that interpret or change an existing definition are **not decided here**: they are listed in [§11](#11-items-awaiting-approval) and stay pending until approved.

This document defines what a correct incident annotation is. It is the shared reference for:
- human annotators and reviewers of the ground truth;
- the AI-assisted ground-truth correction prompt (PR 4), which must cite this version;
- the VSS extraction prompt variants of the prompt experiments (PR 6/7), which must follow the same definitions.

It is **not** a prompt, and it does not change the production P1 prompt (`contracts/incident_extraction_prompt.txt`), the ground-truth workbook, any frozen label, or the evaluation scoring. Scoring rules belong to the evaluation methodology (PR 1B). A change to this document is a new version (`v1.1`, …) with a [`decisions.md`](../../.docs/decisions.md) entry; labels made under one version are never silently re-read under another.

## Contents

1. [Principles](#1-principles)
2. [Incident](#2-incident)
3. [Entities](#3-entities)
4. [Instruments](#4-instruments)
5. [Assets](#5-assets)
6. [Classifying an object or being](#6-classifying-an-object-or-being)
7. [Descriptions](#7-descriptions)
8. [Uncertainty](#8-uncertainty)
9. [Ground-truth fields and visual grounding](#9-ground-truth-fields-and-visual-grounding)
10. [Worked examples](#10-worked-examples)
11. [Items awaiting approval](#11-items-awaiting-approval)
12. [Changelog](#12-changelog)

## 1. Principles

1. **Observable evidence only.** Record what the video shows. Never infer identity, motive, relationship, ownership, cause, injury, fatality or outcome that cannot be seen.
2. **One primary incident per video.** Annotate the single main abnormal or harmful event. Other activity is context: it is not a separate incident and does not add items.
3. **Relevance, not visibility.** A person, animal or object is recorded only when it matters to the primary incident (§3, §4, §5). Being on screen is never enough.
4. **Prefer omission over an unsupported entry.** When the evidence does not support an item, a classification or an attribute, leave it out and record the doubt (§8).
5. **Same definitions everywhere.** Ground truth, correction and VSS extraction use these definitions. They may use different prompts and formats.

## 2. Incident

### 2.1 Type

Exactly one of the five canonical types (lowercase, as in `incident-contract-v4`). The workbook's legacy labels map as shown.

| Type | Definition | Includes | Excludes | Workbook label |
|---|---|---|---|---|
| `road accident` | A collision or loss of control involving at least one road vehicle | vehicle–vehicle, vehicle–pedestrian, vehicle–cyclist, single-vehicle crashes | deliberate ramming of people as an attack (see §11, A8) | `Road Accident` |
| `burglary` | Unlawful entry into, or theft from, a building, enclosure, vehicle or machine (shop, house, ATM) | forced entry, theft of property, attempted entry | theft by force or threat against a person present (see §11, A8) | `Burglary` |
| `explosion` | A sudden release of energy with blast, flash, fireball or projected debris | gas, vehicle, device and industrial explosions, and the fire or damage that directly follows | a fire with no visible explosion (see §11, A8) | `Explosion` |
| `assault` | Deliberate physical aggression by one or more people against a person | punching, kicking, striking with an object, armed attack, group attacks; legacy `fighting` | verbal arguments with no physical contact | `Assault` (`Fighting` is legacy) |
| `animal attack` | An animal biting, charging, mauling or otherwise physically attacking a person or another animal | dog bites, livestock charges, animal-on-animal attacks | an animal merely present or passing (see §11, A9) | `Animal` (legacy) |

**Primary type rule (pending, A14).** When an incident has elements of two types (for example a collision that causes an explosion), the proposed rule is that the type is the **initiating event** that the rest of the incident follows from, with the consequence recorded in the description.

### 2.2 Start and end timestamps

Integer seconds from the start of the video, as in the production prompt.

- **Start:** the earliest observable second at which the abnormal or harmful event itself begins. Normal activity before it is excluded. If the incident is already under way in the first frame, the start is `0` and the doubt is recorded (§8).
- **End:** the earliest observable second at which the event has clearly ceased or reached a stable post-incident state. Continuing consequences that are part of the active incident (a fire still burning, people still fighting, vehicles still moving after impact) keep it open. If the incident is still visibly ongoing when the video ends, the end is the last observable second.
- **Duration** is `end − start`. It is derived, never annotated separately.
- **Round** to the nearest whole second at which the change is visible. Never extend the window beyond the video.

### 2.3 Severity (scale unchanged)

The five levels and their definitions are exactly those of the workbook *Severity Guide* and the production prompt:

| Level | Label | Definition | Examples / indicators |
|---|---|---|---|
| 1 | Minimal / Very Low | Little to no harm or danger. No injuries, negligible property damage, and negligible disruption. | Minor verbal disagreement; harmless animal presence; minor incident with no injury or meaningful damage. |
| 2 | Low | Minor harm or limited danger. May involve minor injuries, limited property damage, or temporary disruption, but the situation is not seriously threatening. | Minor physical altercation; minor road accident; limited property damage; minor injury not requiring urgent intervention. |
| 3 | Moderate | Significant harm or clear public-safety risk. May involve significant injuries, substantial property damage, or behaviour that could reasonably escalate into serious harm. | Physical fight causing injury; substantial vehicle collision; burglary with property damage; dangerous animal threatening a person. |
| 4 | High | Severe harm or major danger. May involve severe injuries, major property damage, or significant danger to multiple people. | Serious assault; major vehicle collision with severe injuries; large explosion causing major damage; armed confrontation posing immediate danger. |
| 5 | Critical | Extreme or catastrophic harm. Involves fatalities, imminent risk of multiple deaths, massive destruction, or widespread danger. | Fatal incident; major explosion threatening many people; catastrophic collision with multiple casualties; event posing immediate lethal danger to a large group. |

The text is the workbook's, word for word, except level 3: the workbook writes "Significant harm / clear public-safety risk", and the production prompt writes "Significant harm or clear public-safety risk". The prompt's wording is used here; the meaning is the same.

**Decision rules.**

1. **Two dimensions, both visible.** Assess **observed harm** (injury, damage, disruption that the video shows) and **demonstrated danger** (a threat to people that the video shows: a weapon brandished at someone, a blast near bystanders, a vehicle striking a pedestrian). Severity is the level that the **more serious** of the two supports.
2. **Danger must be demonstrated, not imagined.** Danger counts only when the video shows the means and the exposure together (a knife held towards a person; people inside the blast area). A dangerous-looking situation with no one exposed is not danger to people.
3. **Never infer unseen outcomes.** A person who falls and does not move is "lies motionless", not "fatally injured". Fatality (level 5) requires the video to establish it (for example an unmistakable fatal impact). Otherwise the level is set by what is visible and the doubt is recorded.
4. **Count people.** "Multiple people" (levels 4 and 5) means two or more people visibly harmed or visibly exposed to the danger.
5. **Property alone** rarely exceeds level 3. Major property damage (a destroyed vehicle or shopfront) supports level 4 only when it is major in the sense of the rubric. Massive destruction supports level 5.
6. **Severity reasoning.** For every label, the annotator must be able to state the decisive evidence in one sentence ("Level 4: the explosion engulfs the forecourt where two people are standing"). It is recorded wherever the ground-truth format provides a field (see §11, A13).

**Tie-break between adjacent levels.** When the evidence fits two adjacent levels equally, choose the **lower** level, unless an indicator named in the higher level's definition is visible. The lower choice follows from principle 1 (no inference). It is pending approval as A10 in §11.

**Category examples (calibration, within the unchanged scale).**

| Type | Level 1–2 | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|
| road accident | low-speed bump, minor damage, people walk away (2) | substantial collision, vehicle disabled, a person knocked down and getting up | high-speed collision with people visibly thrown or trapped; pedestrian struck at speed | multiple casualties visibly established; vehicle into a crowd |
| burglary | attempted entry, no damage, no one confronted (1–2); theft without damage (2) | forced entry with visible damage (door, window, ATM) | burglary with an armed confrontation of a person present | (rare) |
| explosion | small flash or pop, no damage, no one nearby (1–2) | contained explosion with local damage, no one visibly exposed | large blast causing major damage, or people inside the blast area | blast engulfing many people, massive destruction |
| assault | shoving, a single slap, no visible injury (2) | fight with repeated blows or a person knocked down | serious assault: sustained beating of a defenceless person, attack with a weapon | visibly fatal attack; attack endangering a crowd |
| animal attack | animal lunges or chases, no contact (1–2; see A9) | bite or knock-down of a person, or a dangerous animal threatening a person | sustained mauling, severe visible injury | (rare) |

### 2.4 Incident description

One to three objective sentences: what happened, who was involved (by role and appearance, not identity), the key action and the observable outcome (§7). See A6 for length.

## 3. Entities

An **entity** is a living being (human or animal) **directly relevant** to the primary incident.

| Role | Include? | Rule |
|---|---|---|
| Participant (attacker, driver seen controlling the vehicle, intruder) | Yes | Causes or takes part in the incident |
| Victim / target | Yes | Is attacked, struck, threatened or otherwise materially affected |
| Responder / intervener | Yes | Takes an observable action directly related to the incident: separates fighters, assists a victim, confronts a participant, fights a fire |
| Bystander | No | Watches, walks past or stays near without affecting or being affected by the incident |
| Background person or animal | No | Visible but unrelated |

- **Significance is behavioural, not spatial.** Proximity, visibility or watching never makes someone an entity. Becoming a target (struck by debris, chased) or acting (stepping in) does.
- **Occupants of vehicles** are entities only when visible and relevant. A vehicle whose driver cannot be seen is an asset with no driver entity (pending as A2).
- **Groups:** each individually distinguishable significant person is a separate entity. See A11 for crowds that cannot be told apart.
- **Type:** `human`, `animal`, or `unknown` when the being cannot be identified as either (for example a figure too small or dark to tell).
- **Identifiers:** `E1`, `E2`, … in order of first significant involvement, without gaps. Instruments refer to their holder by this id.
- **Temporal fields** (`timestamp_seconds`, `first_seen_seconds`, `last_seen_seconds`) are VSS output fields. The ground truth does not label them (§9).

## 4. Instruments

An **instrument** is a non-living object that is **both**:
1. **visibly held in the hand** of an entity at some point during the incident, and
2. **relevant** to the incident (used, brandished, carried as part of the act, or used to respond).

- Instruments need not be weapons: a phone used to film, a bag of stolen goods, or a fire extinguisher used on the fire all qualify when held and relevant.
- **Holder:** the entity visibly holding it (`E#`). Use `null` only when the holder cannot be determined. A holder must be an entity in the same annotation.
- **Name:** the most specific lowercase noun the video supports ("crowbar", "knife", "bottle"). When it cannot be identified, see A5.
- **Not instruments:** objects worn (helmet, mask), attached to the body, or only near or belonging to an entity; vehicles (see A1); objects never seen in a hand.

### 4.1 Threat level (scale unchanged)

| Level | Label | Definition | Examples / indicators |
|---|---|---|---|
| 1 | Minimal / Very Low | The instrument presents little to no realistic capacity for harm in the observed context. | Wallet, bag, phone, harmless everyday object. |
| 2 | Low | The instrument could cause minor harm but is not normally capable of causing serious injury in the observed context. | Small lightweight object used aggressively; object capable of causing minor injury. |
| 3 | Moderate | The instrument could reasonably cause significant injury or is being used in a threatening manner. | Heavy blunt object; stick used aggressively; object being wielded as an improvised weapon. |
| 4 | High | The instrument is capable of causing severe injury or death and presents a clear immediate threat in the observed context. | Knife or other dangerous weapon being brandished; heavy weapon used to attack another person. |
| 5 | Critical | The instrument presents an immediate and extreme lethal threat, particularly to multiple people or over a wide area. | Weapon being actively used with clear lethal potential; explosive device posing immediate danger to multiple people. |

The text is the workbook's, word for word. "Bag" appears at level 1 in the workbook guide and not in the production prompt; it is an example, not a definition change. The prompt's level 4 example reads "heavy weapon being used to attack another person"; the meaning is the same.

**Decision rules.**

1. **Potential, not outcome.** Rate the instrument's capacity to harm **in the observed context**, whether or not anyone was hurt. A brandished knife is level 4 even if no one is cut.
2. **Context lowers or raises within the scale.** The same object differs by use: a stick carried is 1–2; a stick swung at a person is 3. A crowbar used on a door with no one present is rated by what it could do to people in that context (see A10b).
3. **Responders' tools** (extinguisher, hose, first-aid kit) are level 1 unless used aggressively.
4. **Explosive devices** follow the rubric: level 5 when posing immediate danger to multiple people, otherwise by the observed context (see A3).
5. **Tie-break:** as for severity, the lower of two adjacent levels unless the higher level's indicator is visible (A10).

## 5. Assets

An **asset** is a non-living object, of any size, that is **relevant** to understanding the incident and **not held in the hand** of any entity.

- **Relevant** means it is involved, affected or damaged, targeted, interacted with, or otherwise needed to understand what happened: the cars in a collision, the ATM being broken into, the door forced open, the gas cylinder that exploded.
- **Exclude background objects:** scenery, furniture, parked vehicles and buildings that play no part. Do not list every visible object.
- **Name:** concise lowercase noun ("car", "atm", "shop door"). **Description:** observable characteristics and its relevance ("silver hatchback, rear bumper crushed").
- **Identifiers:** `A1`, `A2`, … in order of relevance or appearance, without gaps.

## 6. Classifying an object or being

```text
Living being?
├─ yes → directly relevant (participant, victim, responder)? → ENTITY, else not recorded
└─ no  → relevant to the incident?
          ├─ no  → not recorded (background)
          └─ yes → visibly held in an entity's hand during its relevant involvement?
                    ├─ yes → INSTRUMENT
                    └─ no  → ASSET
```

- The same object is never both an instrument and an asset at the same time. If it changes state (picked up, then thrown and lying on the ground), see A4.
- **Examples:**

| Object in context | Class | Why |
|---|---|---|
| knife held by an attacker | instrument | held, relevant |
| chair picked up and swung at someone | instrument | held during its relevant use |
| chair knocked over during a fight | asset (if relevant) or not recorded | not held |
| car that collides | asset | not hand-held (A1) |
| car used to ram a gate during a burglary | asset | not hand-held (A1) |
| crowbar used on a door | instrument | held, relevant |
| door forced open | asset | target |
| bag of stolen goods carried out | instrument | held, part of the act |
| backpack worn by a passer-by | not recorded | background |
| fire extinguisher used by a responder | instrument | held, relevant (threat 1) |
| gas cylinder that explodes | asset | not held |
| phone held up to film, not otherwise involved | not recorded, unless filming is part of the incident | relevance |

## 7. Descriptions

All descriptions are objective, concise and informative. They preserve meaningful visual detail and add nothing that cannot be seen.

| Field | Format | Example |
|---|---|---|
| Incident | 1–3 sentences: event → who (by role and appearance) → key action(s) → observable outcome | "A man in a dark hoodie forces the shop's glass door with a crowbar and removes the cash box from the counter. He leaves on foot; no one else is present." |
| Entity | appearance (clothing, colours, distinguishing features) + role and action | "Man in a dark hoodie and jeans who forces the door and takes the cash box." |
| Instrument | appearance + how it is used | "Metal crowbar used to lever the door frame." |
| Asset | appearance + relevance or state | "Glass shop door; frame bent and glass cracked after being forced." |

**Wording rules.**
- Use role words ("the driver", "the attacker", "a responder") and visible appearance, never names, occupations or relationships.
- Use observable verbs ("strikes", "falls", "lies motionless"), not conclusions ("kills", "is unconscious").
- Use apparent descriptors only within the rules of A7.
- Refer to other items by role or appearance in free text. Ids appear only in structured fields.
- No speculation words as fact ("clearly intends to", "the owner"). An uncertain attribute is written as uncertain (§8).
- **Partially visible objects:** describe the visible part ("long dark object, partly hidden by the body"). Do not complete it from imagination.

## 8. Uncertainty

- If something cannot be established, **say so rather than guess**: omit the item or attribute, or use the hedged wording "appears to", "possibly", "cannot be determined".
- Prefer omission for whole items (principle 4). Prefer hedged wording for attributes of an item that is clearly present.
- Typical cases: incident under way before the video starts (start `0`, recorded); holder of an instrument not visible (holder `null`); object not identifiable (A5); injury not visible (no injury claimed).
- The ground truth must not force an answer that the video cannot support. Where the ground-truth format has a field for notes or uncertainty, the doubt goes there (A13).

## 9. Ground-truth fields and visual grounding

| Workbook sheet | Annotated fields | Not annotated |
|---|---|---|
| `gt_incidents` | Type, Start_Timestamp, End_Timestamp, Description, Severity_Level, Labelled_By, Labelled_DateTime | Duration (derived), title, location, timeline, severity reason (A13) |
| `gt_entities` | Entity_ID, Type, Description | Image, temporal fields, label |
| `gt_instruments` | Instrument_ID, Entity_ID (holder), Name, Description, Threat_Level | Image, timestamp, label |
| `gt_assets` | Asset_ID, Name, Description | Image, timestamp, label |

- **Image fields are intentionally empty.** No screenshots and no bounding boxes are required, and an empty image is never an error. Some workbook rows hold Google Drive links. These are informational and are not part of the label.
- **Representative frame** (`timestamp_seconds`) and **detector label** (`label`) are VSS output fields. For VSS, the frame should show the item clearly, preferably during its significant involvement, and need not be its first appearance. The ground truth does not label them, and they are not scored unless an evaluation-methodology version approves it.
- **IDs** are trimmed text (`E4`, not `E4 `). Holder references must name an existing entity of the same incident.

## 10. Worked examples

**Correct**

- *Road accident, level 3.* Two cars collide at a junction. One spins and stops; both drivers get out and walk around. Entities: the two drivers (visible after the crash). Assets: both cars. Instruments: none. Severity 3: substantial collision with no visible injury.
- *Burglary, level 3.* A person in a hoodie levers a shop door with a crowbar, enters and leaves with a box. Entity: E1. Instruments: crowbar (holder E1, threat 3: heavy tool, no person exposed; see A10b), box of goods (holder E1, threat 1). Assets: door (forced), counter (if interacted with).
- *Assault, level 4.* Two people knock a third to the ground and kick him repeatedly. One bystander watches from a doorway. Entities: E1, E2 (attackers), E3 (victim). Not the bystander. Severity 4: sustained beating of a defenceless person.

**Incorrect, with the fix**

| Annotation | Problem | Fix |
|---|---|---|
| Entity "woman walking past in the background" | bystander, no involvement | remove |
| Instrument "suv" holder E3 | vehicle is not hand-held | asset "suv" (A1) |
| Severity 5 "victim was killed" when the victim lies still | outcome inferred | level by visible harm; "lies motionless"; record doubt |
| Description "the owner chases the thief" | relationship inferred | "a man in a white shirt chases the intruder" |
| Instrument name "red item" | vague when the object is identifiable | most specific supported noun, or A5 convention |
| Holder `E4 ` (trailing space) | malformed id | `E4` |

## 11. Items awaiting approval

These are interpretations or changes to existing definitions that this draft does **not** decide. Wherever the text above cites an item number (for example "(A1)" or "pending, A14"), it shows the recommended option, and that text is provisional until the item is approved. Until then the earlier practice stands, and no label is changed on the strength of a pending item.

| # | Question | Evidence in the ground truth | Options | Recommendation |
|---|---|---|---|---|
| A1 | Can a vehicle be an instrument (e.g. driven at a gate or a person)? | Burglary004 I1 "suv", threat 3 | (a) never: vehicles are assets, as the hand-held rule says; (b) allow vehicles used as weapons as instruments | **(a)**: keeps the hand-held rule, which the scale's examples assume |
| A2 | Is an unseen driver or occupant an entity? | 9 incidents have no entities (Explosion003/011/014/016/028, RoadAccidents005/017/029/069) | (a) no: only visible beings; (b) yes, type `unknown` | **(a)**: principle 1 |
| A3 | Explosives held during a burglary: threat by the rubric's "explosive device" example (5) or by observed context? | Burglary010 I4 "explosives", threat 3 | (a) 5 whenever an explosive device is held; (b) 5 only if it poses immediate danger to multiple people, otherwise by context | **(b)**: the rubric's wording |
| A4 | An object held, then dropped or thrown | — | (a) instrument if held during its relevant use; (b) classify by its state at the most relevant moment | **(a)** |
| A5 | Naming an object that cannot be identified | Assault015 "object", Assault032 "weapon", Burglary093 "red item", Burglary066/Explosion004 "tool" | (a) "unidentified object" + visible traits in the description; (b) the most general true noun ("tool", "weapon") | **(b)** when a general noun is supported (it still matches), else **(a)** |
| A6 | Incident description length | GT median 358 characters (max 651); prompt says 1–3 sentences | (a) 1–3 sentences, no hard cap; (b) 1–3 sentences and at most ~60 words | **(a)**: correction should not shorten valid descriptions only for length |
| A7 | Apparent gender and age words ("man", "woman", "child", "elderly") | used throughout entity descriptions | (a) allowed as apparent visual descriptors, never ethnicity, never certainty about identity; (b) avoid them, use clothing only | **(a)**: they are what matching and reviewers rely on |
| A8 | Category boundaries: robbery with force against a person present; mutual fight; vehicle deliberately driven at people; fire without visible explosion | — | define each as: robbery → `assault` if violence to the person is the main event, else `burglary`; mutual fight → `assault`; ramming people → `assault`; fire without explosion → outside the five types (flag the clip) | as listed. Needs approval because it moves clips between categories |
| A9 | Can an `animal attack` be severity 1 ("harmless animal presence")? | 7 of 15 animal incidents are level 1 | (a) yes, when there is no contact and no one is threatened; (b) no: an attack is at least 2 | **(a)**: the scale is unchanged, and a type does not set a minimum severity. Reviewers should check these 7 for the "attack" type itself |
| A10 | Tie-break between adjacent levels (severity and threat) | — | (a) lower level unless the higher level's indicator is visible; (b) higher level (precautionary) | **(a)** |
| A10b | Threat of a tool used only on property (no person exposed) | Burglary052 metal bar 3 / hand tool 2 | (a) rate its capacity to harm people in that context (heavy tool → 3); (b) rate the use (no person → 1–2) | **(a)**: the rubric rates capacity, not use |
| A11 | Crowds that cannot be told apart | Assault027 has 7 entities | (a) list each distinguishable significant person, and describe the indistinguishable rest in the incident description; (b) one entity per person regardless | **(a)** |
| A12 | Responders' tools as instruments | Explosion002 fire extinguisher, Explosion004 hose (threat 1) | (a) instruments, threat 1 (current practice); (b) not recorded | **(a)** |
| A13 | Where severity reasons, notes and uncertainty live in the ground truth | the workbook has no such columns | (a) add optional `review_notes` / `uncertain` fields in ground-truth v1.0 (not scored); (b) keep them only in the correction log | **(a)**, decided with PR 4/5 (format) |
| A14 | Type of an incident with elements of two types (e.g. a collision that causes an explosion) | — | (a) the initiating event; (b) the event that causes the most harm; (c) the event most visible in the clip | **(a)**: it does not depend on judging harm, and the consequence stays in the description |

## 12. Changelog

| Version | Date | Change |
|---|---|---|
| v1.0 (draft) | 2026-10-27 | First version: scales unchanged, decision rules and examples added, A1–A14 pending approval |
