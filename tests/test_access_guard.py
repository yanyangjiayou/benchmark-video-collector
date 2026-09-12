from mvp.access_guard import PlatformAccessGuard


def test_access_pause_survives_restart_and_can_be_cleared(tmp_path):
    path = tmp_path / "guard.json"
    first = PlatformAccessGuard(path)
    first.block("xhs", "操作频繁")

    reopened = PlatformAccessGuard(path)
    assert reopened.get("xhs")["reason"] == "操作频繁"
    assert reopened.get("xhs")["detected_at"]

    reopened.clear("xhs")
    assert PlatformAccessGuard(path).get("xhs") is None
