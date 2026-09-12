import React from "react";
import { inr, routing, score } from "../api.js";
import { Card, Chip, Empty, RoutingBadge } from "./Shared.jsx";

const PAGE = 25;

function initials(lead) {
  const name = lead.entity_name || lead.segment || "?";
  return name.slice(0, 2).toUpperCase();
}

function LeadRow({ lead, onOpen }) {
  const r = routing(lead.routing_class);
  const signals = lead.identity_signals ?? {};

  return (
    <button className="lead-row" onClick={() => onOpen(lead.lead_id)}>
      <span
        className="lead-icon"
        style={{ background: r.bg, color: r.text }}
        aria-hidden="true"
      >
        {initials(lead)}
      </span>

      <span className="lead-main">
        <span className="lead-title">
          {lead.entity_name || lead.address || lead.lead_id}
        </span>
        <span className="lead-meta">
          {lead.capacity_kw?.toFixed(1)} kW · {lead.segment} ·{" "}
          {lead.pincode ?? "no pincode"} · payback{" "}
          {lead.payback_years?.toFixed(1)}y · IRR{" "}
          {lead.irr_pct?.toFixed(0)}%
        </span>
        <span className="chips">
          <RoutingBadge value={lead.routing_class} />
          {lead.segment_unknown && <Chip tone="warn">needs qualification</Chip>}
          {lead.consumption_assumed && <Chip>consumption estimated</Chip>}
          {signals.udyam && <Chip tone="ok">Udyam</Chip>}
          {signals.mca && <Chip tone="ok">MCA</Chip>}
          {signals.gst && <Chip tone="ok">GST</Chip>}
          {!lead.sla_eligible && <Chip tone="danger">below SLA</Chip>}
        </span>
      </span>

      <span className="lead-money">
        <span className="lead-money-value">
          {inr(lead.net_monthly_benefit_rs)}
        </span>
        <span className="lead-money-label">net / month</span>
      </span>

      <span className="lead-scores">
        <span className="lead-scores-value">
          {score(lead.propensity_score)} / {score(lead.financing_score)}
        </span>
        <span className="lead-scores-label">prop / fin</span>
      </span>
    </button>
  );
}

export default function LeadList({
  data,
  page,
  onPage,
  onOpen,
  filterLabel,
  minPropensity,
  onMinPropensity,
}) {
  const leads = data?.leads ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : page * PAGE + 1;
  const to = Math.min(total, page * PAGE + leads.length);

  return (
    <Card
      className="leads-card"
      title="Ranked leads"
      subtitle={
        filterLabel
          ? `Filtered to ${filterLabel}`
          : "Sorted by propensity, then financing eligibility"
      }
      actions={
        <div className="row">
          <label className="caption" htmlFor="minprop">
            Min propensity
          </label>
          <input
            id="minprop"
            type="number"
            min="0"
            max="100"
            step="5"
            value={minPropensity}
            onChange={(e) => onMinPropensity(Number(e.target.value))}
            style={{ width: 74 }}
          />
        </div>
      }
    >
      {leads.length === 0 ? (
        <Empty title="No leads yet">
          Run ingestion from the Data tab, or drive a conversation in the
          WhatsApp tab to create one.
        </Empty>
      ) : (
        <>
          <div>
            {leads.map((lead) => (
              <LeadRow key={lead.lead_id} lead={lead} onOpen={onOpen} />
            ))}
          </div>

          <div className="spread" style={{ marginTop: 14 }}>
            <span className="caption">
              {from}–{to} of {total.toLocaleString("en-IN")}
            </span>
            <div className="row">
              <button
                className="btn small"
                disabled={page === 0}
                onClick={() => onPage(page - 1)}
              >
                Previous
              </button>
              <button
                className="btn small"
                disabled={!data?.has_more}
                onClick={() => onPage(page + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

export { PAGE };
