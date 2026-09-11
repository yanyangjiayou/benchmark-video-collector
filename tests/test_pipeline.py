from datetime import datetime
import io

import pytest
from openpyxl import load_workbook

from mvp import pipeline
from mvp.exports import list_exports
from mvp.history import CollectionHistory
from mvp.rules import CollectionRequest


class FakeCrawler:
    def __init__(self, output="", code=0):
        self.stdout = io.StringIO(output)
        self.code = code

    def wait(self):
        return self.code


def request():
    return CollectionRequest(platform="dy", trigger_type="creator_url",
                             creator_url="https://www.douyin.com/user/MS4wLjABAAAAexample")


def test_duplicate_only_batch_remembers_creator(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *args, **kwargs: FakeCrawler())
    monkeypatch.setattr(pipeline, "read_rows", lambda *args: [{
        "aweme_id": "123", "nickname": "博主甲", "video_download_url": "https://example.test/video.mp4",
        "create_time": datetime.now().timestamp(), "liked_count": 999,
    }])
    history = CollectionHistory(tmp_path / "runtime/collection_history.sqlite3")
    history.record_many([{"platform": "dy", "content_id": "123"}])
    _, summary, rows = pipeline.run_job(request(), "", lambda message: None)
    assert not rows
    assert summary["history_skipped"] == 1
    assert list_exports(tmp_path / "output")[0]["account_display"] == "博主甲"


def test_crawler_error_with_zero_exit_is_not_an_empty_success(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *args, **kwargs: FakeCrawler("ERROR login failed\n"))
    with pytest.raises(RuntimeError, match="平台未返回内容"):
        pipeline.run_job(request(), "", lambda message: None)
    assert not list((tmp_path / "output").glob("*.xlsx"))
    assert next((tmp_path / "runtime/jobs").glob("*/crawler.log")).read_text() == "ERROR login failed\n"


def test_crawler_subprocess_reuses_current_python(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline.sys, "executable", "C:\\video-collector\\.venv\\Scripts\\python.exe")
    observed = {}

    def popen(command, *args, **kwargs):
        observed["command"] = command
        return FakeCrawler()

    monkeypatch.setattr(pipeline.subprocess, "Popen", popen)
    pipeline.run_job(request(), "", lambda message: None)
    assert observed["command"][0] == "C:\\video-collector\\.venv\\Scripts\\python.exe"


def test_douyin_image_post_audio_is_not_a_video():
    assert not pipeline.is_video({"video_download_url": "audio.mp4", "note_download_url": "photo.jpeg"}, "dy")
    assert pipeline.is_video({"video_download_url": "video.mp4", "note_download_url": ""}, "dy")


def test_reads_douyin_storage_directory_and_multiple_dates(tmp_path):
    folder = tmp_path / "douyin/jsonl"
    folder.mkdir(parents=True)
    (folder / "creator_contents_2026-09-10.jsonl").write_text('{"aweme_id":"1"}\n')
    (folder / "creator_contents_2026-09-11.jsonl").write_text('{"aweme_id":"2"}\n')
    assert [row["aweme_id"] for row in pipeline.read_rows(tmp_path, "dy")] == ["1", "2"]
    media = tmp_path / "douyin/videos/1/video.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"test")
    assert pipeline.find_media(tmp_path, "dy", "1") == media


def test_export_uses_explicit_creator_account_column(tmp_path):
    destination = tmp_path / "result.xlsx"
    pipeline.export_excel([{
        "采集标记": "dy:123",
        "博主账号": "博主甲",
        "标题": "示例",
        "发布时间": "2026-09-11 12:00:00",
        "视频转文字": "正文",
        "点赞数": 350,
        "收藏数": 10,
        "原始链接": "https://www.douyin.com/video/123",
    }], destination)
    workbook = load_workbook(destination, read_only=True, data_only=True)
    try:
        assert [cell.value for cell in workbook.active[1]][1] == "博主账号"
        assert workbook.active["B2"].value == "博主甲"
    finally:
        workbook.close()
