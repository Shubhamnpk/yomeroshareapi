# Mero Share IPO Automation Service

Production-ready microservice to automate Mero Share (Nepal CDSC) IPO applications using FastAPI and Playwright.

## Features
- Login and IPO application automation
- Optional API key for unlimited requests
- Rate limiting (10 requests/minute/IP) for unauthenticated users
- HTTPS enforcement
- Stateless (no DB, no credential storage)
- Dockerized deployment
- Singleton Chromium browser with per-request isolated contexts

## System Requirements

### Minimum (single-user, low traffic)
| Resource | Requirement |
|---|---|
| CPU | 1 core, 2+ GHz |
| RAM | **1 GB** (512 MB for OS + ~250 MB for Chromium + overhead) |
| Storage | 1 GB for Playwright browsers + dependencies |
| Network | Stable internet (Mero Share is in Nepal; latency varies) |

### Recommended (production, multiple users)
| Resource | Requirement |
|---|---|
| CPU | 2+ cores, 2.5+ GHz |
| RAM | **2 GB** (supports ~5-8 concurrent automations) |
| Storage | 2 GB |
| Network | Low-latency connection to Nepal CDSC servers |

### Platform Support

| Platform | Status | Notes |
|---|---|---|
| **Docker** (Linux amd64) | Supported | Uses playwright/python:jammy image |
| **Railway** | Supported | Builds from Dockerfile directly |
| **Fly.io** | Compatible | Needs sufficient /dev/shm (use --disable-dev-shm-usage) |
| **Heroku** | Possible | Requires container registry |
| **Kubernetes** | Good fit | Singleton browser per pod, scale horizontally |
| **Windows** | Dev only | Not recommended for production |
| **macOS** | Dev only | Not recommended for production |

## Architecture

### Browser Lifecycle

```
Server start
    |
    v
init_browser()  --  Launches ONE Chromium (headless) on startup
    |                    Takes ~2s, uses ~80 MB base
    |
    v
User Request A  -->  create_context()  -->  Isolated context A  -->  close context
User Request B  -->  create_context()  -->  Isolated context B  -->  close context
    |
    v
Server stop
    |
    v
close_browser()  --  Kills Chromium process
```

- **One browser** lives as long as the server
- **Per-request contexts** are fully isolated (cookies, localStorage, JS state)
- **Semaphore** (max 5) prevents hammering Mero Share
- **Unnecessary resources blocked**: images, fonts, media, tracking domains

### Memory Comparison

| Scenario | Memory | Notes |
|---|---|---|
| Cold start (no users) | ~80 MB | Browser loaded, idle |
| 1 active request | ~95 MB | Browser + 1 context |
| 5 concurrent requests | ~150 MB | Browser + 5 contexts |
| Old approach (per-request browser) | ~440 MB / request | Unusable beyond 2 concurrent |

### Performance

| Operation | Average Time | Notes |
|---|---|---|
| Login (Mero Share) | 3-8 s | Depends on Mero Share server response |
| Portfolio | 4-7 s | Includes login + navigation |
| Apply IPO | 10-30 s | Multi-step form + PIN submission |
| Browser launch (now eliminated) | 2-3 s | Was incurred per request before singleton |

> Mero Share rate-limits rapid requests. Maintain **>=5s gap** between requests to avoid errors.

## Project Structure

```
Dockerfile
docker-compose.yml
requirements.txt
.env.example
.gitignore
src/
  __init__.py
  main.py           -- FastAPI app, startup/shutdown events
  browser.py        -- Singleton Chromium manager
  meroshare.py      -- Automation logic (login, IPO, portfolio)
  models.py         -- Pydantic request/response models
  utils.py          -- DPS fetching, time helpers
scrape_dps.py       -- Utility to scrape DP list from login page
test.py             -- CLI test script
```

## Setup

1. Create an `.env` file from `.env.example` and set your API key.
2. Build and run:

```bash
docker-compose up --build
```

The API listens on port `8000`.

### Local Development (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt
playwright install chromium
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Railway Deployment

Railway can build directly from this Dockerfile.
1. Push this repo to GitHub.
2. In Railway, create a new project and select "Deploy from GitHub repo".
3. Railway detects the Dockerfile automatically and builds the service.
4. Set environment variables in Railway:
   - `API_KEY` (optional but recommended)
   - `DPS_URL` (optional)
5. Ensure the service port is set to the Railway `PORT` variable (Dockerfile already uses it).

