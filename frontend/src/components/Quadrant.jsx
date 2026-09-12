import React, { useMemo } from "react";
import {
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ResponsiveContainer,
} from "recharts";
import {
  FINANCING_BAR,
  PROPENSITY_BAR,
  ROUTING,
  inr,
  score,
} from "../api.js";
import { Card } from "./Shared.jsx";

const QUADRANTS = [
  {
    key: "high_propensity_finance_risk",
    x1: 0, x2: FINANCING_BAR, y1: PROPENSITY_BAR, y2: 100,
  },
  {
    key: "high_priority",
    x1: FINANCING_BAR, x2: 100, y1: PROPENSITY_BAR, y2: 100,
  },
  {
    key: "discard_or_nurture",
    x1: 0, x2: FINANCING_BAR, y1: 0, y2: PROPENSITY_BAR,
  },
  {
    key: "low_propensity_financeable",
    x1: FINANCING_BAR, x2: 100, y1: 0, y2: PROPENSITY_BAR,
  },
];

function PointTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--border-strong)",
        borderRadius: 8,
        padding: "8px 10px",
        fontSize: 12,
        maxWidth: 240,
      }}
    >
      <div style={{ fontWeight: 500, marginBottom: 2 }}>
        {d.entity_name || d.lead_id}
      </div>
      <div style={{ color: "var(--text-secondary)" }}>
        propensity {score(d.propensity_score)} · financing{" "}
        {score(d.financing_score)}
      </div>
      <div style={{ color: "var(--text-secondary)" }}>
        {d.capacity_kw?.toFixed(1)} kW ·{" "}
        {inr(d.net_monthly_benefit_rs)}/mo net
      </div>
    </div>
  );
}

export default function Quadrant({ leads, active, onSelectClass, onPickLead }) {
  const groups = useMemo(() => {
    const out = {};
    for (const key of Object.keys(ROUTING)) out[key] = [];
    for (const lead of leads) {
      (out[lead.routing_class] ?? out.discard_or_nurture).push(lead);
    }
    return out;
  }, [leads]);

  return (
    <Card
      title="Dual-axis score"
      subtitle="Propensity to convert against financing eligibility. Click a quadrant to filter the list."
      actions={
        active && (
          <button className="btn small" onClick={() => onSelectClass(null)}>
            Clear filter
          </button>
        )
      }
    >
      <div className="quadrant-chart" style={{ width: "100%", height: 310 }}>
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />

            {QUADRANTS.map((q) => (
              <ReferenceArea
                key={q.key}
                x1={q.x1}
                x2={q.x2}
                y1={q.y1}
                y2={q.y2}
                fill={ROUTING[q.key].bg}
                fillOpacity={active && active !== q.key ? 0.35 : 1}
                stroke="none"
                onClick={() => onSelectClass(active === q.key ? null : q.key)}
                style={{ cursor: "pointer" }}
              />
            ))}

            <XAxis
              type="number"
              dataKey="financing_score"
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              label={{
                value: "Financing eligibility →",
                position: "bottom",
                offset: 8,
                style: { fontSize: 11, fill: "var(--text-secondary)" },
              }}
            />
            <YAxis
              type="number"
              dataKey="propensity_score"
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              label={{
                value: "Propensity →",
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: "var(--text-secondary)" },
              }}
            />

            <ReferenceLine x={FINANCING_BAR} stroke="var(--border-strong)" />
            <ReferenceLine y={PROPENSITY_BAR} stroke="var(--border-strong)" />

            <Tooltip content={<PointTooltip />} />

            {Object.entries(groups).map(([key, data]) => (
              <Scatter
                key={key}
                data={data}
                fill={ROUTING[key].color}
                fillOpacity={active && active !== key ? 0.25 : 0.9}
                onClick={(d) => onPickLead?.(d.lead_id)}
                style={{ cursor: "pointer" }}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <div className="legend">
        {Object.entries(ROUTING).map(([key, r]) => (
          <button
            key={key}
            className="legend-item"
            onClick={() => onSelectClass(active === key ? null : key)}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              opacity: active && active !== key ? 0.4 : 1,
            }}
          >
            <span className="swatch" style={{ background: r.color }} />
            {r.label}
            <span style={{ color: "var(--text-muted)" }}>
              ({groups[key].length})
            </span>
          </button>
        ))}
      </div>
      <p className="caption" style={{ marginTop: 8 }}>
        A lead that scores high on propensity but low on financing is a false
        positive — it will fail underwriting after the quote.
      </p>
    </Card>
  );
}
