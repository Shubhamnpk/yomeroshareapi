from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, Page, Browser

from .models import ApplyIPORequest


class CaptchaRequiredError(Exception):
    pass


class AutomationFailedError(Exception):
    pass


BLOCKED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet", "texttrack", "imageset"}
BLOCKED_RESOURCE_DOMAINS = {
    "google-analytics.com", "googletagmanager.com", "facebook.net",
    "doubleclick.net", "hotjar.com", "newrelic.com",
}

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


async def _setup_page(page: Page) -> None:
    await page.set_viewport_size({"width": 1280, "height": 800})
    await page.route(
        "**/*",
        lambda route: _handle_route(route),
    )


async def _handle_route(route) -> None:
    request = route.request
    resource_type = request.resource_type
    if resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    url = request.url
    for domain in BLOCKED_RESOURCE_DOMAINS:
        if domain in url:
            await route.abort()
            return
    await route.continue_()


async def _launch_browser(p) -> Browser:
    browser = await p.chromium.launch(
        headless=True,
        args=CHROMIUM_ARGS,
    )
    return browser


async def _create_page(browser: Browser) -> Page:
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    page = await context.new_page()
    await _setup_page(page)
    page.set_default_timeout(30000)
    page.set_default_navigation_timeout(60000)
    return page


@dataclass
class AutomationResult:
    success: bool
    message: str
    application_id: Optional[str] = None
    user_name: str = ''


@dataclass
class CheckAllotmentResult:
    status: str
    is_allotted: bool
    allotted_quantity: str
    details: Dict[str, str]
    user_name: str = ''


@dataclass
class PortfolioResult:
    portfolio: List[Dict[str, object]]
    message: Optional[str] = None
    user_name: str = ''


@dataclass
class TestLoginResult:
    success: bool
    message: str
    user_name: str = ''


async def _detect_captcha(page) -> bool:
    selectors = [
        'input[name*="captcha" i]',
        'input[id*="captcha" i]',
        'input[placeholder*="captcha" i]',
        '#captcha',
    ]
    for selector in selectors:
        try:
            count = await page.locator(selector).count()
            if count and count > 0:
                return True
        except Exception:
            continue
    return False


async def _select_dp(page, dp_id: str) -> None:
    await page.wait_for_selector('.select2-selection', timeout=20000)
    await page.click('.select2-selection')
    await page.wait_for_selector('.select2-search__field', state='visible', timeout=10000)
    await page.type('.select2-search__field', dp_id, delay=100)
    await page.wait_for_selector('.select2-results__option', state='visible', timeout=10000)
    await page.keyboard.press('Enter')


async def _click_button_by_text(page, text: str) -> None:
    await page.evaluate(
        """
        (btnText) => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const target = buttons.find(btn => (btn.textContent || '').includes(btnText));
            if (target) target.click();
        }
        """,
        text,
    )


async def _login(page, dp_id: str, username: str, password: str) -> None:
    await page.goto('https://meroshare.cdsc.com.np/#/login', wait_until='domcontentloaded')
    if await _detect_captcha(page):
        raise CaptchaRequiredError('CAPTCHA detected on login page. Manual intervention required.')

    try:
        await _select_dp(page, dp_id)
    except Exception:
        await page.keyboard.press('Enter')

    await page.wait_for_selector('#username', state='visible', timeout=15000)
    await page.click('#username')
    await page.type('#username', username, delay=50)
    await page.click('#password')
    await page.type('#password', password, delay=50)

    await _click_button_by_text(page, 'Login')

    try:
        await page.wait_for_function(
            """
            () => window.location.href.includes('/dashboard') ||
            document.querySelector('.toast-error') !== null ||
            (document.body.textContent || '').includes('Attempts remaining')
            """,
            timeout=30000,
        )
    except Exception:
        pass

    if '/dashboard' not in page.url:
        error_msg = await page.evaluate(
            """
            () => {
                const toast = document.querySelector('.toast-error, .toast-message');
                if (toast && toast.textContent) return toast.textContent.trim();
                if ((document.body.textContent || '').includes('Attempts remaining')) return 'Invalid credentials.';
                return null;
            }
            """
        )
        raise AutomationFailedError(error_msg or 'Login failed or timed out. Check credentials.')


