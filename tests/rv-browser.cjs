/* Run with Playwright installed: node tests/rv-browser.cjs [base URL].
 * Exports a test function for environments with a bundled browser runtime.
 */
const assert = require('node:assert/strict');
async function run(browser, base, width = 1440) {
  const context = await browser.newContext({viewport:{width,height:1000},hasTouch:width<650});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error') errors.push(m.text());});
  page.on('response',r=>{if(r.status()>=400) errors.push(`${r.status()} ${r.url()}`);});
  await page.goto(base+'index.html');
  await page.getByRole('link',{name:'RV 相對價值',exact:true}).click();
  await page.waitForSelector('.rv-point');
  assert.match(page.url(),/\/rv\/$/);
  await page.reload(); await page.waitForSelector('.rv-point');
  assert.equal(await page.locator('[name=section]:checked').inputValue(),'Overview');
  assert.deepEqual(await page.locator('[name=metric]:checked').evaluateAll(es=>es.map(e=>e.value)),['Spread']);
  const metrics = ['Spread','10Y','30Y','10s30s'];
  const data = await (await page.request.get(base+'assets/rv-data.json')).json();
  let combinations = 0, summaries = 0;
  for(const section of ['Overview','Cyclical','Non-Cyclical']) {
    const before = await page.locator('[name=metric]:checked').evaluateAll(es=>es.map(e=>e.value));
    await page.locator(`[name=section][value="${section}"]`).check();
    assert.deepEqual(await page.locator('[name=metric]:checked').evaluateAll(es=>es.map(e=>e.value)),before);
    for(let mask=0;mask<16;mask++) {
      for(const m of metrics)await page.locator(`[name=metric][value="${m}"]`).setChecked(false);
      for(let i=0;i<4;i++) await page.locator(`[name=metric][value="${metrics[i]}"]`).setChecked(Boolean(mask&(1<<i)));
      assert.equal(await page.locator('.rv-chart').count(),mask ? 1 : 0);
      const expected=mask&8 ? ['10s30s'] : metrics.filter((_,i)=>mask&(1<<i));
      assert.deepEqual(await page.locator('[name=metric]:checked').evaluateAll(es=>es.map(e=>e.value)),expected);
      assert.equal(await page.locator('.rv-series-legend span').count(),expected.length);
      if(mask===0) assert.equal(await page.locator('#rv-status').innerText(),'請選擇至少一個指標');
      const overflow = await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      assert.equal(overflow,false,`${width}/${section}/${mask} page overflow`);
      combinations++;
    }
    for(const metric of metrics) {
      await page.locator(`[name=metric][value="${metric}"]`).check();
      if(metric!=='10s30s')assert.equal(await page.locator('[name=metric][value="10s30s"]').isChecked(),false);
      const points=page.locator(`.rv-point[data-metric="${metric}"]`);
      assert.equal(await points.count(),data.sections[section][metric].length*5);
      for(let i=0;i<await points.count();i++) {
        const point=points.nth(i); await point.focus();
        await page.keyboard.press('Enter');
        const text = await page.locator('#rv-tooltip').innerText();
        const sector=await point.getAttribute('data-sector');
        const row=data.sections[section][metric].find(r=>r.sector===sector);
        assert.ok(text.includes(row.sector));
        assert.equal(await page.locator('#rv-tooltip dl').count(),0);
        for(const f of [await point.getAttribute('data-field')]) {
          const expected=new Intl.NumberFormat('en-US',{maximumFractionDigits:6}).format(row[f]*(f==='pct'?100:1));
          assert.ok(text.includes(expected),`${section}/${metric}/${row.sector}/${f}: ${text}`); summaries++;
          assert.equal(text.split('：').length,2,'Only one data value per tooltip');
        }
        await page.keyboard.press('Escape'); assert.equal(await page.locator('#rv-tooltip').isHidden(),true);
      }
    }
  }
  await page.locator('[name=section][value="Overview"]').check();
  const point=page.locator('.rv-point[data-field="current"]').first();
  await point.scrollIntoViewIfNeeded();
  if(width<650) await point.tap(); else await point.hover();
  assert.equal(await page.locator('#rv-tooltip').isVisible(),true);
  const box=await page.locator('#rv-tooltip').boundingBox();
  assert.ok(box.x>=0 && box.x+box.width<=width && box.y>=0 && box.y+box.height<=1000);
  await page.keyboard.press('Escape');
  await page.getByRole('link',{name:'返回券商報告知識庫',exact:true}).click();
  assert.ok(page.url().endsWith('/index.html'));
  assert.deepEqual(errors,[]);
  await context.close();
  return {width,combinations,summaries,errors};
}
module.exports={run};
if(require.main===module) (async()=>{
  const {chromium}=require('playwright');
  const browser=await chromium.launch({headless:true,channel:process.env.RV_BROWSER_CHANNEL||'chrome'});
  try {for(const width of [1440,768,375]) console.log(await run(browser,process.argv[2]||'http://localhost:8765/',width));}
  finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
