"""A visual report of one browser-demo run: what happened, how the agent worked, and where. Demo only, not evidence.

    python browser-demo/report.py <run folder> [--no-stills]

Reads what run_demo.py kept (run.json, terminal.jsonl, journey.jsonl, the screenshots and the
copy's folder under run-data/) and writes report.html, a self-contained page, beside them. Unless
--no-stills is given it also exports each section as a 1920-wide PNG under stills/, for slides or
the video. Python standard library only; the stills use the container's Playwright.

The checker numbers here are recomputed after the run from the same files, with the checker's own
functions and the window `run.py demo` used. The verdict that counts is the one the demo printed.
"""

import argparse
import base64
import glob
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CUSTOMER = "web-01"
PHASES = ["survey", "triage", "remediate", "verify", "hand_over"]
PHASE_LABEL = {"survey": "Survey", "triage": "Triage", "remediate": "Remediate", "verify": "Verify",
               "hand_over": "Hand over"}
LETTERS = {"A": "Access", "B": "Bottlenecks", "C": "Capacity", "D": "Dependencies", "E": "Events"}
COMPONENT_ROLE = {"gateway": "front door for customer apps", "payments": "posts payments to the ledger",
                  "screening": "fraud screening, primary", "screening-standby": "fraud screening, standby",
                  "clearing": "sends posted payments on", "network": "national network (another organisation)"}
ALERT_DELAY_S = 5.0     # ic/contract.py ALERT_DELAY_S
CHECK_WINDOW_S = 20.0   # ic/contract.py CHECK_WINDOW_S
e = html.escape


# ----- reading the run -----

def jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def load(run_dir):
    data = os.path.join(run_dir, "run-data")
    run = json.load(open(os.path.join(run_dir, "run.json"), encoding="utf-8"))
    agent_files = sorted(glob.glob(os.path.join(data, "agent-*.json")))
    result = json.load(open(agent_files[-1], encoding="utf-8")) if agent_files else None
    terminal = jsonl(os.path.join(run_dir, "terminal.jsonl"))
    logs = {}
    for path in glob.glob(os.path.join(data, "logs", "*.jsonl")):
        logs[os.path.basename(path)[:-6]] = jsonl(path)
    ports = json.load(open(os.path.join(data, "ports.json"), encoding="utf-8"))["ports"]
    components = [c for c in ports if c != "supervisor" and "->" not in c]
    return {"dir": run_dir, "data": data, "run": run, "result": result, "terminal": terminal,
            "journey": jsonl(os.path.join(run_dir, "journey.jsonl")),
            "browser": jsonl(os.path.join(data, "web-01-journal.jsonl")),
            "customers": jsonl(os.path.join(data, "customers.jsonl")),
            "changes": jsonl(os.path.join(data, "changes.jsonl")), "logs": logs, "components": components}


def line_time(run, pattern):
    for rec in run["terminal"]:
        if pattern in rec["line"]:
            return rec["t"]
    return None


def moments(run):
    r = run["result"]
    pipeline = [c["t"] for c in run["changes"] if c.get("actor") not in ("incident-commander",)]
    injected = line_time(run, "fault(s) injected")
    t_fault = min([t for t in pipeline + [injected] if t] or [r["t_start"] - ALERT_DELAY_S])
    sent = [a["t"] for a in r["actions"] if a.get("sent")]
    last = max(sent + [r["t_declared"]])
    ws = last + 1.0   # run.py demo waits until the window that starts 1 s after the last action has ended
    bank_up = next((j["t"] for j in run["journey"] if j["event"] == "bank_up"), None)
    return {"start": line_time(run, "starting a fresh") or (bank_up or t_fault) - 3, "bank_up": bank_up,
            "fault": t_fault, "alert": r["t_start"], "first_action": r["t_first_action"] or None,
            "declared": r["t_declared"], "window": (ws, ws + CHECK_WINDOW_S),
            "verdict": line_time(run, "CHECKER:"),
            "verdict_text": next((x["line"] for x in run["terminal"] if x["line"].startswith("CHECKER:")), "no verdict")}


def recompute(run, m):
    """The checker's own numbers for the demo's window, from the copied files (read only)."""
    try:
        from targets.bank import checker, ledger
        records = checker.read_customer_log(os.path.join(run["data"], "customers.jsonl"))
        conn = ledger.connect(run["data"], readonly=True)
        try:
            book = checker.Ledger(conn)
            ws, we = m["window"]
            journeys = checker.judge_journeys(records, book, ws, we)
            ghost, lost = checker.match_customers(records, book.payments_by_e2e(ws - checker.RECENT_LEDGER_GRACE_S),
                                                  ws, we)
            impact = checker.impact(records, book, m["fault"], we)
            rows = conn.execute("SELECT end_to_end_id, id, status, amount_minor, created_t FROM payments "
                                "WHERE end_to_end_id LIKE ? ORDER BY created_t", (CUSTOMER + "-%",)).fetchall()
            ledger_rows = [dict(zip(("e2e", "id", "status", "amount_minor", "created_t"), row)) for row in rows]
            return {"journeys": journeys, "ghost": ghost, "lost": lost, "impact": impact,
                    "duplicates": book.duplicates(ws), "ledger_rows": ledger_rows,
                    "browser_in_window": [rec for rec in records if rec.get("customer") == CUSTOMER
                                          and rec["kind"] == "payment" and ws <= rec["t_start"] < we]}
        finally:
            conn.close()
    except Exception as exc:   # the report still renders without these numbers
        return {"error": f"{type(exc).__name__}: {exc}"}


def demo_faults():
    try:
        from targets.bank.platform import Platform
        return Platform.demo_faults
    except Exception:
        return []


# ----- helpers -----

def sar(minor):
    return f"SAR {minor / 100:,.2f}"


def secs(t, m):
    d = t - m["fault"]
    return f"T{'+' if d >= 0 else '−'}{abs(d):.1f} s"


def describe_change(c):
    d = c.get("detail") or {}
    if c["kind"] == "config":
        frm, to = d.get("from"), d.get("to")
        if d.get("key") == "max_transfer_minor":
            frm, to = sar(frm), sar(to)
        verb = "reverts" if d.get("revert") else "sets"
        return f"{verb} {d.get('key')} {frm} → {to}"
    if c["kind"] == "failover":
        return f"fails over {c['component']} from {d.get('from')} to {d.get('to')}"
    return f"{c['kind']} {json.dumps(d)}"


def trace_components(event, components):
    """Which components one agent step touched."""
    data = event.get("data") or {}
    summary = event.get("summary", "")
    if data.get("target"):
        return [data["target"]]
    if event["name"] == "logs":
        for c in sorted(components, key=len, reverse=True):
            if summary.endswith("from " + c):
                return [c]
    if event["name"] == "probe":
        return ["gateway", "payments", "screening", "clearing"]
    if event["name"] in ("describe", "observe", "abcde") or event["kind"] == "note" and event["name"] == "check":
        return ["all"]
    if event["kind"] == "model":
        return ["model"]
    return []


def params_text(action):
    return ", ".join(f"{k} {v}" for k, v in (action.get("params") or {}).items())


def b64(path):
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode()


