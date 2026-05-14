from types import SimpleNamespace
from uuid import uuid4

from main import _reindex_job_targets_tenant


def test_reindex_job_targets_tenant_matches_tenant_id_column():
    tenant_id = str(uuid4())
    job = SimpleNamespace(tenant_id=tenant_id, meta_json={})
    assert _reindex_job_targets_tenant(job, tenant_id) is True


def test_reindex_job_targets_tenant_matches_meta_target_tenant_id():
    tenant_id = str(uuid4())
    job = SimpleNamespace(tenant_id=None, meta_json={"target_tenant_id": tenant_id})
    assert _reindex_job_targets_tenant(job, tenant_id) is True


def test_reindex_job_targets_tenant_rejects_other_tenant():
    job = SimpleNamespace(tenant_id=str(uuid4()), meta_json={"target_tenant_id": str(uuid4())})
    assert _reindex_job_targets_tenant(job, str(uuid4())) is False
