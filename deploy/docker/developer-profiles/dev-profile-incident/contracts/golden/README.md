# Request goldens

The exact request bodies this profile sends to models, one JSON file per request kind with named cases. Each producer of a case (the console, eval or the agent) has a test that builds the request with its own code and compares it with the case. Two producers of one case therefore send the same request, and a change to any prompt or setting fails a test until its golden changes in the same PR. `vlm-gateway` forwards the console's body unchanged, so it has no golden of its own.

## What is inside

| File | Cases | Producers |
|---|---|---|
| [p1.json](p1.json) | `base` | agent, console, eval |
| | `reviewer` (a reviewer instruction) | agent, console |
| | `captions` (the caption pass's context), `marks` (set-of-marks), `captions-and-marks` | agent |
| [rp1.json](rp1.json) | `report` | agent, eval |
| [caption.json](caption.json) | `window` (default 20 s, 32 frames), `remainder` (a shorter last window) | agent |
| [grounding.json](grounding.json) | `best-match` (grounding, object tracking) | agent |
| [zoom.json](zoom.json) | `look-<type>-frame`, `look-<type>-close-up`, `merge-<type>` for `entity` and `asset` (an instrument takes the asset branch with its own word); `describe-box` (a reviewer-drawn box) | agent |
| [chart.json](chart.json) | `request` (dashboard "Ask for a chart") | console |
| [chat.json](chat.json) | `incident-answer` (grounded chat), `library-plan` and `library-answer` (a library question's plan and answer) | agent |
| [load_golden.py](load_golden.py) | The loader, standard library only | tests |

The producer tests, each of which also asserts that it covers every case naming its producer:
- console: [parity-golden.test.mjs](../../incident-console-v2/tests/parity-golden.test.mjs), with its rules in [golden.mjs](../../incident-console-v2/tests/support/golden.mjs);
- eval: [test_parity_golden.py](../../eval/tests/test_parity_golden.py), which also checks that every golden is well formed;
- agent: [test_parity_golden.py](../../../../../../services/agent/tests/unit_test/incident_contract/test_parity_golden.py).

## Case format

A case has:
- `description` and `producers`;
- `inputs`: what the test passes to the producer. Placeholders such as `<model>` and `<video-url>` stand for per-call values;
- `transport` (optional): keys a producer may add, with exactly this value. Today that is only the agent's `"stream": false`;
- `body`.

Bodies are compared as JSON values. Key order, whitespace and `0` against `0.0` do not count; booleans are not numbers; arrays keep their order. An inline image (`data:image/jpeg;base64,...`) counts as `data:image/jpeg;base64,<jpeg>`, because the encoded bytes depend on the encoder.

The P1 prompt is stored as `{"$contract_text": "incident_extraction_prompt.txt", "sha256": "..."}` and the strict `response_format` as `{"$contract_json": "fixtures/response_format.json", "sha256": "..."}`. The loader substitutes the file after checking its hash, so a contract change updates one hash per case instead of copying 27 KB into every case. Every other prompt, from [prompts](../prompts/README.md), is stored literally.

## Changing a request

1. Change the producer's code. If the change is to P1 or RP1, edit the contract files here too and bump [VERSION](../VERSION).
2. The producer's golden test fails with a diff. Update the case's `body`, or the `sha256` of a referenced contract file, in the same PR.
3. Every other producer of the case must then match as well: that is the parity check.
4. A change that is not a contract bump also gets a line in the [Decision log](../../.docs/decisions.md) saying why.

Not covered here: the template chat, which makes no model call, the routed chat and video-check prompts, which are off and have one producer, and the experiment prompts in [experiments](../experiments/README.md), which have their own registry hashes.

## Read more

- [Analysis schema: The analysis request](../../.docs/analysis-schema.md#2-the-analysis-request-identical-to-eval-p1): how the P1 body is built
