import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage();
p.on("console", m => { if (m.type() !== "log") console.log(`[${m.type()}] ${m.text()}`); });
p.on("pageerror", e => console.log("[pageerror] " + e.message));
await p.goto("http://127.0.0.1:8765/era5.html");
await p.waitForFunction(() => document.getElementById("out").textContent.includes("DONE"), null, { timeout: 120000 }).catch(() => console.log("[timeout]"));
console.log(await p.evaluate(() => document.getElementById("out").textContent));
await b.close();
