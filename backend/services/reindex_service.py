import main as legacy_main


async def trigger_reindex(*, request, user_ctx, db):
    return await legacy_main.trigger_reindex(request=request, user_ctx=user_ctx, db=db)


async def list_reindex_jobs(*, user_ctx, db, tenant_id=None):
    return await legacy_main.list_reindex_jobs(user_ctx=user_ctx, db=db, tenant_id=tenant_id)
