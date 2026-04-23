import React, { useState, useEffect } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppBar, Box, Button, Container, CssBaseline, Stack, Toolbar, Typography } from '@mui/material';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import ChatWidget from './components/ChatWidget';
import LoginPage from './components/LoginPage';
import AdminDashboard from './components/AdminDashboard';
import { loadToken, setAuthToken } from './api';

function AppContent({ auth, onLogin, onLogout }) {
  const location = useLocation();
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
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 700 }}>Migraine Chatbot Control</Typography>
            {auth && (
              <Stack direction="row" spacing={2} alignItems="center">
                <Link to="/admin/chat">Chat</Link>
                <Link to="/admin/dashboard">Dashboard</Link>
                <Button onClick={onLogout} variant="outlined">Logout</Button>
              </Stack>
            )}
          </Toolbar>
        </AppBar>
      )}
      <Container maxWidth="xl" disableGutters>
        <Box sx={{ minHeight: isAdminRoute ? "calc(100vh - 64px)" : "100vh" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/admin/chat" replace />} />
            <Route path="/admin/chat" element={auth ? <ChatWidget mode="admin" /> : <LoginPage onLogin={onLogin} />} />
            <Route path="/admin/dashboard" element={auth ? <AdminDashboard role={auth.role} tenantId={auth.tenant_id} /> : <LoginPage onLogin={onLogin} />} />
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
      if (cachedRole) setAuth({ role: cachedRole, tenant_id: cachedTenant });
    }
  }, []);

  const onLogin = (data) => {
    setAuth(data);
    localStorage.setItem("role", data.role);
    localStorage.setItem("tenant_id", data.tenant_id || "");
  };

  const onLogout = () => {
    setAuthToken(null);
    setAuth(null);
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