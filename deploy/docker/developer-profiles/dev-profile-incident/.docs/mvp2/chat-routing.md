# Report-first chat routing

How `INCIDENT_CHAT_MODE=routed` answers a question about one report version, what it was measured against, and what remains before it is switched on. **Routed mode and video checks are both off.** The default is still template mode.

## Routes

The selected report version is the source of truth. `utils/chat_routing.py` decides with no model call, from the question and what the report's composed answer turns out to be. The conversation does not change the route: a follow-up that reaches the model carries its history.

| Route | Used for | Calls | Source label |
|---|---|---|---|
| 1. Deterministic | A question asking only for a kind of report field: the timeline, who, where, a time in the video, objects, taken, weapons, severity, type, when. Also greetings and plainly unrelated questions | None | Answered from the stored report |
| 2. Report-grounded model | Anything that names something, reasons, leans on the conversation or points at a described moment. Also roles (attacker, victim, who started it), names, injuries, causes, and people found only in the report's text | One text call on the report | AI reading of the stored report |
| 3. Video check | Only on the reviewer's click, after an offer | One blind vision call, one text comparison | Fresh video check |
| 4. Insufficient | The report cannot answer and no check can help (a motive, or checks are off) | As route 1 or 2 | As route 1 or 2, with `grounding.route: insufficient` |

An offer of a video check is made when checks are on and:
- the question asks for one or disputes the report ("was that actually a dog?");
- the model says the missing detail is something visible;
- the question is what followed the incident, the timeline has nothing after it, and footage remains.

A motive is never offered a check: footage cannot show one. With checks off, an answer missing a visible detail says a check of the video isn't available.

## How code reads a question

`utils/chat_questions.py` reads the wording first:
- "Take place" reads as "happen", so it can never be a taking. This is what turned "where the incident take place" into a theft answer.
- A typo is corrected only towards a fixed list of intent words. Correcting towards everyday words changed 14 frozen questions wrongly ("battle" to "bottle").
- A time in the question ("0:30", "at 30 seconds", "after 0:30", "between 0:10 and 0:20") is a moment. A bare number is not ("longer than 30 seconds").

`utils/report_answers.py` then answers without guessing:
- **Who:** an entity of type `unknown` is a person when its label or description says so. An empty people list is not a statement that nobody was there: the events that mention people are listed, uncounted, because "a man ... the man" cannot be counted. Animals are shown instead of "no people".
- **Where:** `incident.location` as written.
- **A role, name, injury or cause:** the report's own wording, else a plain statement that it does not establish it. Nobody is called the attacker or the victim by the code.
- **Unrelated questions:** a greeting or a small list of topics (weather, jokes, news) the report does not mention gets a redirect. Anything else the report cannot answer says so.
- **Conflicts:** code flags only a reversed incident window. A check of location against description wording flagged 40 of the 256 stored revisions, and the flags read were all false ("shop" against "store"), so conflicts of meaning are left to the routed prompt.

`utils/chat_followups.py` serves template mode and the failed-model fallback. "What happened next?" follows the last event an earlier answer told. A pronoun resolves only when one person fits, by the report, the last turn that named someone, or the label's he or she; otherwise a short question names the candidates.

## When something fails

| Failure | What the reviewer sees |
|---|---|
| Chat model timeout, 429, invalid or empty reply (routed) | `200`. What the report settles, with a note that the AI reader is unavailable, or a request to try again |
| Same, for a motive, a dispute, a video request, or an answer that found nothing | `200`. A request to try again: a composed "doesn't mention hit" for "why did he hit him?" could be false |
| Chat model failure (grounded, library) | `502` with a plain `detail` |
| Report store failure | `503` or `502` with a plain `detail` |
| Unexpected error while composing (template) | `200`. A request to try again |
| Malformed report field | The field counts as empty, and the rest of the report answers |

The real error goes to the agent or console log. The console shows the agent's `detail` for a 4xx, and a plain message for anything else, except that a video check's own reason is kept.

## What keeps each source apart

- **Model answers** have three labelled parts: what the report records, an interpretation, and what is not established. Code writes the labels.
- **Citations** must be ids the version holds; an unknown id is dropped and recorded. A card uses its evidence entry's second. An item with no stored second gets no card. An item the answer names gets a card even if the model forgot to cite it, or flagged a useful partial answer as insufficient.
- **Times** in a model answer must belong to the event they stand beside (`utils/chat_attribution.py`). A single time must be that event's start, or its end after "by" or "until". A range must run from an event's start to an event's end, both described by the sentence. In text that describes no event, a time may be a named item's own stored second, or the incident window. Anything else stays plain text: no jump is better than a wrong one. The written text is never changed.
- **Missing times** are added by code: a clause that plainly describes one event, and gives no time, gets that event's time from the report, once per event. A denial or a description of an object gets none.
- **Cards for a partial answer** come from what it affirms: an item only denied ("no collar on the dog") gets none.
- **Video looks** are blind: the VLM gets the question and clip, never the report's claim. A text call then compares them. A conflict is flagged for a person; nothing is corrected or stored. Their times are never linked, they get no cards, and the console keeps them out of the history the report model reads.