def fonts_css():
    faces = [("Plex Sans", "IBMPlexSans.woff2", "400 600"), ("Plex Cond", "IBMPlexSansCondensed-600.woff2", "600"),
             ("Plex Mono", "IBMPlexMono-400.woff2", "400"), ("Plex Mono", "IBMPlexMono-500.woff2", "500")]
    out = []
    for family, name, weight in faces:
        path = os.path.join(HERE, "fonts", name)
        if os.path.exists(path):
            out.append(f"@font-face{{font-family:'{family}';font-weight:{weight};font-display:swap;"
                       f"src:url(data:font/woff2;base64,{b64(path)}) format('woff2')}}")
    return "\n".join(out)


# ----- the swimlane timeline -----

def timeline_svg(run, m, rc):
    r = run["result"]
    comps = run["components"]
    t_lo = (m["bank_up"] or m["start"]) - m["fault"] - 1.5
    t_hi = (m["verdict"] or m["window"][1] + 10) - m["fault"] + 2.0
    label_w, plot_w = 196, 1180
    W = label_w + plot_w + 24
    x = lambda t: label_w + (t - m["fault"] - t_lo) / (t_hi - t_lo) * plot_w
    lanes = [("browser", "Browser customer", "web-01 · Chromium", 74),
             ("crowd", "Simulated customers", "20 · payments per second", 64)]
    lanes += [(c, c, COMPONENT_ROLE.get(c, ""), 40) for c in comps]
    lanes += [("agent", "Incident commander", "ABCDE · frozen agent", 86), ("checker", "Independent checker", "customers' logs + ledger", 46)]
    top = 64
    y, ypos = top, {}
    for key, _, _, h in lanes:
        ypos[key] = (y, h)
        y += h + 8
    H = y + 36
    s = [f'<svg class="tl" viewBox="0 0 {W} {H}" width="100%" style="min-width:1100px;height:auto" role="img" '
         f'aria-label="Swimlane timeline of the incident, by component">']
    # lane backgrounds and labels
    for key, name, sub, h in lanes:
        y0, _ = ypos[key]
        s.append(f'<rect x="{label_w}" y="{y0}" width="{plot_w}" height="{h}" class="lane"/>')
        s.append(f'<text x="12" y="{y0 + h / 2 - 3}" class="ln">{e(name)}</text>'
                 f'<text x="12" y="{y0 + h / 2 + 13}" class="ls">{e(sub)}</text>')
    # axis
    first = int(t_lo // 5 * 5)
    for t in range(first, int(t_hi) + 1, 5):
        if t < t_lo:
            continue
        s.append(f'<line x1="{x(t + m["fault"]):.1f}" x2="{x(t + m["fault"]):.1f}" y1="{top - 6}" y2="{H - 30}" class="grid"/>')
        s.append(f'<text x="{x(t + m["fault"]):.1f}" y="{H - 12}" class="tick" text-anchor="middle">{t:+d} s</text>'
                 if t else f'<text x="{x(m["fault"]):.1f}" y="{H - 12}" class="tick strong" text-anchor="middle">T = 0</text>')
    # the scored window
    ws, we = m["window"]
    s.append(f'<rect x="{x(ws):.1f}" y="{top - 6}" width="{x(we) - x(ws):.1f}" height="{H - 30 - top + 6}" class="win"/>')
    # state bands on component lanes
    failover = next((c for c in run["changes"] if c["kind"] == "failover"), None)
    revert = next((c for c in run["changes"] if c["kind"] == "config" and (c.get("detail") or {}).get("revert")), None)
    pipeline = next((c for c in run["changes"] if c.get("actor") == "pipeline"), None)
    end = m["verdict"] or we

    def band(comp, t0, t1, cls, text):
        if comp not in ypos or t1 <= t0:
            return
        y0, h = ypos[comp]
        s.append(f'<rect x="{x(t0):.1f}" y="{y0 + 4}" width="{x(t1) - x(t0):.1f}" height="{h - 8}" rx="3" class="{cls}"/>')
        if x(t1) - x(t0) > len(text) * 6.2 + 20:   # room beside the diamond that marks the band's start
            s.append(f'<text x="{x(t0) + 14:.1f}" y="{y0 + h / 2 + 4}" class="bt">{e(text)}</text>')
    if pipeline:
        band(pipeline["component"], pipeline["t"], revert["t"] if revert else end, "bad",
             "limit SAR " + f'{(pipeline.get("detail") or {}).get("to", 0) / 100:,.0f}')
    slow = [f for f in demo_faults() if f["type"] == "slow_screening"]
    if slow:
        band("screening", m["fault"], failover["t"] if failover else end, "bad", "slow, in path")
        if failover:
            band("screening", failover["t"], end, "muted", "still slow, out of the payment path")
    if failover:
        band("screening-standby", failover["t"], end, "good", "serving fraud screening")
    # component log events (warnings and errors)
    for comp, records in run["logs"].items():
        if comp not in ypos:
            continue
        y0, h = ypos[comp]
        for rec in records:
            if rec.get("level") not in ("WARN", "ERROR"):
                continue
            cls = "dotwarn" if rec["level"] == "WARN" else "doterr"
            n = rec.get("occurrences", 1)
            s.append(f'<circle cx="{x(rec["t"]):.1f}" cy="{y0 + h - 7}" r="{3 + min(n, 20) ** 0.5:.1f}" class="{cls}">'
                     f'<title>{e(comp)} {e(rec["level"])}: {e(rec.get("msg", ""))} (×{n})</title></circle>')
    # change feed diamonds
    for c in run["changes"]:
        if c["component"] not in ypos:
            continue
        y0, h = ypos[c["component"]]
        cx, cy = x(c["t"]), y0 + h / 2
        cls = "act" if c.get("actor") == "incident-commander" else "fault"
        s.append(f'<path d="M{cx:.1f} {cy - 9} l9 9 -9 9 -9 -9z" class="{cls}"><title>{e(c.get("actor", ""))}: '
                 f'{e(describe_change(c))}</title></path>')
    # slow screening has no change-feed entry: mark the injection itself
    if slow and "screening" in ypos:
        y0, h = ypos["screening"]
        cx, cy = x(m["fault"]), y0 + h / 2
        s.append(f'<path d="M{cx:.1f} {cy - 9} l9 9 -9 9 -9 -9z" class="fault hollow"><title>injected: slow fraud '
                 f'screening (no change-feed entry)</title></path>')
    # simulated customers, per second
    y0, h = ypos["crowd"]
    buckets = {}
    for rec in run["customers"]:
        if rec.get("kind") != "payment" or rec.get("customer") == CUSTOMER:
            continue
        b = buckets.setdefault(int(rec["t_start"] - m["fault"] - t_lo), {"ok": 0, "rejected": 0, "failed": 0})
        b[rec["outcome"]] = b.get(rec["outcome"], 0) + 1
    peak = max([sum(b.values()) for b in buckets.values()] or [1])
    bw = plot_w / (t_hi - t_lo) * 0.78
    for sec, b in sorted(buckets.items()):
        base = y0 + h - 3
        for kind in ("ok", "rejected", "failed"):
            hh = b[kind] / peak * (h - 8)
            if hh <= 0:
                continue
            base -= hh
            s.append(f'<rect x="{x(sec + t_lo + m["fault"]):.1f}" y="{base:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                     f'class="c{kind}"><title>{sec + t_lo:+.0f} s: {b["ok"]} ok, {b["rejected"]} refused, '
                     f'{b["failed"]} failed</title></rect>')
    # browser customer attempts
    y0, h = ypos["browser"]
    last_label = [-1e9, -1e9]
    for i, a in enumerate(run["browser"]):
        cx = x(a["t_start"])
        ans = a.get("answer") or {}
        cls = {"ok": "cok", "rejected": "crejected", "failed": "cfailed"}[a["outcome"]]
        label = (f'{a["status"]} refused' if a["outcome"] == "rejected" else
                 "already paid" if ans.get("replayed") else f'{a["status"]} paid' if a["outcome"] == "ok"
                 else f'{a["status"]} failed')
        row = 0 if cx - last_label[0] > len(label) * 7.2 + 10 else 1
        last_label[row] = cx
        s.append(f'<circle cx="{cx:.1f}" cy="{y0 + 18}" r="8" class="{cls} ring"><title>{e(a["end_to_end_id"])} '
                 f'{sar(a["amount_minor"])}: {e(label)} {e(ans.get("error", ""))}</title></circle>')
        s.append(f'<text x="{cx:.1f}" y="{y0 + 44 + row * 16}" class="bl" text-anchor="middle">{e(label)}</text>')
    # agent phases and steps
    y0, h = ypos["agent"]
    trace = r["trace"]
    starts = []
    for ev in trace:
        if not starts or starts[-1][0] != ev["phase"]:
            starts.append((ev["phase"], ev["t"]))
    for i, (phase, t0) in enumerate(starts):
        t1 = starts[i + 1][1] if i + 1 < len(starts) else trace[-1]["t"] + 0.6
        x0, x1 = x(r["t_start"] + t0), x(r["t_start"] + t1)
        s.append(f'<rect x="{x0:.1f}" y="{y0 + 6}" width="{max(x1 - x0, 3):.1f}" height="22" rx="3" class="ph {phase}">'
                 f'<title>{PHASE_LABEL[phase]} {t0:.1f}–{t1:.1f} s</title></rect>')
    row_end = [-1e9, -1e9, -1e9]   # greedy: each label takes the first row where it fits
    for phase, t0 in starts:
        lx = x(r["t_start"] + t0)
        width = len(PHASE_LABEL[phase]) * 7.4 + 8
        row = next((i for i, end in enumerate(row_end) if lx >= end), len(row_end) - 1)
        row_end[row] = lx + width
        s.append(f'<text x="{lx:.1f}" y="{y0 + 50 + row * 14}" class="pl {phase}t">{PHASE_LABEL[phase]}</text>')
    for ev in trace:
        cx = x(r["t_start"] + ev["t"])
        cls = "tk act" if ev["kind"] == "action" else "tk"
        s.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y0 + 30}" y2="{y0 + 34 + (10 if ev["kind"] == "action" else 0)}" '
                 f'class="{cls}"><title>{ev["t"]:.1f} s {e(ev["phase"])} {e(ev["name"])}: {e(ev["summary"])}</title></line>')
    # checker
    y0, h = ypos["checker"]
    s.append(f'<rect x="{x(ws):.1f}" y="{y0 + 8}" width="{x(we) - x(ws):.1f}" height="{h - 16}" rx="3" class="chk"/>')
    s.append(f'<text x="{x(ws) + 6:.1f}" y="{y0 + h / 2 + 4}" class="bt">scored window (20 s)</text>')
    if m["verdict"]:
        ok = m["verdict_text"].startswith("CHECKER: RECOVERED")
        s.append(f'<circle cx="{x(m["verdict"]):.1f}" cy="{y0 + h / 2}" r="9" class="{"cok" if ok else "crejected"}"/>')
    # moment markers
    marks = [("fault", "faults land", "mk bad"), ("alert", "alert · agent starts", "mk"),
             ("first_action", "first action", "mk good"), ("declared", "hand over", "mk"),
             ("verdict", "checker verdict", "mk")]
    placed = []
    for key, text, cls in marks:
        t = m.get(key)
        if not t:
            continue
        mx = x(t)
        s.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="{top - 6}" y2="{H - 30}" class="{cls}"/>')
        row = 0
        while any(abs(mx - px) < 120 and pr == row for px, pr in placed):
            row += 1
        placed.append((mx, row))
        label = f"{text} · {secs(t, m)}"
        anchor = "end" if mx + len(label) * 7.4 > W else "start"
        s.append(f'<text x="{mx + (-4 if anchor == "end" else 4):.1f}" y="{18 + row * 16}" class="mt" '
                 f'text-anchor="{anchor}">{e(label)}</text>')
    s.append("</svg>")
    return "".join(s)


