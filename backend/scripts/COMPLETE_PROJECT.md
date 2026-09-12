# Prabha — Complete Technical Documentation

Solar Lead Discovery & Qualification Engine for Residential and SME Rooftops
(Problem Statement #2)

---

## 1. The problem, restated as an engineering brief

India needs 40+ GW of rooftop solar from two buyers who behave nothing alike.

A homeowner wants 3 kW, is chasing the PM Surya Ghar subsidy, and decides
emotionally on payback and monthly bill. An SME wants 100 kW, decides on
tariff arbitrage and IRR, and needs financing that clears a credit committee.

Both are found the same crude way today — paid ads, purchased lists, dealer
walk-ins. The consequences are structural, not incidental:

| Symptom | Root cause |
|---|---|
| Cost per lead keeps climbing | Inbound funnel competes on ad auction price |
| Conversion in low single digits | No viability filter before human contact |
| EPC teams burn days on dead sites | Roof viability unknown until a site visit |
| Leads die *after* the quote | Affordability never checked at the top of funnel |
| Best prospects never appear | An unshaded 8,000 sq ft factory roof on ₹9/unit doesn't raise its hand |

The last two matter most. A lead that looks hot and fails underwriting is a
**false positive**, and the platform has to say so upfront rather than
discovering it three weeks later.

So the system must do three things no ad funnel does:

1. **Find** rooftops from open data, without waiting for a customer
2. **Qualify** on two independent axes — solar viability *and* financing
   eligibility — before dispatching a human
3. **Route** only survivors, and detect when a partner sits on them

---

## 2. Architecture

```
┌─ Modules 1–2 (discovery) ──────────────────────────────────────┐
│  Overture buildings + places   →  footprint, height, POI        │
│  Udyam / GST / MCA registries  →  SME identity, vintage         │
│  RIICO industrial estates      →  cluster tagging               │
│  DISCOM tariff categories      →  slab assignment               │
│                          ↓                                      │
│                 target_universe.csv                             │
└─────────────────────────┬───────────────────────────────────────┘
                          │  POST /api/v1/ingest/file
┌─────────────────────────▼─ Modules 3–9 (this document) ────────┐
│                                                                 │
│  3  Solar viability      pvlib: position, POA irradiance,       │
│                          tilt/azimuth optimisation, shading     │
│                          → capacity, generation, payback, IRR   │
│                                                                 │
│  4  Financing            PM Surya Ghar CFA, accelerated         │
│                          depreciation, EMI, savings coverage    │
│                          → financing eligibility score          │
│                                                                 │
│  5  Dual-axis scoring    propensity × financing, four quadrants │
│                                                                 │
│  6  WhatsApp             11-state machine, 5 languages,         │
│                          disqualifier-first, instant offer      │
│                                                                 │
│  7  Partner routing      pincode + capacity band + load balance │
│                                                                 │
│  8  Persistence          SQLite: leads, sessions, events, models│
│                                                                 │
│  9  Closed loop          leakage detection, mistake analysis,   │
│                          bounded score calibration              │
└─────────────────────────────────────────────────────────────────┘
```

**~10,100 lines of Python across 37 endpoints, 37 unit tests, and a
35-check live smoke test.**

---

## 3. Technology and why

| Layer | Technology | Rationale |
|---|---|---|
| API | FastAPI + Uvicorn | Async, Pydantic-native, OpenAPI generated from code |
| Validation | Pydantic v2 | Typed contracts; alias-mapped ingestion absorbs upstream schema drift |
| Geospatial | GeoPandas, Shapely, pyproj, pyogrio | Footprints, UTM reprojection, centroid extraction, cadastral joins |
| Solar physics | pvlib | NREL-derived; real solar position and plane-of-array irradiance |
| Numerics | NumPy, pandas | IRR by bisection, EMI amortisation, 25-year cashflows |
| Learning | scikit-learn | Depth-3 decision tree over funded/rejected outcomes |
| Storage | SQLite (WAL) | Zero-config, survives restart, one module swaps to PostGIS |
| Messaging | WhatsApp Cloud API (Graph v21) | HMAC-SHA256 verified webhooks, replay-protected |
| External data | PVGIS, NASA POWER | Open irradiance APIs, cached per ~1 km tile |

Three choices worth defending:

**pvlib, not a flat yield factor.** Most MVPs multiply kW by 1,450. We compute
solar position, optimise tilt and azimuth, and derive plane-of-array
irradiance. The difference shows up in shaded and badly-oriented roofs, which
is exactly where lead quality is decided.

**Rules first, ML second.** The score is explainable rules. scikit-learn only
supplies a **bounded ±15 correction** learned from terminal outcomes, and
only for score bands with ≥5 observations. A black box cannot justify itself
to a credit committee, and a model trained on forty outcomes has not earned
the right to overrule domain logic.

**No LLM in the WhatsApp flow.** It is a deterministic state machine. It
cannot hallucinate a subsidy figure at a customer, and every branch is
unit-testable without a network call.

---

## 4. Module 3 — Solar viability engine

`app/engines/solar_engine.py`, `building_engine.py`

**Roof area.** Footprint from Overture, reprojected to the local UTM zone so
areas are in true metres. Height estimated in priority order: explicit
`height` tag → `building:levels × 3 m` → area-based heuristic. Usable
fraction is 0.70 residential (setbacks, water tanks, stairwells) and 0.80 C&I.

**Irradiance.** pvlib computes solar position across representative times,
then plane-of-array irradiance for candidate tilt/azimuth pairs. The optimum
is selected per site rather than assumed.

**Shading.** Neighbouring building heights cast geometric shadows; annual
shading loss is derived from the fraction of representative hours occluded.

**Sizing** is the binding minimum of three constraints:

```python
min(roof_limited_kw, consumption_limited_kw, sanctioned_load_limited_kw)
```

The third constraint is the one most quotes omit, and it is why they get
rejected at discom feasibility. The API returns which constraint bound.

**Segment logic differs, as the PS requires.** Residential is subsidy-led and
sized slightly *above* consumption (1.10 headroom). C&I is tariff-arbitrage-led
and sized *below* load (0.90) to avoid exporting at a poor net-billing rate.

---

## 5. Module 4 — Financing engine

`subsidy_engine.py`, `offer_engine.py`, `financing_engine.py`

### PM Surya Ghar (residential)

```
30,000/kW × first 2 kW  +  18,000 × 3rd kW  →  capped at ₹78,000
```

A 3 kW and a 10 kW home system draw identical CFA. The engine returns
`capacity_above_subsidy_cap_kw` so the UI can say so — this single fact
reshapes residential sizing advice and most quotes get it wrong.

### Accelerated depreciation (C&I)

40% year-1 under Appendix I, plus 20% additional under s.32(1)(iia) for
manufacturing, halved if the asset runs under 180 days in the financial year,
at a 25.17% effective tax rate.

Critically, this is returned as a **separate line, never netted into CAPEX**.
It is a tax shield realisable only against taxable profit, and the response
carries an explicit caveat string saying so.

### The number that closes the sale

```
monthly_savings_rs − monthly_emi_rs = net_monthly_benefit_rs
```

The PS names this explicitly. It is computed, surfaced in the API, and is the
largest figure in the WhatsApp message.

### CAPEX vs OPEX for SMEs

Both routes are modelled side by side — geared CAPEX with the AD shield
against a RESCO PPA at zero upfront — with a recommendation and a written
rationale. In testing, a 150 kW factory was recommended OPEX because the PPA
beat the geared CAPEX case on month-one cash. That is the answer a credit
committee actually needs.

### Financing score

Built from: payback within SLA, IRR above threshold, **whether annual savings
cover annual EMI** (the heaviest weight), GST registration, and business
vintage. Every component returns a plain-language reason string.

---

## 6. Module 5 — Dual-axis scoring

`scoring_engine.py`

Two independent scores, never blended:

- **Propensity to convert** — solar score, payback, IRR, tariff level, outage
  hours, plus qualification readiness (owned roof, bills supplied, photo)
- **Financing eligibility** — the section above

Thresholds: propensity ≥ 55, financing ≥ 50.

| | Financing ≥ 50 | Financing < 50 |
|---|---|---|
| **Propensity ≥ 55** | `high_priority` — route now | `high_propensity_finance_risk` — **false positive** |
| **Propensity < 55** | `low_propensity_financeable` — nurture | `discard_or_nurture` |

The top-right-to-top-left distinction is the product. A lead that looks hot
and will fail underwriting is flagged before anyone drives out.

> **Bug found and fixed during integration.** The original thresholds
> (≥70 for high priority, <55 for financeable) left a gap: a lead at
> propensity 62 with financing 100 matched no rule and fell through to
> `discard_or_nurture`. The system was silently discarding above-bar,
> fully financeable leads. It is now a clean two-way split per axis, with a
> test that sweeps all 441 score combinations and asserts every one lands in
> exactly one class.

---

## 7. Module 6 — WhatsApp conversational qualification

`whatsapp_flow.py` (819 lines), `i18n/messages.py`, `providers/whatsapp_client.py`

### Design principle: cheapest disqualifier first

```
language → segment → OWNERSHIP → pincode → roof area →
sanctioned load → 3 bills → [GST → vintage] → photo → OFFER → consent → route
```

Ownership is question **three**, before any solar computation runs. A rented
roof kills the deal regardless of irradiance, so it exits the conversation
having consumed zero computation and zero field visit. That is the PS
requirement — "drops out unviable leads without a field visit" — implemented
literally.

### Vernacular

Five languages: English, Hindi, Marathi, Gujarati, Tamil. Missing keys fall
back to English rather than crashing, so a partial translation ships safely.
Rupees use Indian digit grouping (`₹1,70,500`), because `₹170,500` does not
read as money to the buyer.

### Drop reasons

Six codes, each with a customer-facing explanation in their language:
`rented_roof`, `low_consumption`, `tiny_roof`, `heavy_shading`,
`poor_economics`, `emi_exceeds_savings`.

The wording is deliberate: *"We would rather tell you this now than send
someone to sell you something that does not work."* A clean no protects the
brand and costs nothing.

### Engineering properties

- **Pure**: `handle_message()` returns messages and state; it never touches
  the network. The entire funnel is testable without a WhatsApp account.
- **Resumable**: state persists per phone number, 72-hour TTL.
- **Replay-protected**: Meta retries aggressively; message IDs are
  de-duplicated so a retry cannot re-ask a question.
- **Signature-verified**: HMAC-SHA256 on `X-Hub-Signature-256`.
- **Escape hatches**: `RESTART`, `HELP`, `RESUME`, `NO CONTACT`,
  `CHECK AGAIN`, `OWNER OK` work in any state. Three unparseable replies
  auto-escalate to a human rather than looping the customer.
- **Transport-agnostic**: a console adapter drives the full funnel with no
  Meta account, via `POST /api/v1/whatsapp/simulate`.

### Verified output (Hindi, 650 sq ft, ₹2,000/month)

```
सुझाया गया सिस्टम: 2.56 kW
अनुमानित लागत: ₹1,40,800
पीएम सूर्य घर सब्सिडी: - ₹70,080
मासिक EMI: ₹954   |   मासिक बचत: ₹1,905
हर महीने शुद्ध लाभ: ₹952        ← the closing number
```

### Two webhook bugs fixed

The original code read Meta's `hub.mode` / `hub.challenge` as **headers** and
returned JSON. Meta sends them as **query parameters** and expects the raw
challenge as plain text — verification would have failed every time. The
event schema was also flat, while real payloads nest as
`entry[].changes[].value.messages[]`, so no live webhook would ever have
bound.

---

## 8. Module 7 — Partner routing and leakage control

`partner_engine.py`, `tracking_engine.py`

**Routing** matches on pincode (exact beats prefix), capacity band, and
segment, then ranks by specificity, rating, proximity, and **spare daily
capacity**. The last one matters: without it the top partner floods and
quietly sits on leads, which is the leakage the PS asks us to prevent.

**Leakage detection returns three distinct buckets**, never merged, because
each needs a different action:

| Bucket | Meaning | Action |
|---|---|---|
| `untouched` | Assigned, never contacted | Chase the partner |
| `stalled` | Contacted, frozen mid-funnel | Chase the lead |
| `unrouted` | Qualified, never assigned | Fix our own routing |

**Status regression is flagged.** A lead moving backwards through the funnel
usually means a partner reopening a dead lead to reset their SLA clock.

**Partner portal withholds scores by design.** A partner who can see the
ranking works the top of the list and lets the rest rot. They get the SLA
clock instead. A rejection re-routes immediately to the next best partner,
excluding the rejector, so handing a lead back never parks it forever.

---

## 9. Module 9 — Closed-loop learning

`learning_engine.py`

The PS: *"Feed disbursed, dropped and rejected outcomes back into the scoring
model so cost per funded customer falls with every cycle."*

That requires the system to **name its own errors**, not report an accuracy
number.

| Error class | Cost | Visibility |
|---|---|---|
| **False positive** | Scored above bar, then died. Burned a field visit. | Obvious |
| **False negative** | Scored below bar but funded anyway. Revenue the filter would discard. | **Invisible unless sub-threshold leads are tracked** — which they are |

Outputs:

- Precision, recall, and the ten worst of each class with a `cost` string
- A `bias` verdict — `over_optimistic` / `over_conservative` / `balanced` —
  with guidance on which bar to move
- **Calibration by score band**: observed funding rate vs expected, with a
  warning flag on any band where the rate *falls* as the score rises. That is
  the clearest possible signal a feature weight is wrong.
- A versioned, persisted model and a **bounded ±15 additive correction**,
  applied only to bands with ≥5 outcomes, always with a plain-language reason

Validated on 60 seeded outcomes where funding depended on `financing_score`:
the tree independently assigned it 94% of feature importance, and calibration
flagged the non-monotonic band.

`cost_per_funded_customer_rs` returns `null` until a lead funds — honest, not
a fabricated zero.

---

## 10. Bonus — Addressable-capacity heatmap

`heatmap_engine.py`

Two aggregation modes, both emitting GeoJSON.

**Grid** — equal-area cells, percentile-banded (`very_low` → `very_high`)
rather than fixed thresholds, because a residential colony and an industrial
estate differ by an order of magnitude in kW.

**Cadastral** — aggregates to real plot boundaries and carries parcel
attributes through. Column names are auto-resolved across state portals:
`khasra_no`, `survey_no`, `plot_id` all map to `parcel_id`. Per parcel:
`total_addressable_kw`, `largest_roof_kw`, `roof_coverage_pct`,
`kw_per_1000_sqm_plot`, `land_use`, `zone`, and `acquisition_profile`
(`single_anchor` vs `multi_roof_campaign` — one negotiation versus a
campaign, which sales must tell apart).

Two correctness decisions: buildings match by **centroid-within-parcel**, so
a shed straddling a boundary is not double-counted; and
`unmatched_buildings` is **reported, not dropped**, so a layer misalignment
is visible immediately.

---

## 11. Integration with modules 1–2

`ingest_engine.py`

The seam is deliberately permissive. Field names are **alias-mapped and
verified against the real `target_universe.csv` schema**, not guessed:

| Their column | Our field |
|---|---|
| `building_id` | candidate id |
| `building_area_m2` | roof area |
| `candidate_pincode` | pincode |
| `place_name` / `udyam_enterprise_name` | entity name |
| `gst_available` | GST flag |

`GET /api/v1/ingest/schema` returns the full table, so integration is a link,
not a schema argument.

**`C&I` is split into commercial vs industrial** using `place_category` and
`industrial_cluster_match`. Their classifier emits one combined bucket, which
is correct for discovery but wrong for pricing — the AD shield and C&I sizing
rule apply to a factory, not a retail showroom.

**`Unknown` is flagged, not guessed.** Roughly a third of rows land there.
They are screened on conservative commercial assumptions, marked
`segment_unknown: true`, and routed to `qualify_segment_via_whatsapp`.

**Failures are reported, never silent.** Unlocatable rows appear in
`skipped_detail` with a reason; one malformed row does not abort the batch.
A broken column mapping shows up on the first run rather than as a quietly
short lead count.

> **Two bugs their real schema exposed.** pandas reads pincodes as `int64`,
> and partner routing called `.startswith()` on one — `AttributeError`
> mid-batch. And an empty `place_name` is `float('nan')`, which is neither
> `None` nor `""`, so it passed the emptiness check and would have rendered
> a business called "nan" on the dashboard. Both now have regression tests.

---

## 12. Data provenance — what is real

| Source | Use | Status |
|---|---|---|
| Overture buildings | Roof footprints | ✅ Real open data |
| Overture places | POI → segment classification | ✅ Real |
| NASA POWER / PVGIS | Irradiance, specific yield | ✅ Real open APIs |
| Udyam registry | SME identity, fuzzy name+pincode match | ✅ Real |
| RIICO estates | Cluster tagging, 23 Jaipur areas | ⚠️ Hand-compiled, real names |
| GST / MCA | Vintage, constitution | ❌ **Synthetic** (SHA256-seeded) |
| DISCOM tariffs | Slab rates | ⚠️ `MVP_CONFIG`, confidence 0.35 |
| Pincode centroids | Geocoding | ⚠️ 20-entry seed |
| Partner registry | EPC routing | ⚠️ 3 illustrative partners |

`scripts/check_data.py` audits this on demand. The distinction that matters:
**every engine works; these change the numbers, not the code.**

Two things we do not claim:

**No credit bureau integration.** `credit_score` is always `None`. Financing
readiness is inferred from open signals — GST presence, Udyam vintage, and
savings-vs-EMI coverage. A bureau pull needs consent and a lending partner,
so it belongs *after* WhatsApp qualification, not at the top of a cold funnel.

**Tariff confidence is surfaced, not hidden.** Every tariff response carries
`source` and `confidence`. The UI shows them.

---

## 13. Testing

| Layer | Command | Coverage |
|---|---|---|
| Unit | `pytest tests/ -q` | 37 tests, 3 s, no network |
| Data audit | `python scripts/check_data.py` | Real vs placeholder |
| Demo data | `python scripts/make_demo_data.py` | Synthetic geo, no module 1–2 needed |
| Integration | `python scripts/smoke_test.py` | 35 checks against a live server |

The smoke test catches what unit tests structurally cannot: routers not
mounted, DB not writable, geo files unreadable, a route shadowed by another.
It exits non-zero, so it drops into CI unchanged.

Notable regression tests: the 441-combination quadrant sweep; integer
pincodes; pandas NaN; webhook replay; lazy estimator resolution outside a
lifespan hook; partner portal score-hiding.

---

## 14. Deployment

240 MB of dependencies rules out serverless (250 MB caps). Container hosting
with a persistent disk — SQLite on an ephemeral filesystem loses every lead
on redeploy.

`Dockerfile` uses `python:3.11-slim` without a compiler, since every geo
package ships manylinux wheels; adding `build-essential` would cost ~400 MB
for nothing. Single worker, because SQLite with WAL tolerates concurrent
readers but not multiple writer processes — scaling means PostgreSQL, not
more workers.

**Public exposure** is gated by two env vars, unset by default:
`RAAH_API_KEY` (shared key on all but `/health`, `/docs`, and the Meta
webhook, which is signature-verified instead) and `RAAH_ALLOWED_ORIGINS`.
This is a shared key, not per-user auth — it stops drive-by scraping of a
public URL, which is the right bar here, stated plainly rather than
overclaimed.

---

## 15. Honest limitations

1. **GST and MCA data are synthetic.** The matching pipeline is real and
   swaps to live registry data unchanged.
2. **No credit bureau.** See §12.
3. **Tariffs are placeholder** at confidence 0.35. Highest-value data fix —
   every rupee figure derives from those slabs.
4. **Shading is geometric**, from neighbouring building heights. No trees, no
   terrain, no LiDAR.
5. **No authentication beyond a shared key.**
6. **SQLite, single writer.** Fine to tens of thousands of leads; PostGIS is
   one module away.
7. **Pincode geocoding is a 20-entry seed.** Outside it, WhatsApp leads fall
   back to prefix matching or do not appear on the map.

---

## 16. What makes this different

Most submissions to this PS will build a map of rooftops with a solar
calculator. Three things here are not that:

**The second axis.** Financing eligibility is scored separately and a hot
lead that will fail underwriting is labelled a false positive *upfront*. The
quadrant is the product, not a chart.

**Disqualification as a feature.** The rented-roof path ends in four
messages, having run zero solar computation. Telling a customer honestly that
solar will not pay back at their site is cheaper than a truck roll and
protects the brand.

**A loop that names its own mistakes.** Not "the model is 87% accurate", but
"these seven leads burned a field visit, these ten were revenue we would have
discarded, and the bar is over-optimistic — raise the financing threshold
before the propensity one."

---

## Appendix — endpoint index

```
GET    /health · /api/v1/system/status

GET    /api/v1/leads                       list, paginated, filterable
GET    /api/v1/leads/{id}
PATCH  /api/v1/leads/{id}/qualification

POST   /api/v1/whatsapp/simulate           drive the funnel, no Meta account
GET    /api/v1/whatsapp/transcript/{phone}
DELETE /api/v1/whatsapp/session/{phone}
GET    /api/v1/webhooks/whatsapp           Meta verification handshake
POST   /api/v1/webhooks/whatsapp           signed, replay-protected

POST   /api/v1/heatmap/cluster             grid | cadastral | both
GET    /api/v1/heatmap/leads               lead pins by bbox

GET    /api/v1/analytics/leakage           untouched | stalled | unrouted
GET    /api/v1/analytics/funnel            cost per funded customer
GET    /api/v1/partners · /partners/scorecard
POST   /api/v1/partners/route

GET    /api/v1/partner-portal/{id}/leads · /summary
POST   /api/v1/partner-portal/{id}/leads/{lead}/status · /reject

GET    /api/v1/learning/mistakes · /calibration · /model
POST   /api/v1/learning/run · /learning/apply

POST   /api/v1/ingest/candidates · /ingest/file
GET    /api/v1/ingest/schema

POST   /api/v1/solar/analyze · /financing/evaluate · /scoring/evaluate
POST   /api/v1/analyze · /tracking/evaluate
```

Interactive reference: `http://localhost:8000/docs`