Conversations are per version: `ReportPage` holds a thread per version and draft, a closed panel keeps it, New chat clears it. The agent is stateless and reads the last eight turns from the request.

## Evaluation (2026-11-06, no model calls)

Method: template answers composed by this code for the frozen C3 questions and corpora, scored by the frozen code scorer at worktree commit `563b6305c`, against the stored Nemotron 3 Ultra answers. Incident questions only: 99 on the oracle corpus (ground-truth reports), 89 on the system corpus (Nano contingency reports). References are AI-generated. Scripts and outputs: `/home/hengz/evalv2-data/v2/runs/chat-route-compare-2026-11-06/`. Frozen runs are unchanged (checksums verified).

| Exact answers | Oracle: template | Oracle: grounded | System: template | System: grounded |
|---|---|---|---|---|
| All incident questions | 51/79 | 72/79 | 13/71 | 28/71 |
| Routed to code | 51/59 | 52/59 | 13/54 | 13/54 |
| Routed to the model | 0/20 | 20/20 | 0/17 | 15/17 |

Reading it:
- **Correction (2026-11-07):** the "scorer artefact" below is only part of the window gap. 3 of the 10 window rows on each corpus were "Between which timestamps does the incident take place?", which template answered as a theft. That is fixed, and the question now gets the window.
- **Grounded beats template on all questions, because template cannot refuse.** Every unanswerable and false-premise question scored 0 on template, and the router sends all of them to the model.
- **On the questions routed to code, the two are level.** Oracle's one-point gap includes a scorer artefact: code writes `1:34` where the scorer wants 94 seconds (window 5/10 against 10/10). Without the window class, code leads 46/49 to 42/49.
- **Routing keeps the model's accuracy for about a quarter of its tokens:** 26% to 30% of the tokens went on questions the router still sends to the model. Projected exact: oracle 71/79, system 28/71.
- **Model times are reliable:** 0 of 113 times in stored answers are unsupported.
- **System accuracy is limited by report quality**, not by the route. The earlier attribution traced those losses to report facts.

The comparison also found two bugs, now fixed: "What kind of incident does this report describe?" and "...in this event?" were read as chronologies.

## Text-model pilot (2026-11-06, paid, owner-approved)

Real calls to Nemotron 3 Ultra through the real router, from an isolated local process: no video call, no shared service touched. Runner: `eval/scripts/chat_routed_pilot.py`. Set: `eval/experiments/v2/chat-routed-pilot/`. Outputs and manifests: `/home/hengz/evalv2-data/v2/runs/chat-routed-pilot-2026-11-06/`. Frozen runs are unchanged (checksums verified).

**Spend:** 80 calls, 126,324 tokens (117,998 prompt, 8,326 completion), 0 failed calls. About $0.09 at OpenRouter's public rate for this model ($0.60 and $2.40 per million). That rate is an assumption: Switchyard's billing is not visible here.

### Populations

The frozen C3 chat set has 119 questions: 99 about one incident and 20 about the library. Library questions are outside this work.

| Population | Oracle | System | Note |
|---|---|---|---|
| Incident rows answered | 99 | 89 | System has no report for 10 |
| Routed to code | 69 | 63 | |
| Routed to the model | 30 | 26 | 56 pairs, but 30 distinct questions |
| Code-scorable as exact | 79 | 71 | Holder and facts classes have no exact score |
| Model-routed and exact-scorable | 20 | 17 | The earlier "20" |
| Asked in this pilot | 20 | 26 | 46: 10 oracle holder questions were left out to keep within budget, having no code score |

The questions and references are frozen, and stored grounded answers exist for all of them. Oracle reports hold no timeline, evidence or uncertainties, so timestamps and cards can only be judged on system and finals reports.

### Results

| Exact answers | Template | Grounded (stored) | Routed (new) |
|---|---|---|---|
| Oracle, all scorable | 51/79 | 72/79 | 71/79 |
| System, all scorable | 13/71 | 28/71 | 29/71 |
| Oracle, model-routed | 0/20 | 20/20 | 20/20 |
| System, model-routed | 0/17 | 15/17 | 16/17 |

- **No significant difference between routed and grounded.** On the 17 paired system questions, 2 improved and 1 got worse. This is a tie.
- **The gain over template comes from routing;** the prompt change neither helped nor hurt measurably here.
- **The frozen set tests refusal, not answering:** 45 of its 46 model answers were refusals. The 9 holder "false refusals" are correct: those reports hold no such object.
- **Routed mode spends far less:** only 26% to 30% of grounded's tokens went on questions it still sends to the model. Code answers in about 3 ms; the model took a median of 1.3 s (p90 6.7 s).

### Timestamps and cards on free-form questions

No item-level reference set exists, so these are counts, not precision or recall. 26 model answers on finals reports, each in its latest state: 10 were re-asked after fixes, and K1, K5 and K6 were replayed from their stored replies, on the earlier prompt.

