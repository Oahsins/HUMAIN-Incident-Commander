# Browser customer demo (demo, not evidence)

A real Chromium customer uses the real test bank while `python run.py demo` injects its two-fault
incident and the frozen incident commander responds. The customer is refused during the incident,
retries the same payment until it is paid, retries once more and is told "already paid" with the
same payment id, then pays normally after the handover. The browser and the demo's terminal are
filmed side by side, and the independent checker counts the browser customer in its verdict.

It is a demo of one run of a fault pair the agent was tuned on. It says nothing about accuracy:
the held-out results do that. Label any clip from it "demo, not evidence".

## Run it

```
python browser-demo/run_demo.py --port-base 27800
```

It needs the repository's requirements, Node, and the Playwright and Chromium already in the
container (`PLAYWRIGHT_NODE_MODULE` defaults to `/opt/node-tools/node_modules/playwright`). It
sets no model key: the agent's model answers come from the keyless replay
`replays/demo-frozen.jsonl`. Everything lands in `browser-demo/out/<time>/`, which git ignores:

| File | What it is |
|---|---|
| `browser-demo.mp4` | the whole run, browser beside the terminal (about 75 s) |
| `browser-demo-cut.mp4` | a 25-30 s highlight cut for the project video (`cut.py`) |
| `report.html` | the visual report: story, swimlane timeline, map of the bank, ABCDE survey, checker numbers, shot list |
| `stills/` | each report section as a 1920-wide PNG |
| `shots/` | the browser at the key moments |
| `terminal.log`, `terminal.jsonl` | the demo's terminal, plain and time-stamped |
| `journey.jsonl`, `trace.zip` | what the browser did, and its Playwright trace |
| `run.json` | command, commit, and `run.py hash` before and after |
| `run-data/` | a copy of the bank copy's folder after the run |

## Pieces

- `server.py` (standard library) serves the customer page and forwards `/api/pay`,
  `/api/payment/<id>` and `/api/balance` to the gateway at port base + 0. After every payment
  attempt it appends one line to the copy's `customers.jsonl` in the simulated customers' own
  format (customer `web-01`, ids `web-01-000001` onwards, account `cust-20`). Responses map as in
  `targets/bank/customers.py`: 2xx ok, 4xx rejected, 5xx or a timeout failed. Without those lines
  the checker would count the browser's payments as ghost payments.
- `page.html` shows only what a customer sees: amount, Pay, Retry same payment, the last result,
  the payment list and the balance. `stage.html` and `terminal.html` put it beside the terminal for filming.
- `journey.cjs` runs one continuous Chromium session with video and a trace, locked to
  `127.0.0.1`, with WebSockets and service workers blocked. It follows the demo by reading its
  terminal log. Its post-incident payments fall inside the checker's scored window; its "already
  paid" retry happens before the handover, so the window holds only fresh payments.
- `run_demo.py` runs everything, `cut.py` cuts the highlight clip and `report.py` writes the report.

## What it does not touch

No hashed file changes: no gateway route, no `run.py` subcommand, no edit to `ic/demo.py` or
`targets/bank/`. The only writes outside this folder go to the copy's folder under `runs/`.
`run_demo.py` records `python run.py hash --json` before and after and says whether they match.
No file is named `test_*.py`, so CI's pytest never collects it.
