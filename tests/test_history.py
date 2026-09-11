from mvp.history import CollectionHistory
from mvp.pipeline import select_new_candidates
from openpyxl import Workbook


def entry(content_id: str, media_hash: str = "") -> dict[str, str]:
    return {
        "platform": "xhs",
        "content_id": content_id,
        "title": f"title-{content_id}",
        "media_sha256": media_hash,
        "batch_id": "batch-1",
    }


def test_history_persists_content_and_media_markers(tmp_path):
    database = tmp_path / "collection_history.sqlite3"
    history = CollectionHistory(database)
    assert history.record_many([entry("note-1", "a" * 64)]) == 1

    reopened = CollectionHistory(database)
    assert reopened.seen_content_ids("xhs", ["note-1", "note-2"]) == {"note-1"}
    assert reopened.seen_media_hashes(["a" * 64, "b" * 64]) == {"a" * 64}
    assert reopened.record_many([entry("note-1", "a" * 64)]) == 0


def test_second_collection_returns_next_unseen_items(tmp_path):
    history = CollectionHistory(tmp_path / "collection_history.sqlite3")
    rows = [{"note_id": f"note-{index}"} for index in range(1, 21)]

    first, first_stats = select_new_candidates(rows, "xhs", 10, history)
    assert [item["note_id"] for item in first] == [f"note-{index}" for index in range(1, 11)]
    assert first_stats["history_skipped"] == 0

    history.record_many([entry(item["note_id"]) for item in first])
    second, second_stats = select_new_candidates(rows, "xhs", 10, history)
    assert [item["note_id"] for item in second] == [f"note-{index}" for index in range(11, 21)]
    assert second_stats["history_skipped"] == 10


def test_duplicate_ids_inside_one_scan_are_removed(tmp_path):
    history = CollectionHistory(tmp_path / "collection_history.sqlite3")
    rows = [{"note_id": "note-1"}, {"note_id": "note-1"}, {"note_id": "note-2"}]

    selected, stats = select_new_candidates(rows, "xhs", 10, history)
    assert [item["note_id"] for item in selected] == ["note-1", "note-2"]
    assert stats["duplicates_in_scan"] == 1


def test_legacy_excel_is_imported_once(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["标题", "视频转文字", "原始链接"])
    sheet.append(["old", "transcript", "https://www.xiaohongshu.com/explore/note-old?x=1"])
    sheet.append(["failed", "未取得视频文件，无法转写", "https://www.xiaohongshu.com/explore/note-failed"])
    workbook.save(output / "xhs_old.xlsx")

    history = CollectionHistory(tmp_path / "collection_history.sqlite3")
    assert history.import_excel_exports(output) == 1
    assert history.import_excel_exports(output) == 0
    assert history.seen_content_ids("xhs", ["note-old", "note-failed"]) == {"note-old"}
