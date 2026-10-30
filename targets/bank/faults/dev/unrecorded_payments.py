"""Practice fault: a payments release tells customers a payment went through but never writes it (root cause: bad_release).

The new release answers about half of all payments with "posted" and a payment
id, exactly as a healthy release does, but skips the ledger write for them:
nothing errors and no log line shows the loss. The money never leaves the
account, the payment never reaches clearing, and reading it back by its id
(GET /payment/<id>) answers 404. The checker counts each one as a lost payment.
The deploy appears in the change log. The right fix is to roll back payments.

The release's code is _unrecorded_release.py next to this file. It is deployed
through Control with module_path under its own label, so no label resolves to
it unless this fault deployed it: bad_update and every other case that deploys
a release by label run exactly as before.

params: {"actor": <optional; default a random actor from the pool>}
"""

import os
import time

from targets.bank.faults.common import actor

TYPE = "unrecorded_payments"
CLASSES = ["bad_release"]
RELEASE = "1.3.1"
MODULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_unrecorded_release.py")


def inject(control, params, rng):
    healthy = control.deploy("payments", RELEASE, module_path=MODULE, actor=actor(params, rng))
    return {"type": TYPE, "target": "payments", "class": "bad_release",
            "detail": {"release": RELEASE, "answering": healthy}, "t": time.time()}
