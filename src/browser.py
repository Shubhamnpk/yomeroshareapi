from __future__ import annotations

import asyncio
import logging

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("mero-share-service")

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--no-first-run",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
    "--disable-ipc-flooding-protection",
    "--mute-audio",
]

BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "texttrack", "imageset"}
BLOCKED_RESOURCE_DOMAINS = {
    "google-analytics.com", "googletagmanager.com", "facebook.net",
    "doubleclick.net", "hotjar.com", "newrelic.com",
}

_playwright = None
_browser: Browser | None = None
_semaphore = asyncio.Semaphore(5)
_init_lock = asyncio.Lock()


async def _block_route(route) -> None:
    req = route.request
    if req.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    for domain in BLOCKED_RESOURCE_DOMAINS:
        if domain in req.url:
            await route.abort()
            return
    await route.continue_()


async def init_browser() -> None:
    global _playwright, _browser
    async with _init_lock:
        if _browser and _browser.is_connected():
            return
        if _browser:
            try:
                await _browser.close()
            except Exception:
                pass
        logger.info("Launching browser...")
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=CHROMIUM_ARGS,
        )
        logger.info("Browser initialized")


async def close_browser() -> None:
    global _playwright, _browser
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    logger.info("Browser closed")


async def get_browser() -> Browser:
    if _browser is None or not _browser.is_connected():
        await init_browser()
    return _browser


async def is_browser_healthy() -> bool:
    return _browser is not None and _browser.is_connected()


async def create_context() -> tuple[BrowserContext, Page]:
    async with _semaphore:
        browser = await get_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await page.route("**/*", _block_route)
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)
        return context, page