# ----- where: the bank's map -----

def where_svg(run, m):
    r = run["result"]
    boxes = {"browser": (20, 40, "Browser customer", "web-01 · real Chromium"),
             "crowd": (20, 150, "20 simulated customers", "pay and read balances nonstop"),
             "gateway": (300, 95, "gateway", "front door"),
             "payments": (560, 95, "payments", "posts to the ledger"),
             "screening": (840, 20, "screening", "fraud check · primary"),
             "screening-standby": (840, 170, "screening-standby", "fraud check · standby"),
             "clearing": (560, 300, "clearing", "sends payments on"),
             "network": (840, 300, "network", "another organisation"),
             "agent": (20, 300, "Incident commander", "ABCDE · guard-wrapped")}
    bw, bh = 220, 64
    failover = next((c for c in run["changes"] if c["kind"] == "failover"), None)
    s = ['<svg class="map" viewBox="0 0 1090 400" width="100%" style="min-width:820px;height:auto" role="img" '
         'aria-label="Map of the bank: where the faults landed and where the agent acted">',
         '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
         '<path d="M0 0L10 5L0 10z" class="arh"/></marker>'
         '<marker id="arg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
         '<path d="M0 0L10 5L0 10z" class="arhg"/></marker></defs>']

    def edge(a, b, cls="ed", label=None, ay=0.5, by=0.5):
        ax, ay0 = boxes[a][0] + bw, boxes[a][1] + bh * ay
        bx, by0 = boxes[b][0], boxes[b][1] + bh * by
        mid = (ax + bx) / 2
        s.append(f'<path d="M{ax} {ay0} C{mid} {ay0} {mid} {by0} {bx - 2} {by0}" class="{cls}" '
                 f'marker-end="url(#{"arg" if "good" in cls else "ar"})"/>')
        if label:
            s.append(f'<text x="{mid}" y="{(ay0 + by0) / 2 - 6}" class="el" text-anchor="middle">{e(label)}</text>')
    edge("browser", "gateway", by=0.35)
    edge("crowd", "gateway", by=0.65)
    edge("gateway", "payments")
    edge("payments", "screening", "ed cut" if failover else "ed", ay=0.35)
    edge("payments", "screening-standby", "ed good" if failover else "ed faint", ay=0.65)
    s.append(f'<path d="M{boxes["payments"][0] + 170} {boxes["payments"][1] + bh} V{boxes["clearing"][1] - 2}" '
             f'class="ed" marker-end="url(#ar)"/>')
    edge("clearing", "network")
    for key, (bx, by, name, sub) in boxes.items():
        cls = "bx agent" if key == "agent" else "bx cust" if key in ("browser", "crowd") else "bx"
        s.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" class="{cls}"/>'
                 f'<text x="{bx + 14}" y="{by + 27}" class="bn">{e(name)}</text>'
                 f'<text x="{bx + 14}" y="{by + 47}" class="bs">{e(sub)}</text>')
    # the agent's actions, drawn from the agent box to where it acted
    acts = [a for a in r["actions"] if a.get("sent")]
    ax0, ay0 = boxes["agent"][0] + bw, boxes["agent"][1] + bh / 2
    for i, a in enumerate(acts):
        if a["target"] not in boxes:
            continue
        tx, ty = boxes[a["target"]][0] + 60, boxes[a["target"]][1] + bh
        s.append(f'<path d="M{ax0} {ay0 - 10 + i * 20} C{ax0 + 160} {ay0 - 10 + i * 20} {tx} {ty + 120} {tx} {ty + 3}" '
                 f'class="ed good act" marker-end="url(#arg)"/>')
    # fault and action badges
    badges = []
    fault_n = 0
    for f in demo_faults():
        fault_n += 1
        comp = "payments" if f["type"] == "bad_setting" else "screening" if f["type"] == "slow_screening" else None
        if comp:
            badges.append((comp, f"F{fault_n}", "bf"))
    for i, a in enumerate(acts, 1):
        badges.append((a["target"], f"A{i}", "ba"))
    count = {}
    for comp, text, cls in badges:
        if comp not in boxes:
            continue
        k = count.get(comp, 0)
        count[comp] = k + 1
        bx, by = boxes[comp][0] + bw - 18 - k * 34, boxes[comp][1]
        s.append(f'<circle cx="{bx}" cy="{by}" r="15" class="{cls}"/><text x="{bx}" y="{by + 5}" '
                 f'class="bdt" text-anchor="middle">{text}</text>')
    s.append("</svg>")
    return "".join(s)


