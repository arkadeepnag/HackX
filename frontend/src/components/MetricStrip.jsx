import React, { useEffect, useState } from "react";
import { getFunnel, getLeakage, getLeads, inr } from "../api.js";
import { Metric } from "./Shared.jsx";

export default function MetricStrip({ refreshKey }) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      getLeads({ limit: 1000 }),
      getFunnel(),
      getLeakage(),
    ]).then(([leadsR, funnelR, leakR]) => {
      if (cancelled) return;
      const leads = leadsR.status === "fulfilled" ? leadsR.value : null;
      const funnel = funnelR.status === "fulfilled" ? funnelR.value : null;
      const leak = leakR.status === "fulfilled" ? leakR.value : null;

      const kw = (leads?.leads ?? []).reduce(
        (sum, l) => sum + (l.capacity_kw ?? 0),
        0
      );
      setState({
        loading: false,
        total: leads?.total ?? 0,
        mw: kw / 1000,
        cost: funnel?.cost_per_funded_customer_rs ?? null,
        leaking:
          (leak?.untouched_count ?? 0) +
          (leak?.stalled_count ?? 0) +
          (leak?.unrouted_count ?? 0),
      });
    });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (state.loading) {
    return (
      <div className="metrics">
        {["Qualified leads", "Addressable", "Cost per funded", "Leaking"].map(
          (l) => (
            <Metric key={l} label={l} value="—" />
          )
        )}
      </div>
    );
  }

  return (
    <div className="metrics">
      <Metric label="Qualified leads" value={state.total.toLocaleString("en-IN")} />
      <Metric label="Addressable" value={`${state.mw.toFixed(1)} MW`} />
      {/* null until a lead funds — an honest empty state beats a fake zero */}
      {state.cost === null ? (
        <Metric
          label="Cost per funded customer"
          value="Awaiting first funded outcome"
          muted
        />
      ) : (
        <Metric label="Cost per funded customer" value={inr(state.cost)} />
      )}
      <Metric
        label="Leaking"
        value={state.leaking}
        note={state.leaking ? "needs chasing" : "nothing overdue"}
      />
    </div>
  );
}
