/* Sections 28-30 -- Quality Administration, Defect Severity, Quality Gate;
   Section 18 Material Hold Workflow; NCR. */
var Views = window.Views || {};
Views.quality = {

  async inspections() {
    const d = await Api.get("/v1/inspections");
    const canInspect = Auth.hasPerm("INSPECT_BATCH");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Quality Inspections</h2><div class="page-actions">${canInspect ? `<button class="btn btn-primary" id="new-insp-btn">+ New Inspection</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" }, { label: "Target", render: (i) => `${i.targetType} / ${i.targetId.slice(0, 8)}` },
        { label: "Parameter", key: "parameter" }, { label: "Expected", render: (i) => `${fmtNum(i.expectedMin)} - ${fmtNum(i.expectedMax)}` },
        { label: "Actual", render: (i) => fmtNum(i.actualValue) }, { label: "Result", render: (i) => statusBadge(i.result) },
        { label: "Inspector", key: "inspectorName" }, { label: "When", render: (i) => fmtDate(i.timestamp) },
      ], d.items, { emptyText: "No inspections recorded." })}</div>
    `;
    if (canInspect) document.getElementById("new-insp-btn").addEventListener("click", () => this.newInspectionModal());
  },

  newInspectionModal() {
    openModal({
      title: "New Quality Inspection",
      bodyHtml: `<form id="insp-form">
        <div class="form-grid">
          <div class="field"><label>Target Type</label><select name="targetType"><option>MATERIAL_BATCH</option><option>PRODUCT_BATCH</option></select></div>
          <div class="field"><label>Target ID</label><input name="targetId" required placeholder="paste batch ID" /></div>
          <div class="field"><label>Parameter</label><input name="parameter" /></div>
          <div class="field"><label>Result</label><select name="result" id="insp-result"><option value="PASS">PASS</option><option value="FAIL">FAIL</option></select></div>
          <div class="field"><label>Expected Min</label><input name="expectedMin" type="number" step="any" /></div>
          <div class="field"><label>Expected Max</label><input name="expectedMax" type="number" step="any" /></div>
          <div class="field"><label>Actual Value</label><input name="actualValue" type="number" step="any" /></div>
          <div class="field span-2"><label>Remarks</label><textarea name="remarks"></textarea></div>
        </div>
        <div id="fail-fields" hidden>
          <div class="section-divider">Failure Details (drives Section 29 severity classification)</div>
          <div class="form-grid">
            <div class="field"><label>Category</label><select name="category"><option>MATERIAL</option><option>MACHINE</option><option>PROCESS</option><option>OPERATOR</option><option>MEASUREMENT</option><option>UNKNOWN</option></select></div>
            <div class="field"><label><input type="checkbox" name="safetyOrRegulatory" /> Safety or regulatory risk</label></div>
            <div class="field"><label><input type="checkbox" name="alreadyPropagated" /> Already propagated downstream</label></div>
            <div class="field"><label><input type="checkbox" name="exceedsPrimaryBand" /> Exceeds primary tolerance band</label></div>
            <div class="field"><label><input type="checkbox" name="affectsFitFormFunction" /> Affects fit/form/function</label></div>
          </div>
        </div>
      </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Record Inspection</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("insp-result").addEventListener("change", (e) => { document.getElementById("fail-fields").hidden = e.target.value !== "FAIL"; });
        document.getElementById("save-btn").onclick = async () => {
          const form = document.getElementById("insp-form");
          const data = formToObject(form);
          data.safetyOrRegulatory = !!form.safetyOrRegulatory.checked;
          data.alreadyPropagated = !!form.alreadyPropagated.checked;
          data.exceedsPrimaryBand = !!form.exceedsPrimaryBand.checked;
          data.affectsFitFormFunction = !!form.affectsFitFormFunction.checked;
          ["expectedMin", "expectedMax", "actualValue"].forEach((k) => { if (data[k]) data[k] = parseFloat(data[k]); else delete data[k]; });
          try {
            const res = await Api.post("/v1/inspections", data);
            toast(res.defect ? `Inspection recorded -- ${res.defect.severity} defect raised.` : "Inspection recorded (PASS).", "success");
            closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Defects ----------------

  async defects() {
    const d = await Api.get("/v1/defects");
    const canCreate = Auth.hasPerm("CREATE_DEFECT", "REPORT_QUALITY_DEFECT");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Defects</h2><div class="page-actions">${canCreate ? `<button class="btn btn-primary" id="new-defect-btn">+ Report Defect</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" }, { label: "Target", render: (x) => `${x.targetType} / ${x.targetId.slice(0, 8)}` },
        { label: "Category", key: "category" }, { label: "Severity", render: (x) => statusBadge(x.severity) },
        { label: "Status", render: (x) => statusBadge(x.status) }, { label: "Detected", render: (x) => fmtDate(x.detectedAt) },
        { label: "Description", key: "description" },
      ], d.items, { emptyText: "No defects recorded." })}</div>
    `;
    if (canCreate) document.getElementById("new-defect-btn").addEventListener("click", () => {
      openModal({
        title: "Report Defect",
        bodyHtml: `<form id="def-form"><div class="form-grid">
          <div class="field"><label>Target Type</label><select name="targetType"><option>PRODUCT_BATCH</option><option>MATERIAL_BATCH</option></select></div>
          <div class="field"><label>Target ID</label><input name="targetId" required /></div>
          <div class="field"><label>Category</label><select name="category"><option>MATERIAL</option><option>MACHINE</option><option>PROCESS</option><option>OPERATOR</option><option>MEASUREMENT</option><option>UNKNOWN</option></select></div>
          <div class="field"><label>Severity (leave blank to auto-classify)</label><select name="severity"><option value="">Auto (Section 29)</option><option>MINOR</option><option>MAJOR</option><option>CRITICAL</option></select></div>
          <div class="field span-2"><label>Description</label><textarea name="description" required></textarea></div>
        </div></form>`,
        footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Submit</button>`,
        onMount: () => {
          document.getElementById("cancel-btn").onclick = closeModal;
          document.getElementById("save-btn").onclick = async () => {
            const data = formToObject(document.getElementById("def-form"));
            if (!data.severity) delete data.severity;
            try { const res = await Api.post("/v1/defects", data); toast(`Defect recorded (${res.severity}).`, "success"); closeModal(); App.route(); }
            catch (err) { notifyError(err); }
          };
        },
      });
    });
  },

  // ---------------- Quality Holds (Section 18) ----------------

  async holds() {
    const d = await Api.get("/v1/holds");
    const canCreate = Auth.hasPerm("CREATE_HOLD", "REQUEST_HOLD");
    const canRelease = Auth.hasPerm("RELEASE_HOLD");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Quality Holds</h2><div class="page-actions">${canCreate ? `<button class="btn btn-primary" id="new-hold-btn">+ New Hold</button>` : ""}</div></div>
      <p class="flow-note">Section 18: a hold blocks new reservations immediately, finds affected runs/orders, and raises an alert. A run still drawing on the held batch is auto-moved to ON_HOLD (Acceptance Test AT-2).</p>
      <div class="card">${dataTable([
        { label: "Target", render: (h) => `${h.targetType} / ${h.targetId.slice(0, 8)}` }, { label: "Reason", key: "reason" },
        { label: "Status", render: (h) => statusBadge(h.status) }, { label: "Created", render: (h) => fmtDate(h.createdAt) },
        { label: "", render: (h) => canRelease && ["OPEN", "PENDING"].includes(h.status) ? `<button class="btn btn-sm" data-release="${h.id}">Release</button> <button class="btn btn-sm" data-reject="${h.id}">Reject</button>` : "" },
      ], d.items, { emptyText: "No quality holds." })}</div>
    `;
    if (canCreate) document.getElementById("new-hold-btn").addEventListener("click", () => this.newHoldModal());
    if (canRelease) {
      content.querySelectorAll("[data-release]").forEach((b) => b.addEventListener("click", () => this.transitionHold(b.dataset.release, "RELEASE")));
      content.querySelectorAll("[data-reject]").forEach((b) => b.addEventListener("click", () => this.transitionHold(b.dataset.reject, "REJECT")));
    }
  },

  async transitionHold(holdId, action) {
    const reason = prompt(`Reason for ${action.toLowerCase()}?`) || "";
    try { await Api.post(`/v1/holds/${holdId}/transitions`, { action, reason }); toast(`Hold ${action.toLowerCase()}d.`, "success"); App.route(); }
    catch (err) { notifyError(err); }
  },

  newHoldModal() {
    openModal({
      title: "New Quality Hold",
      bodyHtml: `<form id="hold-form"><div class="form-grid cols-1">
        <div class="field"><label>Target Type</label><select name="targetType"><option>MATERIAL_BATCH</option><option>PRODUCT_BATCH</option></select></div>
        <div class="field"><label>Target ID</label><input name="targetId" required placeholder="paste batch ID" /></div>
        <div class="field"><label>Reason</label><textarea name="reason" required></textarea></div>
      </div></form>
      <p class="form-help">If you only hold REQUEST_HOLD permission, this creates a PENDING suggestion for an authorized role to act on (Section 7).</p>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Submit</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/holds", formToObject(document.getElementById("hold-form"))); closeModal(); toast("Hold submitted.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- NCR ----------------

  async ncr() {
    const [ncrResp, defectsResp] = await Promise.all([Api.get("/v1/ncrs"), Api.get("/v1/defects")]);
    const canCreate = Auth.hasPerm("CREATE_NCR");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>NCR &amp; Corrective Action</h2><div class="page-actions">${canCreate ? `<button class="btn btn-primary" id="new-ncr-btn">+ New NCR</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" }, { label: "Description", key: "description" }, { label: "Root Cause", key: "rootCause" },
        { label: "Corrective Action", key: "correctiveAction" }, { label: "Status", render: (n) => statusBadge(n.status) },
        { label: "", render: (n) => canCreate && n.status !== "CLOSED" ? `<button class="btn btn-sm" data-edit-ncr="${n.id}">Update</button>` : "" },
      ], ncrResp.items, { emptyText: "No NCRs yet." })}</div>
    `;
    if (canCreate) {
      document.getElementById("new-ncr-btn").addEventListener("click", () => this.newNcrModal(defectsResp.items));
      content.querySelectorAll("[data-edit-ncr]").forEach((b) => b.addEventListener("click", () => this.editNcrModal(b.dataset.editNcr, ncrResp.items)));
    }
  },

  newNcrModal(defects) {
    openModal({
      title: "New NCR",
      bodyHtml: `<form id="ncr-form"><div class="form-grid cols-1">
        <div class="field"><label>Defect</label><select name="defectId">${optionList(defects, "id", (d) => `${d.code} (${d.severity})`)}</select></div>
        <div class="field"><label>Description</label><textarea name="description" required></textarea></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/ncrs", formToObject(document.getElementById("ncr-form"))); closeModal(); toast("NCR created.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  editNcrModal(ncrId, ncrs) {
    const n = ncrs.find((x) => x.id === ncrId);
    openModal({
      title: `Update ${n.code}`,
      bodyHtml: `<form id="ncr-edit-form"><div class="form-grid cols-1">
        <div class="field"><label>Root Cause</label><textarea name="rootCause">${esc(n.rootCause || "")}</textarea></div>
        <div class="field"><label>Corrective Action</label><textarea name="correctiveAction">${esc(n.correctiveAction || "")}</textarea></div>
        <div class="field"><label>Status</label><select name="status"><option ${n.status === "OPEN" ? "selected" : ""}>OPEN</option><option ${n.status === "IN_PROGRESS" ? "selected" : ""}>IN_PROGRESS</option><option ${n.status === "CLOSED" ? "selected" : ""}>CLOSED</option></select></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Save</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.patch(`/v1/ncrs/${ncrId}`, formToObject(document.getElementById("ncr-edit-form"))); closeModal(); toast("NCR updated.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },
};
window.Views = Views;
