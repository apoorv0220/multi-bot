import main as legacy_main


async def usage_summary(*, user_ctx, db, tenant_id=None):
    return await legacy_main.admin_usage_summary(user_ctx=user_ctx, db=db, tenant_id=tenant_id)


async def overview(*, user_ctx, db, tenant_id=None):
    return await legacy_main.admin_overview(user_ctx=user_ctx, db=db, tenant_id=tenant_id)
