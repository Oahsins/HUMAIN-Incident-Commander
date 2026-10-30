"""Verify sealed bytes and freeze provenance without changing either."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _sealed_roots(split):
    if split == "heldout":
        return ["scenarios/heldout", "targets/bank/faults/heldout"]
    if split == "transfer":
        return ["scenarios/transfer", "targets/dispatch/faults"]
    raise ValueError("--final requires heldout or transfer")


def sealed_files(root, split):
    """This inventory is also suitable for the sealing writer."""
    root = Path(root).resolve()
    files = {}
    for relative in _sealed_roots(split):
        for path in sorted((root / relative).rglob("*")):
            if not path.is_file() or path.name in {"SEALED.json", ".gitkeep"} or "__pycache__" in path.parts:
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError("sealed path escapes the repository")
            files[path.relative_to(root).as_posix()] = file_hash(path)
    return files


def verify_seals(root, split):
    root = Path(root)
    seal_path = root / "scenarios" / split / "SEALED.json"
    metadata = json.loads(seal_path.read_text(encoding="utf-8"))
    seals = metadata.get("seals", [])
    if not seals or not isinstance(seals[-1].get("files"), dict) or not seals[-1]["files"]:
        raise ValueError("the newest seal has no file hashes")
    expected = seals[-1]["files"]
    actual = sealed_files(root, split)
    if set(expected) != set(actual):
        raise ValueError("sealed file inventory differs from the newest seal")
    if any(actual[name] != digest for name, digest in expected.items()):
        raise ValueError("sealed file hash differs from the newest seal")
    return {"seal": seals[-1]["seal"], "sha256": file_hash(seal_path)}


def git(root, *args):
    completed = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if completed.returncode:
        raise ValueError("Git provenance check failed: " + " ".join(args[:2]))
    return completed.stdout.strip()


def current_hashes():
    # Public freeze interface. Do not duplicate or inspect the agent hash code.
    from run import hashes
    return hashes()


def verify_freeze(root, split, hashes=None):
    root = Path(root).resolve()
    hashes = current_hashes() if hashes is None else hashes
    tag = "freeze-1"
    try:
        git(root, "rev-parse", "--verify", "refs/tags/freeze-1a")
        tag = "freeze-1a"
    except ValueError:
        pass
    freeze = git(root, "rev-parse", f"{tag}^{{commit}}")
    head = git(root, "rev-parse", "HEAD")
    dirty = git(root, "status", "--porcelain", "--untracked-files=all", "--", "ic", "targets/bank", "baselines", "eval", "configs", "run.py")
    if dirty:
        raise ValueError("frozen source paths contain uncommitted changes")
    if split != "transfer":
        if head != freeze:
            raise ValueError(f"--final requires HEAD at {tag}")
    else:
        # Dispatch is added after the freeze. Compare against the public hash
        # command in an isolated detached worktree, then remove that worktree.
        with tempfile.TemporaryDirectory(prefix="ic-freeze-") as temp:
            checkout = Path(temp) / "checkout"
            git(root, "worktree", "add", "--detach", str(checkout), freeze)
            try:
                output = subprocess.run([sys.executable, "run.py", "hash", "--json"], cwd=checkout,
                                        text=True, capture_output=True, check=True).stdout
                frozen_hashes = json.loads(output)
            finally:
                git(root, "worktree", "remove", str(checkout))
        if frozen_hashes.get("agent") != hashes.get("agent"):
            raise ValueError("transfer agent hash differs from the freeze")
    return {"tag": tag, "commit": freeze}
