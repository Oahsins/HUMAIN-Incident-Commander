"""A unit terminal's status report, defined once: what unit-sync can read and what it cannot.

A report is the body a terminal posts to cad /mdt, kept as text in field_queue.payload_json:
    {"unit": "M3", "kind": "status" | "heartbeat", "status": "enroute", "incident_id": 512 | null, "t": 1767225600.1}

It cannot be read when any of these holds:
- the text is not JSON, or not a JSON object;
- unit is missing, not a string, or not a unit on the roster (TEST-1 is on the roster);
- kind is not "status" or "heartbeat";
- status is not available, enroute, onscene or outofservice;
- incident_id is neither null (or absent) nor a positive whole number below 2**63 (true and false are not numbers);
- the status and the incident disagree: enroute and onscene need an incident, available and outofservice need none;
- t is missing, or not a finite number (true and false are not numbers).
A time in the future can be read. Other keys are ignored. So every report that can be read can also be applied:
unit-sync never fails on a report this module accepts.

unit-sync parses with parse(); the checker uses unreadable(). Errors name the field, never its value.
"""

import json
import math
from collections import namedtuple

from targets.dispatch import area

KINDS = ("status", "heartbeat")
STATUSES = ("available", "enroute", "onscene", "outofservice")
MAX_ID = 2 ** 63   # the largest whole number the database can store, plus one

Report = namedtuple("Report", "unit kind status incident_id t")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse(payload_json):
    """The report in payload_json as a Report. Raises ValueError("<field>: <reason>") when it cannot be read."""
    try:
        body = json.loads(payload_json)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("payload: not valid JSON") from None
    if not isinstance(body, dict):
        raise ValueError("payload: not a JSON object") from None
    unit = body.get("unit")
    if not isinstance(unit, str) or unit not in area.ROSTER_IDS:
        raise ValueError("unit: missing or not on the roster") from None
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("kind: not status or heartbeat") from None
    status = body.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("status: not a known unit status") from None
    incident_id = body.get("incident_id")
    if incident_id is not None and not (isinstance(incident_id, int) and not isinstance(incident_id, bool)
                                        and 0 < incident_id < MAX_ID):
        raise ValueError("incident_id: not null or a positive whole number") from None
    if (incident_id is None) != (status in ("available", "outofservice")):
        raise ValueError("incident_id: does not match the status") from None
    t = body.get("t")
    try:
        t = float(t) if _number(t) else None
    except OverflowError:   # a whole number too large for a float
        t = None
    if t is None or not math.isfinite(t):
        raise ValueError("t: missing or not a finite number") from None
    return Report(unit, kind, status, incident_id, t)


def unreadable(payload_json):
    """True exactly when parse() would raise."""
    try:
        parse(payload_json)
    except ValueError:
        return True
    return False


def build(unit, kind, status, incident_id, t):
    """The JSON body a terminal sends (crews and the probe use it)."""
    return {"unit": unit, "kind": kind, "status": status, "incident_id": incident_id, "t": t}