async def _get_username(page) -> str:
    await page.wait_for_selector('.user-profile.dropdown .profile-text', state='attached', timeout=15000)
    await page.wait_for_timeout(1000)
    return await page.evaluate(
        """
        () => {
            const el = document.querySelector('.user-profile.dropdown .user-profile-name span');
            if (el) {
                const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text) return text;
            }
            return 'User';
        }
        """
    )


async def _logout(page) -> None:
    try:
        direct_selectors = [
            'a[href*="logout" i]',
            'a[href*="signout" i]',
            'a[href*="sign-out" i]',
            '.logout-btn',
            '.btn-logout',
            '#logout',
        ]
        for sel in direct_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    return
            except Exception:
                continue

        toggle_selectors = [
            '.user-profile-name',
            '.user-name',
            '.profile-icon',
            '.dropdown-toggle',
            '.nav-item.dropdown',
        ]
        for sel in toggle_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await page.wait_for_timeout(1500)
                    clicked = await page.evaluate(
                        """
                        () => {
                            const items = document.querySelectorAll('button, a, li, .dropdown-item');
                            for (const item of items) {
                                const t = (item.textContent || '').toLowerCase().trim();
                                if (t.includes('logout') || t.includes('sign out')) {
                                    item.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                        """
                    )
                    if clicked:
                        await page.wait_for_timeout(1000)
                        return
            except Exception:
                continue
    except Exception:
        pass


