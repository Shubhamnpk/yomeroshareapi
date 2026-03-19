import { NextResponse } from 'next/server';
import { getMeroShareBrowser } from "../_lib/browser";

export async function POST(req: Request) {
    let browser: any = null;
    try {
        const { credentials, options } = await req.json();

        if (!credentials || !credentials.dpId || !credentials.username || !credentials.password) {
            return NextResponse.json({ error: "Missing Mero Share credentials" }, { status: 400 });
        }

        try {
            browser = await getMeroShareBrowser({ showBrowser: Boolean(options?.showBrowser) });
            const page = await browser.newPage();

            // 1. Attempt Login
            await page.goto('https://meroshare.cdsc.com.np/#/login', { waitUntil: 'networkidle2' });

            // Search and select DP
            await page.waitForSelector('.select2-selection', { timeout: 10000 });
            await page.click('.select2-selection');
            await page.type('.select2-search__field', credentials.dpId);
            await page.keyboard.press('Enter');

            await page.type('#username', credentials.username);
            await page.type('#password', credentials.password);

            await page.click('button[type="submit"]');

            // Wait to see if login succeeds or fails
            try {
                // Wait for dashboard indicators with a longer timeout
                await page.waitForFunction(() => {
                    return window.location.href.includes('/dashboard') ||
                        document.querySelector('.toast-error') !== null ||
                        document.querySelector('.error-message') !== null ||
                        document.querySelector('.user-name') !== null;
                }, { timeout: 30000 });

                const currentUrl = page.url();
                const hasUserName = await page.evaluate(() => document.querySelector('.user-name') !== null);

                if (currentUrl.includes('/dashboard') || hasUserName) {
                    // Success!
                    const name = await page.evaluate(() => document.querySelector('.user-name')?.textContent?.trim() || "User");

                    await browser.close();
                    return NextResponse.json({
                        success: true,
                        message: `Login Successful! Welcome, ${name}.`,
                    });
                } else {
                    // Check for error toast
                    const errorMsg = await page.evaluate(() => {
                        const alert = document.querySelector('.toast-error') || document.querySelector('.error-message');
                        return alert?.textContent?.trim();
                    });

                    await browser.close();
                    return NextResponse.json({
                        success: false,
                        error: errorMsg || "Login failed. Check your DP ID, username, or password.",
                    }, { status: 401 });
                }
            } catch (navError) {
                await browser.close();
                return NextResponse.json({
                    success: false,
                    error: "Mero Share is too slow to respond (30s timeout). Please try again later.",
                }, { status: 408 });
            }

        } catch (innerError: any) {
            console.error("Browser Error:", innerError);
            if (browser) await browser.close();
            return NextResponse.json({
                error: `Automation Error: ${innerError.message}. Make sure Chrome is installed locally.`
            }, { status: 500 });
        }

    } catch (error: any) {
        console.error("Request Parsing Error:", error);
        return NextResponse.json({ error: `Request Error: ${error.message}` }, { status: 400 });
    }
}
