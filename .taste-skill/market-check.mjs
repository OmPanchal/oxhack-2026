import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { Browser, sleep } from '/Users/darius/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
import { probe, layout, app } from '/Users/darius/.agents/skills/design-taste-frontend/scripts/lib/probe.mjs';
import { judge, judgeLayout, judgeApp, APP_SKIP } from '/Users/darius/.agents/skills/design-taste-frontend/scripts/lib/rules.mjs';
mkdirSync('.taste-skill/market', { recursive: true });
const browser = await Browser.launch();
const results = [];
async function settle() { await sleep(100); }
async function value(page, selector, next) {
  await page.eval(({ selector, next }) => { const element = document.querySelector(selector); const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, String(next)); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); }, { selector, next });
  await settle();
}
try {
  for (const width of [1440, 768, 390]) {
    const page = await browser.newPage({ width, height: width === 390 ? 844 : width === 768 ? 1024 : 900 });
    await page.goto('http://127.0.0.1:3000', { settleMs: 300 });
    await page.eval(() => document.getElementById('tab-market').click());
    await settle(); await page.eval('document.fonts.ready');
    assert.equal(await page.eval(() => document.querySelectorAll('.regional-table tbody tr').length), 3);
    assert.ok(await page.eval(() => document.querySelector('.comparison-finding').textContent.includes('Frankfurt')));
    assert.ok(await page.eval(() => document.querySelector('.inspection-value').textContent.includes('$1.140')));
    assert.equal(await page.eval(() => document.querySelector('[aria-label="Forecast issue"]').options.length), 2);
    await page.screenshot({ path: `.taste-skill/market/${width}-default.jpg`, fullPage: true });
    const m = await page.eval(probe), l = await page.eval(layout), a = await page.eval(app);
    const findings = [...judge(m, { width, allow: ['app-title-size'] }), ...judgeLayout(l, { width, allow: ['app-title-size'] })].filter(f => !APP_SKIP.has(f.id));
    findings.push(...judgeApp(a, m, { width, allow: ['app-title-size'] }));
    await value(page, '[aria-label="Market units required"]', 3);
    assert.ok(await page.eval(() => document.querySelector('.comparison-finding').textContent.includes('N. Virginia')));
    assert.ok(await page.eval(() => document.querySelector('.regional-table').textContent.includes('Below request')));
    await page.eval(() => [...document.querySelectorAll('.region-select')].find(b => b.textContent.includes('Ireland')).click());
    await settle();
    assert.ok(await page.eval(() => document.getElementById('trajectory-title').textContent.includes('Ireland')));
    await value(page, '#inspect-market-slot', 10);
    assert.ok(await page.eval(() => document.querySelector('.inspection-value').textContent.includes('$1.280')));
    const earlier = await page.eval(() => document.querySelector('[aria-label="Forecast issue"]').options[1].value);
    await value(page, '[aria-label="Forecast issue"]', earlier);
    assert.ok(await page.eval(() => document.querySelector('.forecast-freshness').textContent.includes('1h old')));
    await value(page, '[aria-label="Forecast horizon"]', 1);
    assert.ok(await page.eval(() => document.querySelector('.forecast-freshness').textContent.includes('1 of 1')));
    await value(page, '[aria-label="Forecast horizon"]', 6);
    await page.eval(() => document.querySelector('.slot-hit-area').dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await settle();
    assert.ok(await page.eval(() => document.querySelector('.forecast-inspector').textContent.includes('Simulated quote')));
    const oldSlot = await page.eval(() => document.getElementById('inspect-market-slot').value);
    await page.eval(() => document.querySelector('.market-chart-svg').focus());
    await page.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
    await page.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
    await settle();
    assert.equal(Number(await page.eval(() => document.getElementById('inspect-market-slot').value)), Number(oldSlot) + 1);
    const cpu = await page.eval(() => [...document.querySelector('[aria-label="Market resource"]').options].find(o => o.textContent === 'CPU').value);
    await value(page, '[aria-label="Market resource"]', cpu);
    assert.ok(await page.eval(() => document.getElementById('trajectory-title').textContent.includes('CPU')));
    assert.ok(await page.eval(() => document.querySelector('.inspection-value').textContent.includes('$0.050')));
    await page.screenshot({ path: `.taste-skill/market/${width}-cpu.jpg`, fullPage: true });
    await value(page, '[aria-label="Quote data kind"]', 'OBSERVED');
    assert.ok(await page.eval(() => document.querySelector('.comparison-finding').textContent.includes('No current quote')));
    assert.ok(await page.eval(() => [...document.querySelectorAll('.regional-table tbody td[data-label="Current quote"]')].every(td => td.textContent === '—')));
    assert.deepEqual(page.consoleErrors, []);
    results.push({ width, controls: 'pass', capacity: 'pass', issueAndHorizon: 'pass', slotKeyboard: 'pass', cpuIsolation: 'pass', quoteKindIsolation: 'pass', consoleErrors: [], findings });
    await page.close();
  }
  const page = await browser.newPage({ width: 1440, height: 900 });
  await page.goto('http://127.0.0.1:3000', { settleMs: 300 });
  await page.eval(() => {
    const original = window.fetch;
    window.fetch = async (url, options) => {
      if (String(url).includes('/api/')) {
        const data = String(url).endsWith('/replay/state') ? { status: 'READY', currentSlot: 8, seed: 42, strategies: [] } : [];
        return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return original(url, options);
    };
  });
  await value(page, '.source-picker select', 'backend');
  await page.eval(() => document.getElementById('tab-market').click());
  await settle();
  assert.ok(await page.eval(() => document.getElementById('panel-market').textContent.includes('No regional quotes or forecasts')));
  assert.equal(await page.eval(() => document.querySelectorAll('.regional-table tbody tr').length), 0);
  assert.equal(await page.eval(() => document.querySelectorAll('.market-chart-svg').length), 0);
  await page.screenshot({ path: '.taste-skill/market/empty-backend.jpg', fullPage: true });
  results.push({ emptyBackend: 'pass; isolated browser fetch fixture, no backend writes' });
  await page.close();
  writeFileSync('.taste-skill/market/checks.json', JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results));
} finally { await browser.close(); }
