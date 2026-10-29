"""Fraud screening release 4.1.1: a maintenance release with no change in behaviour.

Used as a harmless background change: a deploy that a careful operator should
notice and then rule out.
"""

from targets.bank.releases.screening.v4_1 import Release as Previous


class Release(Previous):
    pass
