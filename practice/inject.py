"""Inject a dispatch practice case: `run.py inject` that can also find the practice faults in this folder.

    python practice/inject.py --system dispatch --port-base 9400 \
        --scenario scenarios/dev/dispatch-practice.jsonl --id dsp-01

Why this folder. Dispatch's own faults folder, targets/dispatch/faults, belongs to Session A, who wrote
the sealed dispatch exam, and the repository keeps nothing there. Everything under targets/dispatch is
also pinned by its git tree id (DECISIONS.md, dispatch row 4). So the three public practice cases,
added on 31 Oct and not part of any exam, keep their fault types here, in practice/<system>/.

What this wrapper changes. For this one command it adds practice/<system>/ to the fault search path,
for fault types named practice_*, and then runs `run.py inject` unchanged. ic/inject.py and run.py are
frozen and stay byte for byte as they are; every other fault type loads exactly as before. Practice
faults never load with --sealed.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ic import inject  # noqa: E402

FROZEN_LOAD = inject.load


def practice_path(system, fault_type):
    return os.path.join(HERE, system, f"{fault_type}.py")


def load(system, fault_type, allow_sealed=False):
    """A practice fault from practice/<system>/, else the frozen loader's answer."""
    path = practice_path(system, fault_type)
    if not allow_sealed and fault_type.startswith("practice_") and os.path.exists(path):
        spec = importlib.util.spec_from_file_location(f"_practice_{system}_{fault_type}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return FROZEN_LOAD(system, fault_type, allow_sealed)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--sealed" in argv:
        raise SystemExit("practice faults never run with --sealed; use python run.py inject")
    import run
    inject.load = load
    try:
        return run.main(["inject", *argv])
    finally:
        inject.load = FROZEN_LOAD


if __name__ == "__main__":
    sys.exit(main())
