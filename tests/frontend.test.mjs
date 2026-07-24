// Frontend DOM test — loads the REAL web/index.html (quant-terminal UI) in jsdom,
// drives its streaming renderer with mock SSE events, asserts DOM + data-viz + XSS.
//   NODE_PATH=<dir-with-jsdom> node tests/frontend.test.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert";
import { createRequire } from "node:module";

const __dir = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { JSDOM } = require("jsdom");

const html = readFileSync(join(__dir, "..", "web", "index.html"), "utf-8");
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true });
const { window } = dom;
const { document } = window;
window.requestAnimationFrame = window.requestAnimationFrame || ((cb) => cb());

let passed = 0;
const ok = (name, cond) => { assert.ok(cond, name); console.log("  [PASS]", name); passed++; };

// --- drive the streaming renderer directly (no network) --------------------
window.handleEvent({ stage: "argue", symbol: "600519.SH" });
ok("symbol badge set", document.getElementById("bSym").textContent === "600519.SH");
ok("pipeline stage 'argue' lit", document.querySelector('.pstage[data-st="argue"]').className.includes("on"));

const evidence = [{ skill: "skill-factor-ranking-sage", summary: "因子", metrics: { ic: 0.079, ir: 0.9, n_obs: 24 } }];
for (const side of ["bull", "bear", "macro", "risk"]) {
  window.handleEvent({
    stage: "claim", id: `${side}-1`, agent: side, side, confidence: 0.6,
    text: side === "bull" ? "<img src=x onerror=alert(1)>看多论据" : `${side} 论据`,
    plain: `${side} 人话`, skills_used: ["skill-x"],
    evidence: side === "bull" ? evidence : [{ skill: "skill-y", summary: "s", metrics: { impact_bps: 97 } }],
  });
}
ok("four agent panels rendered", document.querySelectorAll("#debate .agent").length === 4);
ok("agent id matches claim id", !!document.getElementById("card-bull-1"));

const bullHtml = document.getElementById("card-bull-1").innerHTML;
ok("XSS payload escaped (no live <img)", !bullHtml.includes("<img") && bullHtml.includes("&lt;img"));
ok("data-viz SVG rendered for metrics", document.querySelector("#card-bull-1 .viz svg") !== null);
ok("IC metric labelled", bullHtml.includes("因子 IC"));
ok("beginner 人话 in DOM", bullHtml.includes("bull 人话"));

// audit catches bull-1 via the REAL cli auditor
window.handleEvent({ stage: "audit" });
ok("audit console revealed", !document.getElementById("auditSec").className.includes("hidden"));
window.handleEvent({
  stage: "audit_flag", claim_id: "bull-1", status: "selection_bias", severity: "high",
  reason: "小样本高IC，像挑赢家来吹", remediation: "改用全域", plain: "只挑高分同学",
  provenance: "real-cli", audit_skill: "skill-survivorship-universe-auditor",
});
ok("flagged stamp turned red", document.getElementById("stamp-bull-1").className.includes("bad"));
ok("flagged card got slam animation", document.getElementById("card-bull-1").className.includes("flag-slam"));
ok("verdict row appended", document.querySelectorAll("#verdicts .vrow").length === 1);
ok("severity ring drawn", document.querySelector("#verdicts .vrow .ring") !== null);
ok("REAL provenance badge shown", document.querySelector("#verdicts .prov.real") !== null);

// unflagged claims pass on synthesize
window.handleEvent({ stage: "synthesize" });
ok("unflagged stamp turned green", document.getElementById("stamp-bear-1").className.includes("ok"));

// final result: diverging disagreement map + boundaries + disclaimer
window.handleEvent({
  stage: "result", result: {
    open_disagreements: [
      { topic: "因子", bull_view: "正方看法", bear_view: "反方看法", status: "open" },
      { topic: "数据", bull_view: "a", bear_view: "b", status: "consensus" }],
    consensus: ["都不荐股"], risk_boundaries: ["仅供学习，不构成投资建议"],
    disclaimer: "免责声明文本",
    meta: {
      symbol: "600519.SH", n_claims: 4, n_flags: 1, audit_engine: "real-cli",
      gives_investment_advice: false, recommendation: null,
      modes: { llm_mode: "mock", data_mode: "mock" },
      skills_manifest: { all_skills: ["skill-x"], data: { window: "w", source: "mock", n_bars: 250 } },
    },
  },
});
ok("disagreement tracks rendered", document.querySelectorAll("#dmap .track").length === 2);
ok("open disagreement marked", document.querySelector("#dmap .track.opened") !== null);
ok("risk boundaries rendered", document.querySelectorAll("#bounds li").length === 1);
ok("disclaimer shown", document.getElementById("disc").textContent.includes("免责声明"));
ok("recommendation:none bar present", document.querySelector(".recbar .k").textContent.includes("NONE"));
ok("audit-engine badge = real-cli", document.getElementById("bEngine").className.includes("real"));
ok("map + summary sections visible", !document.getElementById("mapSec").className.includes("hidden") &&
   !document.getElementById("sumSec").className.includes("hidden"));

// view toggle: expert is default, beginner toggles
ok("expert mode is default (not beginner)", !document.body.classList.contains("beginner"));
document.getElementById("mBeg").onclick();
ok("beginner toggle works", document.body.classList.contains("beginner"));

console.log(`\n✔ frontend DOM (quant-terminal): all ${passed} checks green`);
