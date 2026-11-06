"""Keep machine-specific data and runtime artifacts out of the public tree."""
from pathlib import Path

SKIP_PARTS = {".git", "target", "node_modules", ".pytest_cache", "__pycache__"}
FORBIDDEN_SUFFIXES = {".onnx", ".bin", ".pyc", ".pyo"}


def public_paths(root: Path):
    return [
        path
        for path in root.rglob("*")
        if not any(part in SKIP_PARTS for part in path.relative_to(root).parts)
    ]


def violations(root: Path):
    paths = public_paths(root)
    found = []
    for path in paths:
        rel = path.relative_to(root)
        if path.is_file():
            if path.suffix.lower() in FORBIDDEN_SUFFIXES and not path.name.startswith("Dockerfile."):
                found.append(rel)
            # Audio fixtures already tracked by Voxtype are legitimate; runtime
            # audio belongs nowhere in the optional companion modules.
            if "extras" in rel.parts and path.suffix.lower() == ".wav":
                found.append(rel)
            if path.name in {"transcript", "transcript.tmp"}:
                found.append(rel)
            if path.name in {"install-voice-suite.sh", "uninstall-voice-suite.sh"} or path.suffix == ".service":
                text = path.read_text(errors="replace")
                if "/home/" in text or "/Users/" in text:
                    found.append(rel)
    return sorted(set(found))


def test_public_tree_has_no_private_or_runtime_artifacts(tmp_path):
    # Check the actual checkout while isolating only traversal logic in tests.
    assert violations(Path(".")) == []


def test_public_tree_reports_forbidden_companion_artifacts(tmp_path):
    (tmp_path / "extras/chinese-postprocess").mkdir(parents=True)
    (tmp_path / "extras/chinese-postprocess/weights.onnx").touch()
    (tmp_path / "extras/mouse-hold").mkdir(parents=True)
    (tmp_path / "extras/mouse-hold/transcript").write_text("private text")
    assert violations(tmp_path) == [
        Path("extras/chinese-postprocess/weights.onnx"),
        Path("extras/mouse-hold/transcript"),
    ]


def test_public_tree_allows_existing_core_audio_fixtures(tmp_path):
    fixtures = tmp_path / "tests/fixtures/vad"
    fixtures.mkdir(parents=True)
    (fixtures / "speech.wav").touch()
    assert violations(tmp_path) == []
