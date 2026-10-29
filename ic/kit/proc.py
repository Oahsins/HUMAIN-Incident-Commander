"""Starting and stopping processes the same way on Windows and Linux."""

import os
import subprocess
import sys
import time

import psutil

WINDOWS = os.name == "nt"


def spawn(argv, log_path=None, env=None, detached=False, cwd=None):
    """Start a child process and return its Popen. Output goes to log_path.

    detached=True lets the process outlive the command that started it
    (used by `run.py up`, which returns while the system keeps running).
    """
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL
    kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL,
              "env": {**os.environ, **(env or {})}, "cwd": cwd}
    if WINDOWS:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if detached:
            flags |= subprocess.DETACHED_PROCESS
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs)
    finally:
        if log_path:
            out.close()


def python_argv(module, *args):
    """argv for `python -m module args...` using the same interpreter as this process."""
    return [sys.executable, "-m", module, *[str(a) for a in args]]


def alive(pid):
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def kill(pid, grace_s=0.0):
    """Stop a process and its children. grace_s > 0 asks politely first."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return False
    procs = parent.children(recursive=True) + [parent]
    if grace_s > 0:
        for proc in procs:
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                pass
        gone, procs = psutil.wait_procs(procs, timeout=grace_s)
    for proc in procs:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=3)
    return True


def usage(pid):
    """CPU percent (since the previous call for this pid) and resident memory in MB."""
    try:
        proc = _cached(pid)
        with proc.oneshot():
            return {"cpu_pct": round(proc.cpu_percent(None), 1),
                    "mem_mb": round(proc.memory_info().rss / 1_048_576, 1)}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _CACHE.pop(pid, None)
        return {"cpu_pct": None, "mem_mb": None}


_CACHE = {}


def _cached(pid):
    proc = _CACHE.get(pid)
    if proc is None or not proc.is_running():
        proc = psutil.Process(pid)
        proc.cpu_percent(None)  # first call primes the counter
        _CACHE[pid] = proc
    return proc


def wait_until(check, timeout_s, interval_s=0.1):
    """Poll check() until it returns something truthy or the time runs out."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(interval_s)
    return check()