| Measure | Result |
|---|---|
| Answers with a clickable time | 16 of 26 (the 10 others are mostly refusals or item answers) |
| Times not held by the report | 0 of 38 |
| Answers with a card | 23 of 26 |
| Cards with a thumbnail | 44 of 48 |
| Cards with the wrong stored second | 0 of 48 |
| Duplicate cards | 0 |
| Items named with no card | 1 |

In a browser, on replayed real replies: 6 of 6 times seeked correctly, and 5 of 5 cards loaded a thumbnail and seeked correctly.

### Multi-turn set (26 turns, criteria fixed before running, one reader)

- **Pass 20, partial 5, fail 1.**
- **Fail, D turn 2:** given history from another version, the model repeats it ("the monkey" on a dog report), even with a rule against it. The console starts a new thread per version, so this history cannot reach it there, but the model alone is not safe against it.
- **Partial:** C turn 1 wrote "15.33 seconds", which is not clickable. K1, K2, K5 and K6 have cards but no time.
- **Template, same set:** none of the 8 follow-ups was resolved. Four said so; the others gave an unrelated reply.

### Unsupported claims

The paid AI judge was not run, to stay in budget. One reader (Claude, unvalidated) read all answers and checked a sample against their reports.
- **Misattributed time:** Explosion041 says the vehicle exploded "at 1:31". The report's event runs 1:12 to 1:31, so the time exists but is the wrong end, and it would have sought to the wrong moment. Fixed after the pilot by tying each time to its event (see above): replaying all 52 stored answers leaves 6 times unlinked, including this one, and a read of the 50 written times that stay linked found none on the wrong event.
- **Small embellishment:** "remaining visible until the video ends" (H turn 2).
- No invented person, object or event was found.

The figures above predate the attribution fix, which only touches times and cards: the stored-reply replay is its evidence.

### Not measured

- **The final prompt on the frozen set.** The 46 frozen answers used an earlier prompt; only 10 calls used the final one.
- Judged unsupported-claim and contradiction rates, and grounded mode on the multi-turn set.
- Whether a human reviewer agrees with these readings.
- Route 3 has never run on a real VLM.

## Question-understanding smoke test (2026-11-07, paid, owner-approved)

The prompt changed on 7 Nov, so **the 6 Nov pilot's figures describe the earlier prompt**. It now reads the whole report, keeps role labels to the report's own text, allows partial answers, redirects unrelated questions, asks when a reference is unclear, and flags conflicts.

Real calls to Nemotron 3 Ultra through the real router, from an isolated local process, on four stored reports (assault, explosion, animal, attempted break-in). 25 questions, 46,541 tokens, 0 failed calls, one reader (Claude, unvalidated), criteria not fixed in advance. This is a smoke test, not an evaluation.

- **Pass 23, partial 2, fail 0.** No answer named an attacker or a victim the report did not.
- **Partial:** "Is this the man from yesterday's incident?" was refused as unrelated, when "the report doesn't say" is the better reply. One answer wrote "(9-34 s)", which is not clickable.
- **Still seen:** the model often flags a useful partial answer as insufficient, so its text is right and `route` reads `insufficient`.

Frozen questions replayed through the code with no model call: **no route changed** on 188 rows. 13 composed answers changed kind: the 6 window rows above, 6 name questions now say no name is given, and one "what did the person do" now tells events instead of listing objects.

## Before switching on

**Routed mode is not ready for shared users yet.** The deterministic route is. The model route has no answer-quality blocker, but:

1. **Re-run the frozen questions on the final prompt** (about 72,000 tokens), and run the judged checks or a human review.
2. **Plan for the shared key:** its limit of 4 parallel requests was hit during this work. A rate limit now gets the report's own answer or a request to try again.
3. **Video pilot (paid, needs approval):** see below.
4. **Turn on:** set `INCIDENT_CHAT_MODE=routed` in `.env.remote` (ask first) and restart `vss-agent`. It needs a chat endpoint (`INCIDENT_CHAT_BASE_URL`, else `LLM_BASE_URL`). Video checks need `INCIDENT_VIDEO_CHECK_ENABLED=1` too.
5. **Roll back:** unset the settings and restart. Template mode needs no console change.

## Video checks: what remains

Built behind `INCIDENT_VIDEO_CHECK_ENABLED`: `POST /api/v1/incidents/{video_id}/video-check`, the console action, the blind look, the comparison, and clear errors for a timeout, a rate limit and a missing clip. It writes nothing, runs in the agent's event loop, and is one call per click, so it cannot disturb analysis beyond sharing the provider's rate limit.

Still needed:
- **A live check of the request.** It copies the analysis's `video_url` shape, but the reply format is untested on a real VLM.
- **A measured answer rate:** whether a look answers the missing question, how often it adds unsupported detail, and how it behaves on rate limits.
- **Long clips.** The look samples the whole clip, so a brief moment in a long video can be missed. Cutting the window with `ffmpeg` first is the likely fix.
- **A retry for HTTP 429.** It fails at once today, on purpose, because a reviewer is waiting.
- **A record of checks.** Nothing logs who ran one beyond the agent log. Saving results would need a schema decision.
