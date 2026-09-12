const BASE =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function call(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  let res;
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(
      `Cannot reach the backend at ${BASE}. Is uvicorn running?`,
      0
    );
  }

  if (!res.ok) {
    // Backend detail strings are written for humans — surface them as-is
    // rather than replacing them with a generic message.
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      if (Array.isArray(detail)) detail = JSON.stringify(detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

const qs = (params) =>
  new URLSearchParams(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== null && v !== ""
    )
  ).toString();

/* ------------------------------ leads ------------------------------ */

export const getLeads = (p = {}) => call(`/leads?${qs(p)}`);
export const getLead = (id) => call(`/leads/${encodeURIComponent(id)}`);

/* ------------------------------ chat ------------------------------- */

export const sendChat = (phone, text) =>
  call(`/whatsapp/simulate`, {
    method: "POST",
    body: JSON.stringify({ phone, text }),
  });

export const resetSession = (phone) =>
  call(`/whatsapp/session/${encodeURIComponent(phone)}`, { method: "DELETE" });

/* ------------------------------- map ------------------------------- */

export const getLeadPins = (bbox) => call(`/heatmap/leads?${qs(bbox)}`);

export const buildHeatmap = (body) =>
  call(`/heatmap/cluster`, { method: "POST", body: JSON.stringify(body) });

/* ------------------------------- ops ------------------------------- */

export const getLeakage = () => call(`/analytics/leakage`);
export const getFunnel = () => call(`/analytics/funnel`);
export const getScorecard = () => call(`/partners/scorecard`);
export const getPartners = () => call(`/partners`);

/* ---------------------------- partner ------------------------------ */

export const getPartnerLeads = (id, p = {}) =>
  call(`/partner-portal/${encodeURIComponent(id)}/leads?${qs(p)}`);

export const getPartnerSummary = (id) =>
  call(`/partner-portal/${encodeURIComponent(id)}/summary`);

export const setPartnerStatus = (partnerId, leadId, status) =>
  call(
    `/partner-portal/${encodeURIComponent(partnerId)}/leads/` +
      `${encodeURIComponent(leadId)}/status?${qs({ status })}`,
    { method: "POST" }
  );

/* ---------------------------- learning ----------------------------- */

export const getMistakes = () => call(`/learning/mistakes`);
export const getCalibration = () => call(`/learning/calibration`);
export const runLearning = () => call(`/learning/run`, { method: "POST" });

/* ----------------------------- ingest ------------------------------ */

export const ingestFile = (path) =>
  call(`/ingest/file`, {
    method: "POST",
    body: JSON.stringify({ path, data_mode: "offline", auto_route: true }),
  });

/* --------------------------- formatting ---------------------------- */

/** Indian digit grouping. 170500 -> "1,70,500", which reads as money. */
export function inr(value, { decimals = 0, prefix = "₹" } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return (
    prefix +
    Number(value).toLocaleString("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })
  );
}

/** Scores arrive as raw floats like 65.76068319479907. */
export function score(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(Number(value));
}

export function num(value, decimals = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toFixed(decimals);
}

/** null means "not known yet", never zero. */
export function orDash(value, formatter = (v) => v) {
  return value === null || value === undefined ? "—" : formatter(value);
}

export const ROUTING = {
  high_priority: {
    label: "High priority",
    short: "Route now",
    color: "var(--rc-high)",
    bg: "var(--rc-high-bg)",
    text: "var(--rc-high-text)",
  },
  high_propensity_finance_risk: {
    label: "Financing risk",
    short: "Will fail underwriting",
    color: "var(--rc-risk)",
    bg: "var(--rc-risk-bg)",
    text: "var(--rc-risk-text)",
  },
  low_propensity_financeable: {
    label: "Financeable",
    short: "Needs warming",
    color: "var(--rc-finance)",
    bg: "var(--rc-finance-bg)",
    text: "var(--rc-finance-text)",
  },
  discard_or_nurture: {
    label: "Discard",
    short: "Nurture only",
    color: "var(--rc-discard)",
    bg: "var(--rc-discard-bg)",
    text: "var(--rc-discard-text)",
  },
};

export const routing = (key) => ROUTING[key] ?? ROUTING.discard_or_nurture;

/** Backend thresholds. Drawing the quadrant anywhere else would make the
 *  chart disagree with its own labels. */
export const PROPENSITY_BAR = 55;
export const FINANCING_BAR = 50;

export const BAND_COLORS = {
  very_low: "#e1f5ee",
  low: "#9fe1cb",
  medium: "#5dcaa5",
  high: "#1d9e75",
  very_high: "#0f6e56",
};
