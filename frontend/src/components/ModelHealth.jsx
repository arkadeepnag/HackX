import React, { useEffect, useState } from "react";
import { getCalibration, getMistakes, num, runLearning, score } from "../api.js";
import { Card, Chip, Empty, ErrorBox, Loading } from "./Shared.jsx";

/* Labelled by cost, not by statistic. "False positive" means nothing to an
   ops lead; "wasted field visits" does. */
function MistakeTable({ rows, emptyText }) {
  if (!rows || rows.length === 0) return <p className="caption">{emptyText}</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Lead</th>
          <th className="num">Prop</th>
          <th className="num">Fin</th>
          <th>Outcome</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.lead_id}>
            <td>
              {r.lead_id}
              <div className="caption">{r.cost}</div>
            </td>
            <td className="num">{score(r.propensity_score)}</td>
            <td className="num">{score(r.financing_score)}</td>
            <td>{r.terminal_status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ModelHealth() {
  const [m, setM] = useState(null);
  const [cal, setCal] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = React.useCallback(() => {
    Promise.all([getMistakes(), getCalibration()]).then(
      ([mistakes, calibration]) => {
        setM(mistakes);
        setCal(calibration);
        setError(null);
      },
      (e) => setError(e.message)
    );
  }, []);

  useEffect(load, [load]);

  async function retrain() {
    setBusy(true);
    try {
      await runLearning();
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorBox error={error} onRetry={load} />;
  if (!m) return <Loading label="Loading model health" />;

  if (m.sample_count === 0) {
    return (
      <Card title="Model health">
        <Empty title="No terminal outcomes yet">
          The loop learns from leads that reached funded, dropped or rejected.
          Mark a lead funded in the partner portal to seed it.
        </Empty>
      </Card>
    );
  }

  return (
    <>
      <Card
        title="Where the score was wrong"
        subtitle={m.guidance}
        actions={
          <button className="btn small" onClick={retrain} disabled={busy}>
            {busy ? "Retraining…" : "Retrain"}
          </button>
        }
      >
        <div className="row" style={{ marginBottom: 16 }}>
          <Chip>{m.sample_count} outcomes</Chip>
          <Chip>{m.funded_count} funded</Chip>
          <Chip>precision {m.precision ?? "—"}</Chip>
          <Chip>recall {m.recall ?? "—"}</Chip>
          <Chip tone={m.bias === "balanced" ? "ok" : "warn"}>{m.bias}</Chip>
        </div>

        <div className="grid-2">
          <div>
            <h3>Wasted field visits</h3>
            <p className="caption" style={{ marginBottom: 8 }}>
              {m.false_positives} leads scored above the bar and then died.
            </p>
            <MistakeTable
              rows={m.worst_false_positives}
              emptyText="None — nothing routed has failed yet."
            />
          </div>
          <div>
            <h3>Revenue we would have discarded</h3>
            <p className="caption" style={{ marginBottom: 8 }}>
              {m.false_negatives} leads scored below the bar and funded anyway.
            </p>
            <MistakeTable
              rows={m.worst_false_negatives}
              emptyText="None — the bar is not turning away funded business."
            />
          </div>
        </div>
      </Card>

      <Card
        title="Calibration"
        subtitle="A well-calibrated score funds more often as it rises. A band where the rate falls means a feature weight is wrong."
      >
        <table>
          <thead>
            <tr>
              <th>Band</th>
              <th className="num">Leads</th>
              <th className="num">Funded rate</th>
              <th className="num">Expected</th>
              <th>Warning</th>
            </tr>
          </thead>
          <tbody>
            {(cal?.bands ?? []).map((b) => (
              <tr key={b.band}>
                <td>{b.band}</td>
                <td className="num">{b.count}</td>
                <td className="num">
                  {b.funded_rate === null ? "—" : num(b.funded_rate, 2)}
                </td>
                <td className="num">{num(b.expected_rate, 2)}</td>
                <td>{b.warning ? <Chip tone="warn">{b.warning}</Chip> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
