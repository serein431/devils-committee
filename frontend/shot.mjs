import { chromium } from 'playwright'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
await page.goto('http://localhost:4173')
await page.waitForTimeout(2000)
await page.screenshot({ path: 'preview.png', fullPage: true })
await browser.close()
console.log('done')
