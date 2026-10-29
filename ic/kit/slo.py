"""Customer-impact arithmetic that every system's checker shares (CONTRACT.md sections 10 and 11).

A checker splits the time since the first injection into 5 s buckets, counted from since_t (the last one
may be shorter), and judges each bucket's journeys against the SLO. These helpers turn those judgements
into the generic impact keys the evaluation reads.
"""

import math

BUCKET_S = 5.0


def time_to_mitigate(bucket_met, span_s, bucket_s=BUCKET_S):
    """(seconds, censored): from the start of the span to the start of the first bucket after which every
    bucket up to the end of the span meets the SLO.

    bucket_met maps a bucket's index (bucket 0 starts at the start of the span) to True when its journeys
    met the SLO and False when they missed it. A bucket with no journeys keeps the state of the bucket
    before it, so a quiet moment never counts as mitigation; before the first journeys it counts as met.
    It is 0 when no bucket missed the SLO. When the last bucket still misses it, there is no such bucket:
    censored is True and the seconds are the whole span.
    """
    span_s = max(0.0, float(span_s))
    met, last_missed = True, None
    for index in range(max(1, math.ceil(span_s / bucket_s))):
        met = bucket_met.get(index, met)
        if not met:
            last_missed = index
    if last_missed is None:
        return 0.0, False
    start = (last_missed + 1) * bucket_s
    if start >= span_s:
        return round(span_s, 1), True
    return round(start, 1), False
