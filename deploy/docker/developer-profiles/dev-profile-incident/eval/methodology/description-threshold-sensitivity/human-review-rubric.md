# Description acceptability rubric (blinded human review)

You see a ground-truth description and a generated description. You do not see the model or any score. Judge from the text only. Rate each pair on its own.

| Question | Options | Guide |
|---|---|---|
| Central event correct? | yes / no | Same incident type and same central action: who did what to whom or what happened. A correct type with a different event is "no" |
| Contradiction or hallucination | none / minor / major | Major: a claim that changes the event, such as a wrong animal, wrong victim, or an invented weapon. Minor: colour, count or position slips that leave the event intact |
| Essential omission | none / minor / major | Major: leaves out what makes this incident what it is, such as the break-in in a burglary. Minor: timing, clothing, aftermath |
| Overall acceptable? | yes / no / cannot tell | Yes if a reviewer could rely on it as an accurate short account. Different wording and less detail are fine |

**Rule:** answer yes only if the central event is correct, there is no major contradiction and no major omission. Extra correct detail is fine.

**Process:** two reviewers work independently, then a third resolves differences. Report Cohen's κ before resolving. Do not discuss pairs beforehand. Then join to the key and compute precision, recall, F1, false-pass and false-fail per threshold, weighting strata back to the score distribution. Do not choose a threshold by highest pass rate.