# ----- the page -----

CSS = """
/* Layout: one reading column; wide drawings scroll inside their own frames. */
:root {
  --paper:#f3f6f5; --panel:#ffffff; --ink:#13201c; --muted:#56655f; --rule:#d6dfdb; --lane:#eaf0ed;
  --brand:#0f5c4d; --ok:#1d7f45; --bad:#c0362c; --warn:#a86400; --badbg:#f9e3e0; --okbg:#e2f2e8;
  --survey:#0e7c91; --triage:#a2399c; --remediate:#a77200; --verify:#2f8a4e; --hand_over:#3461c1;
  --display:'Plex Cond','IBM Plex Sans Condensed','Arial Narrow',sans-serif;
  --body:'Plex Sans','IBM Plex Sans',system-ui,sans-serif; --mono:'Plex Mono','IBM Plex Mono',ui-monospace,monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper:#0c1311; --panel:#121b18; --ink:#e3ece8; --muted:#93a49e; --rule:#25332e; --lane:#16211e;
  --brand:#45b896; --ok:#4cc27a; --bad:#f0685c; --warn:#e6a740; --badbg:#3a1d1a; --okbg:#173426;
  --survey:#45c3d8; --triage:#d77ad1; --remediate:#e2b33c; --verify:#5ccf84; --hand_over:#7ea3ff; color-scheme:dark; } }
:root[data-theme="dark"] {
  --paper:#0c1311; --panel:#121b18; --ink:#e3ece8; --muted:#93a49e; --rule:#25332e; --lane:#16211e;
  --brand:#45b896; --ok:#4cc27a; --bad:#f0685c; --warn:#e6a740; --badbg:#3a1d1a; --okbg:#173426;
  --survey:#45c3d8; --triage:#d77ad1; --remediate:#e2b33c; --verify:#5ccf84; --hand_over:#7ea3ff; color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:15px/1.55 var(--body); }
.wrap { max-width:1240px; margin:0 auto; padding-block:28px 64px;
        padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px));
        display:grid; gap:22px; }
section { background:var(--panel); border:1px solid var(--rule); border-radius:10px; padding:22px 24px; min-width:0; }
h1, h2, h3 { font-family:var(--display); font-weight:600; text-wrap:balance; margin:0; letter-spacing:.1px; }
h1 { font-size:clamp(30px, 4.4vw, 46px); line-height:1.05; }
h2 { font-size:25px; line-height:1.15; }
h3 { font-size:18px; }
p { margin:0; max-width:72ch; }
.eyebrow { font:500 12px/1 var(--mono); text-transform:uppercase; letter-spacing:1.2px; color:var(--muted); }
.head { display:grid; gap:12px; padding-block:6px; }
.tag { display:inline-block; font:500 12px/1 var(--mono); letter-spacing:1px; text-transform:uppercase; padding:6px 9px;
       border-radius:4px; color:var(--bad); border:1px solid var(--bad); }
.verdict { display:inline-flex; align-items:center; gap:10px; font:600 20px/1 var(--display); padding:10px 14px;
           border-radius:6px; background:var(--okbg); color:var(--ok); }
.verdict.no { background:var(--badbg); color:var(--bad); }
.row { display:flex; flex-wrap:wrap; gap:12px; align-items:center; }
.stack { display:grid; gap:14px; }
.lede { font-size:17px; color:var(--ink); }
.muted { color:var(--muted); }
.figs { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:1px; background:var(--rule);
        border:1px solid var(--rule); border-radius:8px; overflow:hidden; }
.fig { background:var(--panel); padding:14px 16px; display:grid; gap:4px; align-content:start; }
.fig b { font:600 26px/1.1 var(--display); font-variant-numeric:tabular-nums; }
.fig span { font-size:13px; color:var(--muted); }
ol.story { list-style:none; margin:0; padding:0; display:grid; gap:0; counter-reset:s; }
ol.story li { display:grid; grid-template-columns:96px 150px 1fr; gap:14px; padding:11px 0; border-top:1px solid var(--rule);
              align-items:baseline; }
ol.story li:first-child { border-top:0; }
.t { font:500 13px var(--mono); font-variant-numeric:tabular-nums; color:var(--muted); }
.chip { display:inline-block; font:500 12px/1.2 var(--mono); padding:3px 8px; border-radius:99px; border:1px solid var(--rule);
        color:var(--ink); background:var(--lane); white-space:nowrap; }
.chip.bad { color:var(--bad); border-color:var(--bad); background:transparent; }
.chip.good { color:var(--ok); border-color:var(--ok); background:transparent; }
.chip.cust { color:var(--brand); border-color:var(--brand); background:transparent; }
.frame { overflow-x:auto; border:1px solid var(--rule); border-radius:8px; background:var(--panel); }
.frame svg { display:block; }
.legend { display:flex; flex-wrap:wrap; gap:8px 18px; font-size:13px; color:var(--muted); }
.legend i { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-1px; }
svg text { font-family:var(--body); fill:var(--ink); }
svg .ln { font:600 14px var(--body); fill:var(--ink); } svg .ls { font-size:11.5px; fill:var(--muted); }
svg .lane { fill:var(--lane); } svg .grid { stroke:var(--rule); stroke-width:1; }
svg .tick { font:12px var(--mono); fill:var(--muted); } svg .tick.strong { fill:var(--bad); font-weight:500; }
svg .win { fill:var(--ok); opacity:.07; }
svg .bad { fill:var(--bad); opacity:.22; } svg .good { fill:var(--ok); opacity:.22; } svg .muted { fill:var(--muted); opacity:.15; }
svg .bt { font-size:12px; fill:var(--ink); }
svg .dotwarn { fill:var(--warn); opacity:.85; } svg .doterr { fill:var(--bad); opacity:.85; }
svg .fault { fill:var(--bad); } svg .fault.hollow { fill:var(--panel); stroke:var(--bad); stroke-width:2.5; }
svg .act { fill:var(--ok); }
svg .cok { fill:var(--ok); } svg .crejected { fill:var(--bad); } svg .cfailed { fill:var(--warn); }
svg .ring { stroke:var(--panel); stroke-width:2.5; }
svg .bl { font:500 11.5px var(--mono); fill:var(--ink); }
svg .ph.survey { fill:var(--survey); } svg .ph.triage { fill:var(--triage); } svg .ph.remediate { fill:var(--remediate); }
svg .ph.verify { fill:var(--verify); } svg .ph.hand_over { fill:var(--hand_over); }
svg .pl { font:600 12px var(--body); } svg .surveyt { fill:var(--survey); } svg .triaget { fill:var(--triage); }
svg .remediatet { fill:var(--remediate); } svg .verifyt { fill:var(--verify); } svg .hand_overt { fill:var(--hand_over); }
svg .tk { stroke:var(--muted); stroke-width:1.5; } svg .tk.act { stroke:var(--ok); stroke-width:3; }
svg .chk { fill:var(--ok); opacity:.25; }
svg .mk { stroke:var(--muted); stroke-width:1.2; stroke-dasharray:4 4; } svg .mk.bad { stroke:var(--bad); }
svg .mk.good { stroke:var(--ok); } svg .mt { font:500 12px var(--mono); fill:var(--ink); }
svg .bx { fill:var(--panel); stroke:var(--ink); stroke-width:1.4; } svg .bx.cust { stroke:var(--brand); }
svg .bx.agent { fill:var(--lane); stroke:var(--ok); stroke-width:2; }
svg .bn { font:600 15px var(--body); } svg .bs { font-size:12px; fill:var(--muted); }
svg .ed { fill:none; stroke:var(--muted); stroke-width:1.6; } svg .ed.cut { stroke:var(--bad); stroke-dasharray:6 5; }
svg .ed.good { stroke:var(--ok); stroke-width:2.2; } svg .ed.faint { opacity:.35; } svg .ed.act { stroke-dasharray:2 5; stroke-linecap:round; stroke-width:2.6; }
svg .el { font:500 11.5px var(--mono); fill:var(--muted); }
svg .arh { fill:var(--muted); } svg .arhg { fill:var(--ok); }
svg .bf { fill:var(--bad); } svg .ba { fill:var(--ok); } svg .bdt { font:600 12px var(--mono); fill:var(--panel); }
.keys { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:12px; }
.key { display:grid; grid-template-columns:38px 1fr; gap:10px; align-items:start; font-size:14px; }
.badge { width:32px; height:32px; border-radius:50%; display:grid; place-items:center; font:600 12px var(--mono); color:var(--panel); }
.badge.f { background:var(--bad); } .badge.a { background:var(--ok); }
.phases { display:flex; border-radius:6px; overflow:hidden; height:34px; }
.phases div { display:flex; align-items:center; padding:0 10px; color:var(--panel); font:600 13px var(--body); white-space:nowrap; min-width:max-content; }
.abcde { display:grid; grid-template-columns:repeat(5, minmax(150px, 1fr)); gap:10px; overflow-x:auto; }
.letter { border:1px solid var(--rule); border-radius:8px; padding:12px; display:grid; gap:8px; align-content:start; min-width:0; }
.letter h3 { display:flex; gap:8px; align-items:baseline; }
.letter h3 b { font:600 26px/1 var(--display); color:var(--brand); }
.finding { font-size:13px; display:grid; gap:4px; padding-top:8px; border-top:1px dashed var(--rule); }
.finding .id { font:500 11.5px var(--mono); color:var(--muted); }
.finding.fault .id { color:var(--bad); }
.empty { font-size:13px; color:var(--muted); }
.tablebox { overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th, td { text-align:left; padding:8px 10px 8px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font:500 11.5px var(--mono); text-transform:uppercase; letter-spacing:.8px; color:var(--muted); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
td code, .mono { font:12.5px var(--mono); }
.pill { font:600 11.5px/1 var(--mono); padding:4px 7px; border-radius:4px; color:var(--panel); white-space:nowrap; }
.pill.survey { background:var(--survey); } .pill.triage { background:var(--triage); } .pill.remediate { background:var(--remediate); }
.pill.verify { background:var(--verify); } .pill.hand_over { background:var(--hand_over); }
.out-ok { color:var(--ok); font-weight:600; } .out-rejected { color:var(--bad); font-weight:600; } .out-failed { color:var(--warn); font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:12px; }
.card { border:1px solid var(--rule); border-radius:8px; padding:14px; display:grid; gap:8px; align-content:start; }
.conf { height:6px; background:var(--lane); border-radius:3px; overflow:hidden; } .conf i { display:block; height:100%; background:var(--brand); }
.shots { display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:14px; }
figure { margin:0; display:grid; gap:6px; } figure img { width:100%; border-radius:6px; border:1px solid var(--rule); display:block; }
figcaption { font-size:13px; color:var(--muted); }
.sbar { display:grid; gap:12px; }
.sbar div { display:grid; grid-template-columns:150px 1fr; gap:14px; }
.sbar b { font:600 13px var(--mono); letter-spacing:1px; color:var(--brand); }
.note { border-left:3px solid var(--warn); padding:4px 0 4px 12px; font-size:14px; color:var(--ink); max-width:none; }
@media (max-width: 720px) {
  ol.story li { grid-template-columns:1fr; gap:4px; }
  .figs { grid-template-columns:repeat(2, minmax(0, 1fr)); }
  .sbar div { grid-template-columns:1fr; gap:2px; }
  section { padding:18px 16px; }
}
"""


