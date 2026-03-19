from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from .meroshare import (
    AutomationFailedError,
    CaptchaRequiredError,
    apply_ipo,
    check_allotment,
    get_portfolio,
    test_login,
)
from .models import (
    ApplyIPORequest,
    ApplyIPOResponse,
    CheckAllotmentRequest,
    CheckAllotmentResponse,
    DpsItem,
    PortfolioRequest,
    PortfolioResponse,
    TestLoginRequest,
    TestLoginResponse,
)
from .utils import fetch_dps, utc_now_iso

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / '.env')

API_KEY = os.getenv('API_KEY')
ALLOW_HTTP = os.getenv('ALLOW_HTTP', '0') == '1'
ENVIRONMENT = os.getenv('ENV', os.getenv('ENVIRONMENT', 'production')).lower()

logger = logging.getLogger('mero-share-service')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if not API_KEY:
    logger.warning('API_KEY is not set. Requests will be rate-limited for all users.')

REQUEST_TIMEOUT_SECONDS = 120

app = FastAPI(title='Mero Share IPO Automation Service', version='1.0.0')

def _rate_limit_key(request: Request) -> str:
    header_key = request.headers.get('x-api-key')
    if API_KEY and header_key == API_KEY:
        return f"auth:{uuid.uuid4()}"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


def _get_request_proto(request: Request) -> str:
    forwarded = request.headers.get('forwarded')
    if forwarded:
        for part in forwarded.split(';'):
            if part.strip().lower().startswith('proto='):
                return part.split('=')[1].strip().lower()
    xfp = request.headers.get('x-forwarded-proto')
    if xfp:
        return xfp.split(',')[0].strip().lower()
    return request.url.scheme.lower()


@app.middleware('http')
async def https_enforcer(request: Request, call_next):
    proto = _get_request_proto(request)
    is_local = False
    if request.client:
        is_local = request.client.host in {'127.0.0.1', '::1'}
    allow_http = ALLOW_HTTP or ENVIRONMENT in {'dev', 'development', 'local'} or is_local
    if proto != 'https' and not allow_http:
        return JSONResponse(status_code=400, content={'detail': 'HTTPS required'})
    return await call_next(request)


@app.middleware('http')
async def api_key_guard(request: Request, call_next):
    header_key = request.headers.get('x-api-key')
    if header_key and API_KEY and header_key != API_KEY:
        return JSONResponse(status_code=401, content={'detail': 'API key is incorrect'})
    return await call_next(request)




@app.get('/health')
async def health() -> dict:
    return {'status': 'ok', 'timestamp': utc_now_iso()}


