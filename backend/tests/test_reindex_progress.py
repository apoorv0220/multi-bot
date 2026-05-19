from indexing.progress import normalize_reindex_progress


def test_normalize_uses_planned_total_not_running_total():
    progress = {
        "status": "processing",
        "providers": {
            "woocommerce": {
                "total_records": 500,
                "indexed_records": 500,
                "deleted_records": 0,
                "failed_records": 0,
            },
        },
    }
    snapshot = normalize_reindex_progress(progress, planned_total_records=9658, job_status="running")
    assert snapshot["total_items"] == 9658
    assert snapshot["processed_items"] == 500
    assert snapshot["remaining_items"] == 9158
    assert snapshot["progress_percentage"] < 10
    assert snapshot["progress_percentage"] > 5


def test_normalize_completes_at_100_percent():
    progress = {
        "status": "processing",
        "providers": {
            "woocommerce": {
                "total_records": 100,
                "indexed_records": 100,
                "deleted_records": 0,
                "failed_records": 0,
            },
        },
    }
    snapshot = normalize_reindex_progress(progress, planned_total_records=100, job_status="completed")
    assert snapshot["progress_percentage"] == 100.0
    assert snapshot["remaining_items"] == 0


def test_normalize_partial_providers():
    progress = {
        "providers": {
            "wordpress": {"total_records": 100, "indexed_records": 80, "deleted_records": 0, "failed_records": 0},
            "woocommerce": {"total_records": 50, "indexed_records": 10, "deleted_records": 0, "failed_records": 2},
        },
    }
    snapshot = normalize_reindex_progress(progress, planned_total_records=200, job_status="running")
    assert snapshot["processed_items"] == 92
    assert snapshot["failed_items"] == 2
    assert snapshot["progress_percentage"] == 46.0
