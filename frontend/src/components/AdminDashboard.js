import React, { useCallback, useEffect, useState } from "react";
import { client } from "../api";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  Grid,
  LinearProgress,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";

const AdminDashboard = ({ role, tenantId }) => {
  const [sessions, setSessions] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [users, setUsers] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminTenantId, setAdminTenantId] = useState("");
  const [adminTenantMode, setAdminTenantMode] = useState("existing");
  const [newTenantName, setNewTenantName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [sourceTenantId, setSourceTenantId] = useState("");
  const [sourceDbUrl, setSourceDbUrl] = useState("");
  const [sourceDbType, setSourceDbType] = useState("mysql");
  const [sourceTablePrefix, setSourceTablePrefix] = useState("wp_");
  const [sourceUrlTable, setSourceUrlTable] = useState("wp_custom_urls");
  const [resetOpen, setResetOpen] = useState(false);
  const [resetUserId, setResetUserId] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [success, setSuccess] = useState("");
  const effectiveTenantId = role === "superadmin" ? (sourceTenantId || undefined) : (tenantId || undefined);

  const load = useCallback(async (query = searchQuery) => {
    try {
      const [chatRes, jobRes, usersRes, tenantsRes] = await Promise.all([
        client.get("/api/admin/chats", { params: { q: query || undefined, tenant_id: effectiveTenantId } }),
        client.get("/api/reindex/jobs", { params: { tenant_id: effectiveTenantId } }),
        client.get("/api/admin/users", { params: { tenant_id: effectiveTenantId } }),
        client.get("/api/admin/tenants"),
      ]);
      setSessions(chatRes.data);
      setJobs(jobRes.data);
      setUsers(usersRes.data);
      setTenants(tenantsRes.data);
      if (!sourceTenantId && tenantsRes.data.length > 0) {
        const firstTenant = role === "superadmin" ? tenantsRes.data[0].id : tenantId;
        setSourceTenantId(firstTenant || "");
      }
      if (!adminTenantId && tenantsRes.data.length > 0) {
        const firstTenant = role === "superadmin" ? tenantsRes.data[0].id : tenantId;
        setAdminTenantId(firstTenant || "");
      }
      setError("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading dashboard data");
    }
  }, [adminTenantId, effectiveTenantId, role, searchQuery, sourceTenantId, tenantId]);

  const refreshJobsOnly = useCallback(async () => {
    try {
      const { data } = await client.get("/api/reindex/jobs", { params: { tenant_id: effectiveTenantId } });
      setJobs(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed loading jobs");
    }
  }, [effectiveTenantId]);

  useEffect(() => {
    load("");
  }, [load]);

  useEffect(() => {
    if (tab !== 1) return undefined;
    const id = setInterval(() => {
      refreshJobsOnly();
    }, 5000);
    return () => clearInterval(id);
  }, [tab, refreshJobsOnly]);

  useEffect(() => {
    if (role !== "superadmin") return;
    setSelected(null);
    setMessages([]);
  }, [role, sourceTenantId]);

  useEffect(() => {
    const t = tenants.find((tenant) => tenant.id === sourceTenantId);
    if (!t) return;
    setSourceDbUrl(t.source_db_url || "");
    setSourceDbType(t.source_db_type || "mysql");
    setSourceTablePrefix(t.source_table_prefix || "wp_");
    setSourceUrlTable(t.source_url_table || "wp_custom_urls");
  }, [sourceTenantId, tenants]);

  const loadSession = async (id) => {
    setSelected(id);
    const { data } = await client.get(`/api/admin/chats/${id}`);
    setMessages(data);
  };

  const reindex = async () => {
    await client.post("/api/reindex", role === "superadmin" ? { tenant_id: sourceTenantId || undefined } : { tenant_id: tenantId });
    load();
  };

  const createAdmin = async () => {
    try {
      const payload = {
        email: adminEmail,
        password: adminPassword,
      };
      if (adminTenantMode === "new") {
        payload.new_tenant_name = newTenantName.trim() || undefined;
      } else {
        payload.tenant_id = adminTenantId || undefined;
      }
      await client.post("/api/admin/users", {
        ...payload,
      });
      setSuccess("Admin created successfully");
      setCreateOpen(false);
      setAdminEmail("");
      setAdminPassword("");
      setAdminTenantId("");
      setAdminTenantMode("existing");
      setNewTenantName("");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create admin");
    }
  };

  const updateUserStatus = async (userId, isActive) => {
    try {
      await client.post(`/api/admin/users/${userId}/status`, { is_active: isActive });
      setSuccess(`User ${isActive ? "activated" : "deactivated"} successfully`);
      await load();
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

  const saveSourceConfig = async () => {
    try {
      await client.patch(`/api/admin/tenants/${sourceTenantId}/source-config`, {
        source_db_url: sourceDbUrl || null,
        source_db_type: sourceDbType || null,
        source_table_prefix: sourceTablePrefix || null,
        source_url_table: sourceUrlTable || null,
      });
      setSuccess("Tenant source settings updated");
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to update source settings");
    }
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

  const selectedTenant = tenants.find((t) => t.id === sourceTenantId);

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
        <Box>
          <Typography variant="h4" fontWeight={700}>Admin Dashboard</Typography>
          <Typography color="text.secondary">{role === "superadmin" ? "Global control center" : "Tenant control center"}</Typography>
        </Box>
        <Stack direction="row" spacing={1} alignItems="center">
          {role === "superadmin" && (
            <FormControl size="small" sx={{ minWidth: 220 }}>
              <InputLabel>Tenant</InputLabel>
              <Select
                label="Tenant"
                value={sourceTenantId}
                onChange={(e) => setSourceTenantId(e.target.value)}
              >
                {tenants.map((t) => (
                  <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          <Button variant="outlined" onClick={reindex}>Trigger Reindex</Button>
          {role === "superadmin" && <Button variant="contained" onClick={() => setCreateOpen(true)}>Add Admin</Button>}
        </Stack>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Chats" />
        <Tab label="Jobs" />
        <Tab label="Users" />
        <Tab label="Tenant Sources" />
      </Tabs>

      {tab === 0 && (
        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} mb={1} alignItems="center">
                  <Typography variant="h6">Tenant Chats</Typography>
                </Stack>
                <TextField
                  size="small"
                  label="Search chats"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") load(e.currentTarget.value);
                  }}
                  fullWidth
                  sx={{ mb: 1 }}
                />
                <List dense>
                  {sessions.map((s) => (
                    <ListItemButton key={s.id} selected={selected === s.id} onClick={() => loadSession(s.id)}>
                      <ListItemText primary={s.title || s.id} secondary={`${s.id} | ${s.last_message_at}`} />
                    </ListItemButton>
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={8}>
            <Card>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                  <Typography variant="h6">Conversation</Typography>
                  <Button size="small" onClick={exportTranscript} disabled={!selected}>Export</Button>
                </Stack>
                {selected ? (
                  <Stack spacing={1.5}>
                    {messages.map((m) => (
                      <Box key={m.id} sx={{ p: 1.5, borderRadius: 1, bgcolor: m.sender_type === "assistant" ? "grey.100" : "primary.50" }}>
                        <Typography variant="caption" color="text.secondary">{m.sender_type}</Typography>
                        <Typography>{m.content}</Typography>
                      </Box>
                    ))}
                  </Stack>
                ) : (
                  <Typography color="text.secondary">Select a chat session.</Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {tab === 1 && (
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
                    {!!j.meta?.progress && (
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

      {tab === 2 && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Users</Typography>
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
                    </>
                  )}
                </Stack>
              ))}
            </Stack>
          </CardContent>
        </Card>
      )}

      {tab === 3 && (
        <Card>
          <CardContent>
            <Typography variant="h6" mb={1}>Tenant Source Database Settings</Typography>
            <Typography color="text.secondary" mb={2}>
              Configure database connection details used to generate embeddings for each tenant.
            </Typography>
            <Stack spacing={2}>
              {role === "superadmin" && (
                <FormControl size="small" sx={{ maxWidth: 420 }}>
                  <InputLabel>Tenant</InputLabel>
                  <Select
                    label="Tenant"
                    value={sourceTenantId}
                    onChange={(e) => setSourceTenantId(e.target.value)}
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
              <Stack direction="row" spacing={1} alignItems="center">
                <Button variant="contained" onClick={saveSourceConfig} disabled={!sourceTenantId}>Save Source Settings</Button>
                {selectedTenant && <Chip label={selectedTenant.name} />}
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      )}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Admin</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField label="Email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} fullWidth />
            <TextField label="Password" type="password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} fullWidth />
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
                    <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
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
              (adminTenantMode === "new" ? !newTenantName.trim() : !adminTenantId)
            }
          >
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