@app.get('/', response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <title>Mero Share Automation</title>
        <style>
          :root {
            --bg: #0f172a;
            --card: #111827;
            --accent: #22c55e;
            --muted: #94a3b8;
            --text: #e2e8f0;
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
            background: radial-gradient(1000px 600px at 10% -10%, #1f2937, transparent),
                        radial-gradient(1000px 600px at 100% 0%, #0b3b2a, transparent),
                        var(--bg);
            color: var(--text);
          }
          .wrap { max-width: 980px; margin: 0 auto; padding: 48px 20px; }
          .hero {
            background: linear-gradient(135deg, rgba(34,197,94,0.15), rgba(59,130,246,0.08));
            border: 1px solid rgba(148,163,184,0.2);
            border-radius: 18px;
            padding: 28px;
          }
          h1 { margin: 0 0 10px; font-size: 32px; }
          p { margin: 8px 0; color: var(--muted); line-height: 1.6; }
          .grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 20px; }
          .card {
            background: var(--card);
            border: 1px solid rgba(148,163,184,0.15);
            border-radius: 14px;
            padding: 16px;
          }
          .tag { display: inline-block; font-size: 12px; color: #0b3b2a; background: #a7f3d0; padding: 4px 8px; border-radius: 999px; font-weight: 600; }
          .btn {
            display: inline-block;
            margin-top: 12px;
            color: #0b3b2a;
            background: var(--accent);
            text-decoration: none;
            padding: 10px 14px;
            border-radius: 10px;
            font-weight: 600;
          }
          code { background: #0b1220; padding: 2px 6px; border-radius: 6px; color: #a7f3d0; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <div class="hero">
            <span class="tag">Mero Share Automation</span>
            <h1>IPO, Portfolio, and Allotment Automation API</h1>
            <p>This microservice automates Mero Share (CDSC Nepal) flows using FastAPI + Playwright.</p>
            <p>Use the API to apply IPOs, check allotments, sync portfolio, and fetch DP list.</p>
            <a class="btn" href="/api">Open API Index</a>
          </div>
          <div class="grid">
            <div class="card">
              <h3>Apply IPO</h3>
              <p>Automate My ASBA application with CRN and PIN.</p>
              <p><code>POST /apply-ipo</code></p>
            </div>
            <div class="card">
              <h3>Check Allotment</h3>
              <p>Read application report and allotment status.</p>
              <p><code>POST /check-allotment</code></p>
            </div>
            <div class="card">
              <h3>Portfolio</h3>
              <p>Sync portfolio holdings from Mero Share.</p>
              <p><code>POST /portfolio</code></p>
            </div>
            <div class="card">
              <h3>DP List</h3>
              <p>Fetch Depository Participant list.</p>
              <p><code>GET /dps</code></p>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get('/api', response_class=HTMLResponse)
async def api_index() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width,initial-scale=1" />
        <title>API Index</title>
        <style>
          body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #0b1220; color: #e2e8f0; }
          .wrap { max-width: 900px; margin: 0 auto; padding: 32px 20px; }
          h1 { margin-bottom: 8px; }
          .endpoint { background: #111827; border: 1px solid rgba(148,163,184,0.2); border-radius: 12px; padding: 14px; margin-bottom: 12px; }
          .method { font-weight: 700; color: #22c55e; }
          code { background: #0b1220; padding: 2px 6px; border-radius: 6px; color: #a7f3d0; }
          a { color: #60a5fa; text-decoration: none; }
          .playground { background: #0f172a; border: 1px solid rgba(148,163,184,0.2); border-radius: 14px; padding: 16px; margin-top: 18px; }
          .row { display: flex; gap: 12px; flex-wrap: wrap; }
          select, input, textarea, button {
            background: #111827;
            color: #e2e8f0;
            border: 1px solid rgba(148,163,184,0.3);
            border-radius: 8px;
            padding: 8px 10px;
            font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
          }
          textarea { width: 100%; min-height: 160px; }
          button { background: #22c55e; color: #0b3b2a; font-weight: 700; cursor: pointer; }
          pre { background: #0b1220; padding: 12px; border-radius: 10px; overflow: auto; }
        </style>
      </head>
      <body>
        <div class="wrap">
          <h1>API Index</h1>
          <p>All endpoints require HTTPS in production. For local testing, set <code>ALLOW_HTTP=1</code> or <code>ENV=development</code>.</p>
          <p>Send API key in header: <code>X-API-Key: your-secret-key</code></p>

          <div class="endpoint">
            <span class="method">GET</span> <code>/health</code>
            <p>Health check.</p>
          </div>

          <div class="endpoint">
            <span class="method">GET</span> <code>/dps</code>
            <p>Returns list of Depository Participants.</p>
          </div>

          <div class="endpoint">
            <span class="method">POST</span> <code>/apply-ipo</code>
            <p>Parameters:</p>
            <p><code>dp_id</code>, <code>username</code>, <code>password</code>, <code>crn</code>, <code>pin</code>, <code>ipo_details.company_share_id</code>, <code>ipo_details.units</code>, <code>ipo_details.bank</code></p>
            <pre><code>{
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
}</code></pre>
            <p>Python example:</p>
            <pre><code>import requests

url = "http://localhost:8000/apply-ipo"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "your-secret-key"
}
payload = {
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
resp = requests.post(url, json=payload, headers=headers)
print(resp.status_code)
print(resp.json())</code></pre>
          </div>

          <div class="endpoint">
            <span class="method">POST</span> <code>/check-allotment</code>
            <p>Parameters:</p>
            <p><code>dp_id</code>, <code>username</code>, <code>password</code>, <code>ipo_name</code></p>
            <pre><code>{
  "credentials": {
    "dpId": "13000",
    "username": "mero_user",
    "password": "mero_pass"
  },
  "ipoName": "ACME Laghubitta"
}</code></pre>
          </div>

          <div class="endpoint">
            <span class="method">POST</span> <code>/portfolio</code>
            <p>Parameters:</p>
            <p><code>dp_id</code>, <code>username</code>, <code>password</code></p>
            <pre><code>{
  "credentials": {
    "dpId": "13000",
    "username": "mero_user",
    "password": "mero_pass"
  }
}</code></pre>
          </div>

          <div class="endpoint">
            <span class="method">POST</span> <code>/test-login</code>
            <p>Parameters:</p>
            <p><code>dp_id</code>, <code>username</code>, <code>password</code></p>
            <pre><code>{
  "credentials": {
    "dpId": "13000",
    "username": "mero_user",
    "password": "mero_pass"
  }
}</code></pre>
          </div>

          <div class="playground">
            <h3>Test Playground</h3>
            <p>Use this to send a request to your running API. It uses the current site URL.</p>
            <div class="row">
              <label>Endpoint:
                <select id="endpoint">
                  <option value="/health" data-method="GET">GET /health</option>
                  <option value="/dps" data-method="GET">GET /dps</option>
                  <option value="/test-login" data-method="POST">POST /test-login</option>
                  <option value="/portfolio" data-method="POST">POST /portfolio</option>
                  <option value="/check-allotment" data-method="POST">POST /check-allotment</option>
                  <option value="/apply-ipo" data-method="POST" selected>POST /apply-ipo</option>
                </select>
              </label>
              <label>API Key:
                <input id="apiKey" placeholder="your-secret-key (optional)" />
              </label>
            </div>
            <p>JSON Body (for POST):</p>
            <textarea id="payload">{
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
}</textarea>
            <div class="row">
              <button id="sendBtn">Send Request</button>
            </div>
            <p>Response:</p>
            <pre id="responseBox">Waiting for request...</pre>
          </div>

          <p><a href="/">Back to Home</a></p>
        </div>
        <script>
          const endpointEl = document.getElementById('endpoint');
          const apiKeyEl = document.getElementById('apiKey');
          const payloadEl = document.getElementById('payload');
          const responseBox = document.getElementById('responseBox');
          const sendBtn = document.getElementById('sendBtn');

          sendBtn.addEventListener('click', async () => {
            const path = endpointEl.value;
            const method = endpointEl.selectedOptions[0].dataset.method || 'GET';
            const headers = { 'Content-Type': 'application/json' };
            const apiKey = apiKeyEl.value.trim();
            if (apiKey) headers['X-API-Key'] = apiKey;

            let body = null;
            if (method !== 'GET') {
              try {
                body = JSON.stringify(JSON.parse(payloadEl.value));
              } catch (err) {
                responseBox.textContent = 'Invalid JSON body: ' + err;
                return;
              }
            }

            responseBox.textContent = 'Sending...';
            try {
              const res = await fetch(path, { method, headers, body });
              const text = await res.text();
              let output = text;
              try {
                output = JSON.stringify(JSON.parse(text), null, 2);
              } catch (_) {}
              responseBox.textContent = `Status: ${res.status}\\n\\n${output}`;
            } catch (err) {
              responseBox.textContent = 'Request failed: ' + err;
            }
          });
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.post('/apply-ipo', response_model=ApplyIPOResponse)
@limiter.limit('10/minute')
async def apply_ipo_endpoint(
    payload: ApplyIPORequest,
    request: Request,
) -> ApplyIPOResponse:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(apply_ipo(payload), timeout=REQUEST_TIMEOUT_SECONDS)
        return ApplyIPOResponse(
            status='success',
            message=result.message,
            application_id=result.application_id,
            details={'result': 'submitted'},
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except CaptchaRequiredError as exc:
        return ApplyIPOResponse(
            status='error',
            message=str(exc),
            application_id=None,
            details={'result': 'captcha_required'},
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except AutomationFailedError as exc:
        return ApplyIPOResponse(
            status='error',
            message=str(exc),
            application_id=None,
            details={'result': 'automation_failed'},
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except asyncio.TimeoutError:
        return ApplyIPOResponse(
            status='error',
            message='Request timed out (120s).',
            application_id=None,
            details={'result': 'timeout'},
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception:
        logger.exception('Unhandled error during IPO automation')
        return ApplyIPOResponse(
            status='error',
            message='Unexpected server error.',
            application_id=None,
            details={'result': 'unexpected_error'},
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@app.post('/check-allotment', response_model=CheckAllotmentResponse)
@limiter.limit('10/minute')
async def check_allotment_endpoint(
    payload: CheckAllotmentRequest,
    request: Request,
) -> CheckAllotmentResponse:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            check_allotment(payload.dp_id, payload.username, payload.password, payload.ipo_name),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return CheckAllotmentResponse(
            success=True,
            status=result.status,
            is_allotted=result.is_allotted,
            allotted_quantity=result.allotted_quantity,
            all_details=result.details,
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except AutomationFailedError as exc:
        return CheckAllotmentResponse(
            success=False,
            status='error',
            is_allotted=False,
            allotted_quantity='0',
            all_details={},
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except CaptchaRequiredError as exc:
        return CheckAllotmentResponse(
            success=False,
            status='error',
            is_allotted=False,
            allotted_quantity='0',
            all_details={},
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except asyncio.TimeoutError:
        return CheckAllotmentResponse(
            success=False,
            status='error',
            is_allotted=False,
            allotted_quantity='0',
            all_details={},
            message='Request timed out (120s).',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception:
        logger.exception('Unhandled error during allotment check')
        return CheckAllotmentResponse(
            success=False,
            status='error',
            is_allotted=False,
            allotted_quantity='0',
            all_details={},
            message='Unexpected server error.',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@app.post('/portfolio', response_model=PortfolioResponse)
@limiter.limit('10/minute')
async def portfolio_endpoint(
    payload: PortfolioRequest,
    request: Request,
) -> PortfolioResponse:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            get_portfolio(payload.dp_id, payload.username, payload.password),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        total_positions = len(result.portfolio)
        total_units = sum(float(item.get('units', 0) or 0) for item in result.portfolio)
        return PortfolioResponse(
            success=True,
            portfolio=result.portfolio,
            message=result.message,
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            total_positions=total_positions,
            total_units=total_units,
        )
    except AutomationFailedError as exc:
        return PortfolioResponse(
            success=False,
            portfolio=[],
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except CaptchaRequiredError as exc:
        return PortfolioResponse(
            success=False,
            portfolio=[],
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except asyncio.TimeoutError:
        return PortfolioResponse(
            success=False,
            portfolio=[],
            message='Request timed out (120s).',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception:
        logger.exception('Unhandled error during portfolio fetch')
        return PortfolioResponse(
            success=False,
            portfolio=[],
            message='Unexpected server error.',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@app.post('/test-login', response_model=TestLoginResponse)
@limiter.limit('10/minute')
async def test_login_endpoint(
    payload: TestLoginRequest,
    request: Request,
) -> TestLoginResponse:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            test_login(payload.dp_id, payload.username, payload.password),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return TestLoginResponse(
            success=result.success,
            message=result.message,
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except AutomationFailedError as exc:
        return TestLoginResponse(
            success=False,
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except CaptchaRequiredError as exc:
        return TestLoginResponse(
            success=False,
            message=str(exc),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except asyncio.TimeoutError:
        return TestLoginResponse(
            success=False,
            message='Request timed out (120s).',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception:
        logger.exception('Unhandled error during login test')
        return TestLoginResponse(
            success=False,
            message='Unexpected server error.',
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@app.get('/dps')
@limiter.limit('10/minute')
async def dps_endpoint(
    request: Request,
) -> JSONResponse:
    try:
        raw_items = fetch_dps()
        items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            safe_item = {
                'id': str(item.get('id', '')).strip(),
                'name': str(item.get('name', '')).strip(),
                'code': str(item.get('code', '')).strip(),
            }
            if safe_item['id'] and safe_item['name'] and safe_item['code']:
                items.append(safe_item)
        return JSONResponse(content=items)
    except Exception:
        logger.exception('Unhandled error while fetching DPS list')
        return JSONResponse(content=[])
