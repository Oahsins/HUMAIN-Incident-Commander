"""All seal files in these tests are invented in pytest's temporary folder."""

import json
import subprocess
import pytest

from eval.seals import file_hash, sealed_files, verify_freeze, verify_seals


def fixture_seal(tmp_path, split="heldout"):
    folder = tmp_path / "scenarios" / split
    folder.mkdir(parents=True)
    (folder / "fixture.jsonl").write_bytes(b'{"invented": true}\r\n')
    (folder / ".gitkeep").touch()
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "ignored.pyc").write_bytes(b"unused")
    metadata = {"seals": [{"seal": 1, "files": sealed_files(tmp_path, split)}]}
    (folder / "SEALED.json").write_text(json.dumps(metadata))
    return folder


@pytest.mark.parametrize("split", ["heldout", "transfer"])
def test_matching_seal_ignores_metadata_gitkeep_cache(tmp_path, split):
    folder = fixture_seal(tmp_path, split)
    assert verify_seals(tmp_path, split)["seal"] == 1
    original = file_hash(folder / "fixture.jsonl")
    (folder / "fixture.jsonl").write_bytes(b'{"invented": true}\n')
    assert file_hash(folder / "fixture.jsonl") == original


def test_mismatched_hash_refused(tmp_path):
    folder = fixture_seal(tmp_path)
    (folder / "fixture.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="hash differs"):
        verify_seals(tmp_path, "heldout")


def test_unlisted_file_refused(tmp_path):
    folder = fixture_seal(tmp_path)
    (folder / "extra.py").write_text("unlisted")
    with pytest.raises(ValueError, match="inventory differs"):
        verify_seals(tmp_path, "heldout")


def test_newest_seal_is_authoritative(tmp_path):
    folder = fixture_seal(tmp_path)
    path = folder / "SEALED.json"
    metadata = json.loads(path.read_text())
    metadata["seals"].append({"seal": 2, "files": {"scenarios/heldout/fixture.jsonl": "0" * 64}})
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="hash differs"):
        verify_seals(tmp_path, "heldout")


def git_fixture(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def frozen_repo(tmp_path):
    git_fixture(tmp_path, "init", "-b", "main")
    git_fixture(tmp_path, "config", "user.name", "Fixture")
    git_fixture(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "run.py").write_text('import json\nprint(json.dumps({"agent": "invented-frozen-hash"}))\n')
    (tmp_path / "ic").mkdir()
    (tmp_path / "ic/fixture.py").write_text("# invented\n")
    git_fixture(tmp_path, "add", "run.py", "ic/fixture.py")
    git_fixture(tmp_path, "commit", "-m", "Invented freeze fixture")
    git_fixture(tmp_path, "tag", "freeze-1")


def test_final_freeze_requires_tag_and_clean_paths(tmp_path):
    frozen_repo(tmp_path)
    assert verify_freeze(tmp_path, "heldout", {"agent": "invented-frozen-hash"})["tag"] == "freeze-1"
    (tmp_path / "ic/fixture.py").write_text("# changed\n")
    with pytest.raises(ValueError, match="uncommitted"):
        verify_freeze(tmp_path, "heldout", {})
    git_fixture(tmp_path, "add", "ic/fixture.py")
    git_fixture(tmp_path, "commit", "-m", "Invented later revision")
    with pytest.raises(ValueError, match="HEAD"):
        verify_freeze(tmp_path, "heldout", {})


def test_transfer_compares_frozen_agent_in_detached_worktree(tmp_path):
    frozen_repo(tmp_path)
    (tmp_path / "dispatch-fixture.txt").write_text("new fixture")
    git_fixture(tmp_path, "add", "dispatch-fixture.txt")
    git_fixture(tmp_path, "commit", "-m", "Invented transfer revision")
    verify_freeze(tmp_path, "transfer", {"agent": "invented-frozen-hash"})
    assert len(git_fixture(tmp_path, "worktree", "list").splitlines()) == 1
    with pytest.raises(ValueError, match="agent hash differs"):
        verify_freeze(tmp_path, "transfer", {"agent": "wrong"})
    assert len(git_fixture(tmp_path, "worktree", "list").splitlines()) == 1
