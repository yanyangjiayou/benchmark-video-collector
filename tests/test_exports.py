from datetime import datetime

from openpyxl import Workbook

from mvp.exports import list_exports, resolve_export, save_export_metadata


def make_export(path, rows: int) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["采集标记", "标题"])
    for index in range(rows):
        sheet.append([f"xhs:{index}", f"title-{index}"])
    workbook.save(path)


def test_exports_include_time_platform_and_row_count(tmp_path):
    older = tmp_path / "xhs_20260909_120000_aaaaaa.xlsx"
    newer = tmp_path / "dy_20260910_130000_bbbbbb.xlsx"
    make_export(older, 5)
    make_export(newer, 0)

    items = list_exports(tmp_path)

    assert [item["filename"] for item in items] == [newer.name, older.name]
    assert items[0]["platform_name"] == "抖音"
    assert items[0]["row_count"] == 0
    assert items[1]["platform_name"] == "小红书"
    assert items[1]["row_count"] == 5
    assert items[1]["collected_at_display"] == "2026-09-09 12:00:00"
    datetime.fromisoformat(str(items[1]["collected_at"]))


def test_temporary_current_export_is_hidden(tmp_path):
    make_export(tmp_path / "当前已完成结果.xlsx", 2)
    assert list_exports(tmp_path) == []


def test_export_resolution_rejects_path_traversal(tmp_path):
    path = tmp_path / "xhs_20260909_120000_aaaaaa.xlsx"
    make_export(path, 1)
    assert resolve_export(tmp_path, path.name) == path.resolve()
    assert resolve_export(tmp_path, "../secret.xlsx") is None
    assert resolve_export(tmp_path, "not-an-excel.txt") is None


def test_legacy_workbook_accounts_are_unique_and_visible(tmp_path):
    path = tmp_path / "dy_20260910_130000_aaaaaa.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["标题", "账号"])
    sheet.append(["视频一", "博主甲"])
    sheet.append(["视频二", "博主甲"])
    sheet.append(["视频三", "博主乙"])
    workbook.save(path)
    item = list_exports(tmp_path)[0]
    assert item["accounts"] == ["博主甲", "博主乙"]
    assert item["account_display"] == "博主甲、博主乙"
    assert item["row_count"] == 3


def test_empty_batch_keeps_account_identity(tmp_path):
    path = tmp_path / "xhs_20260910_130000_aaaaaa.xlsx"
    make_export(path, 0)
    save_export_metadata(path, accounts=["博主甲"], creator_url="https://www.xiaohongshu.com/user/profile/abc")
    item = list_exports(tmp_path)[0]
    assert item["row_count"] == 0
    assert item["account_display"] == "博主甲"
    assert item["creator_url"].endswith("/abc")


def test_old_empty_export_does_not_guess_account(tmp_path):
    path = tmp_path / "xhs_20260910_130000_aaaaaa.xlsx"
    make_export(path, 0)
    assert list_exports(tmp_path)[0]["account_display"] == "未记录账号"


def test_invalid_workbook_does_not_hide_valid_history(tmp_path):
    path = tmp_path / "xhs_20260910_130000_aaaaaa.xlsx"
    path.write_bytes(b"incomplete download")
    make_export(tmp_path / "dy_20260910_140000_bbbbbb.xlsx", 1)
    assert len(list_exports(tmp_path)) == 1
