import main as legacy_main


async def list_chats(*, user_ctx, db, q=None, tenant_id=None, page=1, page_size=20):
    return await legacy_main.admin_chats(user_ctx=user_ctx, db=db, q=q, tenant_id=tenant_id, page=page, page_size=page_size)


async def chat_detail(*, session_id, user_ctx, db):
    return await legacy_main.admin_chat_detail(session_id=session_id, user_ctx=user_ctx, db=db)


async def list_users(*, user_ctx, db, tenant_id=None, page=1, page_size=20):
    return await legacy_main.admin_users(user_ctx=user_ctx, db=db, tenant_id=tenant_id, page=page, page_size=page_size)


async def list_visitors(*, user_ctx, db, tenant_id=None, page=1, page_size=20):
    return await legacy_main.admin_visitors(user_ctx=user_ctx, db=db, tenant_id=tenant_id, page=page, page_size=page_size)


async def list_visitor_chats(*, visitor_id, user_ctx, db, tenant_id=None, page=1, page_size=20):
    return await legacy_main.admin_visitor_chats(
        visitor_id=visitor_id,
        user_ctx=user_ctx,
        db=db,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )


async def list_tenants(*, user_ctx, db):
    return await legacy_main.admin_tenants(user_ctx=user_ctx, db=db)


async def update_tenant_source_config(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_source_config(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def update_tenant_branding(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_branding(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def upload_tenant_avatar(*, tenant_id, file, user_ctx, db):
    return await legacy_main.upload_tenant_avatar(tenant_id=tenant_id, file=file, user_ctx=user_ctx, db=db)


async def get_tenant_security_settings(*, tenant_id, user_ctx, db):
    return await legacy_main.get_tenant_security_settings(tenant_id=tenant_id, user_ctx=user_ctx, db=db)


async def update_tenant_quota_settings(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_quota_settings(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def update_tenant_idle_rating_settings(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_idle_rating_settings(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def add_tenant_blocked_ip(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.add_tenant_blocked_ip(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def remove_tenant_blocked_ip(*, tenant_id, blocked_ip_id, user_ctx, db):
    return await legacy_main.remove_tenant_blocked_ip(tenant_id=tenant_id, blocked_ip_id=blocked_ip_id, user_ctx=user_ctx, db=db)


async def add_tenant_blocked_country(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.add_tenant_blocked_country(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def remove_tenant_blocked_country(*, tenant_id, blocked_country_id, user_ctx, db):
    return await legacy_main.remove_tenant_blocked_country(
        tenant_id=tenant_id,
        blocked_country_id=blocked_country_id,
        user_ctx=user_ctx,
        db=db,
    )


async def list_block_word_categories(*, tenant_id, user_ctx, db):
    return await legacy_main.list_tenant_block_word_categories(tenant_id=tenant_id, user_ctx=user_ctx, db=db)


async def create_block_word_category(*, tenant_id, payload, user_ctx, db):
    return await legacy_main.create_tenant_block_word_category(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


async def update_block_word_category(*, tenant_id, category_id, payload, user_ctx, db):
    return await legacy_main.update_tenant_block_word_category(
        tenant_id=tenant_id,
        category_id=category_id,
        payload=payload,
        user_ctx=user_ctx,
        db=db,
    )


async def delete_block_word_category(*, tenant_id, category_id, user_ctx, db):
    return await legacy_main.delete_tenant_block_word_category(tenant_id=tenant_id, category_id=category_id, user_ctx=user_ctx, db=db)


async def add_block_word(*, tenant_id, category_id, payload, user_ctx, db):
    return await legacy_main.add_tenant_block_word(
        tenant_id=tenant_id,
        category_id=category_id,
        payload=payload,
        user_ctx=user_ctx,
        db=db,
    )


async def delete_block_word(*, tenant_id, category_id, word_id, user_ctx, db):
    return await legacy_main.delete_tenant_block_word(
        tenant_id=tenant_id,
        category_id=category_id,
        word_id=word_id,
        user_ctx=user_ctx,
        db=db,
    )


async def create_admin_user(*, payload, user_ctx, db):
    return await legacy_main.create_admin_user(payload=payload, user_ctx=user_ctx, db=db)


async def update_user_status(*, user_id, payload, user_ctx, db):
    return await legacy_main.update_user_status(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)


async def reset_user_password(*, user_id, payload, user_ctx, db):
    return await legacy_main.reset_user_password(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)