def page(run):
    r = run["result"]
    m = moments(run)
    rc = recompute(run, m)
    meta = run["run"]
    ok = m["verdict_text"].startswith("CHECKER: RECOVERED")
    sent = [a for a in r["actions"] if a.get("sent")]
    pipeline = next((c for c in run["changes"] if c.get("actor") == "pipeline"), None)
    failover = next((c for c in run["changes"] if c["kind"] == "failover"), None)
    browser = run["browser"]
    fresh_ok = [a for a in browser if a["outcome"] == "ok" and not (a.get("answer") or {}).get("replayed")]
    out = []
    w = out.append
    w(f"<title>Paid Exactly Once</title>\n<style>\n{fonts_css()}\n{CSS}\n</style>\n<main class=\"wrap\">")

    # ----- header and figures -----
    imp = rc.get("impact") or {}
    j = rc.get("journeys") or {}
    w('<section id="summary" data-still="summary" class="stack">')
    w('<div class="head"><div class="row"><span class="tag">Demo, not evidence</span>'
      f'<span class="eyebrow">Browser customer demo · {e(meta.get("describe") or "")} · '
      f'{e(meta.get("model", ""))}</span></div>'
      '<h1>A real browser customer is refused during the incident, retries, and is paid exactly once</h1>'
      '<p class="lede">A real Chromium customer used the real test bank while two faults landed at once. '
      'The frozen incident commander found both, took two allowlisted actions through its guard and handed over. '
      'Then the independent checker read every customer\'s own log, the browser customer included, and gave its verdict.</p>'
      f'<div class="row"><span class="verdict{"" if ok else " no"}">{e(m["verdict_text"])}</span>'
      f'<span class="muted">printed by <code>run.py demo</code>, {secs(m["verdict"], m) if m["verdict"] else ""} after the faults</span></div></div>')
    figs = [(f'{m["alert"] - m["fault"]:.1f} s', "faults to alert (fixed by the demo)"),
            (f'{(m["first_action"] or m["declared"]) - m["alert"]:.1f} s', "alert to first action"),
            (f'{m["declared"] - m["alert"]:.1f} s', "alert to hand over, after a sustained check"),
            (str(len(sent)), "actions sent, " + ", ".join(a["action"] for a in sent)),
            (f'{len(browser)}', f"browser attempts: {sum(a['outcome'] != 'ok' for a in browser)} refused or failed, "
                                f"{len(fresh_ok)} paid, {sum(bool((a.get('answer') or {}).get('replayed')) for a in browser)} already paid"),
            (str(len({row['e2e'] for row in rc.get('ledger_rows', [])})) + " / " + str(len(rc.get("ledger_rows", []))),
             "browser references / ledger rows: one row each")]
    if imp:
        figs.append((str(imp.get("failed_journeys")), "customer journeys that failed during the incident (all 21 customers)"))
    if j:
        figs.append((f'{j.get("ok")}/{j.get("n")}', "journeys ok in the checker's 20 s window"))
    w('<div class="figs">' + "".join(f'<div class="fig"><b>{e(v)}</b><span>{e(t)}</span></div>' for v, t in figs) + "</div>")
    w("</section>")

    # ----- what happened -----
    steps = []
    if m["bank_up"]:
        steps.append((m["bank_up"], "all", "A fresh copy of the bank starts with 20 simulated customers. Ten seconds of healthy warm-up set the checker's baseline."))
    b0 = next((a for a in browser if a["outcome"] == "ok"), None)
    if b0 and b0["t_start"] < m["fault"]:
        steps.append((b0["t_start"], "browser", f"The browser customer pays {sar(b0['amount_minor'])}. It posts, then clears."))
    if pipeline:
        steps.append((pipeline["t"], pipeline["component"], f"Fault 1: the deployment pipeline {describe_change(pipeline)}. Normal payments are now refused."))
    if any(f["type"] == "slow_screening" for f in demo_faults()):
        steps.append((m["fault"] + 0.001, "screening", "Fault 2: fraud screening slows down. Payments wait on it and time out. Nothing records this one in the change feed."))
    for a in browser:
        ans = a.get("answer") or {}
        if m["fault"] <= a["t_start"] < m["declared"] and a["outcome"] != "ok":
            steps.append((a["t_start"], "browser", f"The browser customer tries {sar(a['amount_minor'])} and is told: HTTP {a['status']}, "
                          f"“{ans.get('error', '')}”. Reference {a['end_to_end_id']}."))
    steps.append((m["alert"], "agent", "The alert fires. The incident commander surveys all components in ABCDE order before touching anything."))
    for a in sent:
        steps.append((a["t"], a["target"], f"Action: {a['action']} on {a['target']} {params_text(a)}. "
                      f"The guard allowed it; result: {a.get('detail', '')}."))
    for a in browser:
        ans = a.get("answer") or {}
        if a["t_start"] >= m["fault"] and a["outcome"] == "ok" and a["t_start"] < m["declared"]:
            text = (f"The browser retries {a['end_to_end_id']} and the bank answers “already paid” with the same payment id {ans.get('payment_id')}. It was not paid twice."
                    if ans.get("replayed") else
                    f"The browser retries the same payment ({a['end_to_end_id']}) and is paid: payment {ans.get('payment_id')}.")
            steps.append((a["t_start"], "browser", text))
    steps.append((m["declared"], "agent", "Two clean checks in a row: the incident commander declares recovery and writes its SBAR handover."))
    for a in browser:
        if a["t_start"] >= m["declared"]:
            steps.append((a["t_start"], "browser", f"The browser customer pays {sar(a['amount_minor'])} as normal ({a['end_to_end_id']}), inside the window the checker scores."))
    if m["verdict"]:
        steps.append((m["verdict"], "checker", f"The independent checker scores the 20 s window from its own evidence: {m['verdict_text'].replace('CHECKER: ', '')}."))
    steps.sort(key=lambda x: x[0])

    def chip(comp, text):
        cls = ("cust" if comp == "browser" else "good" if comp in ("agent", "checker") or text.startswith("Action:")
               else "bad" if text.startswith("Fault") else "")
        name = {"browser": "browser customer", "agent": "incident commander", "all": "whole bank", "checker": "checker"}.get(comp, comp)
        return f'<span class="chip {cls}">{e(name)}</span>'
    w('<section id="story" data-still="story" class="stack"><div class="eyebrow">What happened</div>'
      '<h2>The incident, step by step</h2><p class="muted">Times are from the moment the faults landed (T = 0). '
      'The chip says where in the bank each step happened.</p><ol class="story">')
    for t, comp, text in steps:
        w(f'<li><span class="t">{secs(t, m)}</span><span>{chip(comp, text)}</span><span>{e(text)}</span></li>')
    w("</ol></section>")

    # ----- timeline -----
    w('<section id="timeline" data-still="timeline" class="stack"><div class="eyebrow">When and where</div>'
      '<h2>Every lane of the bank, on one clock</h2>'
      '<p class="muted">Each row is one part of the system. Red bands are faults in effect, green is the repair, '
      'and the pale green column is the 20 s window the checker scored. Hover any mark for its detail.</p>')
    w(f'<div class="frame">{timeline_svg(run, m, rc)}</div>')
    w('<div class="legend"><span><i style="background:var(--ok)"></i>paid / ok</span>'
      '<span><i style="background:var(--bad)"></i>refused (4xx) or a fault</span>'
      '<span><i style="background:var(--warn)"></i>failed (5xx or timeout); amber dots are warnings</span>'
      '<span><i style="background:var(--survey)"></i>survey</span><span><i style="background:var(--triage)"></i>triage</span>'
      '<span><i style="background:var(--remediate)"></i>remediate</span><span><i style="background:var(--verify)"></i>verify</span>'
      '<span><i style="background:var(--hand_over)"></i>hand over</span>'
      '<span>◆ change-feed entry (red: the pipeline, green: the agent); ◇ injected with no entry</span></div></section>')

    # ----- where -----
    w('<section id="where" data-still="where" class="stack"><div class="eyebrow">Where</div>'
      '<h2>Where the faults landed and where the agent acted</h2>'
      f'<div class="frame">{where_svg(run, m)}</div><div class="keys">')
    fn = 0
    for f in demo_faults():
        fn += 1
        if f["type"] == "bad_setting" and pipeline:
            text = (f"<b>payments</b> · {secs(pipeline['t'], m)}. The pipeline {e(describe_change(pipeline))}. "
                    "Found under E (Events) from the change feed.")
        elif f["type"] == "slow_screening":
            text = ("<b>screening</b> · T+0.0 s. Fraud screening slows past the 1 s timeout payments allow it. "
                    "No change-feed entry; found under D (Dependencies) from latency.")
        else:
            text = e(f["type"])
        w(f'<div class="key"><span class="badge f">F{fn}</span><span>{text}</span></div>')
    for i, a in enumerate(sent, 1):
        w(f'<div class="key"><span class="badge a">A{i}</span><span><b>{e(a["target"])}</b> · {secs(a["t"], m)}. '
          f'{e(a["action"])} {e(params_text(a))}: {e(a.get("detail") or "")}</span></div>')
    w("</div>")
    if failover:
        w('<p class="muted" style="font-size:13px">Red dashed: payments called the primary fraud screening before the failover. '
          'Green: it calls the standby after. Dotted green: the incident commander\'s two actions, sent through its guard.</p>')
    w("</section>")

    # ----- how the agent worked -----
    trace = r["trace"]
    starts = []
    for ev in trace:
        if not starts or starts[-1][0] != ev["phase"]:
            starts.append((ev["phase"], ev["t"]))
    total = trace[-1]["t"] + 0.6
    w('<section id="agent" data-still="agent" class="stack"><div class="eyebrow">How the agent worked</div>'
      '<h2>Survey everything first, then triage, remediate, verify and hand over</h2>'
      f'<p>The method comes from emergency medicine: with several injuries at once, survey every system in a fixed '
      f'order before treating any of them. Here that order is ABCDE over every part of the bank. '
      f'This run took {r["t_declared"] - r["t_start"]:.1f} s from alert to handover, with {r.get("steps")} calls to the bank.</p>')
    w('<div class="phases">')
    for i, (phase, t0) in enumerate(starts):
        t1 = starts[i + 1][1] if i + 1 < len(starts) else total
        w(f'<div style="flex:{max(t1 - t0, 0.35):.2f};background:var(--{phase})">{PHASE_LABEL[phase]} · {t1 - t0:.1f} s</div>')
    w("</div>")
    findings = next((ev.get("data", {}).get("findings") for ev in trace if ev["name"] == "abcde"), None) or []
    w('<h3>The survey: what each letter found</h3><div class="abcde">')
    for letter, name in LETTERS.items():
        mine = [f for f in findings if f["letter"] == letter]
        w(f'<div class="letter"><h3><b>{letter}</b>{name}</h3>')
        if not mine:
            w('<span class="empty">nothing abnormal</span>')
        for f in mine:
            w(f'<div class="finding {e(f["severity"])}"><span class="id">{e(f["id"])} · {e(f["component"])} · {e(f["severity"])}</span>'
              f'<span>{e(f["text"])}</span></div>')
        w("</div>")
    w("</div>")
    w('<h3>Root causes the model named, and its actions</h3><div class="cards">')
    for c in r["root_causes"]:
        w(f'<div class="card"><div class="row"><span class="chip bad">{e(c["target"])}</span><b>{e(c["class"])}</b>'
          f'<span class="muted mono">confidence {c.get("confidence", 0):.2f}</span></div>'
          f'<div class="conf"><i style="width:{c.get("confidence", 0) * 100:.0f}%"></i></div><p style="font-size:13.5px">{e(c.get("evidence", ""))}</p></div>')
    for a in sent:
        w(f'<div class="card"><div class="row"><span class="chip good">{e(a["target"])}</span><b>{e(a["action"])}</b>'
          f'<span class="muted mono">{secs(a["t"], m)} · guard: {"allowed" if not a.get("refused") else "refused"} · '
          f'{"ok" if a.get("ok") else "failed"}</span></div><p style="font-size:13.5px"><span class="muted">Reason given:</span> {e(a.get("reason", ""))}</p>'
          f'<p style="font-size:13.5px"><span class="muted">What the bank said:</span> {e(a.get("detail") or "")}</p></div>')
    w("</div>")
    if meta.get("model", "").startswith("replay:"):
        w('<p class="note">Keyless replay: the model\'s answers (the root causes above and the handover below) are the '
          'recorded answers of an earlier live run of the same frozen agent, matched by purpose. The survey, the actions, '
          'the checks and every number in the timeline are live from this run, so the replayed text can quote slightly '
          'different figures from the survey above.</p>')
    w('<h3>Every step, with where it looked or acted</h3><div class="tablebox"><table><thead><tr><th class="num">s</th><th>phase</th>'
      '<th>step</th><th>where</th><th>what it saw or did</th></tr></thead><tbody>')
    for ev in trace:
        where = ", ".join(trace_components(ev, run["components"])) or "—"
        w(f'<tr><td class="num mono">{ev["t"]:.1f}</td><td><span class="pill {ev["phase"]}">{PHASE_LABEL[ev["phase"]]}</span></td>'
          f'<td class="mono">{e(ev["name"])}</td><td class="mono">{e(where)}</td><td>{e(ev["summary"])}</td></tr>')
    w("</tbody></table></div></section>")

    # ----- the browser customer -----
    w('<section id="customer" data-still="customer" class="stack"><div class="eyebrow">The browser customer</div>'
      '<h2>What the customer saw, attempt by attempt</h2>'
      '<p class="muted">Customer web-01 pays from account cust-20 through the real gateway. Each attempt is written to '
      'the customers\' own log in the simulated customers\' format, so the checker counts it like any other customer.</p>'
      '<div class="tablebox"><table><thead><tr><th>time</th><th>reference</th><th class="num">amount</th><th>HTTP</th>'
      '<th>told</th><th>payment id</th><th>scored</th></tr></thead><tbody>')
    ws, we = m["window"]
    for a in browser:
        ans = a.get("answer") or {}
        told = ("already paid (replayed)" if ans.get("replayed") else f"paid, {ans.get('status')}") if a["outcome"] == "ok" \
            else ans.get("error", a["outcome"])
        scored = "in window" if ws <= a["t_start"] < we else "—"
        w(f'<tr><td class="mono">{secs(a["t_start"], m)}</td><td class="mono">{e(a["end_to_end_id"])}</td>'
          f'<td class="num">{sar(a["amount_minor"])}</td><td class="mono">{e(str(a["status"]))}</td>'
          f'<td class="out-{a["outcome"]}">{e(told)}</td><td class="mono">{e(ans.get("payment_id") or "—")}</td><td>{scored}</td></tr>')
    w("</tbody></table></div>")
    if rc.get("ledger_rows"):
        w('<h3>The ledger: one row per reference</h3><div class="tablebox"><table><thead><tr><th>reference</th><th>payment id</th>'
          '<th>status now</th><th class="num">amount</th><th>posted at</th></tr></thead><tbody>')
        for row in rc["ledger_rows"]:
            w(f'<tr><td class="mono">{e(row["e2e"])}</td><td class="mono">{e(row["id"])}</td><td>{e(row["status"])}</td>'
              f'<td class="num">{sar(row["amount_minor"])}</td><td class="mono">{secs(row["created_t"], m)}</td></tr>')
        w("</tbody></table></div>")
    shots = sorted(glob.glob(os.path.join(run["dir"], "shots", "*.png")))
    captions = {"warmup-paid": "Warm-up: paid", "incident-refused": "During the incident: refused",
                "retry-not-yet": "Retry: not yet", "retry-paid": "Retry: paid", "replayed": "Retry again: already paid",
                "after-recovery": "After the handover: paying normally", "checker": "The checker's verdict"}
    if shots:
        w('<h3>Frames from the recording</h3><div class="shots">')
        for path in shots:
            key = os.path.basename(path)[3:-4]
            w(f'<figure><img alt="{e(captions.get(key, key))}" src="data:image/png;base64,{b64(path)}">'
              f'<figcaption>{e(os.path.basename(path))} · {e(captions.get(key, key))}</figcaption></figure>')
        w("</div>")
    w("</section>")

    # ----- checker -----
    w('<section id="checker" data-still="checker" class="stack"><div class="eyebrow">Independent verification</div>'
      '<h2>How the checker decided, and that it counted the browser</h2>'
      '<p>The checker never asks the agent. It reads what customers themselves experienced (their own log) and the '
      'ledger, over the 20 s that start 1 s after the agent\'s last step and end 10 s before the verdict, so every '
      'counted journey has finished.</p>')
    if rc.get("error"):
        w(f'<p class="note">Could not recompute the checker numbers: {e(rc["error"])}</p>')
    else:
        bw_ = rc["browser_in_window"]
        rows = [("journeys in the window", f'{j["n"]} ({j["payments"]["n"]} payments, {j["balances"]["n"]} balance reads)'),
                ("succeeded", f'{j["ok"]} ({(j["success_rate"] or 0) * 100:.1f} %; needs 99 %)'),
                ("browser payments counted", f'{len(bw_)}: ' + ", ".join(f'{x_["end_to_end_id"]} {x_["outcome"]}' for x_ in bw_)),
                ("payments posted that customers were told failed", str(rc["ghost"])),
                ("payments customers were told succeeded but are missing", str(rc["lost"])),
                ("payments posted twice", str(rc["duplicates"])),
                ("customer journeys failed since the faults", str(imp.get("failed_journeys"))),
                ("seconds out of SLO since the faults", str(imp.get("breach_seconds")))]
        w('<div class="tablebox"><table><tbody>' + "".join(f'<tr><th style="width:42%">{e(k)}</th><td>{e(v)}</td></tr>' for k, v in rows)
          + "</tbody></table></div>")
        w('<p class="muted" style="font-size:13px">Recomputed after the run from the copied files with the checker\'s own '
          'functions and the demo\'s window; the verdict that counts is the line the demo printed.</p>')
    w("</section>")

    # ----- handover -----
    w('<section id="handover" data-still="handover" class="stack"><div class="eyebrow">Hand over</div>'
      '<h2>The SBAR the incident commander wrote</h2><div class="sbar">')
    for part in ("situation", "background", "assessment", "recommendation"):
        w(f'<div><b>{part.upper()}</b><p>{e(r["sbar"].get(part, ""))}</p></div>')
    w("</div></section>")

    # ----- for the video -----
    caps = [x_ for x_ in run["journey"] if x_["event"] == "caption" and x_.get("step")]
    w('<section id="video" data-still="video" class="stack"><div class="eyebrow">For the presentation video</div>'
      '<h2>Shot list from this recording</h2><p class="muted">Times are offsets into browser-demo.mp4. The stills/ folder '
      'beside this report holds each section above as a 1920-wide PNG.</p><div class="tablebox"><table><thead><tr>'
      '<th class="num">video</th><th>on screen</th><th>say</th></tr></thead><tbody>')
    say = {"1 ·": "A real browser customer on our test bank. Everything is healthy; the payment posts and clears.",
           "2 ·": "Two faults land at once: a bad config push and a slow dependency.",
           "3 ·": "The customer is refused and keeps retrying. Meanwhile the agent surveys every component before it acts.",
           "4 ·": "Paid once. Retrying again returns the same payment: no double payment.",
           "5 ·": "The agent verified recovery over a sustained window and handed over in SBAR form.",
           "6 ·": "The verdict comes from an independent checker that reads the customers' own experience, including this browser."}
    seen = set()
    for c in caps:
        key = (c["step"], c["text"])
        if key in seen:
            continue
        seen.add(key)
        w(f'<tr><td class="num mono">{c["video_s"]:.1f} s</td><td>{e(c["text"])}</td><td class="muted">{e(say.get(c["step"], ""))}</td></tr>')
    w("</tbody></table></div><p class=\"note\">Label any clip from this run “demo, not evidence”. It is one run of a "
      "fault pair the agent was tuned on; the held-out results are what show accuracy.</p></section>")

    # ----- provenance -----
    hb, ha = meta.get("hashes_before", {}), meta.get("hashes_after", {})
    w('<section id="provenance" class="stack"><div class="eyebrow">Provenance</div><h2>What ran</h2>'
      f'<div class="tablebox"><table><tbody><tr><th style="width:28%">command</th><td class="mono">{e(meta.get("command", ""))}</td></tr>'
      f'<tr><th>commit</th><td class="mono">{e(meta.get("commit") or "")} ({e(meta.get("describe") or "")})</td></tr>'
      f'<tr><th>port base</th><td class="mono">{meta.get("port_base")} (browser app on {meta.get("port_base", 0) + 30})</td></tr>'
      f'<tr><th>browser</th><td>Playwright Chromium, one continuous session, locked to 127.0.0.1, video and trace kept</td></tr>'
      '</tbody></table></div><h3>Frozen hashes, before and after the run</h3><div class="tablebox"><table><thead><tr><th>group</th>'
      '<th>before</th><th>after</th><th></th></tr></thead><tbody>')
    for k in hb:
        same = hb.get(k) == ha.get(k)
        w(f'<tr><td class="mono">{e(k)}</td><td class="mono">{e(hb[k][:16])}…</td><td class="mono">{e((ha.get(k) or "")[:16])}…</td>'
          f'<td class="{"out-ok" if same else "out-rejected"}">{"match" if same else "DIFFER"}</td></tr>')
    w("</tbody></table></div><p class=\"muted\" style=\"font-size:13px\">The browser demo adds only files in browser-demo/ "
      "and writes only to the copy's folder under runs/, which git ignores. No gateway route, run.py subcommand or "
      "hashed file changed.</p></section></main>")
    return "\n".join(out)


