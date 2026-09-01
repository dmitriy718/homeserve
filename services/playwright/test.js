const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto('https://example.com', { waitUntil: 'domcontentloaded', timeout: 30000 });
    const title = await page.title();
    console.log(JSON.stringify({ ok: title === 'Example Domain', title, url: page.url() }));
    if (title !== 'Example Domain') process.exit(1);
  } finally {
    await browser.close();
  }
})();

