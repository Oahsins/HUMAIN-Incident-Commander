"""Test customers: make payments and check balances nonstop, and keep their own log.

Each customer owns one account and pays beneficiaries at other banks. A payment
that times out or fails with a server error is retried with the same
end-to-end id, as banking apps do; a rejection (4xx) is not retried. Every
payment and balance check goes into customers.jsonl, which only the
independent checker reads. The agent never sees it.

Run: python -m targets.bank.customers --data runs/bank-8100 --port 8100 --seed 0
"""

import argparse
import json
import os
import random
import threading
import time

from ic.kit import net

BANKS = ["BANK-A", "BANK-B", "BANK-C", "BANK-D"]


class Log:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, record):
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")


def pay(base, body, attempts=3, attempt_timeout=3.0, deadline_s=8.0):
    """One payment as a customer's app makes it. Returns (outcome, status, payment_id, attempts_used)."""
    started = time.time()
    status, payment_id = None, None
    for attempt in range(1, attempts + 1):
        try:
            status, answer = net.post(f"{base}/pay", body, timeout=attempt_timeout)
            return "ok", status, answer.get("payment_id"), attempt
        except net.CallError as exc:
            status = exc.status if exc.kind == "http" else exc.kind
            if exc.kind == "http" and exc.status < 500:
                return "rejected", status, None, attempt
        if time.time() - started > deadline_s:
            break
        time.sleep(0.3 * attempt)
    return "failed", status, payment_id, attempt


def customer_loop(name, base, log, rng, stop):
    seq = 0
    while not stop.is_set():
        seq += 1
        body = {"from_acct": name, "amount_minor": rng.randint(1_000, 50_000), "currency": "SAR",
                "beneficiary_bank": rng.choice(BANKS), "beneficiary_acct": f"ben-{rng.randint(1, 999):03d}",
                "end_to_end_id": f"{name}-{seq:06d}"}
        t0 = time.time()
        outcome, status, payment_id, used = pay(base, body)
        log.write({"kind": "payment", "t_start": round(t0, 3), "t_end": round(time.time(), 3), "customer": name,
                   "end_to_end_id": body["end_to_end_id"], "amount_minor": body["amount_minor"],
                   "outcome": outcome, "status": status, "payment_id": payment_id, "attempts": used})
        if rng.random() < 0.3:
            time.sleep(rng.uniform(0.6, 1.2))
            t1 = time.time()
            try:
                _, answer = net.get(f"{base}/balance/{name}", timeout=2.0)
                log.write({"kind": "balance", "t": round(t1, 3), "t_end": round(time.time(), 3), "customer": name,
                           "observed_minor": answer.get("balance_minor"), "ok": True})
            except net.CallError as exc:
                log.write({"kind": "balance", "t": round(t1, 3), "t_end": round(time.time(), 3), "customer": name,
                           "observed_minor": None, "ok": False, "status": exc.status or exc.kind})
        stop.wait(rng.uniform(1.0, 3.0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--port", type=int, required=True, help="gateway port")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--customers", type=int, default=20)
    args = parser.parse_args()
    log = Log(os.path.join(args.data, "customers.jsonl"))
    base = f"http://127.0.0.1:{args.port}"
    stop = threading.Event()
    threads = []
    for i in range(args.customers):
        rng = random.Random(args.seed * 1000 + i)
        t = threading.Thread(target=customer_loop, args=(f"cust-{i + 1:02d}", base, log, rng, stop), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.05)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
