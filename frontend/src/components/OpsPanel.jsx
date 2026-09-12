import React, { useEffect, useState } from "react";
import { getFunnel, getLeakage, getScorecard, inr, num } from "../api.js";
import { Card, Chip, Empty, ErrorBox, Loading } from "./Shared.jsx";

/* Three buckets, never merged. Each needs a different action: chase the
   partner, chase the lead, or fix our own routing. */
const BUCKETS = [
  {
    key: "untouched",
    title: "Untouched",
    blurb: "Assigned to a partner who has not made contact. Chase the partner.",
  },
  {
    key: "stalled",
    title: "Stalled",
    blurb: "Contacted, then frozen mid-funnel. Chase the lead.",
  },
  {
    key: "unrouted",
    title: "Unrouted",
    blurb: "Qualified but never assigned. Our routing gap, not theirs.",
  },
];

function LeakTable({ rows }) {
  if (!rows || rows.length === 0) {
    return <p className="caption">Nothing overdue.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Lead</th>
          <th>Partner</th>
          <th>Status</th>
          <th className="num">Idle hrs</th>
          <th className="num">SLA</th>
          <th>Severity</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.lead_id}>
            <td>{r.lead_id}</td>
            <td>{r.partner_id ?? "—"}</td>
            <td>{r.current_status}</td>
            <td className="num">{num(r.idle_hours)}</td>
            <td className="num">{num(r.sla_limit_hours)}</td>
            <td>
              {r.severity ? (
                <Chip tone={r.severity === "critical" ? "danger" : "warn"}>
                  {r.severity}
                </Chip>
              ) : (
                "—"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function OpsPanel() {
  const [leak, setLeak] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [cards, setCards] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getLeakage(), getFunnel(), getScorecard()]).then(
      ([l, f, s]) => {
        setLeak(l);
        setFunnel(f);
        setCards(s.partners ?? []);
      },
      (e) => setError(e.message)
    );
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!leak) return <Loading label="Loading operations" />;

  return (
    <>
      {BUCKETS.map((b) => (
        <Card key={b.key} title={`${b.title} · ${leak[`${b.key}_count`]}`} subtitle={b.blurb}>
          <LeakTable rows={leak[b.key]} />
        </Card>
      ))}

      <Card title="Funnel">
        <table>
          <thead>
            <tr>
              {Object.keys(funnel.funnel).map((k) => (
                <th key={k} className="num">
                  {k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {Object.values(funnel.funnel).map((v, i) => (
                <td key={i} className="num">
                  {v}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 14 }}>
          <Chip>assigned → funded {num(funnel.assigned_to_funded_pct)}%</Chip>
          <Chip>
            cost per funded customer{" "}
            {funnel.cost_per_funded_customer_rs === null
              ? "awaiting first funded outcome"
              : inr(funnel.cost_per_funded_customer_rs)}
          </Chip>
        </div>
      </Card>

      <Card title="Partner scorecard">
        {cards && cards.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Partner</th>
                <th className="num">Assigned</th>
                <th className="num">Contacted</th>
                <th className="num">Funded</th>
                <th className="num">Contact %</th>
                <th className="num">Median hrs</th>
                <th className="num">Breaches</th>
              </tr>
            </thead>
            <tbody>
              {cards.map((p) => (
                <tr key={p.partner_id}>
                  <td>{p.partner_id}</td>
                  <td className="num">{p.assigned}</td>
                  <td className="num">{p.contacted}</td>
                  <td className="num">{p.funded}</td>
                  <td className="num">{num(p.contact_rate_pct)}</td>
                  <td className="num">
                    {p.median_response_hours === null
                      ? "—"
                      : num(p.median_response_hours)}
                  </td>
                  <td className="num">{p.sla_breaches}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty title="No partner activity yet">
            Route a lead from the console or run ingestion with auto-routing.
          </Empty>
        )}
      </Card>
    </>
  );
}
