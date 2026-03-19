import { NextResponse } from 'next/server';
import puppeteer from 'puppeteer-core';
import chromium from '@sparticuz/chromium';

// Define extraction logic outside the handler for clarity
async function getBrowser(showBrowser = false) {
    const isVisibleDebug = process.env.MEROSHARE_VISIBLE_BROWSER === '1' || showBrowser;
    if (process.env.NODE_ENV === 'production' || process.env.VERCEL) {
        return await puppeteer.launch({
            args: chromium.args,
            defaultViewport: (chromium as any).defaultViewport,
            executablePath: await chromium.executablePath(),
            headless: (chromium as any).headless,
        });
    } else {
        // Common paths for Chrome/Edge on Windows
        const executablePaths = [
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            process.env.CHROME_PATH
        ].filter(Boolean) as string[];

        let executablePath = '';
        for (const path of executablePaths) {
            if (require('fs').existsSync(path)) {
                executablePath = path;
                break;
            }
        }

        return await puppeteer.launch({
            args: ['--no-sandbox', '--disable-setuid-sandbox'],
            headless: !isVisibleDebug,
            executablePath: executablePath || undefined,
        });
    }
}

export async function POST(req: Request) {
    let browser: any = null;
    try {
        const { credentials, ipoName, kitta = 10, options } = await req.json();
        const showBrowser = Boolean(options?.showBrowser);

        if (!credentials || !credentials.dpId || !credentials.username || !credentials.password) {
            return NextResponse.json({ error: "Missing Mero Share credentials" }, { status: 400 });
        }

        try {
            browser = await getBrowser(showBrowser);
            const page = await browser.newPage();

            // 1. Login
            await page.goto('https://meroshare.cdsc.com.np/#/login', { waitUntil: 'domcontentloaded' });

            // Search and select DP (Robust Method)
            try {
                // Wait for the dropdown trigger
                await page.waitForSelector('.select2-selection', { timeout: 20000 });
                await page.click('.select2-selection');

                // Type DP ID and wait for results
                await page.waitForSelector('.select2-search__field', { visible: true });
                await page.type('.select2-search__field', credentials.dpId, { delay: 100 });

                // Wait for the specific result to appear in the dropdown
                await page.waitForSelector('.select2-results__option', { visible: true, timeout: 10000 });
                await page.keyboard.press('Enter');
            } catch (dpError) {
                console.error("DP Selection failed:", dpError);
                // Fallback: try pressing Enter blindly if selector wait failed
                await page.keyboard.press('Enter');
            }

            // Fill Username & Password with delay to ensure Angular binding
            await page.waitForSelector('#username', { visible: true });
            await page.type('#username', credentials.username, { delay: 50 });
            await page.type('#password', credentials.password, { delay: 50 });

            // Click Login
            const loginBtn = await page.$('button[type="submit"]');
            if (loginBtn) {
                await loginBtn.click();
            } else {
                await page.keyboard.press('Enter');
            }

            // Wait for dashboard or error
            try {
                await page.waitForFunction(() => {
                    const isDashboard = window.location.href.includes('/dashboard');
                    const hasError = document.querySelector('.toast-error') !== null;
                    const hasAuthError = document.body.textContent?.includes('Attempts remaining');
                    return isDashboard || hasError || hasAuthError;
                }, { timeout: 30000 });
            } catch (waitError) {
                // Timeout logic handled below
            }

            if (!page.url().includes('/dashboard')) {
                const errorMsg = await page.evaluate(() => {
                    const toast = document.querySelector('.toast-error, .toast-message');
                    return toast?.textContent?.trim() || document.body.textContent?.includes('Attempts remaining') ? "Invalid Credentials" : null;
                });
                await browser.close();
                return NextResponse.json({ error: errorMsg || "Login failed or timed out. Check credentials." }, { status: 401 });
            }

            // 2. Navigate to My ASBA
            await page.goto('https://meroshare.cdsc.com.np/#/asba', { waitUntil: 'networkidle2' });

            // 3. Ensure "Apply for Issue" tab is selected and records are loaded
            try {
                // Fast parallel wait: either nav appears OR content loads
                await Promise.race([
                    page.waitForSelector('.nav-link', { timeout: 10000 }),
                    page.waitForSelector('.company-list, .asba-table', { timeout: 10000 })
                ]);

                // Click "Apply for Issue" tab if not already active
                const tabClicked = await page.evaluate(() => {
                    const links = Array.from(document.querySelectorAll('.nav-link'));
                    for (const link of links) {
                        if (link.textContent?.includes('Apply for Issue')) {
                            if (!link.classList.contains('active')) {
                                (link as HTMLElement).click();
                                return true; // We clicked, need to wait for reload
                            }
                            return false; // Already active, no wait needed
                        }
                    }
                    return false;
                });

                // Smart wait: Only wait if we clicked the tab, otherwise data is already there
                if (tabClicked) {
                    await page.waitForSelector('.asba-table, .company-list, app-no-records-found', { timeout: 15000 });
                    await new Promise(resolve => setTimeout(resolve, 2000)); // Reduced from 5s
                } else {
                    // Tab was already active, just verify content is present
                    await page.waitForSelector('.asba-table, .company-list, app-no-records-found', { timeout: 10000 });
                    await new Promise(resolve => setTimeout(resolve, 1000)); // Minimal wait
                }
            } catch (err) {
                await browser.close();
                return NextResponse.json({ error: "ASBA page failed to load correctly." }, { status: 504 });
            }

            // Enhanced check for "No Record(s) Found"
            const isTableEmpty = await page.evaluate(() => {
                const noRecords = !!document.querySelector('app-no-records-found, .fallback-view');
                const hasCards = document.querySelectorAll('.company-list').length > 0;
                const hasRows = document.querySelectorAll('.asba-table tbody tr').length > 0;

                return noRecords || (!hasCards && !hasRows);
            });

            if (isTableEmpty) {
                await browser.close();
                return NextResponse.json({
                    error: "No active IPOs found in your Mero Share list today. (Mero Share says: No Record(s) Found)"
                }, { status: 404 });
            }

            const discoveryResult = await page.evaluate((targetName: string) => {
                const discovered: string[] = [];
                let status = 'NOT_FOUND';

                // Helper: Normalize name for fuzzy matching
                // Removes common corporate suffixes and spaces to match 'Ltd' vs 'Limited'
                const normalize = (name: string) => {
                    return name.toLowerCase()
                        .replace(/\b(limited|ltd|public|private|pvt|co|company|inc)\b/g, '') // Remove suffixes
                        .replace(/[().,-]/g, '') // Remove punctuation
                        .replace(/\s+/g, ' ') // Collapse spaces
                        .trim();
                };

                const targetNormalized = normalize(targetName);

                // Helper: Check match (Exact OR Fuzzy)
                const isMatch = (candidate: string) => {
                    if (!candidate) return false;
                    const candNorm = normalize(candidate);
                    // Match if essential part is contained in either
                    return candNorm.includes(targetNormalized) || targetNormalized.includes(candNorm);
                };

                // Priority: Card Layout (.company-list)
                const cards = Array.from(document.querySelectorAll('.company-list'));
                for (const card of cards) {
                    const nameEl = card.querySelector('span[tooltip="Company Name"]') || card.querySelector('.company-name');
                    const cardText = nameEl?.textContent?.trim() || "";
                    if (cardText) discovered.push(cardText);

                    if (isMatch(cardText)) {
                        const buttons = Array.from(card.querySelectorAll('.action-buttons button, .btn-issue'));

                        // Check for Apply button first
                        const applyBtn = buttons.find(btn => btn.textContent?.toLowerCase().includes('apply'));
                        if (applyBtn) {
                            (applyBtn as HTMLElement).click();
                            status = 'APPLY';
                            break;
                        }

                        // Check for Edit button (Already Applied)
                        const editBtn = buttons.find(btn => btn.textContent?.toLowerCase().includes('edit'));
                        if (editBtn) {
                            (editBtn as HTMLElement).click();
                            status = 'EDIT';
                            break;
                        }
                    }
                }

                // Fallback: Table Layout (.asba-table)
                if (status === 'NOT_FOUND') {
                    const rows = Array.from(document.querySelectorAll('.asba-table tbody tr'));
                    for (const row of rows) {
                        const rowText = row.textContent?.trim() || "";
                        const companyName = rowText.split('\n')[0].trim();
                        if (companyName) discovered.push(companyName);

                        if (isMatch(companyName)) {
                            const buttons = Array.from(row.querySelectorAll('.btn-apply, .btn-issue, button'));

                            const applyBtn = buttons.find(btn => btn.textContent?.toLowerCase().includes('apply'));
                            if (applyBtn) {
                                (applyBtn as HTMLElement).click();
                                status = 'APPLY';
                                break;
                            }

                            const editBtn = buttons.find(btn => btn.textContent?.toLowerCase().includes('edit'));
                            if (editBtn) {
                                (editBtn as HTMLElement).click();
                                status = 'EDIT';
                                break;
                            }
                        }
                    }
                }

                return { status, discovered };
            }, ipoName);

            if (discoveryResult.status === 'NOT_FOUND') {
                await browser.close();
                return NextResponse.json({
                    error: `IPO '${ipoName}' not found. Please check the name.`,
                    details: {
                        searchedFor: ipoName,
                        availableIPOs: discoveryResult.discovered
                    }
                }, { status: 404 });
            }

            // Handle "Already Applied" case (EDIT)
            if (discoveryResult.status === 'EDIT') {
                try {
                    await page.waitForSelector('#appliedKitta', { timeout: 15000 });

                    // Wait for Angular to bind the value (ensure it's not empty)
                    await page.waitForFunction(() => {
                        const input = document.querySelector('#appliedKitta') as HTMLInputElement;
                        return input && input.value && input.value.length > 0;
                    }, { timeout: 5000 });

                    const appliedQty = await page.evaluate(() => {
                        return (document.querySelector('#appliedKitta') as HTMLInputElement).value;
                    });

                    await browser.close();
                    return NextResponse.json({
                        success: true,
                        message: `Already applied for ${appliedQty} kitta.`,
                        alreadyApplied: true,
                        quantity: appliedQty
                    });
                } catch (err) {
                    await browser.close();
                    // If we timeout waiting for value, it might be 0 or failed to load
                    return NextResponse.json({ error: "Found existing application but could not read applied quantity." }, { status: 500 });
                }
            }

            // 4. Fill Application Details (Step 1)
            await page.waitForSelector('#selectBank', { timeout: 15000 });

            // SMART DETECT: Get Minimum Quantity from the page
            const minKitta = await page.evaluate(() => {
                const groups = Array.from(document.querySelectorAll('.form-group'));
                for (const group of groups) {
                    const label = group.querySelector('label')?.textContent?.trim() || "";
                    if (label.includes('Minimum Quantity')) {
                        const val = group.querySelector('.form-value span')?.textContent?.trim();
                        if (val) return parseInt(val);
                    }
                }
                return 10; // Fallback
            });

            // Decide which kitta to apply
            const kittaToApply = (kitta && kitta > 0) ? kitta : minKitta;

            // 1. Select Bank (skip placeholder, choose first real bank)
            await page.waitForFunction(() => (document.querySelector('#selectBank') as HTMLSelectElement).options.length > 1, { timeout: 10000 });
            const bankValue = await page.evaluate(() => {
                const select = document.querySelector('#selectBank') as HTMLSelectElement;
                // Find first option with actual value (skip placeholders)
                for (let i = 0; i < select.options.length; i++) {
                    const val = select.options[i].value;
                    if (val && val.trim() !== '' && !val.toLowerCase().includes('choose')) {
                        return val;
                    }
                }
                // Fallback to index 1 if no valid option found
                return select.options[1]?.value || select.options[0]?.value;
            });
            await page.select('#selectBank', bankValue);

            // Small wait for Angular to process bank selection and load accounts
            await new Promise(resolve => setTimeout(resolve, 1500));

            // 2. Select Account Number (appears after bank selection)
            try {
                await page.waitForSelector('#accountNumber', { timeout: 10000 });
                await page.waitForFunction(() => (document.querySelector('#accountNumber') as HTMLSelectElement).options.length > 0, { timeout: 10000 });
                const accountValue = await page.evaluate(() => {
                    const select = document.querySelector('#accountNumber') as HTMLSelectElement;
                    // Find first option with actual value
                    for (let i = 0; i < select.options.length; i++) {
                        const val = select.options[i].value;
                        if (val && val.trim() !== '' && !val.toLowerCase().includes('choose')) {
                            return val;
                        }
                    }
                    // Fallback to first option
                    return select.options[0]?.value || null;
                });
                if (accountValue) {
                    await page.select('#accountNumber', accountValue);
                    await new Promise(resolve => setTimeout(resolve, 1000));
                }
            } catch (err) {
                console.log("Account number selection skipped or not required");
            }

            // 3. Fill Kitta and CRN
            await page.click('#appliedKitta'); // Focus first
            await page.type('#appliedKitta', kittaToApply.toString(), { delay: 50 });
            await page.type('#crnNumber', credentials.crn, { delay: 50 });

            // Agree to terms
            await page.click('#disclaimer');

            // Click "Proceed" button
            // We search for a button containing the text "Proceed"
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
                const proceedBtn = buttons.find(btn => btn.textContent?.includes('Proceed'));
                if (proceedBtn) (proceedBtn as HTMLElement).click();
            });

            // 5. Enter PIN (Step 2)
            // Note the casing in HTML: transactionPIN
            await page.waitForSelector('#transactionPIN', { timeout: 15000 });
            await page.type('#transactionPIN', credentials.pin, { delay: 100 });

            // Click final "Apply" button
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button[type="submit"]'));
                const applyBtn = buttons.find(btn => btn.textContent?.includes('Apply'));
                if (applyBtn) (applyBtn as HTMLElement).click();
            });

            // 6. Wait for success message
            try {
                await page.waitForFunction(() => {
                    return document.querySelector('.toast-success') !== null ||
                        document.querySelector('.toast-error') !== null;
                }, { timeout: 30000 });

                const successMsg = await page.evaluate(() => document.querySelector('.toast-success')?.textContent?.trim());
                const errorMsg = await page.evaluate(() => document.querySelector('.toast-error')?.textContent?.trim());

                await browser.close();

                if (successMsg) {
                    return NextResponse.json({ success: true, message: successMsg });
                } else {
                    return NextResponse.json({ error: errorMsg || "Application failed at the final step." }, { status: 400 });
                }
            } catch (waitError) {
                await browser.close();
                return NextResponse.json({
                    error: "Application submitted but success message not confirmed. Please check your Mero Share 'Application Report'."
                }, { status: 408 });
            }

        } catch (innerError: any) {
            if (browser) await browser.close();
            return NextResponse.json({ error: innerError.message || "An error occurred during automation." }, { status: 500 });
        }

    } catch (error: any) {
        return NextResponse.json({ error: "Invalid request data" }, { status: 400 });
    }
}
