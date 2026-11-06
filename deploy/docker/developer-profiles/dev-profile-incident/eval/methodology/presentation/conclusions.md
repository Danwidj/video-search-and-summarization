# Overall conclusions

Status 2026-11-06. Super closed at its deadline: 50 of 110 valid, original Track B and chat-a4 not completed. Demonstrated means a valid analysis supports it; tentative means direction or small sample; untested means no valid data.

| Question | Answer | Standing |
|---|---|---|
| Does VSS beat a direct VLM on accuracy? | No significant difference in any comparison, including the matched final run | Demonstrated: no improvement shown. Equivalence is not shown |
| What does VSS cost? | About 2.9× tokens and 8.8× median latency per video in the final run | Demonstrated for this configuration; latency is descriptive |
| What does VSS add? | Evidence boxes, zoomed naming, reviewable versioned reports | Evidence quality is measured against AI references; usefulness to reviewers is untested |
| Best model for valid-report yield | Nano, 95/110 | Demonstrated, Super incomplete |
| Best model among valid outputs | Gemma on severity, object score and description; subsets differ by model | Tentative |
| Which failures are real? | Wrong-event descriptions, Nano severity (no better than always 3), token-limit truncation | Demonstrated |
| Is Super worse? | Unknown. Nano − Super on 44 pairs shows no difference, and 60 items stayed unanswered through outage | Incomplete |
| Does production VSS (tracking on, Super grounding) help? | Unknown | Untested |
| Does grounded chat beat template chat? | Never compared | Untested |
| Is chat reliable? | On good reports, yes (0.80 exact; 0.82 corrected). On pipeline reports, no (0.19); most losses trace to report facts | Demonstrated against AI references |
| Is the dashboard safe? | 57/60, 72/75, no false acceptance | Demonstrated on template-worded requests |

**One-line message.** The pipeline does not yet make extraction measurably more accurate; its measured value is evidence at higher cost, and report quality is what limits downstream chat.
