import React, { useCallback, useEffect, useState } from "react";
import L from "leaflet";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import {
  BAND_COLORS,
  buildHeatmap,
  getLeadPins,
  inr,
  num,
  routing,
  score,
} from "../api.js";
import { Card, Chip, ErrorBox } from "./Shared.jsx";

const DEFAULT = { lat: 26.9124, lon: 75.7873, zoom: 13 };

function BoundsWatcher({ onBounds }) {
  const map = useMapEvents({
    moveend: () => onBounds(map.getBounds()),
  });
  useEffect(() => {
    onBounds(map.getBounds());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

function Recenter({ lat, lon }) {
  const map = useMap();
  useEffect(() => {
    map.setView([lat, lon]);
  }, [lat, lon, map]);
  return null;
}

export default function TerritoryMap({ onOpenLead }) {
  const [pins, setPins] = useState(null);
  const [surface, setSurface] = useState(null);
  const [summary, setSummary] = useState(null);
  const [mode, setMode] = useState("grid");
  const [source, setSource] = useState("demo_data/buildings.geojson");
  const [cadastral, setCadastral] = useState("demo_data/parcels.geojson");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [pinError, setPinError] = useState(null);

  const loadPins = useCallback((bounds) => {
    getLeadPins({
      min_lon: bounds.getWest(),
      min_lat: bounds.getSouth(),
      max_lon: bounds.getEast(),
      max_lat: bounds.getNorth(),
      limit: 2000,
    }).then(
      (fc) => {
        setPins(fc);
        setPinError(null);
      },
      (e) => setPinError(e.message)
    );
  }, []);

  async function loadSurface() {
    setBusy(true);
    setError(null);
    try {
      const body = {
        latitude: DEFAULT.lat,
        longitude: DEFAULT.lon,
        radius_m: 2000,
        building_source: source,
        mode,
        cell_size_m: 200,
        run_solar: false,
      };
      if (mode !== "grid") body.cadastral_source = cadastral;

      const res = await buildHeatmap(body);
      const layer = res[mode === "cadastral" ? "cadastral" : "grid"];
      setSurface(layer);
      setSummary({ ...layer.summary, query: res.query });
    } catch (e) {
      setError(e.message);
      setSurface(null);
      setSummary(null);
    } finally {
      setBusy(false);
    }
  }

  const surfaceStyle = (feature) => ({
    fillColor: BAND_COLORS[feature.properties.intensity_band] ?? "#ccc",
    fillOpacity: 0.55,
    weight: 1,
    color: "rgba(0,0,0,0.15)",
  });

  const onEachSurface = (feature, layer) => {
    const p = feature.properties;
    const title = p.parcel_id
      ? `Parcel ${p.parcel_id}`
      : `Cell ${p.cell_id}`;
    layer.bindPopup(
      `<strong>${title}</strong><br/>` +
        `${num(p.total_addressable_kw)} kW addressable<br/>` +
        `${p.building_count} buildings` +
        (p.land_use ? `<br/>${p.land_use}` : "") +
        (p.roof_coverage_pct ? `<br/>${p.roof_coverage_pct}% roof cover` : "") +
        (p.acquisition_profile
          ? `<br/><em>${p.acquisition_profile.replace(/_/g, " ")}</em>`
          : "")
    );
  };

  // GeoJSON is [lon, lat]; Leaflet wants [lat, lon]. pointToLayer receives
  // the already-converted latlng, so no manual swap is needed here.
  const pinToLayer = (feature, latlng) => {
    const p = feature.properties;
    const r = routing(p.routing_class);
    const marker = L.circleMarker(latlng, {
      radius: 6,
      fillColor: r.color,
      color: "#fff",
      weight: 1.5,
      fillOpacity: 0.95,
    });
    marker.bindPopup(
      `<strong>${p.lead_id}</strong><br/>` +
        `propensity ${score(p.propensity_score)} · financing ${score(
          p.financing_score
        )}<br/>${num(p.capacity_kw)} kW · ${p.segment}<br/>` +
        `<em>${r.label}</em>`
    );
    marker.on("click", () => onOpenLead?.(p.lead_id));
    return marker;
  };

  return (
    <>
      <Card
        title="Territory"
        subtitle="Addressable capacity surface with scored leads on top."
        actions={
          <div className="row">
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="grid">Grid cells</option>
              <option value="cadastral">Cadastral parcels</option>
            </select>
            <button className="btn small" onClick={loadSurface} disabled={busy}>
              {busy ? "Building…" : "Build heatmap"}
            </button>
          </div>
        }
      >
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="building_source path"
            style={{ flex: 1, minWidth: 260 }}
          />
          {mode === "cadastral" && (
            <input
              value={cadastral}
              onChange={(e) => setCadastral(e.target.value)}
              placeholder="cadastral_source path"
              style={{ flex: 1, minWidth: 260 }}
            />
          )}
        </div>
        <p className="caption" style={{ marginTop: -6, marginBottom: 12 }}>
          Paths resolve against the server’s working directory, not your
          browser’s.
        </p>

        <ErrorBox error={error} />
        <ErrorBox error={pinError} />

        <div className="map-wrap">
          <MapContainer
            center={[DEFAULT.lat, DEFAULT.lon]}
            zoom={DEFAULT.zoom}
            style={{ height: "100%", width: "100%" }}
            scrollWheelZoom
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <Recenter lat={DEFAULT.lat} lon={DEFAULT.lon} />
            <BoundsWatcher onBounds={loadPins} />

            {surface && (
              <GeoJSON
                key={JSON.stringify(summary?.bands ?? mode)}
                data={surface}
                style={surfaceStyle}
                onEachFeature={onEachSurface}
              />
            )}
            {pins && pins.features.length > 0 && (
              <GeoJSON
                key={`pins-${pins.features.length}`}
                data={pins}
                pointToLayer={pinToLayer}
              />
            )}
          </MapContainer>
        </div>

        <div className="legend">
          {Object.entries(BAND_COLORS).map(([band, color]) => (
            <span className="legend-item" key={band}>
              <span className="swatch" style={{ background: color }} />
              {band.replace(/_/g, " ")}
            </span>
          ))}
        </div>

        {pins && (
          <p className="caption" style={{ marginTop: 8 }}>
            {pins.summary.returned} leads in view
            {pins.summary.leads_without_coordinates > 0 &&
              ` · ${pins.summary.leads_without_coordinates} lead(s) have no coordinates and cannot be mapped`}
          </p>
        )}
      </Card>

      {summary && (
        <Card title="Top targets">
          <div className="row" style={{ marginBottom: 12 }}>
            <Chip>
              {summary.cell_count ?? summary.parcel_count}{" "}
              {mode === "grid" ? "cells" : "parcels"}
            </Chip>
            <Chip>{num(summary.total_addressable_mw, 2)} MW addressable</Chip>
            <Chip>{summary.query?.capacity_basis?.replace(/_/g, " ")}</Chip>
            {summary.unmatched_buildings > 0 && (
              <Chip tone="warn">
                {summary.unmatched_buildings} buildings outside any parcel
              </Chip>
            )}
          </div>
          <table>
            <thead>
              <tr>
                <th>{mode === "grid" ? "Cell" : "Parcel"}</th>
                <th>Land use</th>
                <th className="num">Buildings</th>
                <th className="num">Addressable kW</th>
                <th>Profile</th>
              </tr>
            </thead>
            <tbody>
              {(surface.top_targets ?? []).slice(0, 10).map((t, i) => (
                <tr key={i}>
                  <td>{t.parcel_id ?? t.cell_id}</td>
                  <td>{t.land_use ?? "—"}</td>
                  <td className="num">{t.building_count}</td>
                  <td className="num">
                    {Math.round(t.total_addressable_kw).toLocaleString("en-IN")}
                  </td>
                  <td>
                    {t.acquisition_profile
                      ? t.acquisition_profile.replace(/_/g, " ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
