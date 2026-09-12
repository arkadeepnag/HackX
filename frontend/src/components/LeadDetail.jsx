import React, { useEffect, useState } from "react";
import { getLead, inr, num, orDash, score } from "../api.js";
import {
  Card,
  Chip,
  ErrorBox,
  Loading,
  RoutingBadge,
} from "./Shared.jsx";

function Row({ label, value }) {
  return (
    <div className="wf-line">
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

/** The waterfall mirrors how a buyer reasons: what it costs, what the
 *  government pays, what they finance, and what lands in their pocket. */
function Waterfall({ capex }) {
  return (
    <div className="waterfall">
      <Row label="Estimated system cost" value={inr(capex.gross_capex_rs)} />
      {capex.subsidy_rs > 0 && (
        <div className="wf-line sub">
          <span>PM Surya Ghar subsidy</span>
          <span>− {inr(capex.subsidy_rs)}</span>
        </div>
      )}
      <div className="wf-line total">
        <span>Your cost</span>
        <span>{inr(capex.net_capex_rs)}</span>
      </div>

      <div style={{ height: 12 }} />

      <Row label="Monthly bill savings" value={inr(capex.monthly_savings_rs)} />
      <Row label="Monthly EMI" value={`− ${inr(capex.monthly_emi_rs)}`} />

      <div className="wf-hero spread">
        <div>
          <div className="wf-hero-label">Net benefit every month</div>
          <div className="caption">
            {capex.cash_positive_from_day_one
              ? "Cash positive from day one"
              : "EMI exceeds savings in year one"}
          </div>
        </div>
        <div className="wf-hero-value">
          {inr(capex.net_monthly_benefit_rs)}
        </div>
      </div>

      <div className="row" style={{ marginTop: 14, gap: 18 }}>
        <span className="caption">
          Payback {num(capex.payback_years)} years
        </span>
        <span className="caption">IRR {num(capex.irr_pct)}%</span>
        <span className="caption">
          {capex.loan_tenure_years}y @ {num(capex.loan_rate_pct)}%
        </span>
      </div>
      <p className="caption" style={{ marginTop: 4 }}>
        {capex.payback_basis}
      </p>
    </div>
  );
}

function OpexComparison({ offer }) {
  const { opex_option: opex, comparison, capex_option: capex } = offer;
  if (!opex || !comparison) return null;
  const ad = capex.incentives?.accelerated_depreciation;
  const pickCapex = comparison.recommendation === "capex";

  return (
    <Card title="CAPEX vs OPEX">
      <div className="grid-2">
        <div
          className="card"
          style={{
            margin: 0,
            borderWidth: pickCapex ? 2 : 1,
            borderColor: pickCapex ? "var(--rc-high)" : "var(--border)",
          }}
        >
          <div className="spread">
            <h3>You buy it</h3>
            {pickCapex && <Chip tone="ok">Recommended</Chip>}
          </div>
          <Row label="Upfront" value={inr(capex.down_payment_rs)} />
          <Row label="Monthly EMI" value={inr(capex.monthly_emi_rs)} />
          <Row
            label="Net monthly benefit"
            value={inr(capex.net_monthly_benefit_rs)}
          />
          {ad && (
            <>
              <Row
                label="Year-1 tax shield"
                value={inr(ad.year1_tax_shield_rs)}
              />
              <p className="caption">
                A tax shield, not a grant — realisable only against taxable
                profit.
              </p>
            </>
          )}
        </div>

        <div
          className="card"
          style={{
            margin: 0,
            borderWidth: pickCapex ? 1 : 2,
            borderColor: pickCapex ? "var(--border)" : "var(--rc-high)",
          }}
        >
          <div className="spread">
            <h3>Developer owns it (PPA)</h3>
            {!pickCapex && <Chip tone="ok">Recommended</Chip>}
          </div>
          <Row label="Upfront" value={inr(0)} />
          <Row
            label="Tariff"
            value={`${inr(opex.ppa_tariff_rs_kwh, { decimals: 2 })}/unit`}
          />
          <Row
            label="Net monthly benefit"
            value={inr(opex.net_monthly_benefit_rs)}
          />
          <Row label="Balance sheet impact" value={opex.balance_sheet_impact} />
        </div>
      </div>
      <p className="caption" style={{ marginTop: 12 }}>
        {comparison.rationale}
      </p>
    </Card>
  );
}

export default function LeadDetail({ leadId, onClose }) {
  const [lead, setLead] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!leadId) return;
    setLead(null);
    setError(null);
    getLead(leadId).then(setLead, (e) => setError(e.message));
  }, [leadId]);

  if (!leadId) return null;

  const q = lead?.qualification ?? {};
  const capex = lead?.offer?.capex_option;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer">
        <div className="spread" style={{ marginBottom: 16 }}>
          <h1>{lead?.entity_name || leadId}</h1>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>

        <ErrorBox error={error} />
        {!lead && !error && <Loading label="Loading lead" />}

        {lead && (
          <>
            <div className="row" style={{ marginBottom: 16 }}>
              <RoutingBadge value={lead.routing_class} />
              <span className="caption">
                propensity {score(lead.propensity_score)} · financing{" "}
                {score(lead.financing_score)} · solar {score(lead.solar_score)}
              </span>
            </div>
            {lead.address && <p className="caption">{lead.address}</p>}

            {capex && (
              <Card title="The numbers">
                <Waterfall capex={capex} />
              </Card>
            )}

            {lead.offer?.opex_option && <OpexComparison offer={lead.offer} />}

            <Card title="Solar">
              <Row
                label="Usable roof area"
                value={`${num(lead.usable_roof_area_m2)} m²`}
              />
              <Row
                label="Recommended capacity"
                value={`${num(lead.capacity_kw, 2)} kW`}
              />
              <Row
                label="Shading loss"
                value={`${num(lead.annual_shading_loss_pct)}%`}
              />
              <Row
                label="Annual generation"
                value={`${orDash(lead.annual_generation_kwh, (v) =>
                  Math.round(v).toLocaleString("en-IN")
                )} kWh`}
              />
              <Row
                label="Tariff"
                value={`${inr(lead.tariff_rs_kwh, { decimals: 2 })}/unit · ${
                  lead.discom ?? "unknown discom"
                }`}
              />
              {lead.sizing?.binding_constraint && (
                <p className="caption">
                  Sizing bound by {lead.sizing.binding_constraint.replace(/_/g, " ")}.
                </p>
              )}
            </Card>

            <Card title="Qualification">
              <Row
                label="Roof ownership"
                value={orDash(q.owned_roof, (v) => (v ? "Owned" : "Rented"))}
              />
              <Row
                label="Sanctioned load"
                value={orDash(q.sanctioned_load_kw, (v) => `${v} kW`)}
              />
              <Row label="Bills supplied" value={q.bill_count ?? 0} />
              <Row
                label="Roof photo"
                value={q.roof_photo_uploaded ? "Uploaded" : "Not supplied"}
              />
              {q.roof_photo_url && (
                <img
                  src={q.roof_photo_url}
                  alt="Roof"
                  style={{
                    width: "100%",
                    borderRadius: 8,
                    marginTop: 10,
                    border: "1px solid var(--border)",
                  }}
                />
              )}
              <div className="chips" style={{ marginTop: 10 }}>
                {lead.identity_signals?.udyam && <Chip tone="ok">Udyam</Chip>}
                {lead.identity_signals?.mca && <Chip tone="ok">MCA</Chip>}
                {lead.identity_signals?.gst && <Chip tone="ok">GST</Chip>}
                {lead.segment_unknown && (
                  <Chip tone="warn">segment needs qualification</Chip>
                )}
                {lead.consumption_assumed && (
                  <Chip>consumption estimated, not measured</Chip>
                )}
              </div>
            </Card>

            <Card title="Why">
              <div className="chips">
                {(lead.reasons ?? []).map((r, i) => (
                  <Chip key={i}>{r}</Chip>
                ))}
              </div>
              {!lead.sla_eligible &&
                (lead.sla_failed_conditions ?? []).length > 0 && (
                  <div className="chips" style={{ marginTop: 8 }}>
                    {lead.sla_failed_conditions.map((c) => (
                      <Chip key={c} tone="danger">
                        fails {c.replace(/_/g, " ")}
                      </Chip>
                    ))}
                  </div>
                )}
              <p className="caption" style={{ marginTop: 10 }}>
                Source: {lead.source ?? "unknown"}
                {lead.location_source && ` · location ${lead.location_source}`}
                {lead.partner_id && ` · assigned ${lead.partner_id}`}
              </p>
            </Card>
          </>
        )}
      </aside>
    </>
  );
}