async def apply_ipo(request: ApplyIPORequest) -> AutomationResult:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await _create_page(browser)
        user_name = ''

        try:
            # 1. Login
            await page.goto('https://meroshare.cdsc.com.np/#/login', wait_until='domcontentloaded')
            if await _detect_captcha(page):
                raise CaptchaRequiredError('CAPTCHA detected on login page. Manual intervention required.')

            try:
                await _select_dp(page, request.dp_id)
            except Exception:
                await page.keyboard.press('Enter')

            await page.wait_for_selector('#username', state='visible', timeout=15000)
            await page.click('#username')
            await page.type('#username', request.username, delay=50)
            await page.click('#password')
            await page.type('#password', request.password, delay=50)

            await _click_button_by_text(page, 'Login')

            try:
                await page.wait_for_function(
                    """
                    () => window.location.href.includes('/dashboard') ||
                    document.querySelector('.toast-error') !== null ||
                    (document.body.textContent || '').includes('Attempts remaining')
                    """,
                    timeout=30000,
                )
            except Exception:
                pass

            if '/dashboard' not in page.url:
                error_msg = await page.evaluate(
                    """
                    () => {
                        const toast = document.querySelector('.toast-error, .toast-message');
                        if (toast && toast.textContent) return toast.textContent.trim();
                        if ((document.body.textContent || '').includes('Attempts remaining')) return 'Invalid credentials.';
                        return null;
                    }
                    """
                )
                raise AutomationFailedError(error_msg or 'Login failed or timed out. Check credentials.')

            user_name = await _get_username(page)

            # 2. Navigate to My ASBA
            await page.goto('https://meroshare.cdsc.com.np/#/asba', wait_until='networkidle')

            # 3. Ensure "Apply for Issue" tab is selected
            tab_clicked = await page.evaluate(
                """
                () => {
                    const links = Array.from(document.querySelectorAll('.nav-link'));
                    for (const link of links) {
                        if ((link.textContent || '').includes('Apply for Issue')) {
                            if (!link.classList.contains('active')) {
                                link.click();
                                return true;
                            }
                            return false;
                        }
                    }
                    return false;
                }
                """
            )

            if tab_clicked:
                await page.wait_for_selector('.asba-table, .company-list, app-no-records-found', timeout=15000)
                await page.wait_for_timeout(2000)
            else:
                await page.wait_for_selector('.asba-table, .company-list, app-no-records-found', timeout=10000)
                await page.wait_for_timeout(1000)

            if await _detect_captcha(page):
                raise CaptchaRequiredError('CAPTCHA detected on ASBA page. Manual intervention required.')

            # 4. Check for empty list
            is_empty = await page.evaluate(
                """
                () => {
                    const noRecords = !!document.querySelector('app-no-records-found, .fallback-view');
                    const hasCards = document.querySelectorAll('.company-list').length > 0;
                    const hasRows = document.querySelectorAll('.asba-table tbody tr').length > 0;
                    return noRecords || (!hasCards && !hasRows);
                }
                """
            )

            if is_empty:
                raise AutomationFailedError('No active IPOs found (Mero Share says: No Record(s) Found).')

            # 5. Find IPO by company_share_id
            target_id = request.ipo_details.company_share_id
            discovery = await page.evaluate(
                """
                (targetId) => {
                    const discovered = [];
                    let status = 'NOT_FOUND';
                    const normalize = (val) => (val || '').toString().toLowerCase().replace(/\\s+/g, '').trim();
                    const normalizeName = (name) => {
                        return (name || '').toLowerCase()
                            .replace(/\\b(limited|ltd|public|private|pvt|co|company|inc)\\b/g, '')
                            .replace(/[().,-]/g, '')
                            .replace(/\\s+/g, ' ')
                            .trim();
                    };
                    const target = normalize(targetId);
                    const targetName = normalizeName(targetId);

                    const matchesTarget = (el) => {
                        if (!el) return false;
                        const text = normalize(el.textContent || '');
                        if (text.includes(target)) return true;
                        if (el.getAttributeNames) {
                            for (const name of el.getAttributeNames()) {
                                const val = el.getAttribute(name);
                                if (val && normalize(val).includes(target)) return true;
                            }
                        }
                        return false;
                    };

                    const matchesName = (candidate) => {
                        if (!candidate) return false;
                        const candNorm = normalizeName(candidate);
                        return candNorm.includes(targetName) || targetName.includes(candNorm);
                    };

                    const clickApplyOrEdit = (root) => {
                        const buttons = Array.from(root.querySelectorAll('button'));
                        const applyBtn = buttons.find(b => (b.textContent || '').toLowerCase().includes('apply'));
                        const editBtn = buttons.find(b => (b.textContent || '').toLowerCase().includes('edit'));
                        if (applyBtn) { applyBtn.click(); return 'APPLY'; }
                        if (editBtn) { editBtn.click(); return 'EDIT'; }
                        return null;
                    };

                    const cards = Array.from(document.querySelectorAll('.company-list, .asba-card, .card'));
                    for (const card of cards) {
                        const nameEl = card.querySelector('span[tooltip="Company Name"], .company-name, .card-title');
                        const name = (nameEl?.textContent || '').trim();
                        if (name) discovered.push(name);
                        if (matchesTarget(card) || matchesName(name)) {
                            const res = clickApplyOrEdit(card);
                            if (res) { status = res; break; }
                        }
                    }

                    if (status === 'NOT_FOUND') {
                        const rows = Array.from(document.querySelectorAll('.asba-table tbody tr'));
                        for (const row of rows) {
                            const rowText = (row.textContent || '').trim();
                            const rowName = rowText.split('\n')[0].trim();
                            if (rowName) discovered.push(rowName);
                            if (matchesTarget(row) || matchesName(rowName)) {
                                const res = clickApplyOrEdit(row);
                                if (res) { status = res; break; }
                            }
                        }
                    }

                    return { status, discovered };
                }
                """,
                target_id,
            )

            if discovery['status'] == 'NOT_FOUND':
                raise AutomationFailedError('IPO not found for the provided company_share_id.')

            if discovery['status'] == 'EDIT':
                try:
                    await page.wait_for_selector('#appliedKitta', timeout=10000)
                    await page.wait_for_function(
                        """
                        () => {
                            const input = document.querySelector('#appliedKitta');
                            return input && input.value && input.value.length > 0;
                        }
                        """,
                        timeout=5000,
                    )
                    applied_qty = await page.evaluate(
                        """
                        () => {
                            const input = document.querySelector('#appliedKitta');
                            return input ? input.value : '';
                        }
                        """
                    )
                    raise AutomationFailedError(f'Already applied for {applied_qty} kitta.')
                except Exception:
                    raise AutomationFailedError('Already applied (could not read applied quantity).')

            # 6. Fill Application Details (Step 1)
            await page.wait_for_selector('#selectBank', timeout=15000)
            await page.wait_for_function(
                """
                () => {
                    const select = document.querySelector('#selectBank');
                    return select && select.options && select.options.length > 1;
                }
                """,
                timeout=10000,
            )

            bank_value = await page.evaluate(
                """
                (bankName) => {
                    const select = document.querySelector('#selectBank');
                    if (!select) return null;
                    const normalize = (val) => (val || '').toLowerCase().trim();
                    const target = normalize(bankName);
                    const opts = Array.from(select.options);
                    const exact = opts.find(o => normalize(o.textContent) === target);
                    if (exact) return exact.value;
                    const partial = opts.find(o => normalize(o.textContent).includes(target) || target.includes(normalize(o.textContent)));
                    if (partial) return partial.value;
                    const fallback = opts.find(o => o.value && !/choose/i.test(o.textContent || ''));
                    return fallback ? fallback.value : null;
                }
                """,
                request.ipo_details.bank,
            )

            if not bank_value:
                raise AutomationFailedError('Bank selection failed. Please verify bank name.')

            await page.select_option('#selectBank', bank_value)
            await page.wait_for_timeout(1500)

            # Select Account Number (if present)
            try:
                await page.wait_for_selector('#accountNumber', timeout=10000)
                account_value = await page.evaluate(
                    """
                    () => {
                        const select = document.querySelector('#accountNumber');
                        if (!select) return null;
                        const opts = Array.from(select.options);
                        const fallback = opts.find(o => o.value && !/choose/i.test(o.textContent || ''));
                        return fallback ? fallback.value : null;
                    }
                    """
                )
                if account_value:
                    await page.select_option('#accountNumber', account_value)
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Fill Kitta and CRN
            await page.click('#appliedKitta')
            await page.type('#appliedKitta', str(request.ipo_details.units), delay=50)
            await page.type('#crnNumber', request.crn, delay=50)

            # Agree to terms
            try:
                await page.click('#disclaimer')
            except Exception:
                pass

            await _click_button_by_text(page, 'Proceed')

            # 7. Enter PIN (Step 2)
            await page.wait_for_selector('#transactionPIN', timeout=15000)
            if await _detect_captcha(page):
                raise CaptchaRequiredError('CAPTCHA detected before PIN submission. Manual intervention required.')

            await page.type('#transactionPIN', request.pin, delay=100)
            await _click_button_by_text(page, 'Apply')

            # 8. Wait for success or error message
            try:
                await page.wait_for_function(
                    """
                    () => document.querySelector('.toast-success') !== null ||
                    document.querySelector('.toast-error') !== null
                    """,
                    timeout=30000,
                )
            except Exception:
                raise AutomationFailedError('Application submitted but success message not confirmed. Please check your Application Report.')

            success_msg = await page.evaluate(
                """
                () => {
                    const toast = document.querySelector('.toast-success');
                    return toast && toast.textContent ? toast.textContent.trim() : null;
                }
                """
            )
            error_msg = await page.evaluate(
                """
                () => {
                    const toast = document.querySelector('.toast-error');
                    return toast && toast.textContent ? toast.textContent.trim() : null;
                }
                """
            )

            if success_msg:
                application_id = None
                match = re.search(r'(\d{4,})', success_msg)
                if match:
                    application_id = match.group(1)
                return AutomationResult(True, success_msg, application_id=application_id, user_name=user_name)

            raise AutomationFailedError(error_msg or 'Application failed at the final step.')

        finally:
            await _logout(page)
            await browser.close()


