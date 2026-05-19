from manage_reindex import ReindexManager


def test_reindex_manager_builds_bearer_headers():
    manager = ReindexManager("http://localhost:8043", bearer_token="abc123")
    assert manager._headers()["Authorization"] == "Bearer abc123"


def test_reindex_manager_job_identifier_supports_api_shapes():
    assert ReindexManager._job_identifier({"id": "job-a"}) == "job-a"
    assert ReindexManager._job_identifier({"job_id": "job-b"}) == "job-b"


def test_reindex_manager_progress_snapshot_supports_provider_progress():
    snapshot = ReindexManager._progress_snapshot(
        {
            "status": "processing",
            "planned_total_records": 200,
            "providers": {
                "wordpress": {"total_records": 100, "indexed_records": 80, "deleted_records": 0, "failed_records": 0},
                "woocommerce": {"total_records": 50, "indexed_records": 10, "deleted_records": 0, "failed_records": 2},
            },
        },
        job_status="running",
    )
    assert snapshot["total_items"] == 200
    assert snapshot["processed_items"] == 92
    assert snapshot["failed_items"] == 2
    assert snapshot["progress_percentage"] == 46.0
    assert snapshot["remaining_items"] == 108
