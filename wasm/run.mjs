// node run.mjs [page] [screenshot.png]   (default page: era5.html)
import { chromium } from "playwright";
const page = process.argv[2] || "era5.html", shot = process.argv[3];
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
p.on("console", m => { if (m.type() !== "log") console.log(`[${m.type()}] ${m.text()}`); });
p.on("pageerror", e => console.log("[pageerror] " + e.message));
await p.goto((process.env.BASE || "http://127.0.0.1:8765/") + page);
await p.waitForFunction(() => document.getElementById("out").textContent.includes("DONE"), null, { timeout: 180000 }).catch(() => console.log("[timeout]"));
console.log(await p.evaluate(() => document.getElementById("out").textContent));
if (shot) { await p.waitForTimeout(1500); await p.screenshot({ path: shot }); console.log("screenshot " + shot); }
await b.close();
