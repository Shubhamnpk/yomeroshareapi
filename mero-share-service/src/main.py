from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
    DpsResponse,
    PortfolioRequest,
    PortfolioResponse,
    TestLoginRequest,
    TestLoginResponse,
)
from .utils import fetch_dps, utc_now_iso

load_dotenv()

API_KEY = os.getenv('API_KEY')

logger = logging.getLogger('mero-share-service')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

if not API_KEY:
    logger.warning('API_KEY is not set. Requests will be rate-limited for all users.')

REQUEST_TIMEOUT_SECONDS = 120

app = FastAPI(title='Mero Share IPO Automation Service', version='1.0.0')

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


def _is_authenticated(request: Request) -> bool:
    return bool(getattr(request.state, 'api_key_valid', False))


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
    if proto != 'https':
        return JSONResponse(status_code=400, content={'detail': 'HTTPS required'})
    return await call_next(request)


@app.middleware('http')
async def api_key_context(request: Request, call_next):
    header_key = request.headers.get('x-api-key')
    request.state.api_key_valid = bool(API_KEY and header_key == API_KEY)
    return await call_next(request)


@app.get('/health')
async def health() -> dict:
    return {'status': 'ok', 'timestamp': utc_now_iso()}


@app.post('/apply-ipo', response_model=ApplyIPOResponse)
@limiter.limit('10/minute', exempt_when=_is_authenticated)
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
@limiter.limit('10/minute', exempt_when=_is_authenticated)
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
@limiter.limit('10/minute', exempt_when=_is_authenticated)
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
@limiter.limit('10/minute', exempt_when=_is_authenticated)
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


@app.get('/dps', response_model=DpsResponse)
@limiter.limit('10/minute', exempt_when=_is_authenticated)
async def dps_endpoint(
    request: Request,
) -> DpsResponse:
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
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
        return DpsResponse(
            items=items,
            count=len(items),
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception:
        logger.exception('Unhandled error while fetching DPS list')
        return DpsResponse(
            items=[],
            count=0,
            timestamp=utc_now_iso(),
            request_id=request_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            message='Failed to fetch DPS list.',
        )
