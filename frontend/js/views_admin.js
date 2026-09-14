/* Sections 10-11 (Users/Roles), 38 (Audit Log), 41 (Reports), System
   Configuration. */
var Views = window.Views || {};
Views.admin = {

  async users() {
    const [usersResp, rolesResp, depsResp] = await Promise.all([Api.get("/v1/users"), Api.get("/v1/roles"), Api.get("/v1/departments")]);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Users</h2><div class="page-actions"><button class="btn btn-primary" id="new-user-btn">+ New User</button></div></div>
      <div class="card">${dataTable([
        { label: "Name", key: "name" }, { label: "Username", key: "username" }, { label: "Email", key: "email" },
        { label: "Department", key: "department" }, { label: "Roles", render: (u) => u.roles.map((r) => `<span class="badge badge-primary" style="margin-right:3px">${esc(r)}</span>`).join("") },
        { label: "Status", render: (u) => statusBadge(u.status) },
        { label: "", render: (u) => `<button class="btn btn-sm" data-edit="${u.id}">Edit</button>` },
      ], usersResp.items, { emptyText: "No users." })}</div>
    `;
    document.getElementById("new-user-btn").addEventListener("click", () => this.userModal(null, rolesResp.items, depsResp.items));
    content.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => this.userModal(usersResp.items.find((u) => u.id === b.dataset.edit), rolesResp.items, depsResp.items)));
  },

  userModal(user, roles, departments) {
    const isEdit = !!user;
    openModal({
      title: isEdit ? `Edit ${user.username}` : "New User",
      bodyHtml: `<form id="user-form"><div class="form-grid">
        <div class="field"><label>Name</label><input name="name" value="${esc(user?.name || "")}" ${isEdit ? "" : "required"} /></div>
        <div class="field"><label>Username</label><input name="username" value="${esc(user?.username || "")}" ${isEdit ? "disabled" : "required"} /></div>
        <div class="field"><label>Email</label><input name="email" type="email" value="${esc(user?.email || "")}" ${isEdit ? "" : "required"} /></div>
        <div class="field"><label>Phone</label><input name="phone" value="${esc(user?.phone || "")}" /></div>
        <div class="field"><label>Department</label><select name="departmentId"><option value="">--</option>${optionList(departments, "id", (d) => d.name)}</select></div>
        <div class="field"><label>Status</label><select name="status"><option ${user?.status === "ACTIVE" ? "selected" : ""}>ACTIVE</option><option ${user?.status === "INACTIVE" ? "selected" : ""}>INACTIVE</option><option ${user?.status === "LOCKED" ? "selected" : ""}>LOCKED</option><option ${user?.status === "SUSPENDED" ? "selected" : ""}>SUSPENDED</option></select></div>
        <div class="field span-2"><label>Roles</label>
          <select name="roleIds" multiple size="6">${roles.map((r) => `<option value="${r.id}" ${user?.roles?.includes(r.name) ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>
        </div>
        <div class="field span-2"><label>${isEdit ? "New Password (leave blank to keep current)" : "Password"}</label><input name="password" type="password" ${isEdit ? "" : "required"} /></div>
      </div>
      <div id="user-form-error" class="form-error" hidden style="margin-top:10px"></div>
      </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">${isEdit ? "Save" : "Create"}</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const form = document.getElementById("user-form");
          const data = formToObject(form);
          data.roleIds = Array.from(form.roleIds.selectedOptions).map((o) => o.value);
          if (!data.password) delete data.password;
          if (!data.departmentId) delete data.departmentId;
          try {
            if (isEdit) await Api.patch(`/v1/users/${user.id}`, data);
            else await Api.post("/v1/users", data);
            closeModal(); toast(isEdit ? "User updated." : "User created.", "success"); App.route();
          } catch (err) {
            const el = document.getElementById("user-form-error"); el.textContent = apiErrorMessage(err); el.hidden = false;
          }
        };
      },
    });
  },

  async roles() {
    const [rolesResp, permsResp] = await Promise.all([Api.get("/v1/roles"), Api.get("/v1/permissions")]);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Roles &amp; Permissions</h2></div>
      ${rolesResp.items.map((r) => `
        <div class="card">
          <h3>${esc(r.name)} <span class="muted">${esc(r.description || "")}</span></h3>
          <div id="perm-list-${r.id}">${permsResp.items.map((p) => `
            <label style="display:inline-flex;align-items:center;gap:4px;margin:2px 10px 2px 0;font-size:12px">
              <input type="checkbox" data-role="${r.id}" value="${p.code}" ${r.permissions.includes(p.code) ? "checked" : ""} /> ${esc(p.code)}
            </label>`).join("")}
          </div>
          <button class="btn btn-sm btn-primary" style="margin-top:10px" data-save-role="${r.id}">Save Permissions</button>
        </div>
      `).join("")}
    `;
    content.querySelectorAll("[data-save-role]").forEach((b) => b.addEventListener("click", async () => {
      const roleId = b.dataset.saveRole;
      const codes = Array.from(content.querySelectorAll(`input[data-role="${roleId}"]:checked`)).map((c) => c.value);
      try { await Api.patch(`/v1/roles/${roleId}/permissions`, { permissionCodes: codes }); toast("Permissions updated.", "success"); }
      catch (err) { notifyError(err); }
    }));
  },

  // ---------------- Audit Logs (Section 38) ----------------

  async auditLogs() {
    const d = await Api.get("/v1/audit-logs?limit=300");
    const chain = await Api.get("/v1/audit-logs/verify-chain").catch(() => null);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Audit Logs</h2>
        <div class="page-actions">${chain ? `<span class="badge ${chain.ok ? "badge-green" : "badge-red"}">Hash chain: ${chain.ok ? "VERIFIED (" + chain.checked + " entries)" : "BROKEN at seq " + chain.brokenAtSeq}</span>` : ""}</div>
      </div>
      <p class="flow-note">Append-only, hash-chained (Section 38). Scope follows your permission: full / limited-to-shop-floor-entities / own actions only (Section 7).</p>
      <div class="card">${dataTable([
        { label: "Seq", key: "seq" }, { label: "When", render: (a) => fmtDate(a.timestamp) }, { label: "User", key: "username" },
        { label: "Action", key: "action" }, { label: "Entity", render: (a) => a.entityType ? `${a.entityType} / ${(a.entityId || "").slice(0, 8)}` : "-" },
        { label: "Reason", key: "reason" },
      ], d.items, { emptyText: "No audit entries visible to your role." })}</div>
    `;
  },

  // ---------------- Reports (Section 41) ----------------

  async reports() {
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Reports</h2><div class="page-actions"><button class="btn" id="refresh-report-btn">Refresh</button></div></div>
      <div class="tabs">
        <button class="tab-btn active" data-tab="production">Production</button>
        <button class="tab-btn" data-tab="resources">Resources</button>
        <button class="tab-btn" data-tab="quality">Quality</button>
        <button class="tab-btn" data-tab="traceability">Traceability</button>
      </div>
      <div id="report-body"><div class="empty-state">Loading...</div></div>
    `;
    const reportBody = content.querySelector("#report-body");
    let requestVersion = 0;
    const loadTab = async (tab) => {
      const version = ++requestVersion;
      content.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
      reportBody.innerHTML = `<div class="empty-state">Loading report...</div>`;
      try {
        const d = await Api.get(`/v1/reports/${tab}`);
        if (version !== requestVersion || !reportBody.isConnected) return;
        reportBody.innerHTML = this.renderReport(tab, d);
      } catch (err) {
        if (version !== requestVersion || !reportBody.isConnected) return;
        reportBody.innerHTML = `<div class="empty-state"><strong>Couldn’t load this report.</strong><br/>${esc(apiErrorMessage(err))}<br/><button class="btn" id="retry-report-btn" style="margin-top:12px">Try again</button></div>`;
        reportBody.querySelector("#retry-report-btn").addEventListener("click", () => loadTab(tab));
      }
    };
    content.querySelectorAll(".tab-btn").forEach((b) => b.addEventListener("click", () => void loadTab(b.dataset.tab)));
    content.querySelector("#refresh-report-btn").addEventListener("click", () => {
      const active = content.querySelector(".tab-btn.active");
      void loadTab(active ? active.dataset.tab : "production");
    });
    void loadTab("production");
  },

  renderReport(tab, d) {
    const countTable = (counts, emptyText) => dataTable([
      { label: "Status", render: ([status]) => statusBadge(status) },
      { label: "Count", render: ([, count]) => fmtNum(count, 0) },
    ], Object.entries(counts || {}), { emptyText });
    const rate = (value) => `${fmtNum((Number(value) || 0) * 100)}%`;

    if (tab === "production") {
      return `
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-value">${fmtNum(d.totalOrders, 0)}</div><div class="kpi-label">Total orders</div></div>
          <div class="kpi-card accent-info"><div class="kpi-value">${fmtNum(d.totalRuns, 0)}</div><div class="kpi-label">Total production runs</div></div>
          <div class="kpi-card ${d.delayedOrders.length ? "accent-warning" : "accent-success"}"><div class="kpi-value">${fmtNum(d.delayedOrders.length, 0)}</div><div class="kpi-label">Delayed orders</div></div>
        </div>
        <div class="grid-2">
          <div class="card"><h3>Orders by status</h3>${countTable(d.ordersByStatus, "No orders to report.")}</div>
          <div class="card"><h3>Delayed orders</h3>${dataTable([
            { label: "Order", key: "orderCode" }, { label: "Due", render: (o) => fmtDate(o.dueDate) },
          ], d.delayedOrders, { emptyText: "No delayed orders." })}</div>
        </div>
        <div class="card"><h3>Completed production runs</h3>${dataTable([
          { label: "Run", key: "runCode" }, { label: "Order", key: "orderCode" },
          { label: "Planned", render: (r) => fmtNum(r.planned) }, { label: "Actual", render: (r) => fmtNum(r.actual) },
          { label: "Status", render: (r) => statusBadge(r.status) },
        ], d.plannedVsActual, { emptyText: "No completed runs yet." })}</div>`;
    }

    if (tab === "resources") {
      return `
        <div class="kpi-grid">
          <div class="kpi-card"><div class="kpi-value">${fmtNum(d.operatorCount, 0)}</div><div class="kpi-label">Operators</div></div>
          <div class="kpi-card ${d.materialShortages.length ? "accent-warning" : "accent-success"}"><div class="kpi-value">${fmtNum(d.materialShortages.length, 0)}</div><div class="kpi-label">Materials without available stock</div></div>
        </div>
        <div class="grid-2">
          <div class="card"><h3>Machines by status</h3>${countTable(d.machinesByStatus, "No machines to report.")}</div>
          <div class="card"><h3>Material shortages</h3>${dataTable([
            { label: "Material", key: "materialName" },
          ], d.materialShortages, { emptyText: "All materials have available stock." })}</div>
        </div>`;
    }

    if (tab === "quality") {
      return `
        <div class="kpi-grid">
          <div class="kpi-card accent-warning"><div class="kpi-value">${fmtNum(d.openHolds, 0)}</div><div class="kpi-label">Open quality holds</div></div>
          <div class="kpi-card ${d.rejectedBatchRate ? "accent-warning" : "accent-success"}"><div class="kpi-value">${rate(d.rejectedBatchRate)}</div><div class="kpi-label">Rejected material batch rate</div></div>
        </div>
        <div class="grid-2">
          <div class="card"><h3>Defects by severity</h3>${countTable(d.defectsBySeverity, "No defects recorded.")}</div>
          <div class="card"><h3>Defects by category</h3>${countTable(d.defectsByCategory, "No defects recorded.")}</div>
        </div>
        <div class="card"><h3>NCRs by status</h3>${countTable(d.ncrsByStatus, "No NCRs recorded.")}</div>`;
    }

    return `
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-value">${fmtNum(d.productBatchCount, 0)}</div><div class="kpi-label">Product batches</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(d.materialBatchCount, 0)}</div><div class="kpi-label">Material batches</div></div>
        <div class="kpi-card ${d.scrapRate ? "accent-warning" : "accent-success"}"><div class="kpi-value">${rate(d.scrapRate)}</div><div class="kpi-label">Scrap rate</div></div>
        <div class="kpi-card ${d.incidentCount ? "accent-warning" : "accent-success"}"><div class="kpi-value">${fmtNum(d.incidentCount, 0)}</div><div class="kpi-label">Recorded incidents</div></div>
      </div>
      <div class="card"><h3>What this report covers</h3><p class="muted">Batch counts, material-to-product traceability coverage, scrap, and related production incidents.</p></div>`;
  },

  // ---------------- System Configuration ----------------

  async settings() {
    const d = await Api.get("/v1/settings");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>System Configuration</h2></div>
      <p class="flow-note">The "configurable, not hard-coded" thresholds from Sections 29, 35, 36, 44, 46.</p>
      <div class="card">
        <form id="settings-form">
          <div class="form-grid">
            ${Object.entries(d.settings).map(([k, v]) => `<div class="field"><label>${esc(k)}</label><input name="${esc(k)}" value="${esc(v)}" /></div>`).join("")}
          </div>
          <button class="btn btn-primary" style="margin-top:14px" type="submit">Save Settings</button>
        </form>
      </div>
    `;
    document.getElementById("settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await Api.patch("/v1/settings", formToObject(e.target)); toast("Settings updated.", "success"); }
      catch (err) { notifyError(err); }
    });
  },
};
window.Views = Views;
