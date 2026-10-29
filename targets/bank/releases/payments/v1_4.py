"""Payments release 1.4: previews the new tiered tariff on every payment.

The tariff is computed but not yet charged (a "dark launch"). The release has
a bug: the top tier's divisor is zero, so every payment over 300.00 SAR fails
with ZeroDivisionError, an HTTP 500. Rolling back to 1.3 fixes it. Used by the
`bad_update` practice fault.
"""

from targets.bank.releases.payments.v1_3 import Release as Base

TIERS = [(10_000, None), (30_000, 2000), (10**12, 0)]   # (upper bound in halalas, fee divisor)


class Release(Base):
    def validate(self, body):
        amount = super().validate(body)
        self.preview_fee(amount)
        return amount

    def preview_fee(self, amount):
        for upper, divisor in TIERS:
            if amount <= upper:
                return 0 if divisor is None else amount // divisor
        return 0
