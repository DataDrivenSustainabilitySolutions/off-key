/** Render the committed specimen sheets with the frontend's locked Playwright. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '../../../frontend/node_modules/@playwright/test/index.mjs';

const brandRoot = fileURLToPath(new URL('../', import.meta.url));
const sourceRoot = fileURLToPath(new URL('./', import.meta.url));
const output = path.join(sourceRoot, 'previews');
const sheets = [
  { page: 'index.html', name: 'comparison', brand: 'aberration', stems: ['stacked-wordmark', 'inline-wordmark'] },
];

async function validateSources() {
  const master = await readFile(path.join(brandRoot, 'logo.svg'), 'utf8');
  const mark = master.match(/<path\b[^>]*\bd="([^"]+)"/)[1];
  for (const stem of new Set(sheets.flatMap(sheet => sheet.stems))) {
    const black = await readFile(path.join(sourceRoot, `${stem}.svg`), 'utf8');
    const white = await readFile(path.join(sourceRoot, `${stem}-white.svg`), 'utf8');
    assert.equal(white, black.replace('fill="currentColor"', 'fill="#fff"'), `${stem}: white export`);
    assert.ok(black.includes(`d="${mark}"`), `${stem}: exact original mark`);
    assert.doesNotMatch(black, /<(?:text|image|use|script|mask)\b/, `${stem}: standalone vector outlines`);
  }
}

function previewServer() {
  return createServer(async (request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (pathname === '/favicon.ico') { response.writeHead(204).end(); return; }
    const target = path.resolve(brandRoot, `.${pathname}`);
    if (!target.startsWith(brandRoot)) { response.writeHead(403).end(); return; }
    try {
      const body = await readFile(target);
      const type = { '.svg': 'image/svg+xml', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png' }[path.extname(target)] ?? 'text/plain';
      response.writeHead(200, { 'content-type': type }).end(body);
    } catch { response.writeHead(404).end(); }
  });
}

async function loadSheet(page, url, sheet) {
  const response = await page.goto(url);
  assert.ok(response.ok(), `${sheet.name}: page loads`);
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())));
  await page.evaluate(() => document.fonts.ready);
  assert.equal(await page.locator('main').getAttribute('data-sheet'), sheet.brand);
  assert.equal(await page.locator('link[rel="stylesheet"]').getAttribute('href'), 'specimen.css');
  assert.equal(await page.locator('.sample img').count(), 4);
  assert.equal(await page.locator('.sample img').evaluateAll(images => images.every(image => image.alt && image.naturalWidth > 0)), true);
  assert.deepEqual(await page.locator('.sample img').evaluateAll(images => images.map(image => image.getAttribute('src'))), sheet.stems.flatMap(stem => [`${stem}.svg`, `${stem}-white.svg`]));
  assert.equal(await page.locator('.artboard').first().evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(250, 250, 247)');
  assert.equal(await page.locator('.artboard--reverse').first().evaluate(element => getComputedStyle(element).backgroundColor), 'rgb(22, 22, 22)');
}

async function renderSheet(browser, base, sheet) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (!response.ok()) errors.push(`${response.status()} ${response.url()}`); });
  const url = `${base}/experiments/${sheet.page}`;
  try {
    await loadSheet(page, url, sheet);
    await page.screenshot({ path: path.join(output, `${sheet.name}-desktop.png`), fullPage: true });
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${sheet.name}: overflow at ${width}`);
      for (const image of await page.locator('img').all()) {
        const box = await image.boundingBox();
        assert.ok(box.width > 0 && box.x >= 0 && box.x + box.width <= width + 0.01, `${sheet.name}: image within viewport`);
      }
      if (width === 390) await page.screenshot({ path: path.join(output, `${sheet.name}-mobile.png`), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 1000 });
    await loadSheet(page, url, sheet);
    await page.keyboard.press('Tab');
    assert.equal(await page.locator('a:focus-visible').count(), 1, `${sheet.name}: visible keyboard focus`);
    const downloads = page.getByRole('link', { name: 'Download SVG', exact: true });
    const filenames = sheet.stems.flatMap(stem => [`${stem}.svg`, `${stem}-white.svg`]);
    for (const [index, filename] of filenames.entries()) {
      const [download] = await Promise.all([
        page.waitForEvent('download', { timeout: 15000 }),
        downloads.nth(index).click(),
      ]);
      assert.equal(download.suggestedFilename(), filename);
    }
    assert.deepEqual(errors, [], `${sheet.name}: browser errors`);
    console.log(`${sheet.brand}: rendered desktop/mobile; SVG sources, light/dark panels, responsive layout, keyboard focus and downloads verified.`);
  } finally { await page.close(); }
}

await validateSources();
await mkdir(output, { recursive: true });
const server = previewServer();
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
let browser;
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const base = `http://127.0.0.1:${server.address().port}`;
  for (const sheet of sheets) await renderSheet(browser, base, sheet);
} finally {
  if (browser) await browser.close();
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
