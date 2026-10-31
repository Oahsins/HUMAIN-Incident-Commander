"""What unit-sync can and cannot read: the one definition in targets/dispatch/fieldmsg.py (docs/DISPATCH.md,
unreadable field reports).

Each rule is broken one field at a time. The error names the field and never a value: the marker ZZMARK sits
in every field it can, and must not show even in the printed traceback. parse() and unreadable() agree on every
case, and on every mix of good and bad fields, which the rules, written out again here, decide. Every report
that can be read can be bound into cad-db, and every report a crew or the probe builds, for every unit on the
roster, every kind and every status, can be read, a far-future time included.
"""

import itertools
import json
import math
import sqlite3
import sys
import time
import traceback

import pytest

from targets.dispatch import area, fieldmsg

MARK = "ZZMARK"
T = 1767225600.125
GOOD = {"unit": "M3", "kind": "status", "status": "enroute", "incident_id": 512, "t": T}
FIELDS = tuple(GOOD)
KINDS = ("status", "heartbeat")
STATUSES = ("available", "enroute", "onscene", "outofservice")
NO_INCIDENT = ("available", "outofservice")   # these carry no incident; enroute and onscene need one
MISSING = object()                            # a field left out of the report
DEEP = "[" * 100_000 + "]" * 100_000          # nested deeper than any JSON reader follows
FAR_FUTURE = (time.time() + 10 * 365 * 86400.0, 253402300799.0, 32503680000, 1e300)
# Python reads a whole number of more than 4,300 digits as an error in the JSON text, unless the limit is lifted.
LONG_NUMBER_FIELD = "payload" if 0 < getattr(sys, "get_int_max_str_digits", lambda: 0)() < 5000 else "t"


def report(**fields):
    """GOOD as JSON text with some fields changed; a field set to MISSING is left out."""
    body = {**GOOD, **fields}
    return json.dumps({key: value for key, value in body.items() if value is not MISSING})


def raw(field, text):
    """GOOD as JSON text with one field's value written as raw JSON text (NaN, 1e999, deep nesting)."""
    parts = (f'"{key}": {text if key == field else json.dumps(value)}' for key, value in GOOD.items())
    return "{" + ", ".join(parts) + "}"


def broken(field, **values):
    """One case per value: GOOD with only that field changed."""
    return [(f"{field} {label}", report(**{field: value}), field) for label, value in values.items()]


def readable(label, payload=None, **fields):
    """A case parse() must read: GOOD with some fields changed, or the payload given, and the Report it gives."""
    body = {**GOOD, **fields}
    incident_id = None if body["incident_id"] is MISSING else body["incident_id"]
    want = fieldmsg.Report(body["unit"], body["kind"], body["status"], incident_id, float(body["t"]))
    return label, report(**fields) if payload is None else payload, want


