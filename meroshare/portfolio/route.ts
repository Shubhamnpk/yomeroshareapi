import { NextResponse } from "next/server";
import { getMeroShareBrowser } from "../_lib/browser";

export async function POST(req: Request) {
    let browser: any = null;
    try {
        const { credentials } = await req.json();

        if (!credentials || !credentials.dpId || !credentials.username || !credentials.password) {
            return NextResponse.json({ error: "Missing Mero Share credentials" }, { status: 400 });
        }

        try {
            browser = await getMeroShareBrowser();
            const page = await browser.newPage();

            // 1. Login
            await page.goto('https://meroshare.cdsc.com.np/#/login', { waitUntil: 'networkidle2' });

            // Search and select DP
            await page.waitForSelector('.select2-selection', { timeout: 15000 });
            await page.click('.select2-selection');
            await page.type('.select2-search__field', credentials.dpId);
            await page.keyboard.press('Enter');

            await page.type('#username', credentials.username);
            await page.type('#password', credentials.password);

            await page.click('button[type="submit"]');

            // Wait for dashboard or error
            await page.waitForFunction(() => {
                return window.location.href.includes('/dashboard') ||
                    document.querySelector('.toast-error') !== null;
            }, { timeout: 30000 });

            if (!page.url().includes('/dashboard')) {
                const errorMsg = await page.evaluate(() => document.querySelector('.toast-error')?.textContent?.trim());
                await browser.close();
                return NextResponse.json({ error: errorMsg || "Login failed" }, { status: 401 });
            }

            // 2. Navigate to My Portfolio
            await page.goto('https://meroshare.cdsc.com.np/#/portfolio', { waitUntil: 'networkidle2' });

            // 3. Wait for Portfolio Table
            try {
                await page.waitForSelector('table', { timeout: 20000 });
            } catch (err) {
                await browser.close();
                return NextResponse.json({ error: "Portfolio table not found or timed out." }, { status: 504 });
            }

            // Check if there's a portfolio (or it's empty)
            const isTableEmpty = await page.evaluate(() => {
                const table = document.querySelector('table tbody');
                return !table || table.textContent?.includes('No Record(s) Found');
            });

            if (isTableEmpty) {
                await browser.close();
                return NextResponse.json({ portfolio: [], message: "No holdings found in your Mero Share portfolio." });
            }

            // 4. Scrape Portfolio Data
            const portfolio = await page.evaluate(() => {
                const rows = Array.from(document.querySelectorAll('table tbody tr'));
                return rows.map(row => {
                    const cols = Array.from(row.querySelectorAll('td'));
                    if (cols.length < 5) return null;

                    // Mero Share Portfolio Table Structure (usually):
                    // 1. S.N.
                    // 2. Scrip
                    // 3. Current Balance
                    // 4. Previous Close
                    // 5. Value

                    const symbolText = cols[1]?.textContent?.trim() || "";
                    // Sometimes it's like "SYMBOL (COMPANY NAME)"
                    const symbol = symbolText.split(' ')[0].toUpperCase();

                    const unitsStr = cols[2]?.textContent?.trim()?.replace(/,/g, '') || "0";
                    const units = parseFloat(unitsStr);

                    const ltpStr = cols[3]?.textContent?.trim()?.replace(/,/g, '') || "0";
                    const currentPrice = parseFloat(ltpStr);

                    return {
                        symbol,
                        units,
                        currentPrice,
                        buyPrice: 0, // Mero Share portfolio doesn't show average cost (Purchase Source does)
                    };
                }).filter(item => item !== null && item.symbol !== "TOTAL");
            });

            await browser.close();
            return NextResponse.json({ success: true, portfolio });

        } catch (innerError: any) {
            console.error("Puppeteer Portfolio Error:", innerError);
            if (browser) await browser.close();
            return NextResponse.json({ error: innerError.message || "An error occurred during portfolio sync." }, { status: 500 });
        }

    } catch (error: any) {
        return NextResponse.json({ error: "Invalid request data" }, { status: 400 });
    }
}
