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

assert.match(html, /600519\.SH/);
assert.match(html, /300750\.SZ/);
assert.match(html, /601318\.SH/);
assert.match(html, /rel="icon"/);
assert.doesNotMatch(html, /仍在吵/);
assert.doesNotMatch(html, /谁发言，谁走到前面/);
assert.match(html, /face-player\[data-side="macro"\]:not\(\.is-active\)/);
assert.match(html, /#bEngine,#bMode\{display:none\}/);
for (const removed of ["AA" + "PL", "NV" + "DA", "TS" + "LA"]) {
  assert.doesNotMatch(html, new RegExp(removed));
}

let passed = 0;
const ok = (name, cond) => { assert.ok(cond, name); console.log("  [PASS]", name); passed++; };

ok("four large heads form the first-screen debate stage",
   document.querySelectorAll("#faceStage .face-player").length === 4);
ok("research details begin after the face stage",
   document.getElementById("faceStage").compareDocumentPosition(document.getElementById("detailsStart")) & window.Node.DOCUMENT_POSITION_FOLLOWING);
ok("stream controls include pause and show-all",
   document.getElementById("stagePause") && document.getElementById("stageRevealAll"));

// --- drive the streaming renderer directly (no network) --------------------
window.handleEvent({ stage: "argue", symbol: "600519.SH" });
ok("symbol badge set", document.getElementById("bSym").textContent === "600519.SH");
ok("pipeline stage 'argue' lit", document.querySelector('.pstage[data-st="argue"]').className.includes("on"));

window.handleEvent({ stage: "claim_start", id: "control-1", agent: "bull", side: "bull" });
document.getElementById("stagePause").click();
const pausedText = document.getElementById("stageQuote").textContent;
const pausedAppend = window.handleEvent({
  stage: "claim_delta", id: "control-1", agent: "bull", side: "bull",
  delta: "暂停时不应继续播放",
});
await new Promise(resolve => window.setTimeout(resolve, 8));
ok("pause stops visible text growth",
   document.getElementById("stageQuote").textContent === pausedText &&
   document.getElementById("stagePause").textContent.includes("继续"));
document.getElementById("stagePause").click();
await pausedAppend;
ok("continue resumes visible text growth",
   document.getElementById("stageQuote").textContent.includes("暂停时不应继续播放"));

window.handleEvent({ stage: "claim_start", id: "control-2", agent: "bear", side: "bear" });
document.getElementById("stageRevealAll").click();
await window.handleEvent({
  stage: "claim_delta", id: "control-2", agent: "bear", side: "bear",
  delta: "点击后立即显示这一整段文字",
});
ok("show-all reveals the complete pending delta",
   document.getElementById("stageQuote").textContent === "点击后立即显示这一整段文字");

const evidence = [{ skill: "skill-factor-ranking-sage", summary: "因子", metrics: { ic: 0.079, ir: 0.9, n_obs: 24 } }];
const stageFrames = [];
const frameObserver = new window.MutationObserver(mutations => {
  mutations.forEach(mutation => stageFrames.push(mutation.target.getAttribute("src")));
});
document.querySelectorAll("#faceStage .face-image").forEach(image => {
  frameObserver.observe(image, { attributes: true, attributeFilter: ["src"] });
});
for (const side of ["bull", "bear", "macro", "risk"]) {
  window.handleEvent({
    stage: "claim_start", id: `${side}-1`, agent: side, side,
  });
  await window.handleEvent({
    stage: "claim_delta", id: `${side}-1`, agent: side, side,
    delta: `${side} 具体论据第一段；`,
  });
  await window.handleEvent({
    stage: "claim_delta", id: `${side}-1`, agent: side, side,
    delta: `${side} 具体论据第二段。`,
  });
  window.handleEvent({
    stage: "claim", id: `${side}-1`, agent: side, side, confidence: 0.6,
    text: side === "bull" ? "<img src=x onerror=alert(1)>看多论据" : `${side} 论据`,
    plain: `${side} 人话`, skills_used: ["skill-x"],
    evidence: side === "bull" ? evidence : [{ skill: "skill-y", summary: "s", metrics: { impact_bps: 97 } }],
  });
}
ok("four agent panels rendered", document.querySelectorAll("#debate .agent").length === 4);
ok("agent id matches claim id", !!document.getElementById("card-bull-1"));
ok("one stage speaker comes forward", document.querySelectorAll("#faceStage .face-player.is-active").length === 1);
ok("first screen streams the detailed claim instead of beginner copy",
   document.getElementById("stageQuote").textContent.includes("具体论据") &&
   !document.getElementById("stageQuote").textContent.includes("人话"));
const activeSpeaker = document.querySelector("#faceStage .face-player.is-active");
ok("active speaker uses one of its animated speaking frames",
   ["speaking", "emphasis", "idle"].includes(activeSpeaker.dataset.frameState) &&
   activeSpeaker.querySelector(".face-image").getAttribute("src").includes(`/${activeSpeaker.dataset.side}-`));
await new Promise(resolve => window.setTimeout(resolve, 12));
frameObserver.disconnect();
ok("speaking head cycles through multiple expression images",
   Number(activeSpeaker.dataset.frameTick) > 0 && new Set(stageFrames).size >= 2);
ok("evidence cards stay compact below the stage", document.querySelectorAll("#debate .agent-avatar").length === 0);

const bullHtml = document.getElementById("card-bull-1").innerHTML;
ok("XSS payload escaped inside the compact evidence card",
   document.querySelectorAll("#card-bull-1 img").length === 0 &&
   !bullHtml.includes('src="x"') && bullHtml.includes("&lt;img"));
ok("data-viz SVG rendered for metrics", document.querySelector("#card-bull-1 .viz svg") !== null);
ok("IC metric labelled", bullHtml.includes("因子 IC"));
ok("beginner 人话 in DOM", bullHtml.includes("bull 人话"));

// audit catches bull-1 via the REAL cli auditor
window.handleEvent({ stage: "audit" });
ok("audit console revealed", !document.getElementById("auditSec").className.includes("hidden"));
ok("audit returns all four heads to their original positions",
   document.querySelectorAll("#faceStage .face-player.is-active").length === 0 &&
   !document.getElementById("faceStage").classList.contains("is-debating"));
ok("audit keeps the latest detailed statement visible",
   document.getElementById("faceStage").classList.contains("is-complete") &&
   document.getElementById("stageQuote").textContent.includes("具体论据"));
window.handleEvent({
  stage: "audit_flag", claim_id: "bull-1", status: "selection_bias", severity: "high",
  reason: "小样本高IC，像挑赢家来吹", remediation: "改用全域", plain: "只挑高分同学",
  provenance: "live", audit_skill: "skill-survivorship-universe-auditor",
});
ok("flagged stamp turned red", document.getElementById("stamp-bull-1").className.includes("bad"));
ok("flagged card got slam animation", document.getElementById("card-bull-1").className.includes("flag-slam"));
ok("verdict row appended", document.querySelectorAll("#verdicts .vrow").length === 1);
ok("severity ring drawn", document.querySelector("#verdicts .vrow .ring") !== null);
ok("live provenance badge shown", document.querySelector("#verdicts .prov.real") !== null);
window.handleEvent({
  stage: "audit_flag", claim_id: "risk-1", status: "missing_evidence", severity: "medium",
  reason: "关键状态数据缺失，无法完成存活偏差检查", remediation: "补齐状态变化和期末股票列表",
  plain: "资料没拿全，不能下结论", provenance: "live",
  audit_skill: "skill-survivorship-universe-auditor",
});
ok("missing evidence has its own audit label",
   document.getElementById("verdicts").textContent.includes("MISSING-EVIDENCE") &&
   !document.getElementById("verdicts").textContent.includes("THIN-DATA"));

// unflagged claims pass on synthesize
window.handleEvent({ stage: "synthesize" });
ok("unflagged stamp turned green", document.getElementById("stamp-bear-1").className.includes("ok"));

// final result: diverging disagreement map + boundaries + disclaimer
window.handleEvent({
  stage: "result", result: {
    open_disagreements: [
      {
        topic: "因子",
        bull_view: "正方长文本 ".repeat(30),
        bear_view: "反方长文本 ".repeat(30),
        status: "open",
      },
      { topic: "数据", bull_view: "a", bear_view: "b", status: "consensus" }],
    consensus: ["都不荐股"], risk_boundaries: ["仅供学习，不构成投资建议"],
    disclaimer: "免责声明文本",
    meta: {
      symbol: "600519.SH", n_claims: 4, n_flags: 1, data_status: "success",
      audit_engine: ["live", "precomputed"],
      gives_investment_advice: false, recommendation: null,
      modes: ["live", "precomputed"],
      skills_manifest: {
        all_skills: ["skill-x"],
        data: { symbol: "600519.SH", status: "success", mode: "live", dataset_hashes: ["sha256:x"] },
        results: [{ skill_id: "skill-x", status: "success", mode: "live" }],
      },
    },
  },
});
ok("disagreement tracks rendered", document.querySelectorAll("#dmap .track").length === 2);
ok("open disagreement marked", document.querySelector("#dmap .track.opened") !== null);
ok("finished research calls open items unresolved, not still running",
   document.querySelector("#dmap .dpill.open").textContent.includes("未达成一致"));
const longTrack = document.querySelector("#dmap .track");
const longLabel = longTrack.querySelector(".lab");
const trackStyle = window.getComputedStyle(longTrack);
const labelStyle = window.getComputedStyle(longLabel);
ok("long disagreement track grows with its text",
   trackStyle.height !== "34px" && ["grid", "flex"].includes(trackStyle.display) && labelStyle.position !== "absolute");
ok("long disagreement text can wrap inside its column",
   ["anywhere", "break-word"].includes(labelStyle.overflowWrap));
ok("risk boundaries rendered", document.querySelectorAll("#bounds li").length === 1);
ok("disclaimer shown", document.getElementById("disc").textContent.includes("免责声明"));
ok("recommendation:none bar present", document.querySelector(".recbar .k").textContent.includes("NONE"));
ok("audit-engine badge reflects real evidence", document.getElementById("bEngine").className.includes("real"));
ok("data and skill statuses shown", document.getElementById("trace").textContent.includes("状态 success") &&
   document.getElementById("trace").textContent.includes("skill-x[success/live]"));
ok("map + summary sections visible", !document.getElementById("mapSec").className.includes("hidden") &&
   !document.getElementById("sumSec").className.includes("hidden"));
await new Promise(resolve => window.setTimeout(resolve, 40));
ok("first screen keeps the last detailed statement after completion",
   document.getElementById("stageQuote").textContent.includes("关键状态数据缺失") &&
   !document.getElementById("stageQuote").textContent.includes("向下滑动"));
ok("completion does not freeze the last speaker in front",
   document.querySelectorAll("#faceStage .face-player.is-active").length === 0 &&
   !document.getElementById("faceStage").classList.contains("is-debating"));

// view toggle: expert is default, beginner toggles
ok("expert mode is default (not beginner)", !document.body.classList.contains("beginner"));
document.getElementById("mBeg").onclick();
ok("beginner toggle works", document.body.classList.contains("beginner"));

// A result without claims must be explicit evidence insufficiency, not "all pass".
window.handleEvent({
  stage: "result", result: {
    claims: [], verdicts: [], open_disagreements: [], consensus: [],
    risk_boundaries: ["当前没有足够数据"], disclaimer: "仅供研究",
    meta: {
      symbol: "600519.SH", n_claims: 0, n_flags: 0,
      data_status: "insufficient-evidence", audit_engine: [], modes: [],
      skills_manifest: {
        all_skills: [], results: [],
        data: { symbol: "600519.SH", status: "insufficient-evidence", mode: null, dataset_hashes: [] },
      },
    },
  },
});
ok("zero-claim result renders safely", document.getElementById("auditSub").textContent.includes("没有可审计论据"));
ok("zero-claim result is not called all pass", !document.getElementById("auditSub").textContent.includes("全部通过"));

console.log(`\n✔ frontend DOM (quant-terminal): all ${passed} checks green`);
