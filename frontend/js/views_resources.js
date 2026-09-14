/* Sections 12-15, 14 -- Machine Administration/State Machine/Maintenance,
   Material Administration, Suppliers, Operators. */
var Views = window.Views || {};
Views.resources = {

  async machines() {
    const d = await Api.get("/v1/machines");
    const canManage = Auth.hasPerm("MANAGE_MACHINES");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Machines</h2><div class="page-actions">${canManage ? `<button class="btn btn-primary" id="new-machine-btn">+ New Machine</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Name", key: "name" }, { label: "Type", key: "type" }, { label: "Location", key: "location" },
        { label: "Capacity", render: (m) => fmtNum(m.capacity) },
        { label: "Status", render: (m) => `${statusBadge(m.status)} ${m.isStale ? '<span class="badge badge-yellow">STALE</span>' : ""}` },
        { label: "", render: (m) => `<button class="btn btn-sm" data-machine="${m.id}">Manage</button>` },
      ], d.items, { emptyText: "No machines registered." })}</div>
    `;
    content.querySelectorAll("[data-machine]").forEach((b) => b.addEventListener("click", () => this.openMachineModal(b.dataset.machine)));
    if (canManage) document.getElementById("new-machine-btn").addEventListener("click", () => this.newMachineModal());
  },

  newMachineModal() {
    openModal({
      title: "New Machine",
      bodyHtml: `<form id="m-form"><div class="form-grid">
        <div class="field"><label>Name</label><input name="name" required /></div>
        <div class="field"><label>Type</label><input name="type" /></div>
        <div class="field"><label>Location</label><input name="location" /></div>
        <div class="field"><label>Capacity (units/hour)</label><input name="capacity" type="number" step="any" value="100" /></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("m-form")); data.capacity = parseFloat(data.capacity);
          try { await Api.post("/v1/machines", data); closeModal(); toast("Machine created.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  MACHINE_TRANSITIONS: {
    AVAILABLE: ["RESERVED", "OFFLINE", "DECOMMISSIONED", "FAULT", "MAINTENANCE"],
    RESERVED: ["RUNNING", "AVAILABLE", "FAULT"], RUNNING: ["PAUSED", "FAULT", "AVAILABLE", "RESERVED"],
    PAUSED: ["RUNNING", "FAULT"], FAULT: ["MAINTENANCE"], MAINTENANCE: ["AVAILABLE", "DECOMMISSIONED"],
    OFFLINE: ["AVAILABLE", "DECOMMISSIONED"], DECOMMISSIONED: [],
  },

  async openMachineModal(machineId) {
    const [m, records] = await Promise.all([Api.get(`/v1/machines/${machineId}`), Api.get(`/v1/machines/${machineId}/maintenance-records`)]);
    const legal = this.MACHINE_TRANSITIONS[m.status] || [];
    const canManage = Auth.hasPerm("MANAGE_MACHINES");
    openModal({
      title: `${m.name} -- ${m.status}`,
      wide: true,
      bodyHtml: `
        <dl class="kv-list">
          <dt>Type</dt><dd>${esc(m.type || "-")}</dd><dt>Location</dt><dd>${esc(m.location || "-")}</dd>
          <dt>Capacity</dt><dd>${fmtNum(m.capacity)} units/hr</dd>
          <dt>Last Heartbeat</dt><dd>${fmtDate(m.lastHeartbeatAt)} ${m.isStale ? '<span class="badge badge-yellow">STALE</span>' : ""}</dd>
        </dl>
        <div class="section-divider">Maintenance Records</div>
        ${dataTable([
          { label: "Type", key: "type" }, { label: "Status", render: (r) => statusBadge(r.status) },
          { label: "Opened", render: (r) => fmtDate(r.openedAt) }, { label: "Notes", key: "notes" },
          { label: "", render: (r) => canManage && r.status === "OPEN" ? `<button class="btn btn-sm" data-complete="${r.id}">Complete</button>` : (canManage && r.status === "COMPLETED" ? `<button class="btn btn-sm" data-verify="${r.id}">Verify</button>` : "") },
        ], records.items, { emptyText: "No maintenance records." })}
        ${canManage ? `
        <div class="section-divider">Actions</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <button class="btn btn-sm" id="heartbeat-btn">Confirm Running / Heartbeat</button>
          ${legal.length ? `<select id="m-transition-select">${legal.map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
          <input id="m-transition-reason" placeholder="reason" style="padding:6px;border:1px solid var(--border);border-radius:6px" />
          <button class="btn btn-primary btn-sm" id="m-transition-btn">Apply Transition</button>` : ""}
        </div>` : ""}
      `,
      footerHtml: `<button class="btn" id="close-btn">Close</button>`,
      onMount: () => {
        document.getElementById("close-btn").onclick = closeModal;
        const hb = document.getElementById("heartbeat-btn");
        if (hb) hb.onclick = async () => { try { await Api.post(`/v1/machines/${machineId}/heartbeat`, {}); toast("Heartbeat recorded.", "success"); closeModal(); App.route(); } catch (e) { notifyError(e); } };
        const tb = document.getElementById("m-transition-btn");
        if (tb) tb.onclick = async () => {
          const toState = document.getElementById("m-transition-select").value;
          const reason = document.getElementById("m-transition-reason").value;
          try { await Api.post(`/v1/machines/${machineId}/transitions`, { toState, reason }); toast(`Machine -> ${toState}.`, "success"); closeModal(); App.route(); }
          catch (err) { notifyError(err); }
        };
        document.querySelectorAll("[data-complete]").forEach((b) => b.onclick = async () => { try { await Api.post(`/v1/machines/${machineId}/maintenance-records/${b.dataset.complete}/complete`, { notes: prompt("Completion notes?") || "" }); closeModal(); App.route(); } catch (e) { notifyError(e); } });
        document.querySelectorAll("[data-verify]").forEach((b) => b.onclick = async () => { try { await Api.post(`/v1/machines/${machineId}/maintenance-records/${b.dataset.verify}/verify`, {}); toast("Verified -- machine returned to AVAILABLE.", "success"); closeModal(); App.route(); } catch (e) { notifyError(e); } });
      },
    });
  },

  // ---------------- Operators ----------------

  async operators() {
    const [d, processesResp] = await Promise.all([Api.get("/v1/operators"), Api.get("/v1/processes")]);
    const canManage = Auth.hasPerm("MANAGE_USERS");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Operators</h2></div>
      <div class="card">${dataTable([
        { label: "Name", key: "name" }, { label: "Employee Code", key: "employeeCode" }, { label: "Shift", key: "shiftPattern" },
        { label: "Skills", render: (o) => o.skills.map((s) => `${esc(s.processName)} (${s.certifiedLevel})`).join(", ") || "-" },
        { label: "", render: (o) => canManage ? `<button class="btn btn-sm" data-skill="${o.id}">+ Skill</button>` : "" },
      ], d.items, { emptyText: "No operators registered. Create operator profiles from Users & Roles." })}</div>
    `;
    if (canManage) content.querySelectorAll("[data-skill]").forEach((b) => b.addEventListener("click", () => this.addSkillModal(b.dataset.skill, processesResp.items)));
  },

  addSkillModal(operatorId, processes) {
    openModal({
      title: "Add Operator Skill",
      bodyHtml: `<form id="skill-form"><div class="form-grid cols-1">
        <div class="field"><label>Process (skill-matching)</label><select name="processId">${optionList(processes, "id", (p) => p.name)}</select></div>
        <div class="field"><label>Certified Level</label><select name="certifiedLevel"><option>BASIC</option><option>QUALIFIED</option><option>EXPERT</option></select></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Add</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post(`/v1/operators/${operatorId}/skills`, formToObject(document.getElementById("skill-form"))); closeModal(); toast("Skill added.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Materials & Batches (Sections 15-18) ----------------

  async materials() {
    const [materialsResp, suppliersResp] = await Promise.all([Api.get("/v1/materials"), Api.get("/v1/suppliers")]);
    const canManage = Auth.hasPerm("MANAGE_MATERIALS");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Materials &amp; Batches</h2><div class="page-actions">${canManage ? `<button class="btn btn-primary" id="new-material-btn">+ New Material</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Name", key: "name" }, { label: "UoM", key: "unitOfMeasure" }, { label: "Category", key: "category" },
        { label: "Batches", key: "batchCount" }, { label: "Available", render: (m) => fmtNum(m.totalAvailable) },
        { label: "", render: (m) => `<button class="btn btn-sm" data-material="${m.id}">Batches</button>` },
      ], materialsResp.items, { emptyText: "No materials defined." })}</div>
    `;
    content.querySelectorAll("[data-material]").forEach((b) => b.addEventListener("click", () => this.openMaterialModal(b.dataset.material, suppliersResp.items)));
    if (canManage) document.getElementById("new-material-btn").addEventListener("click", () => this.newMaterialModal());
  },

  newMaterialModal() {
    openModal({
      title: "New Material",
      bodyHtml: `<form id="mat-form"><div class="form-grid">
        <div class="field span-2"><label>Name</label><input name="name" required /></div>
        <div class="field"><label>Unit of Measure</label><select name="unitOfMeasure"><option>KG</option><option>L</option><option>EA</option><option>M</option></select></div>
        <div class="field"><label>Category</label><input name="category" /></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/materials", formToObject(document.getElementById("mat-form"))); closeModal(); toast("Material created.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  MATERIAL_BATCH_TRANSITIONS: {
    PENDING_INSPECTION: ["AVAILABLE", "REJECTED"], AVAILABLE: ["ON_HOLD", "DEPLETED", "EXPIRED"],
    ON_HOLD: ["AVAILABLE", "REJECTED"], EXPIRED: ["ON_HOLD"], REJECTED: [], DEPLETED: [],
  },

  async openMaterialModal(materialId, suppliers) {
    const batchesResp = await Api.get(`/v1/materials/${materialId}/batches`);
    const canManage = Auth.hasPerm("MANAGE_MATERIALS");
    openModal({
      title: "Material Batches",
      wide: true,
      bodyHtml: `
        ${dataTable([
          { label: "Lot", key: "lotNumber" }, { label: "Status", render: (b) => statusBadge(b.status) },
          { label: "Total", render: (b) => fmtNum(b.totalQuantity) }, { label: "Reserved", render: (b) => fmtNum(b.reservedQuantity) },
          { label: "Consumed", render: (b) => fmtNum(b.consumedQuantity) }, { label: "Available", render: (b) => fmtNum(b.availableQuantity) },
          { label: "Expiry", render: (b) => fmtDate(b.expiryDate) },
          { label: "", render: (b) => canManage && this.MATERIAL_BATCH_TRANSITIONS[b.status] && this.MATERIAL_BATCH_TRANSITIONS[b.status].length ? `<button class="btn btn-sm" data-batch="${b.id}" data-status="${b.status}">Transition</button>` : "" },
        ], batchesResp.items, { emptyText: "No batches yet." })}
        ${canManage ? `<button class="btn btn-sm" style="margin-top:10px" id="new-batch-btn">+ New Batch</button>` : ""}
      `,
      footerHtml: `<button class="btn" id="close-btn">Close</button>`,
      onMount: () => {
        document.getElementById("close-btn").onclick = closeModal;
        const nb = document.getElementById("new-batch-btn");
        if (nb) nb.onclick = () => { closeModal(); this.newBatchModal(materialId, suppliers); };
        document.querySelectorAll("[data-batch]").forEach((b) => b.onclick = () => this.batchTransitionModal(b.dataset.batch, b.dataset.status, materialId, suppliers));
      },
    });
  },

  newBatchModal(materialId, suppliers) {
    openModal({
      title: "New Material Batch",
      bodyHtml: `<form id="batch-form"><div class="form-grid">
        <div class="field"><label>Lot Number</label><input name="lotNumber" required /></div>
        <div class="field"><label>Supplier</label><select name="supplierId">${optionList(suppliers, "id", (s) => s.name)}</select></div>
        <div class="field"><label>Total Quantity</label><input name="totalQuantity" type="number" step="any" required /></div>
        <div class="field"><label>Storage Location</label><input name="storageLocation" /></div>
        <div class="field"><label>Expiry Date (optional)</label><input name="expiryDate" type="date" /></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("batch-form"));
          data.totalQuantity = parseFloat(data.totalQuantity);
          if (data.expiryDate) data.expiryDate = new Date(data.expiryDate).toISOString(); else delete data.expiryDate;
          try { await Api.post(`/v1/materials/${materialId}/batches`, data); closeModal(); toast("Batch created (PENDING_INSPECTION).", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  batchTransitionModal(batchId, currentStatus, materialId, suppliers) {
    const legal = this.MATERIAL_BATCH_TRANSITIONS[currentStatus] || [];
    openModal({
      title: `Batch Transition (currently ${currentStatus})`,
      bodyHtml: `<div class="form-grid cols-1">
        <div class="field"><label>New Status</label><select id="bt-select">${legal.map((s) => `<option value="${s}">${s}</option>`).join("")}</select></div>
        <div class="field"><label>Reason</label><input id="bt-reason" /></div>
      </div>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Apply</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const toState = document.getElementById("bt-select").value;
          const reason = document.getElementById("bt-reason").value;
          try { await Api.post(`/v1/batches/${batchId}/transitions`, { toState, reason }); toast(`Batch -> ${toState}.`, "success"); closeModal(); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Suppliers ----------------

  async suppliers() {
    const d = await Api.get("/v1/suppliers");
    const canManage = Auth.hasPerm("MANAGE_SUPPLIERS", "MANAGE_MATERIALS");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Suppliers</h2><div class="page-actions">${canManage ? `<button class="btn btn-primary" id="new-supplier-btn">+ New Supplier</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Name", key: "name" }, { label: "Contact", key: "contactInfo" },
        { label: "Qualification", render: (s) => statusBadge(s.qualificationStatus) },
      ], d.items, { emptyText: "No suppliers registered." })}</div>
    `;
    if (canManage) document.getElementById("new-supplier-btn").addEventListener("click", () => {
      openModal({
        title: "New Supplier",
        bodyHtml: `<form id="sup-form"><div class="form-grid cols-1">
          <div class="field"><label>Name</label><input name="name" required /></div>
          <div class="field"><label>Contact Info</label><input name="contactInfo" /></div>
          <div class="field"><label>Address</label><input name="address" /></div>
          <div class="field"><label>Qualification Status</label><select name="qualificationStatus"><option>QUALIFIED</option><option>PROBATIONARY</option><option>DISQUALIFIED</option></select></div>
        </div></form>`,
        footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
        onMount: () => {
          document.getElementById("cancel-btn").onclick = closeModal;
          document.getElementById("save-btn").onclick = async () => {
            try { await Api.post("/v1/suppliers", formToObject(document.getElementById("sup-form"))); closeModal(); toast("Supplier created.", "success"); App.route(); }
            catch (err) { notifyError(err); }
          };
        },
      });
    });
  },

  // ---------------- Maintenance (Section 14 summary) ----------------

  async maintenance() {
    const machinesResp = await Api.get("/v1/machines");
    const allRecords = await Promise.all(machinesResp.items.map((m) => Api.get(`/v1/machines/${m.id}/maintenance-records`).then((r) => r.items.map((rec) => ({ ...rec, machineName: m.name })))));
    const flat = allRecords.flat().sort((a, b) => new Date(b.openedAt) - new Date(a.openedAt));
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Maintenance Records</h2></div>
      <div class="card">${dataTable([
        { label: "Machine", key: "machineName" }, { label: "Type", key: "type" }, { label: "Status", render: (r) => statusBadge(r.status) },
        { label: "Opened", render: (r) => fmtDate(r.openedAt) }, { label: "Closed", render: (r) => fmtDate(r.closedAt) }, { label: "Notes", key: "notes" },
      ], flat, { emptyText: "No maintenance history yet." })}</div>
      <p class="flow-note">Open a machine from Resources &rarr; Machines to log a fault (transition to MAINTENANCE), complete work, and verify return-to-service (Section 14 -- dual control: the verifier cannot be the same user who performed the work).</p>
    `;
  },
};
window.Views = Views;
