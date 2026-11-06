"""Exercise the installer against an isolated source tree and temporary HOME."""
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "scripts/install-voice-suite.sh"
UNINSTALL = REPO / "scripts/uninstall-voice-suite.sh"


def make_fixture(tmp_path: Path):
    root = tmp_path / "source"
    (root / "scripts").mkdir(parents=True)
    (root / "extras/chinese-postprocess/bin").mkdir(parents=True)
    (root / "extras/mouse-hold").mkdir(parents=True)
    shutil.copy2(INSTALL, root / "scripts/install-voice-suite.sh")
    shutil.copy2(UNINSTALL, root / "scripts/uninstall-voice-suite.sh")
    (root / "extras/chinese-postprocess/bin/voice-suite-chinese").write_text("#!/bin/sh\nexit 0\n")
    (root / "extras/mouse-hold/mouse_daemon.py").write_text("# fixture\n")
    (root / "extras/mouse-hold/voice-suite-mouse.service").write_text("[Service]\n")
    return root


def env_for(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = mock_bin / "systemctl"
    systemctl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    systemctl.chmod(0o755)
    env = os.environ.copy()
    env.update(HOME=str(home), PATH=f"{mock_bin}:{env['PATH']}", SYSTEMCTL_LOG=str(log))
    return home, log, env


def run(script: Path, *args, env):
    return subprocess.run(["bash", str(script), *args], env=env, text=True, capture_output=True)


def test_scripts_exist_and_pass_bash_syntax():
    assert INSTALL.is_file(), f"missing {INSTALL.relative_to(REPO)}"
    assert UNINSTALL.is_file(), f"missing {UNINSTALL.relative_to(REPO)}"
    for script in (INSTALL, UNINSTALL):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_install_places_files_under_home_and_does_not_enable_by_default(tmp_path):
    source = make_fixture(tmp_path)
    home, log, env = env_for(tmp_path)
    result = run(source / "scripts/install-voice-suite.sh", env=env)
    assert result.returncode == 0, result.stderr
    assert (home / ".local/share/voice-suite/chinese-postprocess/bin/voice-suite-chinese").is_file()
    assert (home / ".local/share/voice-suite/mouse-hold/mouse_daemon.py").is_file()
    assert (home / ".config/systemd/user/voice-suite-mouse.service").is_file()
    assert not log.exists() or log.read_text() == ""
    assert not (home / ".local/share/voxtype").exists()
    assert not (home / ".config/voxtype").exists()


def test_install_enable_mouse_is_explicit_and_backs_up_replaced_files(tmp_path):
    source = make_fixture(tmp_path)
    home, log, env = env_for(tmp_path)
    destination = home / ".local/share/voice-suite/mouse-hold/mouse_daemon.py"
    destination.parent.mkdir(parents=True)
    destination.write_text("user's previous companion file")
    result = run(source / "scripts/install-voice-suite.sh", "--enable-mouse", env=env)
    assert result.returncode == 0, result.stderr
    assert destination.read_text() == "# fixture\n"
    backups = list(destination.parent.glob("mouse_daemon.py.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "user's previous companion file"
    assert log.read_text().splitlines() == ["--user enable --now voice-suite-mouse.service"]


def test_missing_optional_components_are_not_reported_as_installed(tmp_path):
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    shutil.copy2(INSTALL, source / "scripts/install-voice-suite.sh")
    (source / "extras/chinese-postprocess").mkdir(parents=True)
    (source / "extras/mouse-hold").mkdir(parents=True)
    home, log, env = env_for(tmp_path)
    result = run(source / "scripts/install-voice-suite.sh", env=env)
    assert result.returncode != 0
    assert "没有可安装的可选配套内容" in result.stderr
    assert not (home / ".local/share/voice-suite").exists()
    assert not log.exists()


def test_enable_mouse_fails_if_service_is_not_included(tmp_path):
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "extras/chinese-postprocess").mkdir(parents=True)
    (source / "extras/chinese-postprocess/postprocess.js").write_text("// fixture\n")
    (source / "extras/mouse-hold").mkdir(parents=True)
    shutil.copy2(INSTALL, source / "scripts/install-voice-suite.sh")
    home, log, env = env_for(tmp_path)
    result = run(source / "scripts/install-voice-suite.sh", "--enable-mouse", env=env)
    assert result.returncode != 0
    assert "鼠标配套服务模板缺失" in result.stderr
    assert not (home / ".local/share/voice-suite").exists()
    assert not log.exists()


def test_uninstall_stops_service_and_preserves_voxtype_data(tmp_path):
    source = make_fixture(tmp_path)
    home, log, env = env_for(tmp_path)
    share = home / ".local/share/voice-suite/mouse-hold"
    share.mkdir(parents=True)
    (share / "mouse_daemon.py").write_text("installed companion")
    config = home / ".config/systemd/user/voice-suite-mouse.service"
    config.parent.mkdir(parents=True)
    config.write_text("[Service]\n")
    (home / ".local/share/voice-suite/.installed-files").write_text(
        ".local/share/voice-suite/mouse-hold/mouse_daemon.py\n"
        ".config/systemd/user/voice-suite-mouse.service\n"
    )
    for path, value in (
        (home / ".local/share/voxtype/model.bin", "model"),
        (home / ".config/voxtype/config.toml", "private config"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    shutil.copy2(UNINSTALL, source / "scripts/uninstall-voice-suite.sh")
    result = run(source / "scripts/uninstall-voice-suite.sh", env=env)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "--user stop voice-suite-mouse.service",
        "--user disable voice-suite-mouse.service",
    ]
    assert not (share / "mouse_daemon.py").exists()
    assert not config.exists()
    assert (home / ".local/share/voxtype/model.bin").read_text() == "model"
    assert (home / ".config/voxtype/config.toml").read_text() == "private config"
