/* API wrapper: talks to the FastAPI backend, attaches the bearer token,
   handles 401 by forcing re-login, and surfaces structured error payloads
   (Section 45.1's {code, message, details} envelope) to callers. */
const API_BASE = ""; // same-origin; backend serves the frontend too

const Auth = {
  get accessToken() { return localStorage.getItem("pcts_access_token"); },
  set accessToken(v) { v ? localStorage.setItem("pcts_access_token", v) : localStorage.removeItem("pcts_access_token"); },
  get refreshToken() { return localStorage.getItem("pcts_refresh_token"); },
  set refreshToken(v) { v ? localStorage.setItem("pcts_refresh_token", v) : localStorage.removeItem("pcts_refresh_token"); },
  get user() {
    try { return JSON.parse(localStorage.getItem("pcts_user") || "null"); } catch (e) { return null; }
  },
  set user(v) { v ? localStorage.setItem("pcts_user", JSON.stringify(v)) : localStorage.removeItem("pcts_user"); },
  clear() { this.accessToken = null; this.refreshToken = null; this.user = null; },
  hasPerm(...codes) {
    const u = this.user;
    if (!u || !u.permissions) return false;
    return codes.some((c) => u.permissions.includes(c));
  },
};

class ApiError extends Error {
  constructor(status, payload) {
    const msg = typeof payload === "object" && payload
      ? (payload.detail && payload.detail.message) || payload.detail || payload.message || JSON.stringify(payload)
      : String(payload);
    super(msg);
    this.status = status;
    this.payload = payload && payload.detail !== undefined ? payload.detail : payload;
  }
}

async function apiRequest(method, path, body, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (Auth.accessToken) headers["Authorization"] = "Bearer " + Auth.accessToken;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let resp;
  try {
    resp = await fetch(API_BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new ApiError(0, { message: "Network error: could not reach the server." });
  }

  if (resp.status === 401 && !opts.skipAuthRedirect) {
    Auth.clear();
    if (window.App && App.showLogin) App.showLogin("Your session has expired. Please sign in again.");
    throw new ApiError(401, { message: "Session expired." });
  }

  let payload = null;
  const text = await resp.text();
  if (text) {
    try { payload = JSON.parse(text); } catch (e) { payload = text; }
  }

  if (!resp.ok) {
    throw new ApiError(resp.status, payload);
  }
  return payload;
}

const Api = {
  get: (path) => apiRequest("GET", path),
  post: (path, body, opts) => apiRequest("POST", path, body, opts),
  patch: (path, body) => apiRequest("PATCH", path, body),
  put: (path, body) => apiRequest("PUT", path, body),
  del: (path) => apiRequest("DELETE", path),
};
