import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { Browser } from '/Users/darius/.agents/skills/design-taste-frontend/scripts/lib/cdp.mjs';
mkdirSync('.taste-skill/wordmark', { recursive: true });
const browser = await Browser.launch();
try {
 for (const width of [1440,768,390]) {
  const page = await browser.newPage({width,height:width===390?844:900});
  await page.goto('http://127.0.0.1:3000',{settleMs:300});
  await page.eval('document.fonts.ready');
  const check = await page.eval(() => {
    const wordmark=document.querySelector('.brand h1');
    const style=getComputedStyle(wordmark), r=wordmark.getBoundingClientRect();
    return { brand:style.fontFamily, weight:style.fontWeight, body:getComputedStyle(document.body).fontFamily, tab:getComputedStyle(document.querySelector('[role="tab"]')).fontFamily, loaded:document.fonts.check(`400 36px ${style.fontFamily}`), left:r.left,right:r.right,pageWidth:document.documentElement.scrollWidth,viewport:innerWidth };
  });
  assert.ok(check.loaded);
  assert.ok(check.body.includes('IBM Plex Sans') && check.tab.includes('IBM Plex Sans'));
  assert.notEqual(check.brand,check.body);
  assert.equal(check.weight,'400');
  assert.ok(check.pageWidth<=width+1);
  await page.send('DOM.enable'); await page.send('CSS.enable');
  const doc=await page.send('DOM.getDocument');
  const {nodeId}=await page.send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'.brand h1'});
  const fonts=await page.send('CSS.getPlatformFontsForNode',{nodeId});
  assert.ok(fonts.fonts.some(font=>font.isCustomFont && /broken/i.test(font.familyName)));
  console.log(JSON.stringify({width,...check,renderedFonts:fonts.fonts}));
  await page.screenshot({path:`.taste-skill/wordmark/${width}.jpg`,clip:{x:0,y:0,width,height:width===390?190:170}});
  await page.close();
 }
} finally { await browser.close(); }
