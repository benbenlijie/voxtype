"""Keep machine-specific data and runtime artifacts out of the public tree."""
import subprocess
from pathlib import Path

SKIP_PARTS = {".git", "target", "node_modules"}
FORBIDDEN_SUFFIXES = {".onnx", ".bin", ".pyc", ".pyo"}
ALLOWED_WAV_ROOTS = {
    Path("tests/fixtures/vad"),
    Path("tests/fixtures/sensevoice"),
}
PRIVATE_NAME_PARTS = {
    "backup",
    "backups",
    "credentials",
    "credential",
    "keys",
    "private",
    "secrets",
    "logs",
}
PRIVATE_NAME_MARKERS = (
    ".env",
    "apikey",
    "api_key",
    "credential",
    "id_rsa",
    "private_key",
    "secret",
    "token",
)
PRIVATE_SUFFIXES = {".key", ".pem", ".log", ".bak", ".backup", ".orig", ".rej"}


def public_paths(root: Path):
    root = root.resolve()
    try:
        repo_root = Path(
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
    except (OSError, subprocess.CalledProcessError):
        repo_root = None

    if repo_root == root:
        # Inspect tracked files plus untracked files that Git would consider
        # candidates for publication. This deliberately leaves ignored pytest
        # output out of the checkout-wide check, while tracked cache artifacts
        # remain visible and are still rejected below.
        output = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=True,
            capture_output=True,
        ).stdout
        paths = {
            root / Path(relative)
            for relative in output.decode().split("\0")
            if relative
        }
        for path in tuple(paths):
            parent = path.parent
            while parent != root:
                paths.add(parent)
                parent = parent.parent
        return sorted(paths)

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
        rel_parts = {part.lower() for part in rel.parts}
        lower_name = path.name.lower()
        if (
            rel_parts.intersection(PRIVATE_NAME_PARTS)
            or any(marker in lower_name for marker in PRIVATE_NAME_MARKERS)
            or lower_name.endswith("~")
            or lower_name.endswith(tuple(PRIVATE_SUFFIXES))
            or ".bak-" in lower_name
        ):
            found.append(rel)
        if path.is_file():
            if path.suffix.lower() in FORBIDDEN_SUFFIXES and not path.name.startswith("Dockerfile."):
                found.append(rel)
            # Only the existing core fixtures are public. Runtime audio in any
            # other directory must not enter the repository.
            if path.suffix.lower() == ".wav" and not any(
                rel == allowed or allowed in rel.parents for allowed in ALLOWED_WAV_ROOTS
            ):
                found.append(rel)
            if lower_name in {"transcript", "transcript.tmp"}:
                found.append(rel)
            if path.name in {"install-voice-suite.sh", "uninstall-voice-suite.sh"} or path.suffix == ".service":
                text = path.read_text(errors="replace")
                if "/home/" in text or "/Users/" in text:
                    found.append(rel)
        elif path.name in {"__pycache__", ".pytest_cache"}:
            found.append(rel)
    return sorted(set(found))


def test_public_tree_has_no_private_or_runtime_artifacts(tmp_path):
    # Check the actual checkout while isolating only traversal logic in tests.
    assert violations(Path(__file__).resolve().parents[2]) == []


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


def test_public_tree_reports_caches_private_files_and_unapproved_audio(tmp_path):
    (tmp_path / "extras/tests/__pycache__").mkdir(parents=True)
    (tmp_path / "extras/tests/.pytest_cache").mkdir()
    (tmp_path / "extras/mouse-hold").mkdir(parents=True)
    (tmp_path / "extras/mouse-hold/runtime.wav").touch()
    (tmp_path / "tests/fixtures/other.wav").parent.mkdir(parents=True)
    (tmp_path / "tests/fixtures/other.wav").touch()
    (tmp_path / ".env").touch()
    (tmp_path / "private.log").touch()
    (tmp_path / "id_rsa").touch()
    (tmp_path / "config.toml.bak-20261106").touch()
    (tmp_path / "backups").mkdir()

    found = set(violations(tmp_path))
    assert {
        Path("extras/tests/__pycache__"),
        Path("extras/tests/.pytest_cache"),
        Path("extras/mouse-hold/runtime.wav"),
        Path("tests/fixtures/other.wav"),
        Path(".env"),
        Path("private.log"),
        Path("id_rsa"),
        Path("config.toml.bak-20261106"),
        Path("backups"),
    } <= found
