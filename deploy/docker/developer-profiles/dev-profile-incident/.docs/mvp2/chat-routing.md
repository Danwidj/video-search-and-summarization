# Report-first chat routing

How `INCIDENT_CHAT_MODE=routed` answers a question about one report version, what it was measured against, and what remains before it is switched on. **Routed mode and video checks are both off.** The default is still template mode.

## Routes

The selected report version is the source of truth. `utils/chat_routing.py` decides from the question alone, with no model call.

| Route | Used for | Calls | Source label |
|---|---|---|---|
| 1. Deterministic | A question asking only for a kind of report field: the timeline, who, objects, taken, weapons, severity, type, when | None | Answered from the stored report |
| 2. Report-grounded model | Anything that names something, reasons, leans on the conversation or points at one moment | One text call on the report | AI reading of the stored report |
| 3. Video check | Only on the reviewer's click, after an offer | One blind vision call, one text comparison | Fresh video check |
| 4. Insufficient | The report cannot answer and no check can help (a motive, or checks are off) | As route 1 or 2 | As route 1 or 2, with `grounding.route: insufficient` |

An offer of a video check is made when checks are on and:
- the question asks for one or disputes the report ("was that actually a dog?");
- the model says the missing detail is something visible;
- the question is what followed the incident, the timeline has nothing after it, and footage remains.

A motive is never offered a check: footage cannot show one.

## What keeps each source apart

- **Model answers** have three labelled parts: what the report records, an interpretation, and what is not established. Code writes the labels.
- **Citations** must be ids the version holds; an unknown id is dropped and recorded. A card uses its evidence entry's second. An item with no stored second gets no card.
- **Times** in a model answer are checked against every second the report holds, including times stated in its words ("about 4.5s"). A time it does not hold stays plain text.
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
- **Grounded beats template on all questions, because template cannot refuse.** Every unanswerable and false-premise question scored 0 on template, and the router sends all of them to the model.
- **On the questions routed to code, the two are level.** Oracle's one-point gap includes a scorer artefact: code writes `1:34` where the scorer wants 94 seconds (window 5/10 against 10/10). Without the window class, code leads 46/49 to 42/49.
- **Routing keeps the model's accuracy for about a quarter of its tokens:** 26% to 30% of the tokens went on questions the router still sends to the model. Projected exact: oracle 71/79, system 28/71.
- **Model times are reliable:** 0 of 113 times in stored answers are unsupported.
- **System accuracy is limited by report quality**, not by the route. The earlier attribution traced those losses to report facts.

The comparison also found two bugs, now fixed: "What kind of incident does this report describe?" and "...in this event?" were read as chronologies.

Not measured:
- The new `chat/incident-routed` prompt has never run on a model. Route 2's figures are the old prompt's answers.
- Multi-turn follow-ups have no reference set. Tests prove the turns reach the model, not that it resolves them well.
- Judged checks (unsupported claims, fact recall) were not rerun. Facts and holder classes have no code score, so they are outside this table.
- Route 3 has never run on a real VLM.
- Citation recall is not comparable on oracle: its reports hold no evidence seconds, so code gives no cards where the old code showed 0:00.

## Before switching on

1. **Routed pilot (paid, needs approval):** the 56 model-routed frozen questions on `chat/incident-routed`, about 71,000 tokens at the stored rates, scored with the code scorer and the existing judge. Add a small multi-turn set.
2. **Video pilot (paid, needs approval):** see below.
3. **Turn on:** set `INCIDENT_CHAT_MODE=routed` in `generated.env.remote` (ask first) and restart `vss-agent`. It needs a chat endpoint (`INCIDENT_CHAT_BASE_URL`, else `LLM_BASE_URL`). Video checks need `INCIDENT_VIDEO_CHECK_ENABLED=1` too.
4. **Roll back:** unset the settings and restart. Template mode needs no console change.

## Video checks: what remains

Built behind `INCIDENT_VIDEO_CHECK_ENABLED`: `POST /api/v1/incidents/{video_id}/video-check`, the console action, the blind look, the comparison, and clear errors for a timeout, a rate limit and a missing clip. It writes nothing, runs in the agent's event loop, and is one call per click, so it cannot disturb analysis beyond sharing the provider's rate limit.

Still needed:
- **A live check of the request.** It copies the analysis's `video_url` shape, but the reply format is untested on a real VLM.
- **A measured answer rate:** whether a look answers the missing question, how often it adds unsupported detail, and how it behaves on rate limits.
- **Long clips.** The look samples the whole clip, so a brief moment in a long video can be missed. Cutting the window with `ffmpeg` first is the likely fix.
- **A retry for HTTP 429.** It fails at once today, on purpose, because a reviewer is waiting.
- **A record of checks.** Nothing logs who ran one beyond the agent log. Saving results would need a schema decision.
