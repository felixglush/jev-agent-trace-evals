#!/usr/bin/env node
// Drive the annotation app like a user: open a trace, focus a rubric, jump to
// an evidence event, save a label + comment + trace note, reload, and check it
// stuck. Usage: node drive-annotate.cjs <base-url> <trace-id> <rubric-id> <out-dir>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const [base, traceId, rubricId, outDir] = process.argv.slice(2);
  if (!outDir) { console.error("usage: drive-annotate.cjs <base-url> <trace-id> <rubric-id> <out-dir>"); process.exit(2); }
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(`${base}/#${encodeURIComponent(traceId)}`);
  const card = page.locator(`#card-${rubricId}`);
  await card.waitFor();
  await page.screenshot({ path: path.join(outDir, "1-trace.png") });

  await card.locator(".head").click();                       // focus rubric: highlights its evidence
  const refLink = page.locator(`#card-${rubricId} .refs a:visible`).first(); // slice refs sit in a collapsed <details> when no run exists
  if (await refLink.count()) await refLink.click();          // jump to an evidence event
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(outDir, "2-focused.png") });

  const label = await page.locator(`#card-${rubricId} .fb select option`).nth(1).getAttribute("value");
  await page.locator(`#card-${rubricId} .fb select`).selectOption(label);
  await page.locator(`#card-${rubricId} .fb textarea`).fill("verification comment");
  await page.locator(`#card-${rubricId} .fb textarea`).blur();
  await page.locator("#note").fill("verification note");
  await page.locator("#note").blur();
  await page.waitForFunction(id => document.querySelector(`#card-${id} .saved`)?.textContent.includes("saved"), rubricId);
  await page.waitForTimeout(400);

  await page.reload();
  await card.waitFor();
  const kept = await page.locator(`#card-${rubricId} .fb select`).inputValue();
  const comment = await page.locator(`#card-${rubricId} .fb textarea`).inputValue();
  const note = await page.locator("#note").inputValue();
  await page.screenshot({ path: path.join(outDir, "3-after-reload.png") });
  await browser.close();
  const ok = kept === label && comment === "verification comment" && note === "verification note" && errors.length === 0;
  console.log(JSON.stringify({ ok, label, kept, comment, note, errors }));
  process.exit(ok ? 0 : 1);
})();
