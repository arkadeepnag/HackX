import React, { useCallback, useEffect, useState } from "react";
import { getLeads, routing } from "./api.js";
import { ErrorBox } from "./components/Shared.jsx";
import MetricStrip from "./components/MetricStrip.jsx";
import Quadrant from "./components/Quadrant.jsx";
import LeadList, { PAGE } from "./components/LeadList.jsx";
import LeadDetail from "./components/LeadDetail.jsx";
import ChatReplay from "./components/ChatReplay.jsx";
import TerritoryMap from "./components/TerritoryMap.jsx";
import OpsPanel from "./components/OpsPanel.jsx";
import PartnerPortal from "./components/PartnerPortal.jsx";
import ModelHealth from "./components/ModelHealth.jsx";
import DataPanel from "./components/DataPanel.jsx";

const ANALYST_TABS = [
  { key: "console", label: "Lead console" },
  { key: "chat", label: "WhatsApp" },
  { key: "map", label: "Territory" },
  { key: "ops", label: "Operations" },
  { key: "model", label: "Model health" },
  { key: "data", label: "Data" },
];

function Console({ refreshKey, bump, onOpenLead }) {
  const [page, setPage] = useState(0);
  const [minPropensity, setMinPropensity] = useState(0);
  const [routingClass, setRoutingClass] = useState(null);
  const [list, setList] = useState(null);
  const [all, setAll] = useState([]);
  const [error, setError] = useState(null);

  // The list is paginated; the quadrant needs the whole population, so it
  // is fetched separately and once.
  useEffect(() => {
    getLeads({ limit: 1000 }).then(
      (r) => setAll(r.leads ?? []),
      (e) => setError(e.message)
    );
  }, [refreshKey]);

  useEffect(() => {
    getLeads({
      limit: PAGE,
      offset: page * PAGE,
      minimum_propensity_score: minPropensity || undefined,
      routing_class: routingClass || undefined,
    }).then(
      (r) => {
        setList(r);
        setError(null);
      },
      (e) => setError(e.message)
    );
  }, [page, minPropensity, routingClass, refreshKey]);

  const pickClass = (key) => {
    setRoutingClass(key);
    setPage(0);
  };

  return (
    <>
      <ErrorBox error={error} onRetry={bump} />
      <MetricStrip refreshKey={refreshKey} />
      <div className="console-layout">
        <Quadrant
          leads={all}
          active={routingClass}
          onSelectClass={pickClass}
          onPickLead={onOpenLead}
        />
        <LeadList
          data={list}
          page={page}
          onPage={setPage}
          onOpen={onOpenLead}
          filterLabel={routingClass ? routing(routingClass).label : null}
          minPropensity={minPropensity}
          onMinPropensity={(v) => {
            setMinPropensity(v);
            setPage(0);
          }}
        />
      </div>
    </>
  );
}

export default function App() {
  const [role, setRole] = useState("analyst");
  const [tab, setTab] = useState("console");
  const [leadId, setLeadId] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const bump = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && setLeadId(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app">
      <div className="workspace">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Prabha</span>
          <span className="brand-tag">Solar lead intelligence</span>
        </div>

        {role === "analyst" && (
          <nav className="tabs">
            {ANALYST_TABS.map((t) => (
              <button
                key={t.key}
                className={`tab${tab === t.key ? " active" : ""}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        )}

        {/* No auth on the backend by design — this is a view switch, not a
            login. */}
        <div className="role-switch">
          <button
            className={role === "analyst" ? "active" : ""}
            onClick={() => setRole("analyst")}
          >
            Analyst
          </button>
          <button
            className={role === "partner" ? "active" : ""}
            onClick={() => setRole("partner")}
          >
            Partner
          </button>
        </div>
      </header>

      <main className="main">
        {role === "analyst" && (
          <div className="page-intro">
            <div>
              <div className="eyebrow">TERRITORY INTELLIGENCE · LIVE WORKSPACE</div>
              <h1>{ANALYST_TABS.find((t) => t.key === tab)?.label ?? "Workspace"}</h1>
            </div>
            <div className="live-pill"><span /> Pipeline connected</div>
          </div>
        )}
        {role === "partner" ? (
          <PartnerPortal />
        ) : (
          <>
            {tab === "console" && (
              <Console
                refreshKey={refreshKey}
                bump={bump}
                onOpenLead={setLeadId}
              />
            )}
            {tab === "chat" && (
              <ChatReplay onLeadCreated={bump} onOpenLead={setLeadId} />
            )}
            {tab === "map" && <TerritoryMap onOpenLead={setLeadId} />}
            {tab === "ops" && <OpsPanel />}
            {tab === "model" && <ModelHealth />}
            {tab === "data" && <DataPanel onIngested={bump} />}
          </>
        )}
      </main>

      <LeadDetail leadId={leadId} onClose={() => setLeadId(null)} />
      </div>
    </div>
  );
}
