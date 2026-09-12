import React, { useState } from "react";
import { ingestFile, num } from "../api.js";
import { Card, Chip, ErrorBox } from "./Shared.jsx";

export default function DataPanel({ onIngested }) {
  const [path, setPath] = useState(
    "../hackx4.0-main/outputs/target_universe.csv"
  );
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await ingestFile(path);
      setResult(res);
      onIngested?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Ingest discovery candidates"
      subtitle="Reads the target universe produced by the discovery pipeline and runs every row through viability, financing, scoring and routing."
    >
      <div className="row">
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          style={{ flex: 1, minWidth: 320 }}
        />
        <button className="btn primary" onClick={run} disabled={busy}>
          {busy ? "Ingesting…" : "Ingest"}
        </button>
      </div>
      <p className="caption" style={{ marginTop: 8 }}>
        Paths resolve against the server’s working directory, not your
        browser’s.
      </p>

      <ErrorBox error={error} />

      {result && (
        <>
          <div className="row" style={{ marginTop: 16 }}>
            <Chip tone="ok">{result.ingested} ingested</Chip>
            <Chip tone={result.skipped ? "warn" : ""}>
              {result.skipped} skipped
            </Chip>
            <Chip>{result.sla_eligible} clear SLA</Chip>
            <Chip>{num(result.total_addressable_kw)} kW addressable</Chip>
          </div>

          {/* A high skip count means the column mapping is wrong. Showing
              it is the whole point — a silently short lead count is the
              failure mode this guards against. */}
          {result.skipped > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>Skipped rows</h3>
              <table>
                <thead>
                  <tr>
                    <th className="num">Row</th>
                    <th>Candidate</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {result.skipped_detail.slice(0, 20).map((s) => (
                    <tr key={s.index}>
                      <td className="num">{s.index}</td>
                      <td>{s.candidate_id}</td>
                      <td>{s.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </Card>
  );
}
