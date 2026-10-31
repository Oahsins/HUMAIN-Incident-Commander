"""The area the dispatch centre covers: stations, units, kinds of emergency, numbers and distances.

Everything here is made up. Phone numbers have the shape 0PP-555-01NN: no North
American area code starts with 0, and 555-01NN is set aside for fiction. The
map is a 20 x 20 km grid with five stations; each has two medic units and two
engines. TEST-1 is the test caller's unit: it sits at station TEST (0, 0), and
no crew ever staffs it.
"""

import hashlib
import math
import re

GRID_KM = 20.0

STATIONS = {"S1": (4.0, 4.0), "S2": (16.0, 4.0), "S3": (10.0, 10.0), "S4": (4.0, 16.0), "S5": (16.0, 16.0)}
TEST_STATION = "TEST"
TEST_XY = (0.0, 0.0)
TEST_UNIT = "TEST-1"


def _roster():
    """Roster order is station by station: M1, M2, E1, E2, M3, M4, E3, E4, ..."""
    units = []
    for k in range(1, 6):
        station = f"S{k}"
        for unit_type, prefix in (("medic", "M"), ("engine", "E")):
            for n in (2 * k - 1, 2 * k):
                units.append({"id": f"{prefix}{n}", "type": unit_type, "station": station})
    return units


UNITS = _roster()                                   # the 20 real units, in roster order
UNIT_IDS = tuple(u["id"] for u in UNITS)
ROSTER_IDS = frozenset(UNIT_IDS + (TEST_UNIT,))     # every unit CAD knows, TEST-1 included
UNIT_BY_ID = {u["id"]: u for u in UNITS}
UNIT_BY_ID[TEST_UNIT] = {"id": TEST_UNIT, "type": "test", "station": TEST_STATION}

# code: priority (1 is the most urgent), the unit type sent first, its weight in everyday calls, and
# three made-up things a caller says. What callers say is kept only in CAD's incident record.
NATURES = {
    "cardiac": {"priority": 1, "unit_type": "medic", "weight": 0.15, "narratives": (
        "my father collapsed in the kitchen and is not breathing normally",
        "a man fell down in the shop and nobody can feel a pulse",
        "my wife has crushing pain in her chest and is sweating")},
    "breathing": {"priority": 1, "unit_type": "medic", "weight": 0.15, "narratives": (
        "my son is wheezing and cannot finish a sentence",
        "my neighbour is gasping for air and her lips look blue",
        "an older man is struggling to breathe after climbing the stairs")},
    "fall": {"priority": 2, "unit_type": "medic", "weight": 0.20, "narratives": (
        "my grandmother fell on the stairs and cannot get up",
        "a worker fell from a ladder and hurt his leg",
        "a woman slipped on the wet floor and hit her head")},
    "collision": {"priority": 2, "unit_type": "medic", "weight": 0.10, "narratives": (
        "two cars crashed at the junction and one driver is hurt",
        "a car hit a cyclist on the main road",
        "a van went off the road into a wall")},
    "structure_fire": {"priority": 1, "unit_type": "engine", "weight": 0.10, "narratives": (
        "there is smoke coming from the flat upstairs",
        "the kitchen of the restaurant next door is on fire",
        "flames are coming out of a garage roof")},
    "vehicle_fire": {"priority": 2, "unit_type": "engine", "weight": 0.10, "narratives": (
        "a parked car is burning in the car park",
        "smoke is pouring from under the bonnet of a lorry",
        "a scooter caught fire outside the shops")},
    "alarm": {"priority": 3, "unit_type": "engine", "weight": 0.20, "narratives": (
        "the fire alarm in our office building keeps ringing",
        "a smoke alarm is going off in the empty house next door",
        "the alarm panel at the school is sounding")},
    "test": {"priority": 3, "unit_type": "test", "weight": 0.0, "narratives": ("",)},
}
REAL_NATURES = tuple(code for code, n in NATURES.items() if code != "test")
MEDICAL_NATURES = tuple(code for code in REAL_NATURES if NATURES[code]["unit_type"] == "medic")
FIRE_NATURES = tuple(code for code in REAL_NATURES if NATURES[code]["unit_type"] == "engine")

# ----- numbers -----

ANI_PATTERN = re.compile(r"0[0-9]{2}-555-01[0-9]{2}")   # whole string, ASCII digits only (fullmatch)
NORMAL_PP = range(10, 40)           # 3,000 numbers, used in turn by the everyday callers
SURGE_PP_START = 40                 # five blocks of ten PP values (1,000 numbers each), one per helper
SURGE_BLOCKS = 5
TEST_PP = 99                        # the test caller: 099-555-0100 to 099-555-0199


def number(pp, nn):
    return f"0{pp:02d}-555-01{nn:02d}"


def normal_number(index):
    """The everyday callers' numbers, in turn: index 0 is 010-555-0100."""
    index %= len(NORMAL_PP) * 100
    return number(NORMAL_PP.start + index // 100, index % 100)


def surge_number(block, index):
    """Number `index` of a burst helper's block (0-4); 1,000 numbers per block, in turn."""
    index %= 1000
    return number(SURGE_PP_START + 10 * block + index // 100, index % 100)


def test_number(seq):
    return number(TEST_PP, seq % 100)


def valid_number(ani):
    return isinstance(ani, str) and ANI_PATTERN.fullmatch(ani) is not None


def is_test_number(ani):
    return isinstance(ani, str) and ani.startswith(f"0{TEST_PP:02d}-")


def known_number(ani):
    """Does the phone company have records for this number: is it in one of the three pools?"""
    if not valid_number(ani):
        return False
    pp = int(ani[1:3])
    return pp in NORMAL_PP or SURGE_PP_START <= pp < SURGE_PP_START + 10 * SURGE_BLOCKS or pp == TEST_PP


# ----- places -----

def subscriber_location(ani):
    """Where the phone company's records put a number: fixed for each number, (x, y) in km on the grid."""
    if is_test_number(ani):
        return TEST_XY
    digest = hashlib.sha256(ani.encode("utf-8")).digest()
    x = 0.5 + 19.0 * int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    y = 0.5 + 19.0 * int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF
    return (round(x, 3), round(y, 3))


def station_xy(station):
    return TEST_XY if station == TEST_STATION else STATIONS[station]


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def drive_s(km):
    """Field clock: driving time in simulated seconds for a distance in km."""
    return min(1.8, 0.3 + 0.06 * km)
