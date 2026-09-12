# RAAH — Modules 3–9 (WhatsApp qualification flow + fixes)

## Run it

```bash
pip install -r app/requirements.txt
cp app/.env.example app/.env          # works as-is; console mode, no Meta account needed
uvicorn app.main:app --reload
```

## Deployment and real data

See `DEPLOYMENT.md` — which of module 1-2's files to use, how to clip the
large GeoJSON, and where to host.

## Testing before integration

Three layers, cheapest first.

**1. Unit tests — no server, no network, no data (3 seconds)**
```bash
pytest tests/ -q                      # 37 tests
pytest tests/ -v -k heatmap           # one area
```

**2. Demo data — you do not need modules 1-2 to test**
```bash
python scripts/make_demo_data.py                   # defaults to Jaipur
python scripts/make_demo_data.py --lat 28.61 --lon 77.20 --out demo_data
```
Generates a mixed industrial/residential cluster plus cadastral parcels using
the same column names a state portal exports (`khasra_no`, `land_use`,
`ownership`). Point `building_source` at your friend's real file later; nothing
else changes.

**3. Data readiness — what is real vs placeholder**
```bash
python scripts/check_data.py
python scripts/check_data.py --module12 ../hackx4.0-main/outputs
```
Reports which data sources are production versus seed. Everything ships on
placeholder data today: tariffs are `MVP_CONFIG` at confidence 0.35, pincodes
are a 20-entry seed, partner names are invented. Every engine works — these
change the numbers, not the code.

**4. Smoke test — full stack against a running server**
```bash
uvicorn app.main:app &                             # terminal 1
python scripts/smoke_test.py                       # terminal 2
```
35 checks across 8 areas: routers mounted, Meta webhook contract, full
conversational funnel, disqualification, pagination, grid + cadastral heatmap,
leakage, partner portal score-hiding, and the learning loop. Exits non-zero on
failure, so it drops straight into CI.

Unit tests cannot catch what this catches: routers not mounted, DB not writable,
geo files unreadable, or a route shadowed by another.

### Manual poke
```bash
open http://localhost:8000/docs        # every endpoint, interactive

# one conversation turn
curl -X POST localhost:8000/api/v1/whatsapp/simulate \
  -H 'Content-Type: application/json' -d '{"phone":"919812345678","text":"hi"}'
```
Then send in order: `2` `1` `1` `302015` `650` `5` `"1850 2100 1950"` `skip` `1`
for a full Hindi funnel ending in a partner assignment.

### Run demo data first

If `scripts/make_demo_data.py` has not been run, the heatmap check reports a
400 naming the missing file and the path it resolved to. Relative paths resolve
against the **server's** working directory, not your shell's — pass absolute
paths if the two differ.

Drive the whole funnel without WhatsApp:

```bash
curl -X POST localhost:8000/api/v1/whatsapp/simulate \
  -H 'Content-Type: application/json' \
  -d '{"phone":"919812345678","text":"hi"}'
# then send: 2 → 1 → 1 → 302015 → 650 → 5 → "1850 2100 1950" → skip → 1
```

---

## What was broken

