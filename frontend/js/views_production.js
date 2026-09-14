/* Sections 19-26 -- Production Order Administration, Production Run control,
   Scheduling Algorithm, Production Planning. */
var Views = window.Views || {};
Views.production = {

  async orders() {
    const [ordersResp, processesResp] = await Promise.all([Api.get("/v1/production-orders"), Api.get("/v1/processes")]);
    const orders = ordersResp.items;
    const canCreate = Auth.hasPerm("CREATE_ORDERS");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Production Orders</h2>
        <div class="page-actions">${canCreate ? `<button class="btn btn-primary" id="new-order-btn">+ New Order</button>` : ""}</div>
      </div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" },
        { label: "Product", key: "productName" },
        { label: "Qty", render: (o) => fmtNum(o.quantityOrdered, 0) },
        { label: "Process", key: "processName" },
        { label: "Priority", key: "priority" },
        { label: "Due Date", render: (o) => fmtDate(o.dueDate) },
        { label: "Status", render: (o) => statusBadge(o.status) },
        { label: "Runs", key: "runCount" },
        { label: "", render: (o) => `<button class="btn btn-sm" data-view="${o.id}">View</button>` },
      ], orders, { emptyText: "No production orders yet." })}</div>
    `;
    content.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => this.openOrderModal(b.dataset.view)));
    if (canCreate) document.getElementById("new-order-btn").addEventListener("click", () => this.newOrderModal(processesResp.items));
  },

  newOrderModal(processes) {
    openModal({
      title: "New Production Order",
      bodyHtml: `
        <form id="order-form">
          <div class="form-grid">
            <div class="field span-2"><label>Product Name</label><input name="productName" required /></div>
            <div class="field"><label>Quantity Ordered</label><input name="quantityOrdered" type="number" step="any" required /></div>
            <div class="field"><label>Priority (1 = highest)</label><input name="priority" type="number" value="5" min="1" required /></div>
            <div class="field span-2"><label>Process</label><select name="processId" required>${optionList(processes, "id", (p) => p.name)}</select></div>
            <div class="field span-2"><label>Due Date</label><input name="dueDate" type="datetime-local" required /></div>
          </div>
          <div id="order-form-error" class="form-error" hidden style="margin-top:12px"></div>
        </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const form = document.getElementById("order-form");
          if (!form.reportValidity()) return;
          const data = formToObject(form);
          data.dueDate = new Date(data.dueDate).toISOString();
          try {
            await Api.post("/v1/production-orders", data);
            closeModal(); toast("Order created.", "success"); App.route();
          } catch (err) {
            const el = document.getElementById("order-form-error");
            el.textContent = apiErrorMessage(err); el.hidden = false;
          }
        };
      },
    });
  },

  async openOrderModal(orderId) {
    const o = await Api.get(`/v1/production-orders/${orderId}`);
    const transitions = { DRAFT: ["SUBMITTED", "CANCELLED"], SUBMITTED: ["APPROVED", "DRAFT", "CANCELLED"], APPROVED: ["READY", "CANCELLED"], READY: ["RUNNING", "ON_HOLD", "CANCELLED"], RUNNING: ["ON_HOLD", "COMPLETED"], DELAYED: ["RUNNING", "COMPLETED", "ON_HOLD"], ON_HOLD: ["RUNNING", "CANCELLED"] };
    const legal = transitions[o.status] || [];
    openModal({
      title: `${o.code} -- ${o.productName}`,
      wide: true,
      bodyHtml: `
        <dl class="kv-list">
          <dt>Status</dt><dd>${statusBadge(o.status)}</dd>
          <dt>Quantity</dt><dd>${fmtNum(o.quantityOrdered, 0)}</dd>
          <dt>Priority</dt><dd>${o.priority}</dd>
          <dt>Due Date</dt><dd>${fmtDate(o.dueDate)}</dd>
          <dt>Process</dt><dd>${esc(o.processName || "")}</dd>
        </dl>
        <div class="section-divider">Runs</div>
        ${dataTable([
          { label: "Code", key: "code" }, { label: "Status", render: (r) => statusBadge(r.status) },
          { label: "Machine", key: "machineId" }, { label: "Scheduled Start", render: (r) => fmtDate(r.scheduledStart) },
        ], o.runs, { emptyText: "No runs scheduled yet -- use Scheduling to create one." })}
        ${legal.length ? `
        <div class="section-divider">Transition</div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <select id="order-transition-select">${legal.map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
          <input id="order-transition-reason" placeholder="Reason (optional)" style="flex:1;min-width:160px;padding:6px 8px;border:1px solid var(--border);border-radius:6px" />
          <button class="btn btn-primary btn-sm" id="order-transition-btn">Apply</button>
        </div>` : ""}
      `,
      footerHtml: `<button class="btn" id="close-btn">Close</button>`,
      onMount: () => {
        document.getElementById("close-btn").onclick = closeModal;
        const tbtn = document.getElementById("order-transition-btn");
        if (tbtn) tbtn.onclick = async () => {
          const toState = document.getElementById("order-transition-select").value;
          const reason = document.getElementById("order-transition-reason").value;
          try {
            await Api.post(`/v1/production-orders/${orderId}/transitions`, { toState, reason });
            toast(`Order moved to ${toState}.`, "success"); closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Production Runs (Section 22) ----------------

  async runs() {
    const d = await Api.get("/v1/runs");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Production Runs</h2></div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" }, { label: "Order", key: "orderCode" },
        { label: "Step", key: "processStepName" }, { label: "Machine", key: "machineName" },
        { label: "Status", render: (r) => `${statusBadge(r.status)} ${r.isStale ? '<span class="badge badge-yellow">STALE</span>' : ""}` },
        { label: "Scheduled", render: (r) => fmtDate(r.scheduledStart) },
        { label: "Produced", render: (r) => fmtNum(r.quantityProduced, 0) + " / " + fmtNum(r.quantityPlanned, 0) },
        { label: "", render: (r) => `<button class="btn btn-sm" data-run="${r.id}">Manage</button>` },
      ], d.items, { emptyText: "No production runs yet." })}</div>
    `;
    content.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => this.openRunModal(b.dataset.run)));
  },

  async openRunModal(runId) {
    const r = await Api.get(`/v1/runs/${runId}`);
    const canExec = Auth.hasPerm("EXECUTE_PRODUCTION");
    const actions = [];
    if (canExec) {
      if (r.status === "SCHEDULED") actions.push(["Start Run", "start"]);
      if (r.status === "RUNNING") { actions.push(["Pause", "pause"], ["Place On Hold", "hold"], ["Heartbeat / Confirm Running", "heartbeat"]); }
      if (r.status === "PAUSED") actions.push(["Resume", "resume"], ["Place On Hold", "hold"]);
      if (r.status === "ON_HOLD") actions.push(["Release Hold (Resume)", "release-hold"], ["Cancel", "cancel"]);
      if (r.status === "MATERIAL_SUBSTITUTION_PENDING" && Auth.hasPerm("APPROVE_ORDERS", "MANAGE_INCIDENTS")) actions.push(["Approve Substitute Batch", "substitute"]);
      if (r.status === "PARTIALLY_COMPLETED") { actions.push(["Resume Remaining", "resume-partial"]); if (Auth.hasPerm("APPROVE_ORDERS")) actions.push(["Waive Remaining -> Complete", "waive"]); }
      if (r.status === "SCRAP_REWORK_REVIEW" && Auth.hasPerm("RELEASE_HOLD", "APPROVE_ORDERS")) actions.push(["Dispose (Rework/Scrap)", "dispose"]);
      if (r.status === "RUNNING") { actions.push(["Partial Complete...", "partial"], ["Complete Run...", "complete"], ["Request Material Substitution...", "request-sub"]); }
      if (["SCHEDULED", "ON_HOLD"].includes(r.status)) actions.push(["Cancel", "cancel"]);
    }
    openModal({
      title: `${r.code} -- ${r.status}`,
      wide: true,
      bodyHtml: `
        <dl class="kv-list">
          <dt>Order</dt><dd>${esc(r.orderCode)}</dd>
          <dt>Machine</dt><dd>${esc(r.machineName || "-")}</dd>
          <dt>Scheduled</dt><dd>${fmtDate(r.scheduledStart)} &rarr; ${fmtDate(r.scheduledEnd)}</dd>
          <dt>Produced</dt><dd>${fmtNum(r.quantityProduced, 0)} / ${fmtNum(r.quantityPlanned, 0)}</dd>
        </dl>
        <div class="section-divider">Material Consumption (Genealogy)</div>
        ${dataTable([
          { label: "Batch", key: "lotNumber" }, { label: "Material", key: "materialName" }, { label: "Role", key: "role" },
          { label: "Reserved", render: (c) => fmtNum(c.quantityReserved) }, { label: "Consumed", render: (c) => c.quantityConsumed !== null ? fmtNum(c.quantityConsumed) : "-" },
        ], r.consumptions, { emptyText: "No material consumption recorded." })}
        <div class="section-divider">Product Batches</div>
        ${dataTable([
          { label: "Code", key: "code" }, { label: "Produced", render: (p) => fmtNum(p.quantityProduced) },
          { label: "Scrapped", render: (p) => fmtNum(p.scrappedQuantity) }, { label: "Disposition", render: (p) => statusBadge(p.qualityDisposition) },
        ], r.productBatches, { emptyText: "No product batches yet." })}
        ${actions.length ? `<div class="section-divider">Actions</div><div style="display:flex;gap:8px;flex-wrap:wrap">
          ${actions.map(([label, act]) => `<button class="btn btn-sm" data-act="${act}">${label}</button>`).join("")}
        </div>` : ""}
      `,
      footerHtml: `<button class="btn" id="close-btn">Close</button>`,
      onMount: () => {
        document.getElementById("close-btn").onclick = closeModal;
        openModal.currentRun = r;
        document.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => this.runAction(r, b.dataset.act)));
      },
    });
  },

  async runAction(run, action) {
    try {
      if (action === "start") { await Api.post(`/v1/runs/${run.id}/start`, {}); toast("Run started.", "success"); }
      else if (action === "pause") { await Api.post(`/v1/runs/${run.id}/pause`, { reason: prompt("Reason for pause?") || "" }); toast("Run paused.", "success"); }
      else if (action === "resume") { await Api.post(`/v1/runs/${run.id}/resume`, {}); toast("Run resumed.", "success"); }
      else if (action === "hold") { await Api.post(`/v1/runs/${run.id}/hold`, { reason: prompt("Reason for hold?") || "" }); toast("Run placed on hold.", "success"); }
      else if (action === "release-hold") { await Api.post(`/v1/runs/${run.id}/release-hold`, {}); toast("Hold released -- run resumed.", "success"); }
      else if (action === "cancel") { await Api.post(`/v1/runs/${run.id}/cancel`, { reason: prompt("Reason for cancellation?") || "" }); toast("Run cancelled.", "success"); }
      else if (action === "resume-partial") { await Api.post(`/v1/runs/${run.id}/resume-partial`, {}); toast("Run resumed.", "success"); }
      else if (action === "waive") { await Api.post(`/v1/runs/${run.id}/waive-remaining`, { reason: prompt("Reason for waiving remaining quantity?") || "" }); toast("Remaining quantity waived -- run completed.", "success"); }
      else if (action === "heartbeat") { await Api.post(`/v1/runs/${run.id}/heartbeat`, {}); toast("Freshness timer reset.", "success"); }
      else if (action === "complete") { closeModal(); return this.completeRunModal(run, false); }
      else if (action === "partial") { closeModal(); return this.completeRunModal(run, true); }
      else if (action === "request-sub") { closeModal(); return this.requestSubstitutionModal(run); }
      else if (action === "substitute") { closeModal(); return this.approveSubstitutionModal(run); }
      else if (action === "dispose") { closeModal(); return this.disposeScrapReworkModal(run); }
      closeModal(); App.route();
    } catch (err) { notifyError(err); }
  },

  completeRunModal(run, partial) {
    const unposted = run.consumptions.filter((c) => c.quantityConsumed === null);
    openModal({
      title: (partial ? "Partial Completion" : "Complete Run") + " -- Final Consumption Posting",
      bodyHtml: `
        <p class="flow-note">Section 22.3: actual consumption per batch must be confirmed before the run can complete. Leave a field unchanged to accept the reserved quantity.</p>
        <form id="complete-form">
          <div class="field" style="margin-bottom:12px"><label>Quantity Produced</label><input name="quantityProduced" type="number" step="any" required value="${partial ? "" : run.quantityPlanned}" /></div>
          ${unposted.map((c) => `
            <div class="field" style="margin-bottom:8px">
              <label>${esc(c.materialName)} -- Batch ${esc(c.lotNumber)} (reserved ${fmtNum(c.quantityReserved)})</label>
              <input name="post_${c.id}" type="number" step="any" value="${c.quantityReserved}" />
            </div>`).join("")}
        </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">${partial ? "Post Partial Completion" : "Complete Run"}</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const form = document.getElementById("complete-form");
          const data = formToObject(form);
          const postings = unposted.map((c) => ({ consumptionId: c.id, quantityConsumed: parseFloat(data["post_" + c.id]) }));
          try {
            const path = partial ? `/v1/runs/${run.id}/partial-complete` : `/v1/runs/${run.id}/complete`;
            await Api.post(path, { quantityProduced: parseFloat(data.quantityProduced), postings });
            toast("Posted.", "success"); closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  requestSubstitutionModal(run) {
    openModal({
      title: "Request Material Substitution",
      bodyHtml: `
        <form id="sub-form">
          <div class="form-grid cols-1">
            <div class="field"><label>Material ID</label><input name="materialId" placeholder="paste material ID" required /></div>
            <div class="field"><label>Remaining Quantity Needed</label><input name="remainingQuantity" type="number" step="any" required /></div>
          </div>
          <p class="form-help">Tip: open Resources &rarr; Materials to copy the material ID. The system tries automatic FEFO/FIFO reallocation first (Section 16.2); if none qualifies, the run enters MATERIAL_SUBSTITUTION_PENDING for approval.</p>
        </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Submit</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("sub-form"));
          try {
            const res = await Api.post(`/v1/runs/${run.id}/material-substitution/request`, data);
            toast(res.automatic ? "Automatic substitution applied." : "No automatic substitute -- pending approval.", "success");
            closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  approveSubstitutionModal(run) {
    openModal({
      title: "Approve Material Substitution",
      bodyHtml: `
        <form id="approve-sub-form">
          <div class="form-grid cols-1">
            <div class="field"><label>Substitute Batch ID</label><input name="substituteBatchId" required /></div>
            <div class="field"><label>Quantity</label><input name="quantity" type="number" step="any" required /></div>
          </div>
        </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Approve</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("approve-sub-form"));
          data.quantity = parseFloat(data.quantity);
          try {
            await Api.post(`/v1/runs/${run.id}/material-substitution/approve`, data);
            toast("Substitution approved -- run resumed.", "success"); closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  disposeScrapReworkModal(run) {
    openModal({
      title: "Scrap / Rework Disposition (Section 22.4)",
      bodyHtml: `
        <form id="dispose-form">
          <div class="form-grid cols-1">
            <div class="field"><label>Disposition</label><select name="disposition"><option value="REWORK">Rework (run resumes)</option><option value="SCRAP">Scrap (run completes, scrap recorded)</option></select></div>
            <div class="field"><label>Scrapped Quantity</label><input name="scrappedQuantity" type="number" step="any" value="0" /></div>
            <div class="field"><label>Reason</label><input name="reason" /></div>
          </div>
        </form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Confirm</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("dispose-form"));
          data.scrappedQuantity = parseFloat(data.scrappedQuantity || 0);
          try {
            await Api.post(`/v1/runs/${run.id}/scrap-rework/dispose`, data);
            toast("Disposition recorded.", "success"); closeModal(); App.route();
          } catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Scheduling (Sections 23-25, 45.2) ----------------

  async scheduling() {
    const [ordersResp, machinesResp, operatorsResp] = await Promise.all([
      Api.get("/v1/production-orders?status_=APPROVED"), Api.get("/v1/machines"), Api.get("/v1/operators"),
    ]);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Scheduling</h2></div>
      <p class="flow-note">Implements Section 23's per-request algorithm under the Section 25.7 admission-control layer: the server re-validates every check under lock, resolves material demand into actual batch allocations (FEFO/FIFO, Section 16.2), and returns 409 with named alternatives on conflict -- never a silent failure.</p>
      <div class="card">
        <form id="sched-form">
          <div class="form-grid">
            <div class="field"><label>Order (APPROVED only)</label><select name="orderId" id="sched-order"></select></div>
            <div class="field"><label>Process Step</label><select name="processStepId" id="sched-step"></select></div>
            <div class="field"><label>Machine</label><select name="machineId">${optionList(machinesResp.items, "id", (m) => `${m.name} (${m.status})`)}</select></div>
            <div class="field"><label>Operator (optional)</label><select name="operatorId"><option value="">-- none --</option>${optionList(operatorsResp.items, "id", (o) => `${o.name || o.employeeCode}`)}</select></div>
            <div class="field"><label>Requested Start</label><input name="requestedStart" type="datetime-local" required /></div>
            <div class="field"><label>Requested End</label><input name="requestedEnd" type="datetime-local" required /></div>
          </div>
          <div id="bom-lines" class="section-divider">Material Requirements (from BOM)</div>
          <div id="bom-lines-body"></div>
          <div id="sched-error" class="form-error" hidden style="margin-top:12px"></div>
          <div style="margin-top:14px"><button class="btn btn-primary" type="submit">Submit Scheduling Request</button></div>
        </form>
      </div>
      <div id="sched-result"></div>
    `;
    this._orders = ordersResp.items;
    const orderSelect = document.getElementById("sched-order");
    orderSelect.innerHTML = optionList(this._orders, "id", (o) => `${o.code} -- ${o.productName} (${fmtNum(o.quantityOrdered, 0)})`);
    const processesResp = await Api.get("/v1/processes");
    this._processes = processesResp.items;
    const refreshSteps = () => {
      const order = this._orders.find((o) => o.id === orderSelect.value);
      const process = this._processes.find((p) => p.id === (order && order.processId));
      const stepSelect = document.getElementById("sched-step");
      stepSelect.innerHTML = process ? optionList(process.steps, "id", (s) => s.name) : "";
      refreshBom();
    };
    const refreshBom = () => {
      const order = this._orders.find((o) => o.id === orderSelect.value);
      const process = this._processes.find((p) => p.id === (order && order.processId));
      const stepId = document.getElementById("sched-step").value;
      const step = process && process.steps.find((s) => s.id === stepId);
      const body = document.getElementById("bom-lines-body");
      if (!step || !step.bomLines.length) { body.innerHTML = `<p class="muted">This step has no BOM lines.</p>`; return; }
      body.innerHTML = step.bomLines.map((bl, i) => `
        <div class="form-grid cols-3" style="margin-bottom:8px" data-bom-line>
          <div class="field"><label>Material</label><input type="hidden" name="mat_${i}" value="${bl.materialId}" /><span>${esc(bl.materialName)}</span></div>
          <div class="field"><label>Required Qty (${esc(bl.unitOfMeasure)})</label><input name="qty_${i}" type="number" step="any" value="${(bl.quantityPerUnit * (order ? order.quantityOrdered : 1)).toFixed(3)}" /></div>
          <div class="field"><label>Preferred Batch ID (optional)</label><input name="pref_${i}" placeholder="leave blank for FEFO/FIFO" /></div>
        </div>`).join("");
    };
    orderSelect.addEventListener("change", refreshSteps);
    document.getElementById("sched-step").addEventListener?.("change", refreshBom);
    refreshSteps();
    document.getElementById("content").addEventListener("change", (e) => { if (e.target.id === "sched-step") refreshBom(); });

    document.getElementById("sched-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const data = formToObject(form);
      const lines = [];
      form.querySelectorAll("[data-bom-line]").forEach((row, i) => {
        const mat = row.querySelector(`[name^=mat_]`).value;
        const qty = row.querySelector(`[name^=qty_]`).value;
        const pref = row.querySelector(`[name^=pref_]`).value;
        lines.push({ materialId: mat, requestedQuantity: parseFloat(qty), preferredBatchId: pref || null });
      });
      const payload = {
        processStepId: data.processStepId, machineId: data.machineId, operatorId: data.operatorId || null,
        requestedStart: new Date(data.requestedStart).toISOString(), requestedEnd: new Date(data.requestedEnd).toISOString(),
        materialAllocations: lines,
      };
      const errEl = document.getElementById("sched-error");
      errEl.hidden = true;
      try {
        const idempotencyKey = "ui-" + Date.now() + "-" + Math.random().toString(36).slice(2);
        const result = await Api.post(`/v1/production-orders/${data.orderId}/schedule`, payload, { idempotencyKey });
        this.renderScheduleResult(result, null);
        toast("Scheduled successfully -- resources reserved.", "success");
        App.renderNav();
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          this.renderScheduleResult(null, err.payload);
        } else {
          errEl.textContent = apiErrorMessage(err); errEl.hidden = false;
        }
      }
    });
  },

  renderScheduleResult(success, conflict) {
    const el = document.getElementById("sched-result");
    if (success) {
      el.innerHTML = `
        <div class="card" style="border-left:4px solid var(--success)">
          <h3>Scheduled -- ${statusBadge(success.status)}</h3>
          <dl class="kv-list">
            <dt>Run</dt><dd>${esc(success.runCode)}</dd>
            <dt>Expected Completion</dt><dd>${fmtDate(success.expectedCompletion)}</dd>
            <dt>Risk</dt><dd>${statusBadge(success.riskScore.classification)} (score ${success.riskScore.score})</dd>
          </dl>
          <div class="section-divider">Allocated Batches</div>
          ${success.materialAllocations.map((line) => `
            <div style="margin-bottom:6px"><strong>${fmtNum(line.requestedQuantity)} ${esc(line.unit || "")}</strong> requested &rarr;
            ${line.allocatedBatches.map((b) => `<span class="badge badge-blue">${esc(b.lotNumber)}: ${fmtNum(b.quantity)}</span>`).join(" ")}</div>
          `).join("")}
        </div>`;
    } else {
      el.innerHTML = `
        <div class="card" style="border-left:4px solid var(--danger)">
          <h3>409 Conflict -- ${esc(conflict.code)}</h3>
          <p>${esc(conflict.message)}</p>
          ${conflict.details && conflict.details.length ? `<pre style="background:#f7f8fb;padding:10px;border-radius:6px;font-size:12px;overflow-x:auto">${esc(JSON.stringify(conflict.details, null, 2))}</pre>` : ""}
          ${conflict.alternatives && conflict.alternatives.length ? `
            <div class="section-divider">Suggested Alternatives (Section 23.3)</div>
            ${conflict.alternatives.map((a) => `<div class="badge badge-yellow" style="margin-right:6px">${esc(JSON.stringify(a))}</div>`).join("")}
          ` : ""}
        </div>`;
    }
  },

  // ---------------- Planning (Processes / Steps / BOM) ----------------

  async planning() {
    const processesResp = await Api.get("/v1/processes");
    const canManage = Auth.hasPerm("MANAGE_PROCESSES");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Production Planning</h2>
        <div class="page-actions">${canManage ? `<button class="btn btn-primary" id="new-process-btn">+ New Process</button>` : ""}</div>
      </div>
      ${processesResp.items.map((p) => `
        <div class="card">
          <h3>${esc(p.name)} <span class="muted">${esc(p.description || "")}</span></h3>
          ${dataTable([
            { label: "#", key: "sequenceNumber" }, { label: "Step", key: "name" },
            { label: "Cycle Time (min/unit)", key: "standardCycleTime" },
            { label: "BOM Lines", render: (s) => s.bomLines.map((bl) => `${esc(bl.materialName)}: ${fmtNum(bl.quantityPerUnit, 4)} ${esc(bl.unitOfMeasure)}/unit`).join("<br/>") || "-" },
            { label: "", render: (s) => canManage ? `<button class="btn btn-sm" data-add-bom="${s.id}">+ BOM Line</button>` : "" },
          ], p.steps, { emptyText: "No process steps defined." })}
          ${canManage ? `<button class="btn btn-sm" style="margin-top:8px" data-add-step="${p.id}">+ Add Step</button>` : ""}
        </div>
      `).join("") || `<div class="empty-state">No processes defined yet.</div>`}
    `;
    if (canManage) {
      const newBtn = document.getElementById("new-process-btn");
      if (newBtn) newBtn.addEventListener("click", () => this.newProcessModal());
      content.querySelectorAll("[data-add-step]").forEach((b) => b.addEventListener("click", () => this.addStepModal(b.dataset.addStep)));
      content.querySelectorAll("[data-add-bom]").forEach((b) => b.addEventListener("click", () => this.addBomLineModal(b.dataset.addBom)));
    }
  },

  newProcessModal() {
    openModal({
      title: "New Process",
      bodyHtml: `<form id="proc-form"><div class="form-grid cols-1">
        <div class="field"><label>Name</label><input name="name" required /></div>
        <div class="field"><label>Description</label><textarea name="description"></textarea></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Create</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/processes", formToObject(document.getElementById("proc-form"))); closeModal(); toast("Process created.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  async addStepModal(processId) {
    const materialsResp = await Api.get("/v1/materials");
    openModal({
      title: "Add Process Step",
      bodyHtml: `<form id="step-form"><div class="form-grid cols-1">
        <div class="field"><label>Name</label><input name="name" required /></div>
        <div class="field"><label>Sequence Number</label><input name="sequenceNumber" type="number" value="1" /></div>
        <div class="field"><label>Standard Cycle Time (min/unit)</label><input name="standardCycleTime" type="number" step="any" value="1" /></div>
      </div></form>
      <p class="form-help">Add BOM lines afterward from the Planning table.</p>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Add</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("step-form"));
          data.sequenceNumber = parseInt(data.sequenceNumber); data.standardCycleTime = parseFloat(data.standardCycleTime);
          try { await Api.post(`/v1/processes/${processId}/steps`, data); closeModal(); toast("Step added.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  async addBomLineModal(stepId) {
    const materialsResp = await Api.get("/v1/materials");
    openModal({
      title: "Add BOM Line",
      bodyHtml: `<form id="bom-form"><div class="form-grid cols-1">
        <div class="field"><label>Material</label><select name="materialId">${optionList(materialsResp.items, "id", (m) => `${m.name} (${m.unitOfMeasure})`)}</select></div>
        <div class="field"><label>Quantity Per Unit</label><input name="quantityPerUnit" type="number" step="any" required /></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Add</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          const data = formToObject(document.getElementById("bom-form"));
          data.quantityPerUnit = parseFloat(data.quantityPerUnit);
          try { await Api.post(`/v1/process-steps/${stepId}/bom-lines`, data); closeModal(); toast("BOM line added.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },
};
window.Views = Views;
