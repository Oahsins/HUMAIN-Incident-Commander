"""Check this laptop before a run; never print keys or send an incident to a model.

The normal check needs only Python's standard library. With --live, one short
model call also checks the selected provider's connection and credentials.
"""

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
EVAL_PORTS = tuple(base + offset for base in (8100, 8200, 8300) for offset in range(10))
MIN_FREE_BYTES = 2 * 1024 ** 3
KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _packages(root):
    """Read package names without importing packages that may be missing."""
    rows = []
    files = sorted(root.glob("requirements*.txt"))
    if not files:
        return [("FAIL", "Packages", "No requirements files found.")]
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            rows.append(("FAIL", "Packages", "Cannot read " + path.name + "."))
            continue
        for line in lines:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~].*)?", line)
            if not match:
                rows.append(("FAIL", "Packages", "Unsupported requirement in " + path.name + "."))
                continue
            name = match.group(1)
            try:
                importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                rows.append(("FAIL", "Package " + name, "Missing; install " + path.name + "."))
            else:
                rows.append(("PASS", "Package " + name, "Installed."))
    return rows


def _model(root):
    """Match eval's model priority, with the default used for the pre-pilot key check."""
    override = os.environ.get("IC_MODEL", "").strip()
    rows = []
    try:
        config = json.loads((root / "configs" / "models.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError
    except (OSError, ValueError):
        return None, [("FAIL", "Model settings", "Cannot read configs/models.json.")]
    bulk = config.get("bulk")
    model = override or bulk or config.get("default")
    if not override:
        detail = "IC_MODEL unset; evaluation uses the bulk model."
        if not bulk:
            detail = "IC_MODEL unset and bulk is null; AI evaluation will refuse to start. Checking the default provider."
        rows.append(("WARN", "Model selection", detail))
    if not isinstance(model, str) or ":" not in model or not model.partition(":")[2].strip():
        return None, rows + [("FAIL", "Model selection", "Expected provider:model.")]
    provider = model.partition(":")[0]
    if provider in KEY_NAMES:
        name = KEY_NAMES[provider]
        present = bool(os.environ.get(name, "").strip())
        rows.append(("PASS" if present else "FAIL", "Provider key", name + (" is set." if present else " is missing in this process.")))
    elif provider in ("lmstudio", "replay", "mock"):
        rows.append(("PASS", "Provider key", "This provider needs no API key."))
    else:
        rows.append(("FAIL", "Provider key", "Unsupported model provider."))
    return model, rows


def _busy_ports(ports):
    """Bind each loopback port briefly, without starting any services."""
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                busy.append(port)
    return busy


def _lmstudio():
    """Ask the local server only; do not use an HTTP proxy or an API key."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:1234/v1/models", timeout=1.0) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _live(model):
    # Import only for this explicit check. Do not expose a provider's error body.
    try:
        llm = importlib.import_module("ic.llm")
        result = llm.complete(
            [{"role": "user", "content": "Reply with the single word OK."}],
            model=model, max_tokens=1000, purpose="preflight", retries=0,
        )
        if isinstance(result, dict) and result.get("text", "").strip() == "OK":
            return "PASS", "Live model", "One call returned OK."
        return "FAIL", "Live model", "One call did not return the requested word."
    except Exception:
        return "FAIL", "Live model", "One call failed; check provider access, key and model. Error details withheld."


def main(argv=None) -> int:
    """Print the checks and return 1 for a failure, or 0 for passes and warnings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="make one short model call")
    args = parser.parse_args(argv)
    rows = [("PASS" if sys.version_info >= (3, 11) else "FAIL", "Python", "Python 3.11 or later required.")]
    rows.extend(_packages(ROOT))
    model, model_rows = _model(ROOT)
    rows.extend(model_rows)
    busy = _busy_ports(EVAL_PORTS)
    port_detail = ("Unavailable: " + ", ".join(map(str, busy)) if busy else
                   "All 30 ports are free (8100-8109, 8200-8209, 8300-8309).")
    rows.append(("FAIL" if busy else "PASS", "Evaluation ports", port_detail))
    try:
        free = shutil.disk_usage(ROOT).free
        rows.append(("PASS" if free >= MIN_FREE_BYTES else "FAIL", "Free disk", f"{free / 1024 ** 3:.1f} GiB free; at least 2 GiB required."))
    except OSError:
        rows.append(("FAIL", "Free disk", "Cannot measure free space."))
    local_model_up = _lmstudio()
    local_detail = ("Local server is answering." if local_model_up else
                    "Local server is not answering (optional).")
    rows.append(("PASS" if local_model_up else "WARN", "LM Studio", local_detail))
    if args.live:
        if any(row[0] == "FAIL" for row in rows):
            rows.append(("FAIL", "Live model", "Skipped because a prerequisite failed; no model call made."))
        else:
            rows.append(_live(model))
    print(f"{'STATUS':<7} {'CHECK':<23} DETAIL")
    print("-" * 78)
    for status, check, detail in rows:
        print(f"{status:<7} {check:<23} {detail}")
    failures = sum(row[0] == "FAIL" for row in rows)
    warnings = sum(row[0] == "WARN" for row in rows)
    print(f"\nPreflight: {failures} failed, {warnings} warnings.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
