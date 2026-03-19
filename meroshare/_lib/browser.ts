import puppeteer from "puppeteer-core"
import chromium from "@sparticuz/chromium"

export async function getMeroShareBrowser(options?: { showBrowser?: boolean }) {
  const isVisibleDebug = process.env.MEROSHARE_VISIBLE_BROWSER === "1" || Boolean(options?.showBrowser)

  if (process.env.NODE_ENV === "production" || process.env.VERCEL) {
    return await puppeteer.launch({
      args: chromium.args,
      defaultViewport: (chromium as any).defaultViewport,
      executablePath: await chromium.executablePath(),
      headless: (chromium as any).headless,
    })
  }

  const executablePaths = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    process.env.CHROME_PATH,
  ].filter(Boolean) as string[]

  let executablePath = ""
  for (const path of executablePaths) {
    if (require("fs").existsSync(path)) {
      executablePath = path
      break
    }
  }

  return await puppeteer.launch({
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
    headless: !isVisibleDebug,
    executablePath: executablePath || undefined,
  })
}
