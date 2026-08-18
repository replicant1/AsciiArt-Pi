#!/usr/bin/env node
/*
 * Screenshot one region of the display selection guide, headlessly.
 *
 * The guide is a visual document that is easy to edit blind and get wrong -
 * a colspan that gives no clue how far it reaches, a custom property set on
 * the wrong element so a panel renders black on black. Both of those shipped
 * before anyone looked at the output. This renders a chosen element so the
 * layout can be checked before publishing, in either theme.
 *
 *   node tools/render_region.js docs/guides/display-selection-guide.html out.png ".table-wrap" 1 dark
 *
 * Arguments: source, output, CSS selector, index into the matches, theme
 * ("light" or "dark"; omit to follow the OS preference).
 *
 * Needs puppeteer. If it is not installed directly, the copy bundled with
 * @mermaid-js/mermaid-cli is used, since that is already a dependency for
 * validating the README diagrams.
 */

const fs = require('fs');

function loadPuppeteer() {
  const candidates = [
    'puppeteer',
    '/opt/homebrew/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer',
    '/usr/local/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer',
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* try the next */ }
  }
  console.error('puppeteer not found. npm i -g puppeteer, or install mermaid-cli.');
  process.exit(1);
}

(async () => {
  const [src, out, selector, nth, theme] = process.argv.slice(2);
  if (!src || !out || !selector) {
    console.error('usage: render_region.js <src.html> <out.png> <selector> [index] [light|dark]');
    process.exit(2);
  }

  // The guide is a fragment: the publisher wraps it in a document skeleton with
  // a minimal reset, so reproduce that here or the layout will not match.
  const attr = theme ? ` data-theme="${theme}"` : '';
  const wrapped = `<!doctype html><html${attr}><head><meta charset="utf-8">
    <style>*{box-sizing:border-box;margin:0;padding:0}</style></head>
    <body>${fs.readFileSync(src, 'utf8')}</body></html>`;
  const tmp = out + '.html';
  fs.writeFileSync(tmp, wrapped);

  const browser = await loadPuppeteer().launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1100, height: 900, deviceScaleFactor: 2 });
    await page.goto('file://' + tmp, { waitUntil: 'networkidle0' });
    const matches = await page.$$(selector);
    const el = matches[Number(nth || 0)];
    if (!el) {
      console.error(`selector "${selector}" matched ${matches.length} element(s); index ${nth || 0} is out of range`);
      process.exit(1);
    }
    await el.screenshot({ path: out });
    console.log(`wrote ${out}`);
  } finally {
    await browser.close();
    fs.unlinkSync(tmp);
  }
})();
