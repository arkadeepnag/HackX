# Deployment and real data

## Part 1 — Which of your teammate's data to use

His pipeline produces two files with very different sizes and roles.

| File | Size | Verdict |
|---|---|---|
| `outputs/target_universe.csv` | a few MB | **Use the real file. Always.** |
| `outputs/jaipur_buildings_places.geojson` | 100s of MB | **Clip it. Never ship the full file.** |

### target_universe.csv — use it as-is

This is the lead source and it is small. Ingest it directly:

```bash
curl -X POST localhost:8000/api/v1/ingest/file \
  -H 'Content-Type: application/json' \
  -d '{"path":"../hackx4.0-main/outputs/target_universe.csv",
       "data_mode":"offline","auto_route":true}'
```

Start with `"limit": 500` on the first run. Check `skipped` and
`skipped_detail` before scaling up — a high skip count means the column
mapping is wrong, and finding that on 500 rows is faster than on 40,000.

Use `"data_mode": "offline"` for bulk ingestion. `"real"` calls PVGIS/NASA
POWER per ~1 km tile; across a full city that is thousands of HTTP requests
and the upstream APIs will rate-limit you. Offline mode uses cached
climatology and is accurate enough for screening.

### The GeoJSON — clip it

The heatmap reads this file on every request. A 300 MB layer means a slow
endpoint, a huge container image, and a repository you cannot push.

```bash
python scripts/clip_geodata.py \
  --input ../hackx4.0-main/outputs/jaipur_buildings_places.geojson \
  --lat 26.7963 --lon 75.8397 --radius-km 3 \
  --min-area-m2 100 --format gpkg \
  --output app/data/demo_cluster.gpkg
```

Pick the coordinates of the cluster you will actually demo — Sitapura or
Vishwakarma industrial area for Jaipur. The result is real Overture geometry
at a size you can commit and deploy.

`--format gpkg` writes GeoPackage: binary, roughly a third the size of
GeoJSON, and faster to read. `--min-area-m2 100` matches the filter his
`create_target_universe.py` already applies, so the two layers agree.

### So: real data or dummy?

**Real data for leads, clipped real data for the map, placeholder for the
rest — and say so.**

Run `python scripts/check_data.py` for the current state. The four remaining
placeholder files, in order of how much they change your numbers:

1. **`app/data/tariffs.json`** — `MVP_CONFIG` at confidence 0.35. Every
   rupee on your dashboard derives from these slabs. Replacing this with the
   real RERC FY 2026-27 order is the single highest-value data fix. Your
   teammate already has the source in `data/reference/discom_tariffs.csv`.
2. **`app/data/pincodes.json`** — 20 seed entries. Load the India Post
   directory and set `RAAH_PINCODE_PATH`.
3. **`app/data/partners.json`** — three invented EPCs. Rename them to real
   local installers, or label them clearly as illustrative.
4. **`app/data/reliability.json`** — SAIDI defaults. Low impact; leave it.

Do not hide the placeholders. `tariff_source` and `confidence` are on every
tariff response — surface them in the UI. A team that flags its own
uncertainty reads as more rigorous, not less.

---

## Part 2 — Hosting

### The constraint that decides everything

The dependency stack is **240 MB installed** (pandas 68, sklearn 45, numpy
40, pvlib 32, pyogrio 23, pyproj 22, shapely 6, geopandas 4).

That rules out:
- **Vercel / Netlify / AWS Lambda** — 250 MB limits, and these are built for
  request-scoped functions, not a stateful geospatial service
- **Any free tier without a persistent disk** — SQLite on an ephemeral
  filesystem loses every lead on redeploy

### Recommended: Render, Docker, with a disk

`Dockerfile` and `render.yaml` are in the repo.

```bash
git push                      # connect the repo in the Render dashboard
```

`render.yaml` already declares a 1 GB disk at `/data` and sets
`RAAH_DB_PATH=/data/raah.db`. Without that disk the database resets on every
deploy.

Set these as dashboard secrets, never in git:
`WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`.

The image builds in roughly 4-6 minutes. Cold start is 20-40 seconds because
importing geopandas and pvlib is slow — hence the health check
`start-period`.

### Alternatives

| Host | Fit | Watch out for |
|---|---|---|
| **Railway** | Good. Detects the Dockerfile, volumes are easy | Usage-based billing after the trial credit |
| **Fly.io** | Good. Real volumes, deploys close to users | `fly.toml` config, slightly steeper learning curve |
| **Render free tier** | Demo only | Sleeps after 15 min idle, **no persistent disk** |
| **Hugging Face Spaces** | Free, Docker, no card | Public by default, 50 s request timeout |
| **A student VPS** | Cheapest, full control | You maintain it |

### Honest hackathon advice

**Demo from localhost. Deploy as the backup.**

A judge watching a 40-second cold start, or a free instance that slept, is
worse than a laptop running `uvicorn`. Deploy so the link exists and the
work is verifiable, then present locally.

If you must present from the deployed instance, hit `/health` five minutes
beforehand to wake it, and pre-run the ingestion so the dashboard has data.

### Frontend

Build the React app and deploy it to Vercel or Netlify — static assets, no
size constraint, free tier is genuinely fine. Set
`VITE_API_URL=https://your-backend.onrender.com/api/v1`.

CORS is already `allow_origins=["*"]`, so no backend change is needed.
Tighten it to your actual frontend origin before anything real:

```python
allow_origins=["https://raah.vercel.app", "http://localhost:5173"]
```

---

## Part 3 — Making it public safely

### Lock it before you expose it

Two environment variables, both unset by default so local work is
unaffected.

```bash
# generate a key
python -c "import secrets; print(secrets.token_urlsafe(32))"

RAAH_API_KEY=<that value>
RAAH_ALLOWED_ORIGINS=https://raah.vercel.app,http://localhost:5173
```

With `RAAH_API_KEY` set, every endpoint requires `X-API-Key`. Four paths
stay open by design: `/health` (load balancers probe it), `/docs`,
`/openapi.json`, and `/api/v1/webhooks/whatsapp` — Meta signs its own calls
and cannot send your header, so that route is protected by
`X-Hub-Signature-256` instead. Set `WHATSAPP_APP_SECRET` or that signature
check is skipped.

Frontend side:

```js
const res = await fetch(url, {
  headers: { "Content-Type": "application/json",
             "X-API-Key": import.meta.env.VITE_API_KEY },
});
```

This is a shared key, not per-user auth. Anyone with the frontend bundle can
read it. It stops drive-by scraping of a public URL, not a determined
attacker — which is the right bar for a hackathon, as long as you say so if
asked.

### Quick public URL (demo, WhatsApp webhook)

For a live Meta webhook you need public HTTPS. A tunnel is faster than
deploying:

```bash
# option A — cloudflared, no signup
cloudflared tunnel --url http://localhost:8000

# option B — ngrok, stable subdomain on a paid plan
ngrok http 8000
```

Paste the HTTPS URL into Meta's webhook config as
`https://<tunnel>/api/v1/webhooks/whatsapp`, with the verify token from
`WHATSAPP_VERIFY_TOKEN`. The GET handshake returns the raw challenge, so
verification succeeds immediately.

Tunnels are ephemeral. Fine for a demo, wrong for a submission link.

**`raah.db` must be gitignored.** It holds phone numbers from your test
conversations.

**Run the full check before pushing:**

```bash
pytest tests/ -q                    # 37 tests
python scripts/check_data.py        # what is real
uvicorn app.main:app &
python scripts/smoke_test.py        # 35 live checks
```