async def check_allotment(dp_id: str, username: str, password: str, ipo_name: str) -> CheckAllotmentResult:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await _create_page(browser)

        try:
            await _login(page, dp_id, username, password)
            user_name = await _get_username(page)

            await page.goto('https://meroshare.cdsc.com.np/#/asba', wait_until='networkidle')

            report_tab_found = False
            try:
                await page.wait_for_function(
                    """
                    () => {
                        const elements = Array.from(document.querySelectorAll('.nav-link, .nav-item span, a span'));
                        return elements.some(el => (el.textContent || '').includes('Application Report'));
                    }
                    """,
                    timeout=20000,
                )

                report_tab_found = await page.evaluate(
                    """
                    () => {
                        const links = Array.from(document.querySelectorAll('.nav-link, .nav-item a'));
                        for (const link of links) {
                            const text = (link.textContent || '').trim();
                            if (text.includes('Application Report')) {
                                if (link.classList.contains('active')) return true;
                                link.click();
                                return true;
                            }
                        }
                        return false;
                    }
                    """
                )

                if report_tab_found:
                    await page.wait_for_timeout(4000)
            except Exception:
                report_tab_found = False

            if not report_tab_found:
                raise AutomationFailedError("Could not find 'Application Report' tab.")

            found_report = False
            try:
                await page.wait_for_selector('.asba-table, .company-list', timeout=20000)
                found_report = await page.evaluate(
                    """
                    (targetIpo) => {
                        const normalize = (name) => {
                            return (name || '').toLowerCase()
                                .replace(/\\b(limited|ltd|public|private|pvt|co|company|inc)\\b/g, '')
                                .replace(/[().,-]/g, '')
                                .replace(/\\s+/g, ' ')
                                .trim();
                        };
                        const targetNormalized = normalize(targetIpo);
                        const isMatch = (candidate) => {
                            if (!candidate) return false;
                            const candNorm = normalize(candidate);
                            return candNorm.includes(targetNormalized) || targetNormalized.includes(candNorm);
                        };

                        const cards = Array.from(document.querySelectorAll('.company-list'));
                        if (cards.length > 0) {
                            for (const card of cards) {
                                const nameEl = card.querySelector('.company-name span[tooltip=\"Company Name\"], .company-name');
                                const cardText = (nameEl?.textContent || '').trim();

                                if (isMatch(cardText)) {
                                    const buttons = Array.from(card.querySelectorAll('.action-buttons button'));
                                    const reportBtn = buttons.find(btn => (btn.textContent || '').toLowerCase().includes('report')) ||
                                        card.querySelector('.btn-issue');
                                    if (reportBtn) {
                                        reportBtn.click();
                                        return true;
                                    }
                                }
                            }
                        }

                        const rows = Array.from(document.querySelectorAll('.asba-table tbody tr'));
                        for (const row of rows) {
                            const rowText = (row.textContent || '').trim();
                            const companyName = rowText.split('\\n')[0].trim();
                            if (isMatch(companyName)) {
                                const reportBtn = row.querySelector('.btn-report, .ca-report, .ca.report, i.mdi-file-document') ||
                                    Array.from(row.querySelectorAll('button')).find(btn => btn.innerHTML.includes('mdi-file-document'));
                                if (reportBtn) {
                                    reportBtn.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    }
                    """,
                    ipo_name,
                )
            except Exception:
                found_report = False

            if not found_report:
                raise AutomationFailedError(f'Application report for \"{ipo_name}\" not found in your account.')

            await page.wait_for_selector('.asba-report-detail, .modal-content, .card-body, .row', timeout=15000)
            await page.wait_for_timeout(3000)

            report_data = await page.evaluate(
                """
                () => {
                    const data = {};
                    const formGroups = Array.from(document.querySelectorAll('.form-group'));
                    formGroups.forEach(group => {
                        const labelEl = group.querySelector('label');
                        const labelText = (labelEl?.textContent || '').trim();
                        if (labelText) {
                            const valueEl = group.querySelector('.form-value span') || group.querySelector('.input-group label');
                            const valueText = (valueEl?.textContent || '').trim();
                            if (valueText) {
                                data[labelText] = valueText;
                            }
                        }
                    });

                    const statusValue = data['Status'] || data['Allotment Status'] || 'Unknown';
                    const lowerStatus = statusValue.toLowerCase();
                    const isAllotted = lowerStatus.includes('allot') && !lowerStatus.includes('not');
                    const isVerified = lowerStatus === 'verified';
                    const isNotAllotted = lowerStatus.includes('not allotted') || lowerStatus.includes('not alloted') || lowerStatus.includes('unallotted');

                    let finalStatus = statusValue;
                    if (isVerified) {
                        finalStatus = 'Application Verified (Result Pending)';
                    } else if (isNotAllotted) {
                        finalStatus = 'Not Allotted';
                    }

                    const allottedQuantity = data['Allotted Quantity'] || (isAllotted ? (data['Applied Quantity'] || '0') : '0');

                    return {
                        status: finalStatus,
                        isAllotted,
                        allottedQuantity,
                        allDetails: data
                    };
                }
                """
            )

            return CheckAllotmentResult(
                status=report_data['status'],
                is_allotted=bool(report_data['isAllotted']),
                allotted_quantity=str(report_data['allottedQuantity']),
                details=report_data['allDetails'],
                user_name=user_name,
            )
        finally:
            await _logout(page)
            await browser.close()