STILLS_JS = r"""
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULE || "playwright");
const [file, outDir] = process.argv.slice(1);
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1320, height: 1000 }, deviceScaleFactor: 1920 / 1320, colorScheme: "dark" });
  await page.route("**/*", (r) => r.request().url().startsWith("file://") || r.request().url().startsWith("data:") ? r.continue() : r.abort());
  await page.goto("file://" + file);
  await page.evaluate(() => document.fonts.ready);
  for (const el of await page.$$("[data-still]")) {
    const name = await el.getAttribute("data-still");
    await el.screenshot({ path: `${outDir}/${name}.png` });
    console.log(name);
  }
  await page.screenshot({ path: `${outDir}/full-report.png`, fullPage: true });
  await browser.close();
})();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir")
    parser.add_argument("--no-stills", action="store_true")
    args = parser.parse_args()
    run = load(os.path.abspath(args.run_dir))
    body = page(run)
    path = os.path.join(run["dir"], "report.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                     '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                     '</head>\n<body>\n' + body + "\n</body>\n</html>\n")
    # the same page without the document wrapper, for publishing as a claude.ai artifact
    with open(os.path.join(run["dir"], "report-artifact.html"), "w", encoding="utf-8") as handle:
        handle.write('<meta name="claude:viewport-fit-sides" content="cover">\n' + body + "\n")
    print(f"report: {path}")
    if not args.no_stills:
        stills = os.path.join(run["dir"], "stills")
        os.makedirs(stills, exist_ok=True)
        env = {**os.environ, "PLAYWRIGHT_NODE_MODULE": os.environ.get("PLAYWRIGHT_NODE_MODULE",
                                                                       "/opt/node-tools/node_modules/playwright")}
        subprocess.run(["node", "-e", STILLS_JS, path, stills], env=env, check=False)


if __name__ == "__main__":
    main()
