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
            "providers": {
                "wordpress": {"total_records": 10, "indexed_records": 8, "deleted_records": 1, "failed_records": 0},
                "woocommerce": {"total_records": 5, "indexed_records": 2, "deleted_records": 0, "failed_records": 1},
            },
        }
    )
    assert snapshot["total_items"] == 15
    assert snapshot["processed_items"] == 12
    assert snapshot["failed_items"] == 1
    assert snapshot["progress_percentage"] == 80.0
