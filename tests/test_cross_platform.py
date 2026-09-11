import io
import os
from types import SimpleNamespace

from mvp import app, xhs_video


def test_login_worker_reuses_current_python_and_platform_path_separator(monkeypatch):
    captured = {}
    windows_python = "C:\\video-collector\\.venv\\Scripts\\python.exe"

    def run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="MVP_LOGIN_CONFIRMED\n", stderr="")

    monkeypatch.setattr(app.sys, "executable", windows_python)
    monkeypatch.setattr(app.subprocess, "run", run)
    app.login_worker("dy")

    assert captured["command"][0] == windows_python
    python_paths = captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert python_paths[-2:] == [str(app.ROOT), str(app.ROOT / "vendor/MediaCrawler")]


def test_xhs_worker_reuses_current_python_and_platform_path_separator(tmp_path, monkeypatch):
    root = tmp_path / "project"
    vendor = root / "vendor/MediaCrawler"
    raw = root / "runtime/jobs/test/raw"
    raw.mkdir(parents=True)
    captured = {}
    windows_python = "C:\\video-collector\\.venv\\Scripts\\python.exe"

    class Process:
        stdout = io.StringIO("")

        @staticmethod
        def wait():
            return 0

    def popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return Process()

    monkeypatch.setattr(xhs_video, "ROOT", root)
    monkeypatch.setattr(xhs_video, "VENDOR", vendor)
    monkeypatch.setattr(xhs_video.sys, "executable", windows_python)
    monkeypatch.setattr(xhs_video.subprocess, "Popen", popen)
    xhs_video.download_missing_videos([{"note_id": "note-1"}], raw, lambda message: None)

    assert captured["command"][0] == windows_python
    assert captured["env"]["PYTHONPATH"].split(os.pathsep) == [str(root), str(vendor)]
