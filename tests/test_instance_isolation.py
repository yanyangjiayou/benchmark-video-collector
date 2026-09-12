from mvp.app import APP_ID, instance_info


def test_service_exposes_stable_instance_identity():
    assert APP_ID == "benchmark-video-collector"
    assert instance_info() == {"app_id": APP_ID, "data_scope": "video"}
