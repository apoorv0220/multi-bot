import axios from "axios";

const apiUrl = process.env.REACT_APP_API_URL || "http://localhost:8043";

export const client = axios.create({
  baseURL: apiUrl,
});

export function setAuthToken(token) {
  if (token) {
    client.defaults.headers.common.Authorization = `Bearer ${token}`;
    localStorage.setItem("token", token);
  } else {
    delete client.defaults.headers.common.Authorization;
    localStorage.removeItem("token");
  }
}

export function loadToken() {
  const token = localStorage.getItem("token");
  if (token) {
    setAuthToken(token);
  }
  return token;
}
