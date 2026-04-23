import React, { useState } from "react";
import { client, setAuthToken } from "../api";
import { Alert, Box, Button, Card, CardContent, Container, Stack, TextField, Typography } from "@mui/material";

const LoginPage = ({ onLogin }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const { data } = await client.post("/api/auth/login", { email, password });
      setAuthToken(data.access_token);
      onLogin(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Login failed");
    }
  };

  return (
    <Container maxWidth="sm">
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center" }}>
        <Card sx={{ width: "100%" }}>
          <CardContent sx={{ p: 4 }}>
            <Stack spacing={2}>
              <Typography variant="h4" fontWeight={700}>Sign in</Typography>
              <Typography color="text.secondary">Access your tenant dashboard and chatbot operations.</Typography>
              <Box component="form" onSubmit={submit}>
                <Stack spacing={2}>
                  <TextField label="Email" value={email} onChange={(e) => setEmail(e.target.value)} fullWidth />
                  <TextField type="password" label="Password" value={password} onChange={(e) => setPassword(e.target.value)} fullWidth />
                  <Button variant="contained" type="submit">Sign In</Button>
                </Stack>
              </Box>
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          </CardContent>
        </Card>
      </Box>
    </Container>
  );
};

export default LoginPage;