async def get_portfolio(dp_id: str, username: str, password: str) -> PortfolioResult:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await _create_page(browser)

        try:
            await _login(page, dp_id, username, password)
            user_name = await _get_username(page)

            await page.goto('https://meroshare.cdsc.com.np/#/portfolio', wait_until='networkidle')

            try:
                await page.wait_for_selector('table', timeout=20000)
            except Exception:
                raise AutomationFailedError('Portfolio table not found or timed out.')

            is_table_empty = await page.evaluate(
                """
                () => {
                    const table = document.querySelector('table tbody');
                    return !table || (table.textContent || '').includes('No Record(s) Found');
                }
                """
            )

            if is_table_empty:
                return PortfolioResult(portfolio=[], message='No holdings found in your Mero Share portfolio.', user_name=user_name)

            portfolio = await page.evaluate(
                """
                () => {
                    const rows = Array.from(document.querySelectorAll('table tbody tr'));
                    return rows.map(row => {
                        const cols = Array.from(row.querySelectorAll('td'));
                        if (cols.length < 5) return null;
                        const symbolText = (cols[1]?.textContent || '').trim();
                        const symbol = symbolText.split(' ')[0].toUpperCase();
                        const unitsStr = (cols[2]?.textContent || '').trim().replace(/,/g, '') || '0';
                        const units = parseFloat(unitsStr);
                        const ltpStr = (cols[3]?.textContent || '').trim().replace(/,/g, '') || '0';
                        const currentPrice = parseFloat(ltpStr);
                        return {
                            symbol,
                            units,
                            current_price: currentPrice,
                            buy_price: 0
                        };
                    }).filter(item => item && item.symbol !== 'TOTAL');
                }
                """
            )

            return PortfolioResult(portfolio=portfolio, user_name=user_name)
        finally:
            await _logout(page)
            await browser.close()


async def test_login(dp_id: str, username: str, password: str) -> TestLoginResult:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await _create_page(browser)

        try:
            await _login(page, dp_id, username, password)

            name = await _get_username(page)
            await _logout(page)

            return TestLoginResult(success=True, message=f'Login Successful! Welcome, {name}.', user_name=name)
        finally:
            await browser.close()
