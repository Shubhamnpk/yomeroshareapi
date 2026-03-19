# Mero Share IPO Automation Service

Production-ready microservice to automate Mero Share (Nepal CDSC) IPO applications using FastAPI and Playwright.

## Features
- Login and IPO application automation
- Optional API key for unlimited requests
- Rate limiting (10 requests/minute/IP) for unauthenticated users
- HTTPS enforcement
- Stateless (no DB, no credential storage)
- Dockerized deployment

## Project Structure
```
mero-share-service/
??? Dockerfile
??? docker-compose.yml
??? requirements.txt
??? .env.example
??? src/
?   ??? main.py
?   ??? models.py
?   ??? meroshare.py
?   ??? utils.py
??? README.md
```

## Setup
1. Create an `.env` file from `.env.example` and set your API key.
2. Build and run:

```bash
cd mero-share-service
docker-compose up --build
```

The API listens on port `8000`.

## Quick CLI Test
Use the included `test.py` script to hit endpoints without extra tools.

Example:
```bash
cd mero-share-service
python test.py --test-health
python test.py --test-dps
python test.py --test-login --dp-id 13000 --username USER --password PASS
python test.py --test-portfolio --dp-id 13000 --username USER --password PASS
python test.py --test-allotment --dp-id 13000 --username USER --password PASS --ipo-name "IPO NAME"
python test.py --test-apply --dp-id 13000 --username USER --password PASS --crn CRN --pin PIN --bank "NIC ASIA Bank Limited" --company-share-id "IPO NAME" --units 10
```

## HTTPS Enforcement
This service **requires HTTPS**. In production, put it behind an HTTPS reverse proxy (Nginx, Caddy, Traefik, Cloudflare, etc.) and pass `X-Forwarded-Proto: https`.

## API Key Behavior
- If `X-API-Key` matches `API_KEY`, rate limiting is **disabled** for that request.
- If no API key (or wrong key), requests are allowed but **rate limited** to 10/min/IP.

## API

### Health Check
`GET /health`

Response:
```json
{ "status": "ok", "timestamp": "2026-03-19T00:00:00Z" }
```

### Get DPs
`GET /dps`

Headers:
```
X-API-Key: your-secret-key
```

Response:
```json
{
  "items": [
    { "id": "13100", "name": "NIC ASIA Bank Limited", "code": "NIC" }
  ],
  "count": 1,
  "timestamp": "2026-03-19T00:00:00Z",
  "request_id": "e4c7d6f1-9c1a-4c7a-9a3d-5f5a9b6f27b0",
  "duration_ms": 42,
  "message": null
}
```

### Apply IPO
`POST /apply-ipo`

Headers:
```
X-API-Key: your-secret-key
```

Request body:
```json
{
  "dp_id": "string",
  "username": "string",
  "password": "string",
  "crn": "string",
  "pin": "string",
  "ipo_details": {
    "company_share_id": "string",
    "units": 10,
    "bank": "string"
  }
}
```

Response:
```json
{
  "status": "success",
  "message": "Application submitted successfully",
  "application_id": "123456",
  "details": { "result": "submitted" },
  "timestamp": "2026-03-19T00:00:00Z",
  "request_id": "e4c7d6f1-9c1a-4c7a-9a3d-5f5a9b6f27b0",
  "duration_ms": 8243
}
```

### Check Allotment
`POST /check-allotment`

Headers:
```
X-API-Key: your-secret-key
```

Request body:
```json
{
  "dp_id": "string",
  "username": "string",
  "password": "string",
  "ipo_name": "string"
}
```
You can also send `{ "credentials": { "dpId": "...", "username": "...", "password": "..." }, "ipoName": "..." }` for compatibility with the existing Puppeteer routes.

Response:
```json
{
  "success": true,
  "status": "Application Verified (Result Pending)",
  "is_allotted": false,
  "allotted_quantity": "0",
  "all_details": {},
  "timestamp": "2026-03-19T00:00:00Z",
  "request_id": "e4c7d6f1-9c1a-4c7a-9a3d-5f5a9b6f27b0",
  "duration_ms": 5102
}
```

### Portfolio
`POST /portfolio`

Headers:
```
X-API-Key: your-secret-key
```

Request body:
```json
{
  "dp_id": "string",
  "username": "string",
  "password": "string"
}
```
You can also send `{ "credentials": { "dpId": "...", "username": "...", "password": "..." } }` for compatibility.

Response:
```json
{
  "success": true,
  "portfolio": [
    { "symbol": "ABC", "units": 10, "current_price": 100, "buy_price": 0 }
  ],
  "timestamp": "2026-03-19T00:00:00Z",
  "request_id": "e4c7d6f1-9c1a-4c7a-9a3d-5f5a9b6f27b0",
  "duration_ms": 2920,
  "total_positions": 1,
  "total_units": 10
}
```

### Test Login
`POST /test-login`

Headers:
```
X-API-Key: your-secret-key
```

Request body:
```json
{
  "dp_id": "string",
  "username": "string",
  "password": "string"
}
```
You can also send `{ "credentials": { "dpId": "...", "username": "...", "password": "..." } }` for compatibility.

Response:
```json
{
  "success": true,
  "message": "Login Successful! Welcome, User.",
  "timestamp": "2026-03-19T00:00:00Z",
  "request_id": "e4c7d6f1-9c1a-4c7a-9a3d-5f5a9b6f27b0",
  "duration_ms": 1850
}
```

### CAPTCHA Handling
If a CAPTCHA input field is detected, the service returns an error for manual handling.

### Company Selection Note
The `company_share_id` field is matched against visible text and attributes in the IPO list. If you pass the company name instead of a numeric ID, it will still match using fuzzy name normalization (as in the working Puppeteer flow).

### Bank Selection Note
The service tries to match the provided bank name first. If no match is found, it falls back to the first available bank option (same behavior as the reference Puppeteer code).

## Notes
- The service never stores credentials.
- No sensitive data is logged.
- Timeout per request is 120 seconds.