UNREADABLE = [   # (label, payload_json, the field the error must name)
    ("payload not JSON", "{not json", "payload"),
    ("payload empty", "", "payload"),
    ("payload cut short", report()[:-1], "payload"),
    ("payload cut short after the marker", '{"unit": "ZZMARK", "kind": "ZZM', "payload"),
    ("payload the bare marker", MARK, "payload"),
    ("payload None", None, "payload"),
    ("payload bytes that are not UTF-8", b"\x80\xff{}", "payload"),
    ("payload nested too deep", DEEP, "payload"),
    ("payload a field nested too deep", raw("unit", DEEP), "payload"),
    ("payload a number too long to read", raw("t", "9" * 5000), LONG_NUMBER_FIELD),
    ("payload a list", "[]", "payload"),
    ("payload a list holding a report", f"[{report()}]", "payload"),
    ("payload a number", "512", "payload"),
    ("payload a string", json.dumps(MARK), "payload"),
    ("payload null", "null", "payload"),
    ("payload true", "true", "payload"),
    *broken("unit", missing=MISSING, null=None, number=3, true=True, list=["M3"], object={"id": "M3"},
            off_the_roster="M11", lower_case="m3", padded="M3 ", empty="", a_station="S1",
            another_test_unit="TEST-2", marker=MARK),
    ("unit nested lists", raw("unit", "[" * 50 + "]" * 50), "unit"),
    *broken("kind", missing=MISSING, null=None, number=1, true=True, capitalised="Status", upper_case="STATUS",
            plural="heartbeats", empty="", list=["status"], marker=MARK),
    *broken("status", missing=MISSING, null=None, number=1, true=True, spaced="en route", capitalised="Available",
            closed="closed", cleared="cleared", dispatched="dispatched", empty="", list=["enroute"], marker=MARK),
    *broken("incident_id", true=True, false=False, zero=0, negative=-1, lowest=-2**63, two_to_the_63=2**63,
            two_to_the_64=2**64, huge=10**30, whole_float=5.0, fraction=5.5, text="512", marker=MARK,
            list=[512], object={"id": 512}),
    ("incident_id NaN", raw("incident_id", "NaN"), "incident_id"),
    ("incident_id Infinity", raw("incident_id", "Infinity"), "incident_id"),
    ("incident_id 1e999", raw("incident_id", "1e999"), "incident_id"),
    # the status and the incident must agree
    ("incident_id enroute with null", report(incident_id=None), "incident_id"),
    ("incident_id enroute with none given", report(incident_id=MISSING), "incident_id"),
    ("incident_id onscene with null", report(status="onscene", incident_id=None), "incident_id"),
    ("incident_id heartbeat onscene with none given",
     report(kind="heartbeat", status="onscene", incident_id=MISSING), "incident_id"),
    ("incident_id available with one", report(status="available"), "incident_id"),
    ("incident_id outofservice with one", report(status="outofservice"), "incident_id"),
    ("incident_id heartbeat available with one", report(kind="heartbeat", status="available"), "incident_id"),
    ("incident_id available with false", report(status="available", incident_id=False), "incident_id"),
    ("incident_id available with zero", report(status="available", incident_id=0), "incident_id"),
    *broken("t", missing=MISSING, null=None, true=True, false=False, text=str(T), marker=MARK, list=[T],
            object={"t": T}, huge=10**400, huge_negative=-10**400),
    ("t NaN", raw("t", "NaN"), "t"),
    ("t Infinity", raw("t", "Infinity"), "t"),
    ("t -Infinity", raw("t", "-Infinity"), "t"),
    ("t 1e999", raw("t", "1e999"), "t"),
    ("t -1e999", raw("t", "-1e999"), "t"),
]

MARKED = [   # the marker everywhere it can be: no error may repeat it
    *[(f"{field} marker in a list", report(**{field: [MARK]}), field) for field in FIELDS],
    *[(f"{field} marker in an object", report(**{field: {MARK: MARK}}), field) for field in FIELDS],
    ("unit marker in every field", json.dumps({**dict.fromkeys(FIELDS, MARK), MARK: MARK}), "unit"),
    ("unit marker only in other keys", json.dumps({MARK: MARK, "note": MARK}), "unit"),
]

READABLE = [
    readable("the example"),
    readable("a heartbeat", kind="heartbeat"),
    readable("on scene", status="onscene"),
    readable("available with null", status="available", incident_id=None),
    readable("available with no incident given", status="available", incident_id=MISSING),
    readable("out of service", kind="heartbeat", status="outofservice", incident_id=None),
    readable("the test unit", unit=area.TEST_UNIT),
    readable("the smallest incident id", incident_id=1),
    readable("the largest incident id cad-db stores", incident_id=2**63 - 1),
    readable("a whole-number time", t=1767225600),
    readable("time zero", t=0),
    readable("a time long past", t=-5.5),
    readable("a far-future time", t=253402300799.0),
    readable("the largest float time", t=sys.float_info.max),
    readable("a whole-number time a float still holds", t=10**300),
    readable("extra keys holding the marker", note=MARK, **{MARK: [MARK]}),
    readable("spaces around", payload="  " + report() + "\n"),
    readable("keys in another order", payload=json.dumps(dict(reversed(GOOD.items())))),
]

POOLS = (   # good and bad values for each field, in FIELDS order; every mix of them is tried
    (MISSING, None, 7, MARK, "M3", area.TEST_UNIT),
    (MISSING, True, MARK, "status", "heartbeat"),
    (MISSING, MARK, "available", "enroute", "onscene", "outofservice"),
    (MISSING, None, True, 0, 5.0, 2**63, MARK, 512, 2**63 - 1),
    (MISSING, None, True, MARK, float("nan"), float("inf"), 10**400, T, 32503680000, 0),
)


