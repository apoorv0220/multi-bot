import React, { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { AppBar, Box, Button, Container, CssBaseline, Stack, Toolbar, Typography } from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import ChatWidget from './components/ChatWidget';
import LoginPage from './components/LoginPage';
import AdminDashboard from './components/AdminDashboard';
import { loadToken, setAuthToken, setAuthFailureHandler } from './api';

function AppContent({ auth, onLogin, onLogout }) {
  const location = useLocation();
  const navigate = useNavigate();

  const handleSessionExpired = useCallback(() => {
    onLogout();
    navigate('/admin/dashboard/overview', { replace: true });
  }, [navigate, onLogout]);

  useEffect(() => {
    setAuthFailureHandler(handleSessionExpired);
    return () => setAuthFailureHandler(() => {});
  }, [handleSessionExpired]);
  const isAdminRoute = location.pathname.startsWith("/admin");
  const isEmbedRoute = location.pathname === "/embed";

  if (isEmbedRoute) {
    return <ChatWidget mode="public" />;
  }

  return (
    <>
      {isAdminRoute && (
        <AppBar position="static" color="inherit" elevation={1}>
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 700 }}>Chatbot Control</Typography>
            {auth && (
              <Stack direction="row" spacing={2} alignItems="center">
                <Link to="/admin/dashboard/overview">Dashboard</Link>
                <Button onClick={onLogout} variant="outlined">Logout</Button>
              </Stack>
            )}
          </Toolbar>
        </AppBar>
      )}
      <Container maxWidth="xl" disableGutters>
        <Box sx={{ minHeight: isAdminRoute ? "calc(100vh - 64px)" : "100vh" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/admin/dashboard/overview" replace />} />
            <Route path="/admin/chat" element={<Navigate to="/admin/dashboard/overview" replace />} />
            <Route path="/admin/dashboard/*" element={auth ? <AdminDashboard role={auth.role} tenantId={auth.tenant_id} tenantIds={auth.tenant_ids || []} /> : <LoginPage onLogin={onLogin} />} />
            <Route path="/admin/dashboard" element={<Navigate to="/admin/dashboard/overview" replace />} />
            <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
          </Routes>
        </Box>
      </Container>
    </>
  );
}

function App() {
  const [auth, setAuth] = useState(null);
  const theme = createTheme({
    palette: {
      mode: "light",
      primary: { main: "#0f62fe" },
      secondary: { main: "#6f42c1" },
      background: { default: "#f6f8fb" },
    },
    shape: { borderRadius: 10 },
  });

  useEffect(() => {
    if (loadToken()) {
      const cachedRole = localStorage.getItem("role");
      const cachedTenant = localStorage.getItem("tenant_id");
      const cachedTenantIdsRaw = localStorage.getItem("tenant_ids");
      let cachedTenantIds = [];
      if (cachedTenantIdsRaw) {
        try {
          cachedTenantIds = JSON.parse(cachedTenantIdsRaw);
        } catch (err) {
          cachedTenantIds = [];
        }
      }
      if (cachedRole) setAuth({ role: cachedRole, tenant_id: cachedTenant, tenant_ids: cachedTenantIds });
    }
  }, []);

  const onLogin = (data) => {
    setAuth(data);
    localStorage.setItem("role", data.role);
    localStorage.setItem("tenant_id", data.tenant_id || "");
    localStorage.setItem("tenant_ids", JSON.stringify(data.tenant_ids || []));
  };

  const onLogout = () => {
    setAuthToken(null);
    setAuth(null);
    localStorage.removeItem("role");
    localStorage.removeItem("tenant_id");
    localStorage.removeItem("tenant_ids");
    localStorage.removeItem("admin_dashboard_selected_tenant_id");
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <AppContent auth={auth} onLogin={onLogin} onLogout={onLogout} />
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App; 