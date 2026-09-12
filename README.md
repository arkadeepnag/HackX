# RAAH — Modules 3–9 (WhatsApp qualification flow + fixes)

## Run it

```bash
pip install -r app/requirements.txt
cp app/.env.example app/.env          # works as-is; console mode, no Meta account needed
uvicorn app.main:app --reload
pytest tests/ -q                      # 13 tests, no network
```

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

## Wiring in your friend's modules 1–2

The flow currently sizes from a customer-reported roof area and a national
fallback yield of 1450 kWh/kWp. When the building footprints and geo data land,
inject the real estimator — **one call, no flow changes**:

```python
# app/main.py, after imports
from app.engines import whatsapp_flow
from app.engines.lead_engine import LeadEngine

engine = LeadEngine()

def real_estimator(context: dict) -> dict:
    lat, lon = lookup_centroid(context["pincode"])        # from module 1-2
    resource = engine.solar_resource.get(lat, lon, "real")
    tariff   = engine.tariff_provider.resolve(lat, lon, context["segment"])
    return {
        "specific_yield_kwh_per_kw": resource["annual_specific_yield"],
        "tariff_rs_kwh": engine.tariff_provider.marginal_rate(
            context.get("monthly_consumption_kwh", 300), tariff),
        "state": tariff["state"],
        "latitude": lat, "longitude": lon,
        "shading_loss_pct": roof_shading(lat, lon),        # from solar_engine
        "source": "pvgis+discom",
    }

whatsapp_flow.set_estimator(real_estimator)
```

Once that's in, a discovered rooftop and a WhatsApp walk-in produce identical
economics — the conversation only supplies the disqualifiers satellites can't see
(ownership, sanctioned load, actual bills).

---

## Two things to verify before demo day

1. **Subsidy rates.** ₹30k/kW (first 2 kW), ₹18k (3rd), ₹78k cap are in
   `SubsidyConfig`. Confirm against the current MNRE memorandum — they move.
2. **Tariff slabs.** `tariffs.json` is marked `MVP_CONFIG` with confidence 0.35.
   Real DISCOM slabs for your demo city will change every payback number.

Also note `_reliability_score` in `lead_engine.py` *increases* with SAIDI — it's
an outage-opportunity score, not grid quality. Intentional, now documented, but
don't let a judge read it as a bug.