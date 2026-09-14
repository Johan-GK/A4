/* App shell: login flow, navigation (Section 48), router, dashboard,
   notifications, global search. */

const App = {
  pollHandle: null,

  init() {
    document.getElementById("login-form").addEventListener("submit", (e) => this.onLoginSubmit(e));
    document.getElementById("mfa-form").addEventListener("submit", (e) => this.onMfaSubmit(e));
    document.getElementById("logout-btn").addEventListener("click", () => this.logout());
    document.getElementById("nav-toggle").addEventListener("click", () => {
      document.getElementById("sidebar").classList.toggle("collapsed");
    });
    document.getElementById("notif-btn").addEventListener("click", () => this.toggleNotifPanel());
    document.getElementById("global-search").addEventListener("input", debounce((e) => this.onSearch(e.target.value), 300));
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#notif-btn") && !e.target.closest("#notif-panel")) {
        document.getElementById("notif-panel").hidden = true;
      }
      if (!e.target.closest("#global-search") && !e.target.closest("#search-results")) {
        document.getElementById("search-results").hidden = true;
      }
    });
    window.addEventListener("hashchange", () => this.route());

    if (Auth.accessToken && Auth.user) {
      this.showApp();
    } else {
      this.showLogin();
    }
  },

  showLogin(message) {
    if (this.pollHandle) clearInterval(this.pollHandle);
    document.getElementById("login-screen").hidden = false;
    document.getElementById("app-shell").hidden = true;
    document.getElementById("login-form").hidden = false;
    document.getElementById("mfa-form").hidden = true;
    document.getElementById("login-error").hidden = true;
    if (message) {
      const el = document.getElementById("login-error");
      el.textContent = message; el.hidden = false;
    }
  },

  async onLoginSubmit(e) {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    const errEl = document.getElementById("login-error");
    errEl.hidden = true;
    try {
      const result = await Api.post("/v1/auth/login", { username, password }, { skipAuthRedirect: true });
      if (result.mfaRequired) {
        this._loginTicket = result.loginTicket;
        document.getElementById("login-form").hidden = true;
        document.getElementById("mfa-form").hidden = false;
      } else {
        this.onLoginSuccess(result);
      }
    } catch (err) {
      errEl.textContent = apiErrorMessage(err);
      errEl.hidden = false;
    }
  },

  async onMfaSubmit(e) {
    e.preventDefault();
    const code = document.getElementById("mfa-code").value.trim();
    const errEl = document.getElementById("mfa-error");
    errEl.hidden = true;
    try {
      const result = await Api.post("/v1/auth/mfa/verify", { loginTicket: this._loginTicket, code }, { skipAuthRedirect: true });
      this.onLoginSuccess(result);
    } catch (err) {
      errEl.textContent = apiErrorMessage(err);
      errEl.hidden = false;
    }
  },

  onLoginSuccess(result) {
    Auth.accessToken = result.accessToken;
    Auth.refreshToken = result.refreshToken;
    Auth.user = result.user;
    this.showApp();
  },

  async logout() {
    try { await Api.post("/v1/auth/logout", {}); } catch (e) { /* ignore */ }
    Auth.clear();
    this.showLogin();
  },

  showApp() {
    document.getElementById("login-screen").hidden = true;
    document.getElementById("app-shell").hidden = false;
    const u = Auth.user;
    document.getElementById("user-name").textContent = u.name || u.username;
    document.getElementById("user-role").textContent = (u.roles || []).join(", ");
    this.renderNav();
    this.route();
    this.refreshNotifications();
    this.pollHandle = setInterval(() => this.refreshNotifications(), 25000);
  },

  NAV: [
    { group: "Overview", items: [
      { label: "Dashboard", route: "dashboard" },
    ]},
    { group: "Users & Roles", perm: ["MANAGE_USERS", "MANAGE_ROLES"], items: [
      { label: "Users", route: "users", perm: ["MANAGE_USERS"] },
      { label: "Roles & Permissions", route: "roles", perm: ["MANAGE_ROLES"] },
    ]},
    { group: "Production", perm: ["CREATE_ORDERS", "VIEW_ORDERS", "ALLOCATE_RESOURCES", "EXECUTE_PRODUCTION", "VIEW_PRODUCTION"], items: [
      { label: "Orders", route: "orders" },
      { label: "Production Runs", route: "runs" },
      { label: "Scheduling", route: "scheduling", perm: ["ALLOCATE_RESOURCES"] },
      { label: "Planning", route: "planning", perm: ["MANAGE_PROCESSES", "VIEW_PROCESSES"] },
    ]},
    { group: "Resources", items: [
      { label: "Machines", route: "machines" },
      { label: "Operators", route: "operators" },
      { label: "Materials & Batches", route: "materials" },
      { label: "Suppliers", route: "suppliers" },
    ]},
    { group: "Quality", perm: ["INSPECT_BATCH", "VIEW_QUALITY", "CREATE_DEFECT", "REPORT_QUALITY_DEFECT", "CREATE_HOLD", "REQUEST_HOLD", "CREATE_NCR"], items: [
      { label: "Inspections", route: "inspections" },
      { label: "Defects", route: "defects" },
      { label: "Quality Holds", route: "holds" },
      { label: "NCR / Corrective Action", route: "ncr" },
    ]},
    { group: "Monitoring", items: [
      { label: "Live Production", route: "live" },
      { label: "Alerts", route: "alerts" },
      { label: "Risks", route: "risks", perm: ["VIEW_RISK"] },
      { label: "Incidents", route: "incidents", perm: ["MANAGE_INCIDENTS", "REPORT_INCIDENTS"] },
      { label: "Overrides", route: "overrides", perm: ["CREATE_OVERRIDE", "APPROVE_OVERRIDE"] },
    ]},
    { group: "Traceability", perm: ["VIEW_TRACEABILITY_ALL", "VIEW_TRACEABILITY_LIMITED"], items: [
      { label: "Explorer", route: "traceability" },
    ]},
    { group: "Maintenance", perm: ["MANAGE_MAINTENANCE", "VIEW_MAINTENANCE", "REPORT_MAINTENANCE", "MANAGE_MACHINES"], items: [
      { label: "Maintenance Records", route: "maintenance" },
    ]},
    { group: "Reports", perm: ["VIEW_REPORTS"], items: [
      { label: "Reports", route: "reports" },
    ]},
    { group: "Governance", items: [
      { label: "Audit Logs", route: "audit-logs" },
      { label: "System Configuration", route: "settings", perm: ["MANAGE_SYSTEM_SETTINGS"] },
    ]},
  ],

  renderNav() {
    const sidebar = document.getElementById("sidebar");
    let html = "";
    for (const group of this.NAV) {
      if (group.perm && !Auth.hasPerm(...group.perm)) continue;
      const items = group.items.filter((it) => !it.perm || Auth.hasPerm(...it.perm));
      if (items.length === 0) continue;
      html += `<div class="sidebar-group"><div class="sidebar-group-title">${esc(group.group)}</div>`;
      for (const item of items) {
        html += `<a class="sidebar-link" data-route="${item.route}" href="#/${item.route}">${esc(item.label)}</a>`;
      }
      html += `</div>`;
    }
    sidebar.innerHTML = html;
    sidebar.querySelectorAll(".sidebar-link").forEach((a) => {
      a.addEventListener("click", () => {
        sidebar.querySelectorAll(".sidebar-link").forEach((x) => x.classList.remove("active"));
        a.classList.add("active");
      });
    });
  },

  ROUTES: {
    "dashboard": () => App.renderDashboard(),
    "users": () => Views.admin.users(),
    "roles": () => Views.admin.roles(),
    "orders": () => Views.production.orders(),
    "runs": () => Views.production.runs(),
    "scheduling": () => Views.production.scheduling(),
    "planning": () => Views.production.planning(),
    "machines": () => Views.resources.machines(),
    "operators": () => Views.resources.operators(),
    "materials": () => Views.resources.materials(),
    "suppliers": () => Views.resources.suppliers(),
    "inspections": () => Views.quality.inspections(),
    "defects": () => Views.quality.defects(),
    "holds": () => Views.quality.holds(),
    "ncr": () => Views.quality.ncr(),
    "live": () => Views.monitoring.live(),
    "alerts": () => Views.monitoring.alerts(),
    "risks": () => Views.monitoring.risks(),
    "incidents": () => Views.monitoring.incidents(),
    "overrides": () => Views.monitoring.overrides(),
    "traceability": () => Views.monitoring.traceability(),
    "maintenance": () => Views.resources.maintenance(),
    "reports": () => Views.admin.reports(),
    "audit-logs": () => Views.admin.auditLogs(),
    "settings": () => Views.admin.settings(),
  },

  route() {
    const hash = window.location.hash.replace(/^#\//, "") || "dashboard";
    const [base] = hash.split("?");
    document.querySelectorAll(".sidebar-link").forEach((a) => a.classList.toggle("active", a.dataset.route === base));
    const handler = this.ROUTES[base];
    const content = document.getElementById("content");
    if (!handler) {
      content.innerHTML = `<div class="empty-state">Not found.</div>`;
      return;
    }
    content.innerHTML = `<div class="empty-state">Loading...</div>`;
    Promise.resolve(handler()).catch((err) => {
      console.error(err);
      content.innerHTML = `<div class="empty-state">Failed to load: ${esc(apiErrorMessage(err))}</div>`;
    });
  },

  navigate(route) {
    window.location.hash = "#/" + route;
  },

  async renderDashboard() {
    const d = await Api.get("/v1/dashboard");
    const content = document.getElementById("content");
    const k = d.kpis;
    const kpiCard = (label, value, accent) => `<div class="kpi-card ${accent ? "accent-" + accent : ""}"><div class="kpi-value">${value}</div><div class="kpi-label">${esc(label)}</div></div>`;
    content.innerHTML = `
      <div class="page-header"><h2>Dashboard</h2><div class="page-actions"><button class="btn" id="refresh-dash">Refresh</button></div></div>
      <div class="kpi-grid">
        ${kpiCard("Active Orders", k.activeOrders)}
        ${kpiCard("Running Machines", k.runningMachines, "info")}
        ${kpiCard("Available Machines", k.availableMachines, "success")}
        ${kpiCard("Material Holds", k.materialHolds, "warning")}
        ${kpiCard("Quality Holds", k.qualityHolds, "warning")}
        ${kpiCard("Critical Alerts", k.criticalAlerts, "danger")}
        ${kpiCard("Delayed Orders", k.delayedOrders, "warning")}
        ${kpiCard("Open Incidents", k.openIncidents, "danger")}
      </div>
      <div class="grid-2">
        <div class="card">
          <h3>Production Status</h3>
          ${this.statusBars(d.productionStatus)}
        </div>
        <div class="card">
          <h3>Machine Status</h3>
          ${this.statusBars(d.machineStatus)}
        </div>
      </div>
      <div class="grid-2">
        <div class="card">
          <h3>Critical Alerts</h3>
          ${d.criticalAlertsList.length ? d.criticalAlertsList.map((a) => `<div style="padding:8px 0;border-bottom:1px solid #f0f1f4"><strong>[!] ${esc(a.type)}</strong><br/><span class="muted">${esc(a.message)}</span></div>`).join("") : `<p class="muted">No critical alerts.</p>`}
        </div>
        <div class="card">
          <h3>Resource Conflicts</h3>
          ${d.resourceConflicts.length ? d.resourceConflicts.map((c) => `<div style="padding:8px 0;border-bottom:1px solid #f0f1f4">${esc(c.message)}</div>`).join("") : `<p class="muted">No recent conflicts.</p>`}
        </div>
      </div>
      ${(d.staleness.machines.length || d.staleness.runs.length) ? `
      <div class="card">
        <h3>Stale Data (Section 35.2)</h3>
        ${d.staleness.machines.map((m) => `<div>Machine <strong>${esc(m.name)}</strong> -- no update since ${fmtDate(m.lastHeartbeatAt)}</div>`).join("")}
        ${d.staleness.runs.map((r) => `<div>Run <strong>${esc(r.code)}</strong> -- no update since ${fmtDate(r.lastHeartbeatAt)}</div>`).join("")}
      </div>` : ""}
    `;
    document.getElementById("refresh-dash").addEventListener("click", () => this.route());
  },

  statusBars(counts) {
    const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(counts).map(([k, v]) => `
      <div style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px">
          <span>${statusBadge(k)}</span><span class="muted">${v}</span>
        </div>
        <div class="risk-bar-track"><div class="risk-bar-fill" style="width:${(v / total) * 100}%;background:var(--primary)"></div></div>
      </div>`).join("") || `<p class="muted">No data.</p>`;
  },

  async refreshNotifications() {
    try {
      const d = await Api.get("/v1/notifications?unread_only=true");
      const count = document.getElementById("notif-count");
      count.hidden = d.items.length === 0;
      this._lastNotifs = d.items;
    } catch (e) { /* silent */ }
  },

  async toggleNotifPanel() {
    const panel = document.getElementById("notif-panel");
    if (!panel.hidden) { panel.hidden = true; return; }
    const d = await Api.get("/v1/notifications");
    panel.innerHTML = d.items.length
      ? d.items.map((n) => `<div class="notif-item ${n.readAt ? "" : "unread"}" data-id="${n.id}">
          <div class="notif-msg">${statusBadge(n.severity)} ${esc(n.message)}</div>
          <div class="notif-meta">${timeAgo(n.createdAt)}</div>
        </div>`).join("")
      : `<div class="notif-item muted">No notifications.</div>`;
    panel.hidden = false;
    panel.querySelectorAll(".notif-item[data-id]").forEach((el) => {
      el.addEventListener("click", async () => {
        await Api.patch(`/v1/notifications/${el.dataset.id}`, {});
        this.refreshNotifications();
      });
    });
  },

  async onSearch(q) {
    const results = document.getElementById("search-results");
    if (!q || q.trim().length < 2) { results.hidden = true; return; }
    try {
      const d = await Api.get("/v1/search?q=" + encodeURIComponent(q));
      if (!d.results.length) { results.innerHTML = `<div class="search-item muted">No matches.</div>`; results.hidden = false; return; }
      results.innerHTML = d.results.map((r) => `<div class="search-item" data-type="${r.type}" data-id="${r.id}">${esc(r.label)} ${r.status ? statusBadge(r.status) : ""}</div>`).join("");
      results.hidden = false;
      results.querySelectorAll(".search-item[data-id]").forEach((el) => {
        el.addEventListener("click", () => {
          results.hidden = true;
          document.getElementById("global-search").value = "";
          Views.monitoring.openTraceModal(el.dataset.type, el.dataset.id);
        });
      });
    } catch (e) { /* ignore search errors */ }
  },
};

document.addEventListener("DOMContentLoaded", () => App.init());