def error_of(payload):
    """What parse() raises on payload, or None when it reads it."""
    try:
        fieldmsg.parse(payload)
    except Exception as exc:   # anything but a ValueError fails the checks below
        return exc
    return None


def bound(found):
    """A report's fields bound into SQLite as unit-sync binds them, and read back."""
    conn = sqlite3.connect(":memory:")
    try:
        return conn.execute("SELECT ?, ?, ?, ?, ?", tuple(found)).fetchone()
    finally:
        conn.close()


def finite(number):
    try:
        return math.isfinite(number)
    except OverflowError:   # a whole number too large for a float
        return False


def rules_broken(body):
    """The fields that break the rules, written out again from docs/DISPATCH.md: none when readable."""
    unit, kind, status, incident_id, t = (body.get(field) for field in FIELDS)
    bad = set()
    if not (isinstance(unit, str) and unit in area.ROSTER_IDS):
        bad.add("unit")
    if kind not in KINDS:
        bad.add("kind")
    if status not in STATUSES:
        bad.add("status")
    elif not (incident_id is None or (type(incident_id) is int and 0 < incident_id < 2**63)):
        bad.add("incident_id")
    elif (incident_id is None) != (status in NO_INCIDENT):
        bad.add("incident_id")
    if not (type(t) in (int, float) and finite(t)):
        bad.add("t")
    return bad


@pytest.mark.parametrize("payload,field", [case[1:] for case in UNREADABLE + MARKED],
                         ids=[case[0] for case in UNREADABLE + MARKED])
def test_an_unreadable_report_is_refused_naming_the_field_never_a_value(payload, field):
    exc = error_of(payload)
    assert type(exc) is ValueError, repr(exc)
    assert str(exc).startswith(f"{field}: "), str(exc)
    assert exc.__cause__ is None and exc.__suppress_context__   # raised from None: no inner error is printed
    printed = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert MARK not in printed and MARK not in repr(exc)
    assert fieldmsg.unreadable(payload) is True


@pytest.mark.parametrize("payload,want", [case[1:] for case in READABLE], ids=[case[0] for case in READABLE])
def test_a_readable_report_is_read_and_can_be_stored(payload, want):
    found = fieldmsg.parse(payload)
    assert found == want
    assert type(found.t) is float and (found.incident_id is None or type(found.incident_id) is int)
    assert bound(found) == tuple(found)
    assert fieldmsg.unreadable(payload) is False


def test_parse_and_unreadable_agree_with_the_rules_on_every_mix_of_fields():
    readable_mixes = 0
    for values in itertools.product(*POOLS):
        payload = json.dumps({field: value for field, value in zip(FIELDS, values) if value is not MISSING})
        bad, exc = rules_broken(json.loads(payload)), error_of(payload)
        assert fieldmsg.unreadable(payload) is bool(bad), payload
        if bad:
            assert type(exc) is ValueError and str(exc).split(":")[0] in bad, (payload, repr(exc))
            assert MARK not in str(exc), payload
        else:
            assert exc is None, (payload, repr(exc))
            assert bound(fieldmsg.parse(payload)) == tuple(fieldmsg.parse(payload)), payload
            readable_mixes += 1
    assert readable_mixes == 96   # 2 units x 2 kinds x 8 agreeing status and incident pairs x 3 times


def test_every_report_a_crew_or_the_probe_builds_can_be_read():
    """Crews (people.py) and the probe (spec.py) build reports with fieldmsg.build and post them as JSON: every
    unit on the roster, TEST-1 included, every kind and status, now and far in the future."""
    roster = sorted(area.ROSTER_IDS)
    assert len(roster) == 21 and area.TEST_UNIT in roster
    for unit, kind, status in itertools.product(roster, KINDS, STATUSES):
        incident_id = None if status in NO_INCIDENT else 4096
        for t in (time.time(), *FAR_FUTURE):
            body = fieldmsg.build(unit, kind, status, incident_id, t)
            assert sorted(body) == sorted(FIELDS), body
            found = fieldmsg.parse(json.dumps(body))
            assert found == (unit, kind, status, incident_id, float(t)) and type(found.t) is float, body
            assert not fieldmsg.unreadable(json.dumps(body))
