import axios from "axios";

const apiUrl = process.env.REACT_APP_API_URL || "";

export const client = axios.create({
  baseURL: apiUrl || undefined,
});

let authFailureHandler = () => {};

/** Called after clearing the token on 401 (e.g. navigate to login). */
export function setAuthFailureHandler(fn) {
  authFailureHandler = typeof fn === "function" ? fn : () => {};
}

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const authHeader =
      err.config?.headers?.Authorization ||
      (err.config?.headers?.common && err.config.headers.common.Authorization);
    if (err?.response?.status === 401 && authHeader) {
      setAuthToken(null);
      try {
        authFailureHandler();
      } catch {
        /* ignore */
      }
    }
    return Promise.reject(err);
  },
);

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
