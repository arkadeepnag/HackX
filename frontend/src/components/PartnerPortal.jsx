import React, { useEffect, useState } from "react";
import {
  getPartnerLeads,
  getPartnerSummary,
  getPartners,
  inr,
  num,
  setPartnerStatus,
} from "../api.js";
import { Card, Chip, Empty, ErrorBox, Loading } from "./Shared.jsx";

function slaHours(assignedAt) {
  if (!assignedAt) return null;
  return (Date.now() - new Date(assignedAt).getTime()) / 3_600_000;
}

export default function PartnerPortal() {
  const [partners, setPartners] = useState(null);
  const [selected, setSelected] = useState(null);
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getPartners().then(
      (r) => {
        setPartners(r.partners ?? []);
        if (r.partners?.length) setSelected(r.partners[0].partner_id);
      },
      (e) => setError(e.message)
    );
  }, []);

  const load = React.useCallback(() => {
    if (!selected) return;
    Promise.all([
      getPartnerLeads(selected, { limit: 50 }),
      getPartnerSummary(selected),
    ]).then(
      ([l, s]) => {
        setData(l);
        setSummary(s);
        setError(null);
      },
      (e) => setError(e.message)
    );
  }, [selected]);

  useEffect(load, [load]);

  async function mark(leadId, status) {
    try {
      await setPartnerStatus(selected, leadId, status);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!partners) return <Loading label="Loading partners" />;

  return (
    <>
      <ErrorBox error={error} />
      <Card
        title="Partner portal"
        subtitle="What an installer sees. Internal scores are withheld by design — a partner who can see the ranking works the top and lets the rest rot."
        actions={
          <select
            value={selected ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {partners.map((p) => (
              <option key={p.partner_id} value={p.partner_id}>
                {p.name}
              </option>
            ))}
          </select>
        }
      >
        {summary && (
          <div className="row" style={{ marginBottom: 14 }}>
            <Chip>{summary.open_leads} open</Chip>
            <Chip>{summary.scorecard?.assigned ?? 0} assigned</Chip>
            <Chip>{summary.scorecard?.funded ?? 0} funded</Chip>
            {summary.overdue_contacts?.length > 0 && (
              <Chip tone="danger">
                {summary.overdue_contacts.length} overdue
              </Chip>
            )}
          </div>
        )}

        {!data || data.leads.length === 0 ? (
          <Empty title="No leads assigned">
            Route a lead to this partner from the console.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Lead</th>
                <th>Segment</th>
                <th className="num">kW</th>
                <th className="num">Savings / mo</th>
                <th className="num">EMI</th>
                <th className="num">SLA hrs</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {data.leads.map((l) => {
                const hrs = slaHours(l.assigned_at);
                return (
                  <tr key={l.lead_id}>
                    <td>
                      {l.lead_id}
                      <div className="caption">{l.pincode}</div>
                    </td>
                    <td>{l.segment}</td>
                    <td className="num">{num(l.recommended_capacity_kw)}</td>
                    <td className="num">
                      {inr(l.estimated_monthly_savings_rs)}
                    </td>
                    <td className="num">{inr(l.indicative_emi_rs)}</td>
                    <td className="num">
                      {hrs === null ? "—" : num(hrs)}
                      {hrs > 24 && " ⚠"}
                    </td>
                    <td>
                      <div className="row">
                        <button
                          className="btn small"
                          onClick={() => mark(l.lead_id, "contacted")}
                        >
                          Contacted
                        </button>
                        <button
                          className="btn small"
                          onClick={() => mark(l.lead_id, "funded")}
                        >
                          Funded
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="caption" style={{ marginTop: 12 }}>
          Showing {data?.leads.length ?? 0} of {data?.total ?? 0}.
        </p>
      </Card>
    </>
  );
}
