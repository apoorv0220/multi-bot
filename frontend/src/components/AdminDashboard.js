import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { client } from "../api";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  FormGroup,
  FormControl,
  Grid,
  LinearProgress,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Pagination,
  Select,
  Stack,
  Radio,
  RadioGroup,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";

const DASHBOARD_SELECTED_TENANT_KEY = "admin_dashboard_selected_tenant_id";

const adminApiBase = () => String(client.defaults.baseURL || "").replace(/\/+$/, "");

/** Same rule as widget: API base + `/api/assets/...` (or legacy URL containing that path). */
const adminBrandingAvatarSrc = (raw) => {
  if (!raw) return "";
  const base = adminApiBase();
  if (!base) return raw;
  let path = String(raw).trim();
  if (!path.startsWith("/")) {
    const marker = "/api/assets/";
    const i = path.indexOf(marker);
    path = i >= 0 ? path.slice(i) : path;
  }
  if (!path.startsWith("/")) return path;
  return `${base}${path}`;
};

const AdminDashboard = ({ role, tenantId, tenantIds = [] }) => {
  const [sessions, setSessions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [users, setUsers] = useState([]);
  const [visitors, setVisitors] = useState([]);
  const [selectedVisitorId, setSelectedVisitorId] = useState("");
  const [selectedVisitorSessionId, setSelectedVisitorSessionId] = useState("");
  const [visitorChats, setVisitorChats] = useState([]);
  const [chatsPage, setChatsPage] = useState(1);
  const [chatsTotal, setChatsTotal] = useState(0);
  const [adminsPage, setAdminsPage] = useState(1);
  const [adminsTotal, setAdminsTotal] = useState(0);
  const [visitorsPage, setVisitorsPage] = useState(1);
  const [visitorsTotal, setVisitorsTotal] = useState(0);
  const [visitorChatsPage, setVisitorChatsPage] = useState(1);
  const [visitorChatsTotal, setVisitorChatsTotal] = useState(0);
  const [tenants, setTenants] = useState([]);
  const [usageSummary, setUsageSummary] = useState(null);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminTenantId, setAdminTenantId] = useState("");
  const [adminTenantMode, setAdminTenantMode] = useState("existing");
  const [newUserRole, setNewUserRole] = useState(role === "admin" ? "manager" : "admin");
  const [newTenantName, setNewTenantName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [chatFilter, setChatFilter] = useState("");
  const [sourceTenantId, setSourceTenantId] = useState(() =>
    typeof window !== "undefined" ? localStorage.getItem(DASHBOARD_SELECTED_TENANT_KEY) || "" : "",
  );
  const [sourceDbUrl, setSourceDbUrl] = useState("");
  const [sourceDbType, setSourceDbType] = useState("wordpress");
  const [sourceTablePrefix, setSourceTablePrefix] = useState("wp_");
  const [sourceUrlTable, setSourceUrlTable] = useState("wp_custom_urls");
  const [sourceMode, setSourceMode] = useState("wordpress");
  const [sourceStaticUrlsJson, setSourceStaticUrlsJson] = useState("");
  const [sourceDomainAliases, setSourceDomainAliases] = useState("");
  const [sourceCanonicalBaseUrl, setSourceCanonicalBaseUrl] = useState("");
  const [brandName, setBrandName] = useState("");
  const [widgetPrimaryColor, setWidgetPrimaryColor] = useState("#bf362e");
  const [widgetWebsiteUrl, setWidgetWebsiteUrl] = useState("");
  const [widgetSourceType, setWidgetSourceType] = useState("");
  const [widgetUserMessageColor, setWidgetUserMessageColor] = useState("#bf362e");
  const [widgetBotMessageColor, setWidgetBotMessageColor] = useState("#d5bbb9");
  const [widgetUserMessageTextColor, setWidgetUserMessageTextColor] = useState("#ffffff");
  const [widgetBotMessageTextColor, setWidgetBotMessageTextColor] = useState("#1a1a1a");
  const [widgetHeaderTitle, setWidgetHeaderTitle] = useState("");
  const [widgetWelcomeMessage, setWidgetWelcomeMessage] = useState("");
  const [privacyPolicyUrl, setPrivacyPolicyUrl] = useState("");
  const [corsAllowedOrigins, setCorsAllowedOrigins] = useState("");
  const [avatarUpload, setAvatarUpload] = useState(null);
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState("");
  const [clearBrandingAvatar, setClearBrandingAvatar] = useState(false);
  const [monthlyMessageLimit, setMonthlyMessageLimit] = useState(15000);
  const [quotaReachedMessage, setQuotaReachedMessage] = useState("Monthly message limit reached. Please try again next month.");
  const [idleRatingWaitSeconds, setIdleRatingWaitSeconds] = useState(120);
  const [blockedIps, setBlockedIps] = useState([]);
  const [blockedCountries, setBlockedCountries] = useState([]);
  const [newBlockedIp, setNewBlockedIp] = useState("");
  const [newBlockedIpReason, setNewBlockedIpReason] = useState("");
  const [newBlockedCountry, setNewBlockedCountry] = useState("");
  const [newBlockedCountryReason, setNewBlockedCountryReason] = useState("");
  const [countryReference, setCountryReference] = useState([]);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetUserId, setResetUserId] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [manageTenantsOpen, setManageTenantsOpen] = useState(false);
  const [manageTenantUser, setManageTenantUser] = useState(null);
  const [manageTenantIds, setManageTenantIds] = useState([]);
  const [manageTenantSaving, setManageTenantSaving] = useState(false);
  const [createTenantOpen, setCreateTenantOpen] = useState(false);
  const [newStandaloneTenantName, setNewStandaloneTenantName] = useState("");
  const [blockWordCategories, setBlockWordCategories] = useState([]);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryMode, setNewCategoryMode] = useState("exact");
  const [newCategoryResponse, setNewCategoryResponse] = useState("");
  const [newWordByCategory, setNewWordByCategory] = useState({});
  const [moderationPanel, setModerationPanel] = useState(0);
  const [quickReplies, setQuickReplies] = useState([]);
  const [newQrCategory, setNewQrCategory] = useState("general");
  const [newQrTrigger, setNewQrTrigger] = useState("");
  const [newQrTemplate, setNewQrTemplate] = useState("");
  const [newQrPriority, setNewQrPriority] = useState("0");
  const [newQrThreshold, setNewQrThreshold] = useState("");
  const [quickReplyDrafts, setQuickReplyDrafts] = useState({});
  const [success, setSuccess] = useState("");
  const sessionRequestRef = useRef(0);
  const countriesLoadedRef = useRef(false);
  const location = useLocation();
  const navigate = useNavigate();
  const canSelectTenant = role === "superadmin" || tenantIds.length > 1 || tenants.length > 1;
  const effectiveTenantId = sourceTenantId || tenantId || undefined;
  const PAGE_SIZE = 10;
  const routeTail = (location.pathname.replace("/admin/dashboard/", "") || "overview").replace(/^\/+/, "");
  const routeParts = routeTail.split("/").filter(Boolean);
  const section = routeParts[0] || "overview";
  const usersSubsection = section === "users" ? (routeParts[1] || "admins") : "admins";
  const settingsSubsection = section === "settings" ? (routeParts[1] || "security") : "security";

  const selectedTenant = useMemo(
    () => tenants.find((tenant) => tenant.id === sourceTenantId),
    [tenants, sourceTenantId],
  );
  const brandingAvatarPreviewSrc = useMemo(() => {
    if (avatarPreviewUrl) return avatarPreviewUrl;
    if (!selectedTenant?.avatar_url || clearBrandingAvatar) return "";
    return adminBrandingAvatarSrc(selectedTenant.avatar_url);
  }, [selectedTenant, clearBrandingAvatar, avatarPreviewUrl]);

  const countryLabelByCode = useMemo(() => {
    const m = {};
    (countryReference || []).forEach((c) => {
      if (c?.code) m[c.code] = c.name;
    });
    return m;
  }, [countryReference]);

  const navigateSection = (nextSection) => {
    navigate(`/admin/dashboard/${nextSection}`);
  };

  const navigateUsersSubsection = (nextSubsection) => {
    navigate(`/admin/dashboard/users/${nextSubsection}`);
  };

  const navigateSettingsSubsection = (nextSubsection) => {
    navigate(`/admin/dashboard/settings/${nextSubsection}`);
  };

  const persistSourceTenantId = useCallback((value) => {
    setSourceTenantId(value);
    if (value) {
      localStorage.setItem(DASHBOARD_SELECTED_TENANT_KEY, value);
    } else {
      localStorage.removeItem(DASHBOARD_SELECTED_TENANT_KEY);
    }
  }, []);

  const refreshJobsOnly = useCallback(async () => {
    try {
      const { data } = await client.get("/api/reindex/jobs", { params: { tenant_id: effectiveTenantId } });
      setJobs(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading jobs");
    }
  }, [effectiveTenantId]);

  const loadSecuritySettings = useCallback(async () => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get(`/api/admin/tenants/${effectiveTenantId}/security`);
      setBlockedIps(data.blocked_ips || []);
      setBlockedCountries(data.blocked_countries || []);
      setMonthlyMessageLimit(Number(data.monthly_message_limit || 15000));
      setQuotaReachedMessage(data.quota_reached_message || "Monthly message limit reached. Please try again next month.");
      setIdleRatingWaitSeconds(Number(data.idle_rating_wait_seconds || 120));
      setCorsAllowedOrigins(data.cors_allowed_origins || "");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading security settings");
    }
  }, [effectiveTenantId]);

  const loadBlockWordSettings = useCallback(async () => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get(`/api/admin/tenants/${effectiveTenantId}/block-word-categories`);
      setBlockWordCategories(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading block-word settings");
    }
  }, [effectiveTenantId]);

  const loadQuickReplies = useCallback(async () => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get(`/api/admin/tenants/${effectiveTenantId}/quick-replies`);
      setQuickReplies(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading quick replies");
    }
  }, [effectiveTenantId]);

  const loadTenants = useCallback(async () => {
    try {
      const { data } = await client.get("/api/admin/tenants");
      setTenants(data || []);
      if (!sourceTenantId && data?.length > 0) {
        const firstTenant = tenantIds[0] || tenantId || data[0].id;
        const next = firstTenant || "";
        persistSourceTenantId(next);
      }
      if (!adminTenantId && data?.length > 0) {
        const firstTenant = tenantIds[0] || tenantId || data[0].id;
        setAdminTenantId(firstTenant || "");
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading tenants");
    }
  }, [adminTenantId, sourceTenantId, tenantId, tenantIds, persistSourceTenantId]);

  const loadOverviewSection = useCallback(async () => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get("/api/admin/overview", { params: { tenant_id: effectiveTenantId } });
      setOverview(data);
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading overview");
    }
  }, [effectiveTenantId]);

  const loadChatsSection = useCallback(async (query = chatFilter, page = 1) => {
    if (!effectiveTenantId) return;
    try {
      const [chatRes, usageRes] = await Promise.all([
        client.get("/api/admin/chats", {
          params: { q: query || undefined, tenant_id: effectiveTenantId, page, page_size: PAGE_SIZE },
        }),
        client.get("/api/admin/usage/summary", { params: { tenant_id: effectiveTenantId } }),
      ]);
      setSessions(chatRes.data?.items || []);
      setChatsTotal(Number(chatRes.data?.total || 0));
      setChatsPage(Number(chatRes.data?.page || page));
      setUsageSummary(usageRes.data);
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading chats");
    }
  }, [effectiveTenantId, chatFilter]);

  const loadJobsSection = useCallback(async () => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get("/api/reindex/jobs", { params: { tenant_id: effectiveTenantId } });
      setJobs(data || []);
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading jobs");
    }
  }, [effectiveTenantId]);

  const loadAdminsSection = useCallback(async (page = 1) => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get("/api/admin/users", {
        params: { tenant_id: effectiveTenantId, page, page_size: PAGE_SIZE },
      });
      setUsers(data?.items || []);
      setAdminsTotal(Number(data?.total || 0));
      setAdminsPage(Number(data?.page || page));
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading admins");
    }
  }, [effectiveTenantId]);

  const loadVisitorsSection = useCallback(async (page = 1) => {
    if (!effectiveTenantId) return;
    try {
      const { data } = await client.get("/api/admin/visitors", {
        params: { tenant_id: effectiveTenantId, page, page_size: PAGE_SIZE },
      });
      setVisitors(data?.items || []);
      setVisitorsTotal(Number(data?.total || 0));
      setVisitorsPage(Number(data?.page || page));
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading visitors");
    }
  }, [effectiveTenantId]);

  useEffect(() => {
    if (section !== "jobs") return undefined;
    const id = setInterval(() => {
      refreshJobsOnly();
    }, 5000);
    return () => clearInterval(id);
  }, [section, refreshJobsOnly]);

  useEffect(() => {
    if (!tenants.length || !sourceTenantId) return;
    if (tenants.some((t) => t.id === sourceTenantId)) return;
    const fallback =
      tenantIds.find((id) => tenants.some((t) => t.id === id)) || tenants[0]?.id || tenantId || "";
    persistSourceTenantId(fallback);
  }, [tenants, sourceTenantId, tenantIds, tenantId, persistSourceTenantId]);

  useEffect(() => {
    if (role !== "superadmin") return;
    setSelected(null);
    setMessages([]);
  }, [role, sourceTenantId]);

  useEffect(() => {
    const t = tenants.find((tenant) => tenant.id === sourceTenantId);
    if (!t) return;
    setSourceDbUrl(t.source_db_url || "");
    setSourceDbType(t.source_db_type || "wordpress");
    setSourceTablePrefix(t.source_table_prefix || "wp_");
    setSourceUrlTable(t.source_url_table || "wp_custom_urls");
    setSourceMode(t.source_mode || "wordpress");
    setSourceStaticUrlsJson(t.source_static_urls_json || "");
    setSourceDomainAliases(t.source_domain_aliases || "");
    setSourceCanonicalBaseUrl(t.source_canonical_base_url || "");
    setBrandName(t.brand_name || "");
    setWidgetPrimaryColor(t.widget_primary_color || "#bf362e");
    setWidgetWebsiteUrl(t.widget_website_url || "");
    setWidgetSourceType(t.widget_source_type || "");
    setWidgetUserMessageColor(t.widget_user_message_color || "#bf362e");
    setWidgetBotMessageColor(t.widget_bot_message_color || "#d5bbb9");
    setWidgetUserMessageTextColor(t.widget_user_message_text_color || "#ffffff");
    setWidgetBotMessageTextColor(t.widget_bot_message_text_color || "#1a1a1a");
    setWidgetHeaderTitle(t.widget_header_title || "");
    setWidgetWelcomeMessage(t.widget_welcome_message || "");
    setPrivacyPolicyUrl(t.privacy_policy_url || "");
    setCorsAllowedOrigins(t.cors_allowed_origins || "");
    setClearBrandingAvatar(false);
    setAvatarUpload(null);
    setAvatarPreviewUrl("");
  }, [sourceTenantId, tenants]);

  useEffect(() => {
    if (!avatarUpload) {
      setAvatarPreviewUrl("");
      return undefined;
    }
    const objectUrl = URL.createObjectURL(avatarUpload);
    setAvatarPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [avatarUpload]);

  useEffect(() => {
    setChatsPage(1);
    setAdminsPage(1);
    setVisitorsPage(1);
    setVisitorChatsPage(1);
    setSelectedVisitorId("");
    setSelectedVisitorSessionId("");
    setVisitorChats([]);
    setSearchQuery("");
    setChatFilter("");
  }, [effectiveTenantId]);

  useEffect(() => {
    loadTenants();
  }, [loadTenants]);

  useEffect(() => {
    if (section !== "settings" || settingsSubsection !== "security") return;
    if (countriesLoadedRef.current) return;
    countriesLoadedRef.current = true;
    (async () => {
      try {
        const { data } = await client.get("/api/admin/reference/countries");
        setCountryReference(data.countries || []);
      } catch (err) {
        setError(err?.response?.data?.detail || "Failed loading country list");
      }
    })();
  }, [section, settingsSubsection]);

  useEffect(() => {
    const validSections = ["overview", "chats", "jobs", "users", "settings"];
    if (!validSections.includes(section)) {
      navigate("/admin/dashboard/overview", { replace: true });
      return;
    }
    if (section === "users" && !["admins", "visitors"].includes(usersSubsection)) {
      navigate("/admin/dashboard/users/admins", { replace: true });
      return;
    }
    if (section === "settings" && !["security", "branding", "moderation", "db-settings"].includes(settingsSubsection)) {
      navigate("/admin/dashboard/settings/security", { replace: true });
    }
  }, [navigate, section, usersSubsection, settingsSubsection]);

  useEffect(() => {
    if (!effectiveTenantId) return;
    if (section === "overview") {
      loadOverviewSection();
      return;
    }
    if (section === "chats") {
      loadChatsSection(chatFilter, chatsPage);
      return;
    }
    if (section === "jobs") {
      loadJobsSection();
      return;
    }
    if (section === "users") {
      if (usersSubsection === "admins") {
        loadAdminsSection(adminsPage);
      } else {
        loadVisitorsSection(visitorsPage);
      }
      return;
    }
    if (section === "settings") {
      if (settingsSubsection === "security") {
        loadSecuritySettings();
      } else if (settingsSubsection === "moderation") {
        loadBlockWordSettings();
        loadQuickReplies();
      }
    }
  }, [
    effectiveTenantId,
    section,
    usersSubsection,
    settingsSubsection,
    chatFilter,
    chatsPage,
    adminsPage,
    visitorsPage,
    loadOverviewSection,
    loadChatsSection,
    loadJobsSection,
    loadAdminsSection,
    loadVisitorsSection,
    loadSecuritySettings,
    loadBlockWordSettings,
    loadQuickReplies,
  ]);

  const loadSession = async (id) => {
    setSelected(id);
    setMessages([]);
    const requestSeq = ++sessionRequestRef.current;
    const { data } = await client.get(`/api/admin/chats/${id}`);
    if (requestSeq === sessionRequestRef.current) {
      setMessages(data);
    }
  };

  const reindex = async () => {
    await client.post("/api/reindex", role === "superadmin" ? { tenant_id: sourceTenantId || undefined } : { tenant_id: tenantId });
    await loadJobsSection();
  };

  const loadVisitorChats = useCallback(async (visitorId, page = 1) => {
    setSelectedVisitorId(visitorId);
    setSelectedVisitorSessionId("");
    setSelected(null);
    setMessages([]);
    const { data } = await client.get(`/api/admin/visitors/${visitorId}/chats`, {
      params: { tenant_id: effectiveTenantId, page, page_size: PAGE_SIZE },
    });
    setVisitorChats(data?.items || []);
    setVisitorChatsTotal(Number(data?.total || 0));
    setVisitorChatsPage(Number(data?.page || page));
  }, [effectiveTenantId]);

  useEffect(() => {
    if (!effectiveTenantId || !selectedVisitorId || section !== "users" || usersSubsection !== "visitors") return;
    loadVisitorChats(selectedVisitorId, visitorChatsPage);
  }, [effectiveTenantId, selectedVisitorId, visitorChatsPage, section, usersSubsection, loadVisitorChats]);

  const loadVisitorSession = async (sessionId) => {
    setSelectedVisitorSessionId(sessionId);
    await loadSession(sessionId);
  };

  const createAdmin = async () => {
    try {
      const payload = {
        email: adminEmail,
        password: adminPassword,
        role: newUserRole,
      };
      if (adminTenantMode === "new") {
        payload.new_tenant_name = newTenantName.trim() || undefined;
      } else {
        payload.tenant_id = adminTenantId || undefined;
      }
      await client.post("/api/admin/users", {
        ...payload,
      });
      setSuccess("User created successfully");
      setCreateOpen(false);
      setAdminEmail("");
      setAdminPassword("");
      setAdminTenantId("");
      setAdminTenantMode("existing");
      setNewTenantName("");
      setNewUserRole(role === "admin" ? "manager" : "admin");
      await loadAdminsSection(adminsPage);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create user");
    }
  };

  const updateUserStatus = async (userId, isActive) => {
    try {
      await client.post(`/api/admin/users/${userId}/status`, { is_active: isActive });
      setSuccess(`User ${isActive ? "activated" : "deactivated"} successfully`);
      await loadAdminsSection(adminsPage);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update user status");
    }
  };

  const openReset = (userId) => {
    setResetUserId(userId);
    setNewPassword("");
    setResetOpen(true);
  };

  const resetPassword = async () => {
    try {
      await client.post(`/api/admin/users/${resetUserId}/reset-password`, { new_password: newPassword });
      setSuccess("Password reset successfully");
      setResetOpen(false);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to reset password");
    }
  };

  const openManageUserTenants = async (user) => {
    try {
      const { data } = await client.get(`/api/admin/users/${user.id}/tenants`);
      const ids = (data?.items || []).map((i) => i.tenant_id);
      setManageTenantUser(user);
      setManageTenantIds(ids);
      setManageTenantsOpen(true);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to load user tenant associations");
    }
  };

  const saveManageUserTenants = async () => {
    if (!manageTenantUser) return;
    setManageTenantSaving(true);
    try {
      await client.put(`/api/admin/users/${manageTenantUser.id}/tenants`, { tenant_ids: manageTenantIds });
      setSuccess("User tenant associations updated");
      setManageTenantsOpen(false);
      setManageTenantUser(null);
      setManageTenantIds([]);
      await loadAdminsSection(adminsPage);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update user tenant associations");
    } finally {
      setManageTenantSaving(false);
    }
  };

  const createStandaloneTenant = async () => {
    const name = newStandaloneTenantName.trim();
    if (!name) return;
    try {
      await client.post("/api/admin/tenants", { name });
      setSuccess("Tenant created");
      setCreateTenantOpen(false);
      setNewStandaloneTenantName("");
      await loadTenants();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create tenant");
    }
  };

  const saveSourceConfig = async () => {
    try {
      await client.patch(`/api/admin/tenants/${sourceTenantId}/source-config`, {
        source_db_url: sourceDbUrl || null,
        source_db_type: sourceDbType || null,
        source_table_prefix: sourceTablePrefix || null,
        source_url_table: sourceUrlTable || null,
        source_mode: sourceMode || null,
        source_static_urls_json: sourceStaticUrlsJson || null,
        source_domain_aliases: sourceDomainAliases || null,
        source_canonical_base_url: sourceCanonicalBaseUrl || null,
      });
      setSuccess("Tenant source settings updated");
      await loadTenants();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update source settings");
    }
  };

  const saveBrandingConfig = async () => {
    try {
      const brandingPayload = {
        brand_name: brandName || null,
        widget_primary_color: widgetPrimaryColor || null,
        widget_website_url: widgetWebsiteUrl || null,
        widget_source_type: widgetSourceType || null,
        widget_user_message_color: widgetUserMessageColor || null,
        widget_bot_message_color: widgetBotMessageColor || null,
        widget_user_message_text_color: widgetUserMessageTextColor || null,
        widget_bot_message_text_color: widgetBotMessageTextColor || null,
        widget_header_title: widgetHeaderTitle || null,
        widget_welcome_message: widgetWelcomeMessage || null,
        privacy_policy_url: privacyPolicyUrl || null,
      };
      if (clearBrandingAvatar && !avatarUpload) {
        brandingPayload.avatar_url = "";
      }
      await client.patch(`/api/admin/tenants/${sourceTenantId}/branding`, brandingPayload);
      if (avatarUpload) {
        const fd = new FormData();
        fd.append("file", avatarUpload);
        await client.post(`/api/admin/tenants/${sourceTenantId}/avatar`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setAvatarUpload(null);
        setClearBrandingAvatar(false);
      } else if (clearBrandingAvatar) {
        setClearBrandingAvatar(false);
      }
      setSuccess("Branding and widget configuration updated");
      await loadTenants();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update branding settings");
    }
  };

  const saveSecuritySettings = async () => {
    if (!effectiveTenantId) return;
    try {
      const quotaPayload = {
        quota_reached_message: quotaReachedMessage,
      };
      if (role === "superadmin") {
        quotaPayload.monthly_message_limit = Number(monthlyMessageLimit || 15000);
      }
      await client.patch(`/api/admin/tenants/${effectiveTenantId}/quota`, quotaPayload);
      await client.patch(`/api/admin/tenants/${effectiveTenantId}/idle-rating`, {
        idle_rating_wait_seconds: Number(idleRatingWaitSeconds || 120),
      });
      await client.patch(`/api/admin/tenants/${effectiveTenantId}/branding`, {
        cors_allowed_origins: corsAllowedOrigins || null,
      });
      setSuccess("Security settings updated");
      await loadSecuritySettings();
      await loadTenants();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update security settings");
    }
  };

  const addBlockedIp = async () => {
    try {
      await client.post(`/api/admin/tenants/${effectiveTenantId}/blocked-ips`, {
        ip_address: newBlockedIp,
        reason: newBlockedIpReason,
      });
      setNewBlockedIp("");
      setNewBlockedIpReason("");
      await loadSecuritySettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to add blocked IP");
    }
  };

  const removeBlockedIp = async (id) => {
    try {
      await client.delete(`/api/admin/tenants/${effectiveTenantId}/blocked-ips/${id}`);
      await loadSecuritySettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to remove blocked IP");
    }
  };

  const addBlockedCountry = async () => {
    if (!newBlockedCountry) {
      setError("Select a country to block");
      return;
    }
    try {
      await client.post(`/api/admin/tenants/${effectiveTenantId}/blocked-countries`, {
        country_code: newBlockedCountry,
        reason: newBlockedCountryReason,
      });
      setNewBlockedCountry("");
      setNewBlockedCountryReason("");
      await loadSecuritySettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to add blocked country");
    }
  };

  const removeBlockedCountry = async (id) => {
    try {
      await client.delete(`/api/admin/tenants/${effectiveTenantId}/blocked-countries/${id}`);
      await loadSecuritySettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to remove blocked country");
    }
  };

  const createBlockWordCategory = async () => {
    try {
      await client.post(`/api/admin/tenants/${effectiveTenantId}/block-word-categories`, {
        name: newCategoryName,
        match_mode: newCategoryMode,
        response_message: newCategoryResponse,
      });
      setNewCategoryName("");
      setNewCategoryMode("exact");
      setNewCategoryResponse("");
      await loadBlockWordSettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create category");
    }
  };

  const deleteBlockWordCategory = async (categoryId) => {
    try {
      await client.delete(`/api/admin/tenants/${effectiveTenantId}/block-word-categories/${categoryId}`);
      await loadBlockWordSettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to delete category");
    }
  };

  const addWordToCategory = async (categoryId) => {
    const word = (newWordByCategory[categoryId] || "").trim();
    if (!word) return;
    try {
      await client.post(`/api/admin/tenants/${effectiveTenantId}/block-word-categories/${categoryId}/words`, { word });
      setNewWordByCategory((prev) => ({ ...prev, [categoryId]: "" }));
      await loadBlockWordSettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to add word");
    }
  };

  const deleteWordFromCategory = async (categoryId, wordId) => {
    try {
      await client.delete(`/api/admin/tenants/${effectiveTenantId}/block-word-categories/${categoryId}/words/${wordId}`);
      await loadBlockWordSettings();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to delete word");
    }
  };

  const createQuickReply = async () => {
    if (!newQrTrigger.trim() || !newQrTemplate.trim()) return;
    try {
      const body = {
        category: newQrCategory.trim() || "general",
        trigger_phrase: newQrTrigger.trim(),
        response_template: newQrTemplate.trim(),
        priority: Number(newQrPriority || 0),
        enabled: true,
      };
      const th = newQrThreshold.trim();
      if (th !== "") body.similarity_threshold = Number(th);
      await client.post(`/api/admin/tenants/${effectiveTenantId}/quick-replies`, body);
      setNewQrTrigger("");
      setNewQrTemplate("");
      setNewQrPriority("0");
      setNewQrThreshold("");
      setSuccess("Quick reply added");
      await loadQuickReplies();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to add quick reply");
    }
  };

  const deleteQuickReply = async (id) => {
    try {
      await client.delete(`/api/admin/tenants/${effectiveTenantId}/quick-replies/${id}`);
      await loadQuickReplies();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to delete quick reply");
    }
  };

  const setQuickReplyEnabled = async (row, enabled) => {
    try {
      await client.patch(`/api/admin/tenants/${effectiveTenantId}/quick-replies/${row.id}`, { enabled });
      await loadQuickReplies();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update quick reply");
    }
  };

  const updateQuickReplyDraft = (id, patch) => {
    setQuickReplyDrafts((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }));
  };

  const resetQuickReplyDraft = (row) => {
    setQuickReplyDrafts((prev) => ({ ...prev, [row.id]: { ...row } }));
  };

  const saveQuickReplyDraft = async (row) => {
    const draft = { ...row, ...(quickReplyDrafts[row.id] || {}) };
    try {
      const body = {
        category: (draft.category || "general").trim() || "general",
        trigger_phrase: (draft.trigger_phrase || "").trim(),
        response_template: draft.response_template || "",
        priority: Number(draft.priority || 0),
        enabled: Boolean(draft.enabled),
      };
      const th = String(draft.similarity_threshold ?? "").trim();
      if (th !== "") body.similarity_threshold = Number(th);
      await client.patch(`/api/admin/tenants/${effectiveTenantId}/quick-replies/${row.id}`, body);
      setSuccess("Quick reply updated");
      await loadQuickReplies();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save quick reply");
    }
  };

  const isQuickReplyDirty = (row) => {
    const draft = quickReplyDrafts[row.id];
    if (!draft) return false;
    const toNorm = (v) => String(v ?? "").trim();
    return (
      toNorm(draft.category) !== toNorm(row.category) ||
      toNorm(draft.trigger_phrase) !== toNorm(row.trigger_phrase) ||
      toNorm(draft.response_template) !== toNorm(row.response_template) ||
      toNorm(draft.priority) !== toNorm(row.priority) ||
      toNorm(draft.similarity_threshold) !== toNorm(row.similarity_threshold ?? "") ||
      Boolean(draft.enabled) !== Boolean(row.enabled)
    );
  };

  const exportTranscript = () => {
    if (!selected || !messages.length) return;
    const lines = messages.map((m) => `[${m.created_at}] ${m.sender_type.toUpperCase()}: ${m.content}`);
    const blob = new Blob([lines.join("\n\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `session-${selected}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const aggregateFeedback = sessions.reduce(
    (acc, s) => {
      acc.up += Number(s?.feedback_summary?.up || 0);
      acc.down += Number(s?.feedback_summary?.down || 0);
      return acc;
    },
    { up: 0, down: 0 }
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "240px minmax(0, 1fr)" },
          gap: 2,
          minHeight: "calc(100vh - 120px)",
          alignItems: "stretch",
        }}
      >
        <Box
          component="aside"
          sx={{
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 2,
            p: 2,
            bgcolor: "background.paper",
            minHeight: "100%",
            position: { md: "sticky" },
            top: { md: 16 },
            alignSelf: "start",
          }}
        >
              <Stack spacing={1.25}>
                <Button variant={section === "overview" ? "contained" : "text"} onClick={() => navigateSection("overview")}>Overview</Button>
                <Button variant={section === "chats" ? "contained" : "text"} onClick={() => navigateSection("chats")}>Chats</Button>
                <Button variant={section === "jobs" ? "contained" : "text"} onClick={() => navigateSection("jobs")}>Jobs</Button>
                <Button variant={section === "users" ? "contained" : "text"} onClick={() => navigateSection("users/admins")}>Users</Button>
                {section === "users" && (
                  <Stack pl={1}>
                    <Button size="small" variant={usersSubsection === "admins" ? "contained" : "text"} onClick={() => navigateUsersSubsection("admins")}>Admins</Button>
                    <Button size="small" variant={usersSubsection === "visitors" ? "contained" : "text"} onClick={() => navigateUsersSubsection("visitors")}>Visitors</Button>
                  </Stack>
                )}
                <Button variant={section === "settings" ? "contained" : "text"} onClick={() => navigateSection("settings/security")}>Settings</Button>
                {section === "settings" && (
                  <Stack pl={1}>
                    <Button size="small" variant={settingsSubsection === "security" ? "contained" : "text"} onClick={() => navigateSettingsSubsection("security")}>Security</Button>
                    <Button size="small" variant={settingsSubsection === "branding" ? "contained" : "text"} onClick={() => navigateSettingsSubsection("branding")}>Branding</Button>
                    <Button size="small" variant={settingsSubsection === "moderation" ? "contained" : "text"} onClick={() => navigateSettingsSubsection("moderation")}>Automated Replies</Button>
                    <Button size="small" variant={settingsSubsection === "db-settings" ? "contained" : "text"} onClick={() => navigateSettingsSubsection("db-settings")}>DB Settings</Button>
                  </Stack>
                )}
              </Stack>
        </Box>
        <Box component="main" sx={{ minWidth: 0 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2} gap={2} flexWrap="wrap">
        <Box>
          <Typography variant="h4" fontWeight={700}>Admin Dashboard</Typography>
          <Typography color="text.secondary">{role === "superadmin" ? "Global control center" : "Tenant control center"}</Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          {canSelectTenant && (
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel>Tenant</InputLabel>
              <Select
                label="Tenant"
                value={sourceTenantId}
                onChange={(e) => persistSourceTenantId(e.target.value)}
              >
                {tenants.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.name}
                    {role === "superadmin" ? ` (${t.id})` : ""}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <Button variant="outlined" onClick={reindex}>Trigger Reindex</Button>
          {(role === "superadmin" || role === "admin") && (
            <Button variant="outlined" onClick={() => setCreateTenantOpen(true)}>
              Create Tenant
            </Button>
          )}
          {(role === "superadmin" || role === "admin") && (
            <Button variant="contained" onClick={() => setCreateOpen(true)}>
              {role === "superadmin" ? "Add Admin/Manager" : "Add Manager"}
            </Button>
          )}
        </Stack>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

      {section === "overview" && (
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Total Chats</Typography><Typography variant="h4" fontWeight={700}>{overview?.total_chats || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Unique Users (Visitors)</Typography><Typography variant="h4" fontWeight={700}>{overview?.unique_visitors || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Embeddings Token Usage</Typography><Typography variant="h4" fontWeight={700}>{overview?.embedding_token_usage || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Chat Token Usage</Typography><Typography variant="h4" fontWeight={700}>{overview?.chat_token_usage || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Likes</Typography><Typography variant="h4" fontWeight={700}>{overview?.likes || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Dislikes</Typography><Typography variant="h4" fontWeight={700}>{overview?.dislikes || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Session Ratings</Typography><Typography variant="h4" fontWeight={700}>{overview?.rating_count || 0}</Typography></CardContent></Card>
          </Grid>
          <Grid item xs={12} sm={6} md={4}>
            <Card><CardContent><Typography color="text.secondary">Average Rating</Typography><Typography variant="h4" fontWeight={700}>{overview?.average_rating || 0}</Typography></CardContent></Card>
          </Grid>
        </Grid>
      )}

      {section === "chats" && (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", lg: "minmax(420px, 1fr) minmax(420px, 1fr)" },
            gap: 2,
            alignItems: "start",
          }}
        >
          <Card sx={{ minWidth: 0 }}>
            <CardContent>
              <Stack direction="row" spacing={1} mb={1} alignItems="center">
                <Typography variant="h6">Tenant Chats</Typography>
                <Chip size="small" label={`👍 ${aggregateFeedback.up}`} />
                <Chip size="small" label={`👎 ${aggregateFeedback.down}`} />
                <Chip size="small" label={`Embeddings Tokens ${usageSummary?.embedding_total_tokens || 0}`} />
              </Stack>
              <TextField
                size="small"
                label="Search chats"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setChatFilter(e.currentTarget.value);
                    setChatsPage(1);
                    loadChatsSection(e.currentTarget.value, 1);
                  }
                }}
                fullWidth
                sx={{ mb: 1 }}
              />
              <List dense sx={{ maxHeight: 520, overflowY: "auto" }}>
                {sessions.map((s) => (
                  <ListItemButton key={s.id} selected={selected === s.id} onClick={() => loadSession(s.id)}>
                    <Stack direction="row" alignItems="flex-start" spacing={1} sx={{ width: "100%", minWidth: 0 }}>
                      <ListItemText
                        sx={{ flex: 1, minWidth: 0 }}
                        primary={s.title || s.id}
                        secondary={`${s.visitor_name || "Unknown"}${s.visitor_email ? ` (${s.visitor_email})` : ""} | ${s.id} | ${s.last_message_at} | 👍 ${s?.feedback_summary?.up || 0} 👎 ${s?.feedback_summary?.down || 0}`}
                        secondaryTypographyProps={{ sx: { wordBreak: "break-word" } }}
                      />
                      <Typography variant="body2" color="text.secondary" sx={{ flexShrink: 0, pt: 0.25 }}>
                        {Number(s.message_count ?? 0)} msgs
                      </Typography>
                    </Stack>
                  </ListItemButton>
                ))}
              </List>
              <Stack direction="row" justifyContent="center" sx={{ mt: 1 }}>
                <Pagination
                  count={Math.max(1, Math.ceil(chatsTotal / PAGE_SIZE))}
                  page={chatsPage}
                  onChange={(_, value) => setChatsPage(value)}
                  size="small"
                />
              </Stack>
            </CardContent>
          </Card>
          <Card sx={{ minWidth: 0 }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                <Typography variant="h6">Conversation</Typography>
                <Button size="small" onClick={exportTranscript} disabled={!selected}>Export</Button>
              </Stack>
              {selected ? (
                <Stack spacing={1.5} sx={{ maxHeight: 560, overflowY: "auto" }}>
                  {messages.map((m) => (
                    <Box key={m.id} sx={{ p: 1.5, borderRadius: 1, bgcolor: m.sender_type === "assistant" ? "grey.100" : "primary.50" }}>
                      <Typography variant="caption" color="text.secondary">{m.sender_type}</Typography>
                      <Typography sx={{ wordBreak: "break-word" }}>{m.content}</Typography>
                      {m.sender_type === "assistant" && (
                        <Stack direction="row" spacing={1} sx={{ mt: 0.5, flexWrap: "wrap" }}>
                          <Chip size="small" label={`Prompt ${m?.token_usage?.prompt_tokens || 0}`} />
                          <Chip size="small" label={`Completion ${m?.token_usage?.completion_tokens || 0}`} />
                          <Chip size="small" label={`Total ${m?.token_usage?.total_tokens || 0}`} />
                        </Stack>
                      )}
                      {m.sender_type === "assistant" && (
                        <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
                          <Chip size="small" label={`👍 ${m?.feedback_summary?.up || 0}`} />
                          <Chip size="small" label={`👎 ${m?.feedback_summary?.down || 0}`} />
                        </Stack>
                      )}
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Typography color="text.secondary">Select a chat session.</Typography>
              )}
            </CardContent>
          </Card>
        </Box>
      )}

      {section === "jobs" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Reindex Jobs</Typography>
            <Stack spacing={1}>
              {jobs.map((j) => (
                <Card key={j.id} variant="outlined">
                  <CardContent>
                    <Stack direction="row" spacing={1} alignItems="center" mb={1}>
                      <Typography sx={{ minWidth: 320 }} fontWeight={600}>{j.id}</Typography>
                      {j.tenant_name && <Chip size="small" label={j.tenant_name} />}
                      <Chip size="small" label={j.scope} />
                      <Chip size="small" color={j.status === "completed" ? "success" : j.status === "failed" ? "error" : "default"} label={j.status} />
                    </Stack>
                    {!!j.meta?.progress && j.status !== "completed" && j.status !== "failed" && (
                      <Box sx={{ mb: 1 }}>
                        <LinearProgress
                          variant="determinate"
                          value={Number(j.meta.progress.progress_percentage || 0)}
                          sx={{ height: 8, borderRadius: 10, mb: 0.5 }}
                        />
                        <Typography variant="caption" color="text.secondary">
                          {j.meta.progress.processed_items || 0}/{j.meta.progress.total_items || 0} processed
                          ({Number(j.meta.progress.progress_percentage || 0).toFixed(1)}%)
                        </Typography>
                      </Box>
                    )}
                    <Typography variant="caption" color="text.secondary" display="block">
                      Started: {j.started_at || "N/A"} {j.finished_at ? `| Finished: ${j.finished_at}` : ""}
                    </Typography>
                    {!!j.error && (
                      <Typography variant="caption" color="error.main" display="block">
                        Error: {j.error}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}

      {section === "users" && usersSubsection === "admins" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Admins</Typography>
            <Stack spacing={1}>
              {users.map((u) => (
                <Stack key={u.id} direction="row" spacing={1} alignItems="center">
                  <Typography sx={{ minWidth: 280 }}>{u.email}</Typography>
                  <Chip size="small" label={u.role} color={u.role === "superadmin" ? "secondary" : "primary"} />
                  <Chip size="small" label={u.is_active ? "active" : "inactive"} />
                  {u.role !== "superadmin" && (
                    <>
                      <Button size="small" onClick={() => updateUserStatus(u.id, !u.is_active)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                      <Button size="small" onClick={() => openReset(u.id)}>Reset Password</Button>
                      {(role === "superadmin" || (role === "admin" && u.role === "manager")) && (
                        <Button size="small" onClick={() => openManageUserTenants(u)}>
                          Manage Tenants
                        </Button>
                      )}
                    </>
                  )}
                </Stack>
              ))}
            </Stack>
            <Stack direction="row" justifyContent="center" sx={{ mt: 1 }}>
              <Pagination
                count={Math.max(1, Math.ceil(adminsTotal / PAGE_SIZE))}
                page={adminsPage}
                onChange={(_, value) => setAdminsPage(value)}
                size="small"
              />
            </Stack>
          </CardContent>
        </Card>
      )}

      {section === "users" && usersSubsection === "visitors" && (
        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent>
                <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1} flexWrap="wrap" gap={1}>
                  <Typography variant="h6">Visitors</Typography>
                  <Chip size="small" variant="outlined" label={`${visitorsTotal} total`} />
                </Stack>
                <List dense>
                  {visitors.map((v) => (
                    <ListItemButton
                      key={v.visitor_id}
                      selected={selectedVisitorId === v.visitor_id}
                      onClick={() => {
                        setVisitorChatsPage(1);
                        loadVisitorChats(v.visitor_id, 1);
                      }}
                    >
                      <ListItemText
                        primary={`${v.name || "Unknown"}${v.email ? ` (${v.email})` : ""}`}
                        secondary={`Chats: ${v.chat_count} | Last seen: ${v.last_seen_at || "N/A"}`}
                      />
                    </ListItemButton>
                  ))}
                </List>
                <Stack direction="row" justifyContent="center" sx={{ mt: 1 }}>
                  <Pagination
                    count={Math.max(1, Math.ceil(visitorsTotal / PAGE_SIZE))}
                    page={visitorsPage}
                    onChange={(_, value) => setVisitorsPage(value)}
                    size="small"
                  />
                </Stack>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent>
                <Typography variant="h6" mb={1}>Visitor Chats</Typography>
                {selectedVisitorId ? (
                  <>
                    <List dense>
                      {visitorChats.map((s) => (
                        <ListItemButton
                          key={s.id}
                          selected={selectedVisitorSessionId === s.id}
                          onClick={() => loadVisitorSession(s.id)}
                        >
                          <ListItemText
                            primary={s.title || s.id}
                            secondary={`${s.last_message_at || "N/A"} | 👍 ${s?.feedback_summary?.up || 0} 👎 ${s?.feedback_summary?.down || 0}`}
                          />
                        </ListItemButton>
                      ))}
                    </List>
                    <Stack direction="row" justifyContent="center" sx={{ mt: 1 }}>
                      <Pagination
                        count={Math.max(1, Math.ceil(visitorChatsTotal / PAGE_SIZE))}
                        page={visitorChatsPage}
                        onChange={(_, value) => setVisitorChatsPage(value)}
                        size="small"
                      />
                    </Stack>
                  </>
                ) : (
                  <Typography color="text.secondary">Select a user to view chats.</Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="h6">Conversation</Typography>
                  <Button size="small" onClick={exportTranscript} disabled={!selectedVisitorSessionId}>Export</Button>
                </Stack>
                {!selectedVisitorId ? (
                  <Typography color="text.secondary">Select a visitor first.</Typography>
                ) : !selectedVisitorSessionId ? (
                  <Typography color="text.secondary">Select a visitor chat to view transcript.</Typography>
                ) : (
                  <Stack spacing={1.5} sx={{ maxHeight: 560, overflowY: "auto" }}>
                    {messages.map((m) => (
                      <Box key={m.id} sx={{ p: 1.5, borderRadius: 1, bgcolor: m.sender_type === "assistant" ? "grey.100" : "primary.50" }}>
                        <Typography variant="caption" color="text.secondary">{m.sender_type}</Typography>
                        <Typography sx={{ wordBreak: "break-word" }}>{m.content}</Typography>
                        {m.sender_type === "assistant" && (
                          <Stack direction="row" spacing={1} sx={{ mt: 0.5, flexWrap: "wrap" }}>
                            <Chip size="small" label={`Prompt ${m?.token_usage?.prompt_tokens || 0}`} />
                            <Chip size="small" label={`Completion ${m?.token_usage?.completion_tokens || 0}`} />
                            <Chip size="small" label={`Total ${m?.token_usage?.total_tokens || 0}`} />
                          </Stack>
                        )}
                      </Box>
                    ))}
                  </Stack>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {section === "settings" && settingsSubsection === "security" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Tenant Security and Quota Controls</Typography>
            <Stack spacing={2}>
              <TextField
                label="Monthly Visitor Message Limit"
                type="number"
                value={monthlyMessageLimit}
                onChange={(e) => setMonthlyMessageLimit(e.target.value)}
                disabled={role !== "superadmin"}
                sx={{ maxWidth: 360 }}
              />
              <TextField
                label="Quota Reached Message"
                value={quotaReachedMessage}
                onChange={(e) => setQuotaReachedMessage(e.target.value)}
                fullWidth
              />
              <TextField
                label="CORS Allowed Origins (comma-separated)"
                value={corsAllowedOrigins}
                onChange={(e) => setCorsAllowedOrigins(e.target.value)}
                fullWidth
              />
              <TextField
                label="Idle Rating Wait (seconds)"
                type="number"
                value={idleRatingWaitSeconds}
                onChange={(e) => setIdleRatingWaitSeconds(e.target.value)}
                sx={{ maxWidth: 360 }}
              />
              <Button variant="contained" onClick={saveSecuritySettings} disabled={!effectiveTenantId}>
                Save security settings
              </Button>

              <Typography variant="subtitle1">Blocked IPs</Typography>
              <Stack direction="row" spacing={1}>
                <TextField label="IP address" value={newBlockedIp} onChange={(e) => setNewBlockedIp(e.target.value)} />
                <TextField label="Reason" value={newBlockedIpReason} onChange={(e) => setNewBlockedIpReason(e.target.value)} />
                <Button variant="outlined" onClick={addBlockedIp}>Add IP</Button>
              </Stack>
              <Stack spacing={1}>
                {blockedIps.map((item) => (
                  <Stack key={item.id} direction="row" spacing={1} alignItems="center">
                    <Chip label={item.ip_address} />
                    {item.reason && <Chip variant="outlined" label={item.reason} />}
                    <Button size="small" color="error" onClick={() => removeBlockedIp(item.id)}>Remove</Button>
                  </Stack>
                ))}
              </Stack>

              <Typography variant="subtitle1">Blocked Countries (GeoIP ISO alpha-2)</Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <FormControl sx={{ minWidth: 280 }}>
                  <InputLabel id="blocked-country-select-label">Country</InputLabel>
                  <Select
                    labelId="blocked-country-select-label"
                    label="Country"
                    value={newBlockedCountry}
                    onChange={(e) => setNewBlockedCountry(e.target.value)}
                  >
                    <MenuItem value="">
                      <em>Select…</em>
                    </MenuItem>
                    {countryReference.map((c) => (
                      <MenuItem key={c.code} value={c.code}>
                        {c.name} ({c.code})
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField label="Reason" value={newBlockedCountryReason} onChange={(e) => setNewBlockedCountryReason(e.target.value)} sx={{ minWidth: 200 }} />
                <Button variant="outlined" onClick={addBlockedCountry} disabled={!effectiveTenantId}>
                  Add Country
                </Button>
              </Stack>
              <Stack spacing={1}>
                {blockedCountries.map((item) => (
                  <Stack key={item.id} direction="row" spacing={1} alignItems="center">
                    <Chip
                      label={
                        countryLabelByCode[item.country_code]
                          ? `${countryLabelByCode[item.country_code]} (${item.country_code})`
                          : item.country_code
                      }
                    />
                    {item.reason && <Chip variant="outlined" label={item.reason} />}
                    <Button size="small" color="error" onClick={() => removeBlockedCountry(item.id)}>Remove</Button>
                  </Stack>
                ))}
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      )}

      {section === "settings" && settingsSubsection === "branding" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Tenant Branding and Widget Settings</Typography>
            <Stack spacing={2}>
              <TextField label="Brand Name" value={brandName} onChange={(e) => setBrandName(e.target.value)} fullWidth />
              <TextField
                label="Widget Primary Color"
                value={widgetPrimaryColor}
                onChange={(e) => setWidgetPrimaryColor(e.target.value)}
                placeholder="#bf362e"
                fullWidth
              />
              <TextField
                label="Widget website URL (https://…)"
                value={widgetWebsiteUrl}
                onChange={(e) => setWidgetWebsiteUrl(e.target.value)}
                placeholder="https://example.com"
                fullWidth
              />
              <TextField
                label="Vector primary source_type (Qdrant payload)"
                value={widgetSourceType}
                onChange={(e) => setWidgetSourceType(e.target.value)}
                placeholder="e.g. mrnwebdesigns_ie — empty uses default"
                helperText="Must match indexed payload source_type for primary search; secondary bucket remains external."
                fullWidth
              />
              <TextField
                label="User message bubble color"
                value={widgetUserMessageColor}
                onChange={(e) => setWidgetUserMessageColor(e.target.value)}
                placeholder="#bf362e"
                fullWidth
              />
              <TextField
                label="Bot message bubble color"
                value={widgetBotMessageColor}
                onChange={(e) => setWidgetBotMessageColor(e.target.value)}
                placeholder="#d5bbb9"
                fullWidth
              />
              <TextField
                label="User message text color"
                value={widgetUserMessageTextColor}
                onChange={(e) => setWidgetUserMessageTextColor(e.target.value)}
                placeholder="#ffffff"
                helperText="Hex color for text on the user bubble (contrast with bubble background)."
                fullWidth
              />
              <TextField
                label="Bot message text color"
                value={widgetBotMessageTextColor}
                onChange={(e) => setWidgetBotMessageTextColor(e.target.value)}
                placeholder="#1a1a1a"
                helperText="Hex color for text on the bot bubble (contrast with bubble background)."
                fullWidth
              />
              <TextField label="Widget Header Title" value={widgetHeaderTitle} onChange={(e) => setWidgetHeaderTitle(e.target.value)} fullWidth />
              <TextField
                label="Welcome Message"
                value={widgetWelcomeMessage}
                onChange={(e) => setWidgetWelcomeMessage(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
              <TextField
                label="Privacy Policy URL"
                value={privacyPolicyUrl}
                onChange={(e) => setPrivacyPolicyUrl(e.target.value)}
                fullWidth
              />
              <Stack direction="row" spacing={2} alignItems="flex-start">
                {brandingAvatarPreviewSrc ? (
                  <Box component="img" src={brandingAvatarPreviewSrc} alt="Current widget avatar" sx={{ width: 96, height: 96, borderRadius: 1, objectFit: "cover", border: "1px solid", borderColor: "divider" }} />
                ) : (
                  <Box
                    sx={{
                      width: 96,
                      height: 96,
                      borderRadius: 1,
                      border: "1px dashed",
                      borderColor: "divider",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "text.secondary",
                      typography: "caption",
                      textAlign: "center",
                      px: 1,
                    }}
                  >
                    {clearBrandingAvatar ? "Avatar removed after save" : "No avatar"}
                  </Box>
                )}
                <Stack spacing={1}>
                  <Button variant="outlined" component="label">
                    {avatarUpload ? `Selected: ${avatarUpload.name}` : "Upload avatar (max 10MB)"}
                    <input
                      hidden
                      type="file"
                      accept="image/*"
                      onChange={(e) => {
                        setAvatarUpload(e.target.files?.[0] || null);
                        if (e.target.files?.[0]) setClearBrandingAvatar(false);
                      }}
                    />
                  </Button>
                  {avatarUpload ? (
                    <Button
                      variant="text"
                      size="small"
                      onClick={() => setAvatarUpload(null)}
                    >
                      Discard selected file
                    </Button>
                  ) : null}
                  {selectedTenant?.avatar_url ? (
                    <Button
                      variant="text"
                      color="error"
                      size="small"
                      disabled={!!avatarUpload}
                      onClick={() => setClearBrandingAvatar((v) => !v)}
                    >
                      {clearBrandingAvatar ? "Undo remove" : "Remove avatar"}
                    </Button>
                  ) : null}
                </Stack>
              </Stack>
              <Button variant="contained" onClick={saveBrandingConfig} disabled={!sourceTenantId}>Save Branding</Button>
            </Stack>
          </CardContent>
        </Card>
      )}

      {section === "settings" && settingsSubsection === "moderation" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Automated replies</Typography>
            <Typography variant="body2" color="text.secondary" mb={2}>
              Block words enforce moderation when a trigger matches. Quick replies are fuzzy-matched friendly canned answers (before search).
            </Typography>
            <Tabs value={moderationPanel} onChange={(_, v) => setModerationPanel(v)} sx={{ mb: 2 }}>
              <Tab label="Block word policies" />
              <Tab label="Quick replies (fuzzy)" />
            </Tabs>
            {moderationPanel === 0 && (
            <Stack spacing={2}>
              <Stack direction="row" spacing={1}>
                <TextField
                  label="Category name"
                  value={newCategoryName}
                  onChange={(e) => setNewCategoryName(e.target.value)}
                />
                <FormControl sx={{ minWidth: 160 }}>
                  <InputLabel>Match Mode</InputLabel>
                  <Select label="Match Mode" value={newCategoryMode} onChange={(e) => setNewCategoryMode(e.target.value)}>
                    <MenuItem value="exact">Exact</MenuItem>
                    <MenuItem value="substring">Substring</MenuItem>
                    <MenuItem value="regex">Regex</MenuItem>
                  </Select>
                </FormControl>
              </Stack>
              <TextField
                label="Category response message"
                value={newCategoryResponse}
                onChange={(e) => setNewCategoryResponse(e.target.value)}
                fullWidth
              />
              <Button variant="contained" onClick={createBlockWordCategory} disabled={!newCategoryName.trim() || !newCategoryResponse.trim()}>
                Add Category
              </Button>
              <Stack spacing={1.5}>
                {blockWordCategories.map((category) => (
                  <Card key={category.id} variant="outlined">
                    <CardContent>
                      <Stack direction="row" spacing={1} alignItems="center" mb={1}>
                        <Chip label={category.name} />
                        <Chip variant="outlined" label={category.match_mode} />
                        <Button size="small" color="error" onClick={() => deleteBlockWordCategory(category.id)}>Delete Category</Button>
                      </Stack>
                      <Typography variant="body2" color="text.secondary" mb={1}>{category.response_message}</Typography>
                      <Stack direction="row" spacing={1} mb={1}>
                        <TextField
                          size="small"
                          label="Add trigger word"
                          value={newWordByCategory[category.id] || ""}
                          onChange={(e) => setNewWordByCategory((prev) => ({ ...prev, [category.id]: e.target.value }))}
                        />
                        <Button size="small" variant="outlined" onClick={() => addWordToCategory(category.id)}>Add Word</Button>
                      </Stack>
                      <Stack direction="row" spacing={1} flexWrap="wrap">
                        {(category.words || []).map((w) => (
                          <Chip
                            key={w.id}
                            label={w.word}
                            onDelete={() => deleteWordFromCategory(category.id, w.id)}
                            sx={{ mb: 1 }}
                          />
                        ))}
                      </Stack>
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            </Stack>
            )}
            {moderationPanel === 1 && (
            <Stack spacing={2}>
              <Alert severity="info">
                Response text supports placeholders: a dollar sign plus curly braces around brand_name, assistant_name (from widget header title), or website_url. Deleting a seeded row restores the built-in neutral default for that trigger. Add rows for pricing, contact, emergency wording, etc.
              </Alert>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <TextField label="Category (e.g. greeting)" value={newQrCategory} onChange={(e) => setNewQrCategory(e.target.value)} sx={{ minWidth: 180 }} />
                <TextField label="Trigger phrase" value={newQrTrigger} onChange={(e) => setNewQrTrigger(e.target.value)} sx={{ minWidth: 200 }} placeholder="hello" />
                <TextField label="Priority" value={newQrPriority} onChange={(e) => setNewQrPriority(e.target.value)} sx={{ width: 100 }} />
                <TextField label="Fuzzy threshold (50–100, empty=default)" value={newQrThreshold} onChange={(e) => setNewQrThreshold(e.target.value)} sx={{ minWidth: 220 }} />
              </Stack>
              <TextField
                label="Response template"
                value={newQrTemplate}
                onChange={(e) => setNewQrTemplate(e.target.value)}
                fullWidth
                multiline
                minRows={2}
              />
              <Button variant="contained" onClick={createQuickReply} disabled={!effectiveTenantId || !newQrTrigger.trim() || !newQrTemplate.trim()}>
                Add quick reply
              </Button>
              <Stack spacing={1}>
                {quickReplies.map((row) => (
                  <Card key={row.id} variant="outlined">
                    <CardContent>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap mb={1}>
                        <Chip label={row.category} size="small" />
                        <Stack direction="row" alignItems="center" spacing={0.5}>
                          <Typography variant="caption">Enabled</Typography>
                          <Switch checked={row.enabled} onChange={(e) => setQuickReplyEnabled(row, e.target.checked)} size="small" />
                        </Stack>
                        <Button size="small" color="error" onClick={() => deleteQuickReply(row.id)}>Delete</Button>
                      </Stack>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" mb={1}>
                        <TextField
                          size="small"
                          label="Category"
                          value={(quickReplyDrafts[row.id]?.category ?? row.category) || ""}
                          onChange={(e) => updateQuickReplyDraft(row.id, { category: e.target.value })}
                          sx={{ minWidth: 160 }}
                        />
                        <TextField
                          size="small"
                          label="Trigger"
                          value={(quickReplyDrafts[row.id]?.trigger_phrase ?? row.trigger_phrase) || ""}
                          onChange={(e) => updateQuickReplyDraft(row.id, { trigger_phrase: e.target.value })}
                          sx={{ minWidth: 200 }}
                        />
                        <TextField
                          size="small"
                          label="Priority"
                          value={String(quickReplyDrafts[row.id]?.priority ?? row.priority ?? 0)}
                          onChange={(e) => updateQuickReplyDraft(row.id, { priority: e.target.value })}
                          sx={{ width: 100 }}
                        />
                        <TextField
                          size="small"
                          label="Threshold"
                          value={String(quickReplyDrafts[row.id]?.similarity_threshold ?? (row.similarity_threshold ?? ""))}
                          onChange={(e) => updateQuickReplyDraft(row.id, { similarity_threshold: e.target.value })}
                          sx={{ width: 120 }}
                        />
                      </Stack>
                      <TextField
                        size="small"
                        label="Response template"
                        value={(quickReplyDrafts[row.id]?.response_template ?? row.response_template) || ""}
                        onChange={(e) => updateQuickReplyDraft(row.id, { response_template: e.target.value })}
                        fullWidth
                        multiline
                        minRows={2}
                      />
                      <Stack direction="row" spacing={1} mt={1}>
                        <Button
                          size="small"
                          variant="contained"
                          onClick={() => saveQuickReplyDraft(row)}
                          disabled={!isQuickReplyDirty(row)}
                        >
                          Save
                        </Button>
                        <Button size="small" variant="text" onClick={() => resetQuickReplyDraft(row)}>
                          Reset
                        </Button>
                      </Stack>
                      <Typography variant="caption" color="primary" sx={{ mt: 1, display: "block" }}>
                        Preview: {row.rendered_preview}
                      </Typography>
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            </Stack>
            )}
          </CardContent>
        </Card>
      )}

      {section === "settings" && settingsSubsection === "db-settings" && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Tenant Source Database Settings</Typography>
            <Typography color="text.secondary" mb={2}>
              Configure database connection details used to generate embeddings for each tenant.
            </Typography>
            <Stack spacing={2}>
              {canSelectTenant && (
                <FormControl size="small" sx={{ maxWidth: 420 }}>
                  <InputLabel>Tenant</InputLabel>
                  <Select
                    label="Tenant"
                    value={sourceTenantId}
                    onChange={(e) => persistSourceTenantId(e.target.value)}
                  >
                    {tenants.map((t) => (
                      <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
              <TextField
                label="Source DB URL (DSN)"
                value={sourceDbUrl}
                onChange={(e) => setSourceDbUrl(e.target.value)}
                helperText="Example: mysql://user:password@host:3306/database"
                fullWidth
              />
              <TextField
                label="Source DB Type"
                value={sourceDbType}
                onChange={(e) => setSourceDbType(e.target.value)}
                fullWidth
              />
              <FormControl fullWidth>
                <InputLabel>Source Mode</InputLabel>
                <Select
                  label="Source Mode"
                  value={sourceMode}
                  onChange={(e) => setSourceMode(e.target.value)}
                >
                  <MenuItem value="wordpress">WordPress only</MenuItem>
                  <MenuItem value="static">Static URLs only</MenuItem>
                  <MenuItem value="mixed">WordPress + Static URLs</MenuItem>
                </Select>
              </FormControl>
              <TextField
                label="Table Prefix"
                value={sourceTablePrefix}
                onChange={(e) => setSourceTablePrefix(e.target.value)}
                fullWidth
              />
              <TextField
                label="URL Table"
                value={sourceUrlTable}
                onChange={(e) => setSourceUrlTable(e.target.value)}
                fullWidth
              />
              <TextField
                label="Canonical Base URL"
                value={sourceCanonicalBaseUrl}
                onChange={(e) => setSourceCanonicalBaseUrl(e.target.value)}
                helperText="Used to normalize equivalent hosts (e.g. prod/staging)"
                fullWidth
              />
              <TextField
                label="Domain Aliases"
                value={sourceDomainAliases}
                onChange={(e) => setSourceDomainAliases(e.target.value)}
                helperText="Comma or newline separated URLs to treat as aliases"
                fullWidth
                multiline
                minRows={2}
              />
              <TextField
                label="Static Source URLs (JSON array or newline list)"
                value={sourceStaticUrlsJson}
                onChange={(e) => setSourceStaticUrlsJson(e.target.value)}
                helperText='Examples: ["https://www.chilliapple.co.uk/"] or one URL per line'
                fullWidth
                multiline
                minRows={6}
              />
              <Stack direction="row" spacing={1} alignItems="center">
                <Button variant="contained" onClick={saveSourceConfig} disabled={!sourceTenantId}>Save Source Settings</Button>
                {selectedTenant && <Chip label={selectedTenant.name} />}
                {role === "superadmin" && selectedTenant && (
                  <Chip variant="outlined" label={`Tenant ID: ${selectedTenant.id}`} />
                )}
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      )}
      </Box>
      </Box>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{role === "superadmin" ? "Create Admin/Manager" : "Create Manager"}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} fullWidth />
            <TextField label="Password" type="password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} fullWidth />
            <FormControl fullWidth>
              <InputLabel>Role</InputLabel>
              <Select label="Role" value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)} disabled={role === "admin"}>
                {role === "superadmin" && <MenuItem value="admin">Admin</MenuItem>}
                <MenuItem value="manager">Manager</MenuItem>
              </Select>
            </FormControl>
            <FormControl fullWidth>
              <InputLabel>Tenant Option</InputLabel>
              <Select label="Tenant Option" value={adminTenantMode} onChange={(e) => setAdminTenantMode(e.target.value)}>
                <MenuItem value="existing">Use Existing Tenant</MenuItem>
                <MenuItem value="new">Create New Tenant</MenuItem>
              </Select>
            </FormControl>
            {adminTenantMode === "new" ? (
              <TextField
                label="New Tenant Name"
                value={newTenantName}
                onChange={(e) => setNewTenantName(e.target.value)}
                fullWidth
              />
            ) : (
              <FormControl fullWidth>
                <InputLabel>Tenant</InputLabel>
                <Select label="Tenant" value={adminTenantId} onChange={(e) => setAdminTenantId(e.target.value)}>
                  {tenants.map((t) => (
                    <MenuItem key={t.id} value={t.id}>
                      {t.name}
                      {role === "superadmin" ? ` (${t.id})` : ""}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            onClick={createAdmin}
            variant="contained"
            disabled={
              !adminEmail ||
              !adminPassword ||
              !newUserRole ||
              (adminTenantMode === "new" ? !newTenantName.trim() : !adminTenantId)
            }
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={manageTenantsOpen} onClose={() => setManageTenantsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Manage User Tenants</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {manageTenantUser ? `User: ${manageTenantUser.email} (${manageTenantUser.role})` : ""}
            </Typography>
            <FormControl fullWidth>
              {manageTenantUser?.role === "manager" ? (
                <RadioGroup
                  value={manageTenantIds[0] || ""}
                  onChange={(e) => setManageTenantIds(e.target.value ? [e.target.value] : [])}
                >
                  {tenants.map((t) => (
                    <FormControlLabel
                      key={t.id}
                      value={t.id}
                      control={<Radio size="small" />}
                      label={`${t.name}${role === "superadmin" ? ` (${t.id})` : ""}`}
                    />
                  ))}
                </RadioGroup>
              ) : (
                <FormGroup>
                  {tenants.map((t) => (
                    <FormControlLabel
                      key={t.id}
                      control={
                        <Checkbox
                          size="small"
                          checked={manageTenantIds.includes(t.id)}
                          onChange={(e) => {
                            setManageTenantIds((prev) =>
                              e.target.checked ? [...new Set([...prev, t.id])] : prev.filter((id) => id !== t.id)
                            );
                          }}
                        />
                      }
                      label={`${t.name}${role === "superadmin" ? ` (${t.id})` : ""}`}
                    />
                  ))}
                </FormGroup>
              )}
            </FormControl>
            <Typography variant="caption" color="text.secondary">
              Managers can only have one tenant. Admins can have multiple.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setManageTenantsOpen(false)} disabled={manageTenantSaving}>Cancel</Button>
          <Button
            variant="contained"
            onClick={saveManageUserTenants}
            disabled={
              !manageTenantUser ||
              manageTenantSaving ||
              (manageTenantUser?.role === "manager" ? manageTenantIds.length !== 1 : false)
            }
          >
            Save Associations
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={createTenantOpen} onClose={() => setCreateTenantOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Create Tenant</DialogTitle>
        <DialogContent>
          <TextField
            sx={{ mt: 1 }}
            label="Tenant name"
            value={newStandaloneTenantName}
            onChange={(e) => setNewStandaloneTenantName(e.target.value)}
            fullWidth
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateTenantOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={createStandaloneTenant} disabled={!newStandaloneTenantName.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={resetOpen} onClose={() => setResetOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Reset User Password</DialogTitle>
        <DialogContent>
          <TextField
            sx={{ mt: 1 }}
            type="password"
            label="New Password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            fullWidth
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={resetPassword} disabled={!newPassword}>Reset</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default AdminDashboard;
