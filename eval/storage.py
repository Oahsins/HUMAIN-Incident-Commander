"""Keep complete results immutable, and make interrupted runs safe to resume."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time

import psutil

RETRY_OUTCOMES = {"api_error", "harness_timeout"}


def safe_name(value):
    """A run or case name is one directory name, never a path."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("run, case and arm names must contain only letters, digits, dots, underscores or hyphens")
    if value.endswith((".", " ")) or value.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}:
        raise ValueError("name is reserved on Windows")
    return value


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path, value):
    """Publish a JSON file only after its complete contents reach disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_jsonl(path):
    """A stopped process may leave one incomplete final audit line."""
    if not path or not Path(path).exists():
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            if i != len(lines) - 1:
                raise ValueError(f"invalid evidence line {i + 1} in {Path(path).name}") from None
    return records


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@contextmanager
def run_lock(run_dir):
    """One process may write a named run; the OS releases its lock on a crash.

    The lock file is never unlinked. Replacing a stale PID file has a race in
    which two resumptions can both enter; locking the same file avoids that.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / ".lock"
    owner_path = run_dir / ".lock-owner.json"
    owner = {"pid": os.getpid(), "started": psutil.Process().create_time(), "t": time.time()}
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("this run is already active") from None
        try:
            write_json(owner_path, owner)
            yield
        finally:
            if read_json(owner_path) == owner:
                owner_path.unlink(missing_ok=True)
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pair_dir(run_dir, case_id, arm):
    return Path(run_dir) / "cases" / safe_name(case_id) / safe_name(arm)


def _effective_attempt(directory):
    """Retry infrastructure failures once; preserve both pieces of evidence."""
    directory = Path(directory)
    first = read_json(directory / "record.json")
    if first is None:
        return None
    retry = read_json(directory / "retry" / "record.json")
    effective = dict(retry if retry is not None and first["result"]["outcome"] in RETRY_OUTCOMES | {"harness_error"} else first)
    effective["attempts"] = [first] + ([retry] if retry is not None else [])
    return effective


def effective_record(directory):
    effective = _effective_attempt(directory)
    if effective is not None:
        effective["oracle_validation"] = _effective_attempt(Path(directory) / "oracle-validation")
    return effective


def load_records(run_dir, effective=True):
    """Load only completed pairs; temporary and retry folders are not new cases."""
    records = []
    for path in sorted((Path(run_dir) / "cases").glob("*/*/record.json")):
        if effective:
            records.append(effective_record(path.parent))
        else:
            records.append(read_json(path))
            for kind in ("retry", "oracle-validation", "oracle-validation/retry"):
                extra = read_json(path.parent / kind / "record.json")
                if extra is not None:
                    records.append(extra)
    return records