After deployment, open the service URL and visit:
- `/` for the landing page
- `/api` for the API index

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | - | Secret key for authenticated access |
| `DPS_URL` | Official CDSC URL | Override DPS source (comma-separated) |
| `ALLOW_HTTP` | `0` | Set to `1` to allow HTTP (dev only) |
| `ENV` | `production` | Set to `development` to allow HTTP |
| `PORT` | `8000` | Server port (Railway sets this automatically) |

## Quick CLI Test

```bash
python test.py --test-health
python test.py --test-dps
python test.py --test-login --dp-id 13000 --username USER --password PASS
python test.py --test-portfolio --dp-id 13000 --username USER --password PASS
python test.py --test-allotment --dp-id 13000 --username USER --password PASS --ipo-name "IPO NAME"
python test.py --test-apply --dp-id 13000 --username USER --password PASS --crn CRN --pin PIN --bank "NIC ASIA Bank Limited" --company-share-id "IPO NAME" --units 10
```

## HTTPS Enforcement

This service **requires HTTPS**. In production, put it behind an HTTPS reverse proxy (Nginx, Caddy, Traefik, Cloudflare, etc.) and pass `X-Forwarded-Proto: https`.

For local development, you can allow HTTP by setting:
```
ALLOW_HTTP=1
```
or
```
ENV=development
```

## API Key Behavior
- If `X-API-Key` matches `API_KEY`, rate limiting is **disabled** for that request.
- If no API key (or wrong key), requests are allowed but **rate limited** to 10/min/IP.

## DPS Fetching
The service tries to fetch DPS data from the official URL first. If that endpoint is unreachable (404/timeout), it falls back to `dps.json` (if present) and finally to a small hardcoded list.

You can override the DPS source URL with:
```
DPS_URL=https://meroshare.cdsc.com.np/api/casba/bank/
```
You can also provide multiple URLs separated by commas.

### Scrape DPS From Login Dropdown
If the API is down, you can scrape the DP list from the login dropdown and save it as `dps.json`:
```bash
python scrape_dps.py
```
This writes `dps.json`, which `/dps` will use automatically.

## API

### Health Check
`GET /health`

```json
{ "status": "ok", "timestamp": "2026-03-19T00:00:00Z" }
```

### Get DPs
`GET /dps`

Headers: `X-API-Key: your-secret-key`

```json
[
  { "id": "13100", "name": "NIC ASIA Bank Limited", "code": "NIC" }
]
```

### Apply IPO
`POST /apply-ipo`

Headers: `X-API-Key: your-secret-key`

Parameters:
- `dp_id` (string, required) -- Depository Participant ID
- `username` (string, required) -- Mero Share username
- `password` (string, required) -- Mero Share password
- `crn` (string, required) -- CRN number
- `pin` (string, required) -- Transaction PIN
- `ipo_details.company_share_id` (string, required) -- IPO company name or share ID
- `ipo_details.units` (integer, required) -- Kitta (units)
- `ipo_details.bank` (string, required) -- Bank name for ASBA

```json
{
  "dp_id": "13000",
  "username": "mero_user",
  "password": "mero_pass",
  "crn": "1234567890",
  "pin": "1234",
  "ipo_details": {
    "company_share_id": "ACME Laghubitta",
    "units": 10,
    "bank": "NIC ASIA Bank Limited"
  }
}
```

### Check Allotment
`POST /check-allotment`

Headers: `X-API-Key: your-secret-key`

Parameters: `dp_id`, `username`, `password`, `ipo_name`

You can also send `{ "credentials": { "dpId": "...", "username": "...", "password": "..." }, "ipoName": "..." }` for compatibility.

### Portfolio
`POST /portfolio`

Headers: `X-API-Key: your-secret-key`

Parameters: `dp_id`, `username`, `password`

### Test Login
`POST /test-login`

Headers: `X-API-Key: your-secret-key`

Parameters: `dp_id`, `username`, `password`

## CAPTCHA Handling
If a CAPTCHA input field is detected, the service returns an error for manual handling.

## Company Selection Note
The `company_share_id` field is matched against visible text and attributes in the IPO list. If you pass the company name instead of a numeric ID, it will still match using fuzzy name normalization.

## Bank Selection Note
The service tries to match the provided bank name first. If no match is found, it falls back to the first available bank option.

## Notes
- The service never stores credentials.
- No sensitive data is logged.
- Timeout per request is 120 seconds.
- Mero Share rate-limits rapid logins; allow 5+ seconds between requests.