| Issue | Effect |
|---|---|
| `tracking_engine.py` imported but absent | **App could not start at all** |
| `TariffProvider(path="data/tariffs.json")` relative to CWD | Silently used hardcoded defaults unless launched from `app/` |
| `tariff.get("subsidy_rs", 0)` — key exists in no tariff record | **Every residential lead modelled at full unsubsidised CAPEX** |
| GET verify read `hub.mode`/`hub.challenge` as **headers**, returned JSON | Meta webhook verification would always fail (they're query params; raw text expected) |
| `WhatsAppWebhookEvent` was flat | Real payloads nest as `entry[].changes[].value.messages[]` — would never bind |
| `_representative_rate` = mean of all slab rates | Understates savings ~8% for anyone in an upper slab |
| `segment="industrial"` had no tariff entry | Fell back to **residential** rates, killing the C&I arbitrage thesis |
| In-memory `LEAD_STORE` / `QUALIFICATION_STORE` | All leads lost on restart |
| `/partners/route` echoed back `preferred_partner_ids[0]` | No registry, pincode match, or capacity band |

## What was missing from the PS

Instant offer (`offer_engine.py`), PM Surya Ghar subsidy + accelerated depreciation
(`subsidy_engine.py`), CAPEX-vs-OPEX comparison, **monthly savings net of EMI**,
partner routing (`partner_engine.py`), leakage control and cost-per-funded-customer
(`tracking_engine.py`), and the WhatsApp flow itself (`whatsapp_flow.py`).

---

## New files

```
app/engines/whatsapp_flow.py    11-state machine, 5 languages
app/engines/offer_engine.py     sizing, EMI, net-of-EMI, CAPEX vs OPEX
app/engines/subsidy_engine.py   PM Surya Ghar CFA + AD tax shield
app/engines/partner_engine.py   pincode + capacity band routing
app/engines/tracking_engine.py  SLA, leakage, funnel, cost/funded
app/providers/whatsapp_client.py  Meta adapter + console adapter
app/routers/whatsapp.py         webhook, simulate, partners, analytics
app/i18n/messages.py            en / hi / mr / gu / ta
app/store.py                    SQLite persistence
app/data/partners.json          partner registry
```

## The flow

```
language → segment → OWNERSHIP → pincode → roof area →
sanctioned load → 3 bills → [GST → vintage] → photo → OFFER → consent → route
```

Ownership is asked **third**, before any solar computation runs — a rented roof
kills the deal regardless of irradiance, so the cheapest disqualifier goes first.
Rented roofs exit with zero calculation and zero field visit.

**Drop reasons** (each with a vernacular customer-facing explanation):
`rented_roof`, `low_consumption`, `tiny_roof`, `heavy_shading`, `poor_economics`,
`emi_exceeds_savings`.

**Global commands** (any state): `RESTART`, `HELP`, `RESUME`, `NO CONTACT`,
`CHECK AGAIN`, `OWNER OK`. Three unparseable replies auto-escalate to a human
rather than looping the customer.

### Sample output (Hindi, 650 sq ft, ₹2,000/mo)

```
सुझाया गया सिस्टम: 2.56 kW
अनुमानित लागत: ₹1,40,800
पीएम सूर्य घर सब्सिडी: - ₹70,080
मासिक EMI: ₹954   |   मासिक बचत: ₹1,905
हर महीने शुद्ध लाभ: ₹952        ← the closing number
```

---

## Key endpoints

```
POST   /api/v1/whatsapp/simulate          drive flow without Meta
GET    /api/v1/webhooks/whatsapp          Meta verify handshake (fixed)
POST   /api/v1/webhooks/whatsapp          signed, replay-protected, async
GET    /api/v1/whatsapp/transcript/{phone}
POST   /api/v1/partners/route
GET    /api/v1/partners/scorecard
GET    /api/v1/analytics/leakage          untouched / stalled / unrouted
GET    /api/v1/analytics/funnel           cost per funded customer
POST   /api/v1/analytics/retrain          closed loop
```

---

## Coordinates (fixed)

Leads previously had **no lat/lon** — `solar_engine` built fresh row dicts and
dropped geometry, so every rooftop would have plotted at the query point.
Fixed through the whole chain:

```
building_engine  centroid computed in metric CRS, reprojected to EPSG:4326
      ↓          gdf["latitude"], gdf["longitude"]
solar_engine     carried into each result row
      ↓
lead_engine      exposed on the lead payload
      ↓
store            latitude / longitude / capacity_kw columns + bbox index
```

`GET /api/v1/heatmap/leads?min_lon=&min_lat=&max_lon=&max_lat=` returns scored
leads as a GeoJSON point layer for the map viewport.

## Heatmap (PS bonus)

`POST /api/v1/heatmap/cluster` — `mode` is `grid`, `cadastral`, or `both`.

**Grid**: equal-area cells, percentile-banded (`very_low` → `very_high`) rather
than fixed thresholds, because a residential colony and an industrial estate
differ by an order of magnitude in kW.

**Cadastral**: aggregates to real plot boundaries and carries the parcel
attributes through. Column names are auto-resolved across state portals —
`khasra_no`, `survey_no`, `plot_id` all map to `parcel_id`; `ownership` maps to
`owner_type`. Per parcel you get `total_addressable_kw`, `largest_roof_kw`,
`roof_coverage_pct`, `kw_per_1000_sqm_plot`, `land_use`, `zone`, and
`acquisition_profile` (`single_anchor` vs `multi_roof_campaign` — one
negotiation versus a campaign, which sales needs to tell apart).

Buildings are matched by centroid-within-parcel so a shed straddling a boundary
isn't double-counted, and `unmatched_buildings` is reported rather than silently
dropped. Set `run_solar=true` for shading-adjusted capacity instead of the
geometric estimate.

## Learning from mistakes

`GET /api/v1/learning/mistakes` names the two error classes and their costs:

- **false positives** — scored above the bar, then died. Each burned a field visit.
- **false negatives** — scored below the bar but funded anyway. Invisible unless
  sub-threshold leads are tracked, which they are.

Returns precision, recall, the ten worst of each, and a `bias` verdict
(`over_optimistic` / `over_conservative` / `balanced`) with guidance on which
bar to move.

`GET /api/v1/learning/calibration` shows observed funding rate per score band and
flags any band where the rate *falls* as the score rises — the clearest signal a
feature weight is wrong.

`POST /api/v1/learning/run` refits and persists a versioned model.
`POST /api/v1/learning/apply` applies it as a **bounded additive correction**
(±15 max) on top of the rule-based score, with a plain-language reason. Bands
with fewer than 5 outcomes are left untouched. The rules stay explainable; the
learned layer only nudges.

Verified on 60 seeded outcomes where funding depended on `financing_score`: the
model independently assigned it 94% of feature importance.

## Partner-facing view

`GET /api/v1/partner-portal/{id}/leads` — **scores are deliberately withheld.**
A partner who can see the propensity score works the top of the list and lets
the rest rot, which is exactly the leakage the PS asks us to prevent. They get
capacity, indicative EMI, savings, roof photo, sanctioned load, and the SLA clock.

`POST /.../{lead_id}/reject` releases a lead and immediately re-routes it to the
next best partner excluding the rejector, so a rejection never parks a qualified
lead forever.

## Frontend contract

| Screen | Endpoint |
|---|---|
| Territory map — capacity surface | `POST /heatmap/cluster` (GeoJSON) |
| Territory map — lead pins | `GET /heatmap/leads?bbox` (GeoJSON) |
| Ranked lead list | `GET /leads?limit=&offset=` (now paginated, returns `total`/`has_more`) |
| Dual-axis quadrant | derive client-side from `/leads` |
| Lead detail | `GET /leads/{id}` |
| Conversation | `GET /whatsapp/transcript/{phone}` + `POST /whatsapp/simulate` |
| Partner ops | `GET /analytics/leakage`, `GET /partners/scorecard` |
| Partner portal | `GET /partner-portal/{id}/leads` + `/summary` |
| Model health | `GET /learning/mistakes`, `/learning/calibration` |
| Funnel | `GET /analytics/funnel` |

---

## Modules 1–2 integration (done)

`app/engines/ingest_engine.py` is the seam. Your friend's pipeline ends at
"Candidate Rooftop/SME List"; that list enters here.

```bash
curl -X POST localhost:8000/api/v1/ingest/candidates \
  -H 'Content-Type: application/json' -d '{
    "records": [{"osm_id":"way/8891","lat":26.9124,"lng":75.7873,
                 "footprint_area_m2":1800,"pin_code":"302015",
                 "building_class":"factory","connected_load_kw":150,
                 "udyam":"UDYAM-RJ-17-0001234","years_in_business":7,
                 "has_gst":true}],
    "auto_route": true}'
```

Or straight from his CSV:

```bash
curl -X POST localhost:8000/api/v1/ingest/file \
  -H 'Content-Type: application/json' \
  -d '{"path":"../hackx4.0-main/outputs/target_universe.csv",
       "data_mode":"offline","auto_route":true}'
```

**Aliases are verified against the real `target_universe.csv` schema**, not
guessed. `building_id` → candidate id, `building_area_m2` → roof area,
`candidate_pincode` → pincode, `place_name`/`udyam_enterprise_name` → entity
name, `gst_available` → GST flag. `GET /api/v1/ingest/schema` returns the full
table plus the verified column contract.

**`C&I` is split into commercial vs industrial** using `place_category` and
`industrial_cluster_match`. This matters: the accelerated-depreciation shield
and C&I sizing apply to a factory, not a retail showroom, and module 1–2 cannot
tell them apart from geometry alone.

**`Unknown` segment is flagged, not guessed.** Those rows are screened on
conservative commercial assumptions, marked `segment_unknown: true`, and given
`next_action: qualify_segment_via_whatsapp` — so nobody quotes off an
assumption.

Module 1–2 does not supply `sanctioned_load_kw`, `monthly_consumption_kwh`, or
`business_vintage_years`. Those are assumed at ingest and replaced with real
values during WhatsApp qualification — which is exactly the division of labour
the PS describes.

Records with no coordinates are geocoded from pincode. Records that can be
located nowhere are returned in `skipped_detail` **with a reason** — a broken
column mapping shows up on the first run instead of as a quietly short lead
count. One malformed row does not abort the batch.

`build_estimator()` also upgrades the WhatsApp flow from the national fallback
to per-pincode irradiance and the correct DISCOM tariff. It resolves lazily on
first use, not in a lifespan hook, so it behaves identically under `TestClient`,
scripts, and the live server.

### Pincode geocoding

`app/data/pincodes.json` ships ~20 seed pincodes. Replace it with the full India
Post directory and point `RAAH_PINCODE_PATH` at it. Prefix matches are returned
with lower confidence and flagged as district-level approximations, never as
rooftop coordinates.

---

## Two things to verify before demo day

1. **Subsidy rates.** ₹30k/kW (first 2 kW), ₹18k (3rd), ₹78k cap are in
   `SubsidyConfig`. Confirm against the current MNRE memorandum — they move.
2. **Tariff slabs.** `tariffs.json` is marked `MVP_CONFIG` with confidence 0.35.
   Real DISCOM slabs for your demo city will change every payback number.

Also note `_reliability_score` in `lead_engine.py` *increases* with SAIDI — it's
an outage-opportunity score, not grid quality. Intentional, now documented, but
don't let a judge read it as a bug.
