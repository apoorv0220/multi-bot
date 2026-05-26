from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from models import UserRole


class ReindexRequest(BaseModel):
    tenant_id: Optional[str] = None


class AdminCreateRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[str] = None
    new_tenant_name: Optional[str] = None
    role: Optional[str] = UserRole.admin.value


class UserStatusRequest(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
    new_password: str


class UserTenantAssignRequest(BaseModel):
    tenant_id: str


class UserTenantSetRequest(BaseModel):
    tenant_ids: list[str]


class TenantCreateRequest(BaseModel):
    name: str


class TenantSourceConfigRequest(BaseModel):
    source_db_url: Optional[str] = None
    source_db_type: Optional[str] = None
    source_table_prefix: Optional[str] = None
    source_url_table: Optional[str] = None
    source_mode: Optional[str] = None
    source_static_urls_json: Optional[str] = None
    source_domain_aliases: Optional[str] = None
    source_canonical_base_url: Optional[str] = None


class TenantQuotaConfigRequest(BaseModel):
    monthly_message_limit: Optional[int] = None
    quota_reached_message: Optional[str] = None


class BlockedIPRequest(BaseModel):
    ip_address: str
    reason: Optional[str] = ""


class BlockedCountryRequest(BaseModel):
    country_code: str
    reason: Optional[str] = ""


class GazetteerEntryMatchFlagsPatch(BaseModel):
    id: str
    hard_filter: Optional[bool] = None
    demote_accessory_substrings: Optional[bool] = None
    fixture_stem: Optional[str] = None
    accessory_keywords: Optional[list[str]] = None


class RetrievalProfileGazetteerPatchRequest(BaseModel):
    entries: list[GazetteerEntryMatchFlagsPatch]


class TenantBrandingConfigRequest(BaseModel):
    brand_name: Optional[str] = None
    widget_primary_color: Optional[str] = None
    widget_website_url: Optional[str] = None
    widget_source_type: Optional[str] = None
    widget_user_message_color: Optional[str] = None
    widget_bot_message_color: Optional[str] = None
    widget_user_message_text_color: Optional[str] = None
    widget_bot_message_text_color: Optional[str] = None
    widget_header_title: Optional[str] = None
    widget_welcome_message: Optional[str] = None
    privacy_policy_url: Optional[str] = None
    avatar_url: Optional[str] = None
    cors_allowed_origins: Optional[str] = None
    chat_max_results: Optional[int] = Field(default=None, ge=1, le=50)
    chat_max_results_catalog: Optional[int] = Field(default=None, ge=1, le=50)


class BlockWordCategoryRequest(BaseModel):
    name: str
    match_mode: str
    response_message: str


class BlockWordRequest(BaseModel):
    word: str


class QuickReplyCreateRequest(BaseModel):
    category: str = "general"
    trigger_phrase: str
    response_template: str
    similarity_threshold: Optional[int] = None
    priority: int = 0
    enabled: bool = True


class QuickReplyUpdateRequest(BaseModel):
    category: Optional[str] = None
    trigger_phrase: Optional[str] = None
    response_template: Optional[str] = None
    similarity_threshold: Optional[int] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class TenantIdleRatingConfigRequest(BaseModel):
    idle_rating_wait_seconds: int
