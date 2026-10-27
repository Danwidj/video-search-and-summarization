# Annotation Guidelines v1.0

> **Status: approved (2026-10-27).** Version id `annotation-guidelines-v1.0`. Approved decisions D1 and D2 of the [ground-truth plan](../../.docs/mvp2/ground-truth-and-prompt-experiments-plan.md) apply: the severity and threat scales are unchanged, and this document adds decision rules, tie-breaks, category examples, significance and classification rules, uncertainty handling and description standards. The interpretations A1–A14 are recorded in [§11](#11-decision-record); all fourteen are approved.

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
11. [Decision record](#11-decision-record)
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
| `road accident` | A collision or loss of control involving at least one road vehicle | vehicle–vehicle, vehicle–pedestrian, vehicle–cyclist, single-vehicle crashes | a vehicle deliberately driven at people as an attack (`assault`, §2.1.2) | `Road Accident` |
| `burglary` | Unlawful entry into, or theft from, a building, enclosure, vehicle or machine (shop, house, ATM), including theft there by force or threat against people present when the violence is incidental (§2.1.2) | forced entry, theft of property, attempted entry, robbery at premises with incidental force | theft from a person away from premises (§2.1.2); premises crime where the violence is primary (`assault`) | `Burglary` |
| `explosion` | A sudden release of energy: a blast, a fireball, a flash fire or sudden ignition, or an energetic burst of sparks or debris | gas, vehicle, device and industrial explosions; fuel flash fires; backdrafts; and the fire or damage that directly follows | a fire already burning when the video starts, or one that grows gradually with no sudden release (§2.1.2) | `Explosion` |
| `assault` | Deliberate physical aggression by one or more people against a person | punching, kicking, striking with an object, armed attack, group attacks; legacy `fighting` | verbal arguments with no physical contact | `Assault` (`Fighting` is legacy) |
| `animal attack` | An animal biting, charging, mauling or otherwise physically attacking a person or another animal | dog bites, livestock charges, animal-on-animal attacks | an animal merely present or passing (see §11, A9) | `Animal` (legacy) |

#### 2.1.1 Primary incident when a video contains more than one type (A14)

1. **List the events** in the clip that each match one of the five types, after applying §2.1.2 (incidental force is part of a property crime, not a separate assault).
2. **Centrality first.** For each event, count the whole seconds of the incident window (§2.2) during which that event is observably under way. Apply the start and end rules to the event on its own. Consequences that the type's definition includes count towards their event only while they are **active**: an explosion's fire while flames are visibly burning or spreading, a collision until the vehicles and people come to rest, a fight until the blows stop. **Passive aftermath does not count**: lingering smoke, stationary wreckage or debris, a fire scene after the flames are out, people standing or lying still once the harmful process has stopped. These are the same observable boundaries as the incident end rule (§2.2), applied to each event. **The event under way for more than half of the incident window is the primary incident.**
3. **Severity breaks a tie.** If no event exceeds half, or two overlapping events both do, the event with the higher severity (§2.3, rated alone) is primary.
4. **Initiating event last.** If the severities are also equal, the event the others follow from is primary. Every case is therefore decided the same way.
5. **The whole incident is still annotated:** one window covering the connected sequence, one severity for the whole incident, and every entity, instrument and asset of every event. Only the type depends on this rule.

| Clip (incident window) | Event shares of the window | Severity alone | Primary type |
|---|---|---|---|
| Car hits a car (2 s); its fuel tank explodes and the fireball engulfs two bystanders, burning for 10 s (window 12 s) | collision 2/12, explosion 10/12 | 3 vs 4 | `explosion` (more than half) |
| Multi-car pile-up over 20 s; one car flashes into flame for 3 s at the end, no one near (window 23 s) | collision 20/23, flash fire 3/23 | 3 vs 2 | `road accident` (more than half) |
| Car hits a wall (2 s); the car then burns for 40 s with no one near (window 42 s) | collision 2/42, fire 40/42 | 3 vs 2 | `explosion` if the fire began with a sudden ignition (§2.1); otherwise `road accident`, the fire being a consequence outside the five types |
| Two cars collide (3 s); smoke lingers over the stationary wrecks for 30 s with no flames (window 3 s) | collision 3/3; the smoke is passive aftermath | — | `road accident` (the aftermath is outside the window and counts for nothing) |
| Pedestrian struck by a car (2 s); the driver then fights the pedestrian's companion for 25 s (window 27 s) | collision 2/27, assault 25/27 | 3 vs 3 | `assault` (more than half) |
| Intruder forces an ATM for 30 s; a guard arrives and is struck once (window 32 s) | burglary 32/32, the strike is incidental (§2.1.2) | — | `burglary` |
| Intruder forces a door (10 s), then beats the resident for 20 s while the house is searched (window 30 s) | burglary 30/30 and assault 20/30 overlap, both more than half | 3 vs 4 | `assault` (severity breaks the overlap) |
| Fight (15 s) during which a thrown petrol bomb flares around the victim for 15 s (window 15 s) | assault 15/15 and explosion 15/15 overlap | 4 vs 4 | `assault` (equal severity → initiating event) |

**Why centrality first (decided over "severity first"):**
- **Reproducibility.** Centrality rests on time spans, which annotators already mark. Severity rests on judgments between adjacent levels. In the 2026-10-02 benchmark, models' start and end times were within ±5 s for 30–81% of videos, but their severity was exact for only 22–27%, so severity is this project's least stable field. Human agreement is measured in PR 4 (κ). Severity-first would also make the type flip whenever a severity rating moves by one level, and with two events often rated the same, it would fall back on chronology for a large share of cases.
- **Fit.** "More than half the sequence" matches what the clip is about. A brief, severe event inside a long incident of another kind is still recorded fully in the severity, description and items.
- **Known limit.** A long but still active, low-harm consequence (a car visibly burning for 40 s after a 2 s crash) can outweigh a short, severe cause. Passive aftermath never does, because it is not counted (step 2). The table shows the case and how §2.1's explosion boundary settles it. Review notes (A13) record such cases.

#### 2.1.2 Burglary, robbery, force and clips outside the five types (A8)

**Ordinary meanings.** These are the everyday distinctions, which the five-type taxonomy does not draw:
- **burglary:** entering a building, structure or vehicle unlawfully to steal (or commit another crime), usually without confronting anyone;
- **robbery:** taking property from a person, or in their presence, by force or the threat of force;
- **theft (stealing):** taking property without unlawful entry and without force, for example shoplifting or an unforced bag snatch.

**Project convention for the `burglary` label (intentional; adopted with this version).** `incident-contract-v4` has five types and no robbery or theft type. In this project the `burglary` label therefore means **property crime at premises**:
1. burglary in the ordinary sense;
2. theft from premises, machines or vehicles (an ATM, a vending machine, a shop counter, a parked car);
3. robbery at premises, when the force or threat is incidental (see below).

It does **not** include robbery or theft from a person away from premises. Reasons:
- the five types are fixed by the contract;
- these cases share the observable pattern that P1 must recognise: premises, entry or access, and property taken;
- splitting them would need a contract and taxonomy change, which is out of scope.

The source dataset names the classes separately: UCF-Crime has Burglary, Robbery, Stealing and Shoplifting. Every burglary clip in this dataset (18) comes from its Burglary class, by filename, so the convention changes no current label. It governs borderline and newly uploaded clips. Reports describe the category as "burglary (property crime at premises)" wherever a reader could take it in the legal sense.

**Incidental and primary violence.** Force or threat used only to carry out or escape a property crime is **incidental**: pushing past someone, grabbing an arm, a single strike to get free, or brandishing a weapon to obtain property. It does not make the incident an assault. It is annotated as part of the incident: the threatened person is an entity, the weapon is an instrument with its threat level, and severity rises by the usual rules (an armed confrontation supports level 4). Violence that goes beyond this (repeated or sustained blows, an injury beyond what the theft needs, or an attack that continues after the property is taken) is a separate assault event, and the primary-incident rule (§2.1.1) decides the type.

| Situation | Ordinary term | Type in this project |
|---|---|---|
| Night-time break-in through a shop door, no one present | burglary | `burglary` |
| ATM or vending machine forced open | burglary / theft | `burglary` |
| Shop hold-up: knife pointed at the cashier, cash taken, robber leaves | robbery | `burglary` (incidental threat; knife threat 4; severity 4) |
| House intruder shoves the resident aside and runs out with a bag | robbery | `burglary` (incidental force) |
| Intruder beats a resident for most of the clip while the house is searched | robbery with assault | §2.1.1 decides (the overlap example there gives `assault`) |
| Bag snatched from a person in the street, no further violence | theft / robbery | outside the five types |
| Street robbery in which the victim is beaten for most of the clip | robbery with assault | `assault` |
| Mutual fight; vehicle deliberately driven at people | — | `assault` |

**Clips outside the five types.** When the primary incident matches none of the five types (for example a street theft without significant violence, a fire with no sudden ignition, a medical collapse, vandalism without entry), it is **not forced into the nearest type**:
- the clip is marked `out_of_taxonomy`, with the nearest type and a one-sentence reason recorded in the ground truth's note fields (A13);
- everything else is annotated normally (window, severity, entities, instruments, assets, description);
- **open decision for PR 1B:** how such clips are scored, or whether they are excluded from the reference set (with PR 5 for the frozen version). This document does not decide it.

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

**Tie-break between adjacent levels.** When the evidence fits two adjacent levels equally, choose the **lower** level, unless an indicator named in the higher level's definition is visible. The lower choice follows from principle 1 (no inference). (A10, approved.)

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
- **Occupants of vehicles** are entities only when visible and relevant. A vehicle whose driver cannot be seen is an asset with no driver entity (A2, approved).
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
3. **Responders' equipment** is classified by the same hand-held test as any object (§4, §6; A12 revised wording): an extinguisher a responder holds and discharges is an instrument; a hose is an instrument only while a responder holds and directs it; a hose lying on the ground, a fixed reel or vehicle-mounted equipment is an asset if relevant; equipment carried but not used is not recorded unless carrying it matters to the incident. Its threat level is then rated separately: usually 1, higher only if it is used against a person.
4. **Explosive and incendiary devices** are rated by their **plausible destructive capability and the observed context**, not by how many people are near (A3, revised wording):
   - **5:** a device with plausible lethal capability is being used or readied (lit, armed, placed, thrown or detonated) while **any** person is within its plausible effect range, or it endangers a wide area;
   - **4:** a device with plausible capacity for severe injury is held or handled but not being used or readied, or no one is within its plausible range;
   - **3:** the object is identified as an explosive from context alone, or its capability is unclear or small; the doubt is recorded (§8);
   - consumer pyrotechnics (sparklers, small firecrackers) are rated 1–3 by how they are used.
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
| fire extinguisher held and discharged by a responder | instrument | held and used; threat rated separately (usually 1) |
| fire extinguisher standing on the floor | not recorded, or asset if relevant | not held |
| hose held and directed by a firefighter | instrument | held and used |
| hose lying on the ground, or a fixed hose reel | asset if relevant | not held |
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
- **Age and gender words only with visual support** (A7, revised wording):
  - age terms ("child", "teenager", "adult", "elderly") need visible cues such as body size relative to others, proportions, gait, grey or white hair, or being carried;
  - gender terms ("man", "woman", "boy", "girl") need appearance that makes it reasonably clear; a single cue, such as one garment or hair length, is not enough on its own;
  - with moderate cues write "appears to be …"; without them write "person" plus clothing and other visible features;
  - never infer ethnicity, skin colour, religion, nationality, disability or social status. Colours of clothing and hair, and visible features, are fine.
  - **Pronouns (P1, clarification of A7):** a gendered pronoun ("he", "her") may follow a visually supported gender identification, including a qualified one ("appears to be a man"). Where gender cannot be determined and the description is gender-neutral ("person", a role word), later pronouns referring to that person must be neutral too ("they", "them", "their").
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
| "A woman in a headscarf" where nothing else indicates gender | one garment as the only cue (A7) | "a person in a headscarf", or "appears to be a woman" if other cues support it |
| Type `assault` for a shop hold-up where the robber only threatens the cashier | incidental violence (A8) | `burglary`; knife instrument threat 4; severity 4 |
| Fire extinguisher left standing by a door, recorded as an instrument | not held (A12) | not recorded, or asset if relevant |

## 11. Decision record

Decisions on the interpretations raised by this version, all approved on 2026-10-27 (A3, A7, A8, A12 and A14 after revision). No label changes until the ground-truth correction (PR 4) applies these rules with human review; "label impact" is what that review is expected to touch.

| # | Question | Decision | Status | Label impact (applied in PR 4 review) |
|---|---|---|---|---|
| A1 | Can a vehicle be an instrument? | Never; vehicles are assets (hand-held rule) | Approved | Burglary004 I1 "suv" becomes an asset (1 row) |
| A2 | Is an unseen driver or occupant an entity? | No; only visible beings | Approved | None (the 9 incidents without entities stay so) |
| A3 | Threat level of explosive devices | Plausible destructive capability and observed context; one person in range can support 5 (§4.1 rule 4) | Approved (revised wording) | Burglary010 I4 "explosives" (now 3) re-rated after viewing: 0–1 row |
| A4 | Object held, then dropped or thrown | Instrument if held during its relevant use | Approved | None known |
| A5 | Naming an unidentifiable object | Most general true noun, else "unidentified object" | Approved | Up to 6 names reviewed (Assault015, Assault032, Burglary052, Burglary066, Burglary093, Explosion004) |
| A6 | Incident description length | 1–3 sentences, no word cap | Approved | None |
| A7 | Age and gender words | Only with visual support; never ethnicity and similar (§7) | Approved (revised wording) | No automatic change; reviewers check the 49 of 169 entity descriptions (and incident descriptions) that use such words and rewrite unsupported ones |
| A8 | Category boundaries and clips outside the five types | Ordinary burglary/robbery/theft meanings vs the project's `burglary` = property crime at premises convention; incidental vs primary violence; explosion includes sudden ignition; out-of-taxonomy clips marked, not forced, with their scoring open for PR 1B (§2.1.2) | Approved | No change from the convention (all 18 burglary clips come from the source's Burglary class); no robbery-with-force case found. Explosion011 (smoke burst, no flame) and Explosion014 (fire at a toll plaza) are reviewed as possible out-of-taxonomy clips: 0–2 clips. Explosion002/017/019/029 (sudden ignition or bursts) stay `explosion` |
| A9 | Can an animal attack be severity 1? | Yes; the type sets no minimum. Existing severity-1 labels are reviewed | Approved | Severity of Animal004, Animal011, Animal012 (dangerous animal close to a person) re-checked: 0–3 rows |
| A10 | Tie-break between adjacent levels | Lower level unless the higher level's indicator is visible | Approved | None automatically |
| A10b | Threat of a tool used only on property | Capacity to harm people in that context | Approved | None known |
| A11 | Crowds that cannot be told apart | Distinguishable people listed, the rest in the description | Approved | None |
| A12 | Responders' equipment | Hand-held test applies as to any object; threat rated separately (§4.1 rule 3, §6) | Approved (revised wording) | Explosion002 I2 extinguisher and Explosion004 I2 hose checked against the video: 0–2 rows become assets or are dropped |
| A13 | Where severity reasons, notes and uncertainty live | Optional, unscored note fields in ground-truth v1.0 (format with PR 4/5) | Approved | None (adds fields) |
| P1 | Pronouns after a qualified or neutral description | Gendered pronouns only after a visually supported (possibly qualified) gender identification; neutral pronouns for a person described neutrally (§7) | Approved 2026-10-27 (clarifies A7) | 4 proposed rewrites corrected; 18 hedged rewrites keep their pronouns if the hedge is confirmed |
| A14 | Primary type when a video contains several types | Centrality (event actively under way for more than half the window; passive aftermath not counted), then severity, then the initiating event (§2.1.1) | Approved | None found (no clip mentions two types); applied during review |

**Open for PR 1B (from A8):** how `out_of_taxonomy` clips are scored or excluded; PR 5 applies it to the frozen ground truth.

## 12. Changelog

| Version | Date | Change |
|---|---|---|
| v1.0 (draft) | 2026-10-27 | First version: scales unchanged, decision rules and examples added, A1–A14 pending approval |
| v1.0 (draft, revision 2) | 2026-10-27 | A1, A2, A4, A5, A6, A9, A10, A10b, A11, A13 approved provisionally; A3, A7, A8, A12, A14 rewritten as requested: explosives by capability and context, demographic words only with visual support, incidental versus primary violence and out-of-taxonomy handling, responders' equipment under the hand-held rule, primary incident by most serious harm with a fixed tie-break |
| v1.0 (draft, revision 3) | 2026-10-27 | A3, A7, A12 approved as revised. A8: ordinary burglary/robbery/theft meanings separated from the project's `burglary` = property crime at premises convention. A14: centrality first (more than half the window), severity as tie-break, then initiating event, with a comparison against severity-first |
| v1.0 | 2026-10-27 | Approved. A8 and A14 approved as revised; A14 clarified: passive aftermath (lingering smoke, stationary wreckage, an inactive fire scene) does not count towards an event's active duration |
| v1.0 (clarification P1) | 2026-10-27 | Pronoun policy P1 added to §7 and the decision record. It clarifies A7 and changes no scale, field or definition, so the version stays v1.0 |
