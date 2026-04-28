import main as legacy_main


async def list_chats(*, user_ctx, db, q=None, tenant_id=None):
    return await legacy_main.admin_chats(user_ctx=user_ctx, db=db, q=q, tenant_id=tenant_id)


async def chat_detail(*, session_id, user_ctx, db):
    return await legacy_main.admin_chat_detail(session_id=session_id, user_ctx=user_ctx, db=db)


async def list_users(*, user_ctx, db, tenant_id=None):
    return await legacy_main.admin_users(user_ctx=user_ctx, db=db, tenant_id=tenant_id)


async def list_tenants(*, user_ctx, db):
    return await legacy_main.admin_tenants(user_ctx=user_ctx, db=db)


async def update_tenant_source_config(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_source_config(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def create_admin_user(*, payload, user_ctx, db):
    return await legacy_main.create_admin_user(payload=payload, user_ctx=user_ctx, db=db)


async def update_user_status(*, user_id, payload, user_ctx, db):
    return await legacy_main.update_user_status(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)


async def reset_user_password(*, user_id, payload, user_ctx, db):
    return await legacy_main.reset_user_password(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)
