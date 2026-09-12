import React from "react";
import { routing } from "../api.js";

export function Card({ title, subtitle, actions, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {subtitle && <p className="card-sub">{subtitle}</p>}
      {children}
    </section>
  );
}

export function Metric({ label, value, note, muted = false }) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value${muted ? " muted" : ""}`}>{value}</div>
      {note && <div className="metric-note">{note}</div>}
    </div>
  );
}

export function RoutingBadge({ value }) {
  const r = routing(value);
  return (
    <span
      className="rc-badge"
      style={{ background: r.bg, color: r.text }}
      title={r.short}
    >
      {r.label}
    </span>
  );
}

export function Chip({ children, tone = "" }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="error">
      {error}
      {onRetry && (
        <>
          {" "}
          <button className="btn small" onClick={onRetry}>
            Retry
          </button>
        </>
      )}
    </div>
  );
}

export function Loading({ label = "Loading" }) {
  return (
    <div className="empty">
      <span className="spinner" /> <span className="caption">{label}…</span>
    </div>
  );
}

/** Tariff data ships at confidence 0.35 from MVP_CONFIG. Surfacing that is
 *  more credible than implying precision we do not have. */
export function DataCaveat({ source, confidence }) {
  if (!source && confidence === undefined) return null;
  return (
    <p className="caption" style={{ marginTop: 10 }}>
      Tariff basis: {source ?? "unknown"}
      {confidence !== undefined && ` · confidence ${confidence}`} — figures are
      indicative.
    </p>
  );
}
