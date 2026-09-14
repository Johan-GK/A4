/* Shared rendering helpers: badges, tables, modals, toasts, forms. */

function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function fmtNum(n, digits = 2) {
  if (n === null || n === undefined || n === "") return "-";
  const num = Number(n);
  if (isNaN(num)) return n;
  return num.toLocaleString(undefined, { maximumFractionDigits: digits });
}

const STATUS_COLORS = {
  AVAILABLE: "green", RUNNING: "blue", RESERVED: "primary", PAUSED: "yellow", FAULT: "red",
  MAINTENANCE: "yellow", OFFLINE: "gray", DECOMMISSIONED: "gray",
  PENDING_INSPECTION: "yellow", ON_HOLD: "red", REJECTED: "red", DEPLETED: "gray", EXPIRED: "red",
  RELEASED: "green", REWORK_REQUIRED: "yellow", SCRAPPED: "red",
  DRAFT: "gray", SUBMITTED: "yellow", APPROVED: "blue", READY: "primary", COMPLETED: "green",
  DELAYED: "yellow", CANCELLED: "gray",
  SCHEDULED: "primary", MATERIAL_SUBSTITUTION_PENDING: "yellow", PARTIALLY_COMPLETED: "yellow",
  SCRAP_REWORK_REVIEW: "red",
  OPEN: "yellow", UNDER_INVESTIGATION: "blue", ACTION_REQUIRED: "yellow", CORRECTIVE_ACTION: "blue",
  VERIFICATION: "blue", CLOSED: "green", REOPENED: "red",
  NEW: "yellow", ACKNOWLEDGED: "blue", IN_PROGRESS: "blue", RESOLVED: "green", DISMISSED: "gray",
  ACTIVE: "green", INACTIVE: "gray", LOCKED: "red", SUSPENDED: "red",
  PASS: "green", FAIL: "red",
  LOW: "green", MEDIUM: "yellow", HIGH: "red", CRITICAL: "red",
  MINOR: "yellow", MAJOR: "red",
  PENDING: "yellow", REQUESTED: "yellow",
};
function statusBadge(status) {
  const color = STATUS_COLORS[status] || "gray";
  return `<span class="badge badge-${color}">${esc(status || "-")}</span>`;
}

function riskColor(classification) {
  return { LOW: "#1f8a4c", MEDIUM: "#b8860b", HIGH: "#d1373f", CRITICAL: "#8c1c22" }[classification] || "#888";
}

function dataTable(columns, rows, opts = {}) {
  if (!rows || rows.length === 0) {
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead></table><div class="table-empty">${opts.emptyText || "No records found."}</div></div>`;
  }
  const head = `<tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr>`;
  const body = rows.map((row) => `<tr>${columns.map((c) => `<td>${c.render ? c.render(row) : esc(row[c.key])}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table class="data-table"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

function toast(message, type = "info") {
  const root = document.getElementById("toast-root");
  const div = document.createElement("div");
  div.className = `toast toast-${type}`;
  div.textContent = message;
  root.appendChild(div);
  setTimeout(() => { div.style.opacity = "0"; div.style.transition = "opacity .3s"; setTimeout(() => div.remove(), 300); }, 4200);
}

function apiErrorMessage(err) {
  if (err instanceof ApiError) {
    const p = err.payload;
    if (typeof p === "string") return p;
    if (p && p.message) {
      let msg = p.message;
      if (p.details && p.details.length) msg += " (" + JSON.stringify(p.details[0]) + ")";
      return msg;
    }
    return err.message;
  }
  return err.message || String(err);
}

function notifyError(err) {
  toast(apiErrorMessage(err), "error");
}

/* ---------------- Modal ---------------- */
function closeModal() {
  const root = document.getElementById("modal-root");
  root.innerHTML = "";
}
function openModal({ title, bodyHtml, wide, footerHtml, onMount }) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `
    <div class="modal-overlay" id="modal-overlay">
      <div class="modal-box ${wide ? "wide" : ""}">
        <div class="modal-header"><h3>${esc(title)}</h3><button class="icon-btn" id="modal-close">&times;</button></div>
        <div class="modal-body">${bodyHtml}</div>
        ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ""}
      </div>
    </div>`;
  document.getElementById("modal-close").onclick = closeModal;
  document.getElementById("modal-overlay").addEventListener("click", (e) => {
    if (e.target.id === "modal-overlay") closeModal();
  });
  if (onMount) onMount(root);
}

function formToObject(form) {
  const data = {};
  new FormData(form).forEach((value, key) => {
    if (data[key] !== undefined) {
      if (!Array.isArray(data[key])) data[key] = [data[key]];
      data[key].push(value);
    } else {
      data[key] = value;
    }
  });
  return data;
}

function optionList(items, valueKey, labelFn) {
  return items.map((i) => `<option value="${esc(i[valueKey])}">${esc(labelFn(i))}</option>`).join("");
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function riskBar(score, classification) {
  const pct = Math.max(2, Math.min(100, score));
  return `<div class="risk-bar-track"><div class="risk-bar-fill" style="width:${pct}%;background:${riskColor(classification)}"></div></div>`;
}

function timeAgo(iso) {
  if (!iso) return "-";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}
