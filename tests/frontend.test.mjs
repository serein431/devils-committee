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
const recognitions = [];
const spoken = [];
const fetchCalls = [];
let speechCancelCount = 0;

class MockSpeechRecognition {
  constructor() {
    this.started = false;
    recognitions.push(this);
  }
  start() {
    this.started = true;
    this.onstart?.();
  }
  stop() {
    this.started = false;
    this.onend?.();
  }
  abort() {
    this.started = false;
    this.onend?.();
  }
  emitFinal(transcript, alternatives = []) {
    const choices = [transcript, ...alternatives].map(value => ({ transcript: value }));
    const result = Object.assign({ length: choices.length, isFinal: true }, choices);
    this.onresult?.({ resultIndex: 0, results: [result] });
  }
  end() {
    this.started = false;
    this.onend?.();
  }
}

class MockSpeechSynthesisUtterance {
  constructor(text = "") {
    this.text = text;
  }
}

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  url: "http://localhost:8080/",
  beforeParse(win) {
    win.SpeechRecognition = MockSpeechRecognition;
    win.webkitSpeechRecognition = MockSpeechRecognition;
    win.SpeechSynthesisUtterance = MockSpeechSynthesisUtterance;
    win.speechSynthesis = {
      speaking: false,
      paused: false,
      getVoices: () => [
        { name: "Mock English", lang: "en-US", default: true },
        { name: "Mock Cantonese", lang: "zh-HK", default: false },
        { name: "Mock Mandarin", lang: "zh-CN", default: false },
      ],
      speak(utterance) {
        spoken.push(utterance);
        this.speaking = true;
        win.setTimeout(() => {
          this.speaking = false;
          utterance.onend?.();
        }, 200);
      },
      cancel() {
        speechCancelCount++;
        this.speaking = false;
        this.paused = false;
      },
      pause() { this.paused = true; },
      resume() { this.paused = false; },
      addEventListener() {},
      removeEventListener() {},
    };
    win.fetch = async (url, options = {}) => {
      fetchCalls.push({ url: String(url), options });
      if (String(url) === "/api/follow-up") {
        return {
          ok: true,
          json: async () => ({
            answer: "主持人根据上一轮材料单独回答：波动仍是主要风险。",
            agent: "Chair",
            mode: "single-agent",
            symbol: "600519.SH",
            disclaimer: "本次追问未重新取数或启动多智能体审计。",
          }),
        };
      }
      return {
        ok: true,
        body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
        json: async () => ({ result: {} }),
      };
    };
  },
});
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
assert.match(html, /face-player:hover\{z-index:20/);
assert.match(html, /#bEngine,#bMode\{display:none\}/);
for (const removed of ["AA" + "PL", "NV" + "DA", "TS" + "LA"]) {
  assert.doesNotMatch(html, new RegExp(removed));
}

let passed = 0;
const ok = (name, cond) => { assert.ok(cond, name); console.log("  [PASS]", name); passed++; };
const waitFor = async (predicate, timeoutMs = 500) => {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started >= timeoutMs) return false;
    await new Promise(resolve => window.setTimeout(resolve, 5));
  }
  return true;
};

ok("four large heads form the first-screen debate stage",
   document.querySelectorAll("#faceStage .face-player").length === 4);
ok("research details begin after the face stage",
   document.getElementById("faceStage").compareDocumentPosition(document.getElementById("detailsStart")) & window.Node.DOCUMENT_POSITION_FOLLOWING);
ok("stream controls include pause and show-all",
   document.getElementById("stagePause") && document.getElementById("stageRevealAll"));

// --- browser-native voice input/output -------------------------------------
for (const id of ["voiceInput", "voiceOutput", "voicePause", "voiceStop", "voiceStatus"]) {
  ok(`voice control #${id} exists`, !!document.getElementById(id));
}
ok("follow-up and new-question controls are distinct",
   document.getElementById("go") && document.getElementById("newQuestion"));
ok("voice status is announced accessibly",
   document.getElementById("voiceStatus").getAttribute("aria-live") === "polite");
for (const id of ["voiceInput", "voiceOutput", "voicePause", "voiceStop"]) {
  const control = document.getElementById(id);
  ok(`#${id} has an accessible name`, !!(control.getAttribute("aria-label") || control.textContent.trim()));
}
ok("voice output is enabled by default",
   document.getElementById("voiceOutput").getAttribute("aria-pressed") === "true");

document.getElementById("voiceInput").click();
const recognition = recognitions.at(-1);
ok("microphone click starts recognition", !!recognition?.started);
ok("microphone exposes listening state",
   document.getElementById("voiceInput").classList.contains("listening") &&
   document.getElementById("voiceInput").getAttribute("aria-label").includes("停止") &&
   document.getElementById("voiceStatus").textContent.trim().length > 0);
ok("microphone permission errors tell the user how to recover",
   window.recognitionErrorMessage("not-allowed").includes("地址栏允许麦克风"));

recognition.emitFinal("研究三零零七五", ["研究六零零五一九"]);
recognition.end();
await new Promise(resolve => window.setTimeout(resolve, 5));
ok("final voice transcript normalizes continuous Chinese digits",
   document.getElementById("q").value === "研究600519");
ok("voice recognition considers multiple alternatives", recognition.maxAlternatives === 3);
ok("recognition end submits exactly once",
   fetchCalls.length === 1 &&
   fetchCalls[0].url.includes("topic=%E7%A0%94%E7%A9%B6600519") &&
   JSON.parse(fetchCalls[0].options.body).topic === "研究600519");
document.getElementById("voiceStop").click();

const fetchCountBeforeInvalidCode = fetchCalls.length;
document.getElementById("q").value = "60063.SZ";
document.getElementById("go").click();
await new Promise(resolve => window.setTimeout(resolve, 5));
ok("five-digit A-share code is rejected before sending a request",
   fetchCalls.length === fetchCountBeforeInvalidCode &&
   document.getElementById("stageQuote").textContent.includes("6 位"));

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
  delta: "点击后立即显示**这一整段**文字",
});
ok("show-all reveals the complete pending delta",
   document.getElementById("stageQuote").textContent === "点击后立即显示这一整段文字");
ok("streaming stage renders bold Markdown",
   document.querySelector("#stageQuote strong")?.textContent === "这一整段");

window.handleEvent({ stage: "claim_start", id: "control-3", agent: "macro", side: "macro" });
const longDelta = "真实研究内容".repeat(60);
const longDeltaStarted = Date.now();
await window.handleEvent({
  stage: "claim_delta", id: "control-3", agent: "macro", side: "macro",
  delta: longDelta,
});
ok("a long streamed chunk does not block later network events character by character",
   Date.now() - longDeltaStarted < 80 &&
   document.getElementById("stageQuote").textContent === longDelta);

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
    text: side === "bull" ? "<img src=x onerror=alert(1)>看多**论据**" : `${side} 论据`,
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
ok("claim cards render bold Markdown without showing markers",
   document.querySelector("#card-bull-1 .argue strong")?.textContent === "论据" &&
   !document.querySelector("#card-bull-1 .argue").textContent.includes("**"));
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
  reason: "关键**状态数据**缺失，无法完成存活偏差检查", remediation: "补齐状态变化和期末股票列表",
  plain: "资料没拿全，不能下结论", provenance: "live",
  audit_skill: "skill-survivorship-universe-auditor",
});
ok("missing evidence has its own audit label",
   document.getElementById("verdicts").textContent.includes("MISSING-EVIDENCE") &&
   !document.getElementById("verdicts").textContent.includes("THIN-DATA"));
ok("audit reasons render bold Markdown",
   document.querySelector("#verdicts .vrow:last-child .vreason strong")?.textContent === "状态数据");

window.handleEvent({ stage: "rebut", msg: "四方开始定向回应" });
ok("rebuttal stage is visible", document.getElementById("stage").textContent.includes("定向回应"));
window.handleEvent({
  stage: "claim_start", id: "bull-2", agent: "bull", side: "bull",
  kind: "rebuttal", round: 2, responds_to: ["bear-1"],
});
await window.handleEvent({
  stage: "claim_delta", id: "bull-2", agent: "bull", side: "bull",
  kind: "rebuttal", round: 2, responds_to: ["bear-1"], delta: "回应 bear-1 的流动性前提。",
});
window.handleEvent({
  stage: "claim", id: "bull-2", agent: "bull", side: "bull", confidence: 0.55,
  kind: "rebuttal", round: 2, responds_to: ["bear-1"],
  text: "回应 bear-1 的流动性前提。", plain: "", skills_used: [], evidence: [],
});
ok("rebuttal card names the claim it answers",
   document.querySelector("#card-bull-2 .reply")?.textContent.includes("bear-1"));

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
    consensus: ["都不**荐股**"], risk_boundaries: ["仅供**学习**，不构成投资建议"],
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
ok("summary sections render bold Markdown",
   document.querySelector("#dmap .dcons strong")?.textContent === "荐股" &&
   document.querySelector("#bounds strong")?.textContent === "学习");
ok("disclaimer shown", document.getElementById("disc").textContent.includes("免责声明"));
ok("recommendation:none bar present", document.querySelector(".recbar .k").textContent.includes("NONE"));
ok("audit-engine badge reflects real evidence", document.getElementById("bEngine").className.includes("real"));
ok("data and skill statuses shown", document.getElementById("trace").textContent.includes("状态 success") &&
   document.getElementById("trace").textContent.includes("skill-x[success/live]"));
ok("map + summary sections visible", !document.getElementById("mapSec").className.includes("hidden") &&
   !document.getElementById("sumSec").className.includes("hidden"));
await new Promise(resolve => window.setTimeout(resolve, 80));
ok("first screen keeps the last detailed statement after completion",
   document.getElementById("stageQuote").textContent.includes("回应 bear-1 的流动性前提") &&
   !document.getElementById("stageQuote").textContent.includes("向下滑动"));
ok("completion does not freeze the last speaker in front",
   document.querySelectorAll("#faceStage .face-player.is-active").length === 0 &&
   !document.getElementById("faceStage").classList.contains("is-debating"));

await waitFor(() => {
  const text = spoken.map(utterance => utterance.text).join("\n");
  return text.includes("看多论据") && text.includes("关键状态数据缺失") &&
    (text.includes("都不荐股") || text.includes("仅供学习"));
}, 2000);
const spokenText = spoken.map(utterance => utterance.text).join("\n");
ok("claims narrate the detailed argument", spoken.length > 0 && spokenText.includes("看多论据"));
ok("audit flags narrate the specific reason", spokenText.includes("关键状态数据缺失"));
ok("result summary enters the speech queue",
   spokenText.includes("都不荐股") || spokenText.includes("仅供学习"));
ok("narration strips Markdown markers", !spokenText.includes("**"));
ok("narration explicitly uses Mainland Mandarin",
   spoken.every(utterance => utterance.lang === "zh-CN" && utterance.voice?.lang === "zh-CN"));

window.handleEvent({
  stage: "claim", id: "bull-mute", agent: "bull", side: "bull", confidence: 0.5,
  text: "正在播报时静音", plain: "静音测试", skills_used: [], evidence: [],
});
window.handleEvent({
  stage: "claim", id: "bear-after-mute", agent: "bear", side: "bear", confidence: 0.5,
  text: "静音后开庭仍继续", plain: "静音不影响开庭", skills_used: [], evidence: [],
});
const cancelsBeforeMute = speechCancelCount;
document.getElementById("voiceOutput").click();
ok("turning voice output off cancels current speech", speechCancelCount > cancelsBeforeMute);
await new Promise(resolve => window.setTimeout(resolve, 40));
ok("turning voice output off does not block the court",
   document.getElementById("stageQuote").textContent.includes("静音后开庭仍继续"));
document.getElementById("voiceOutput").click();
window.handleEvent({
  stage: "claim", id: "risk-stop", agent: "risk", side: "risk", confidence: 0.5,
  text: "正在播报时停止", plain: "停止测试", skills_used: [], evidence: [],
});
window.handleEvent({
  stage: "claim", id: "bull-after-stop", agent: "bull", side: "bull", confidence: 0.5,
  text: "停止播报后开庭仍继续", plain: "停止不影响开庭", skills_used: [], evidence: [],
});
await new Promise(resolve => window.setTimeout(resolve, 0));
const cancelsBeforeStop = speechCancelCount;
document.getElementById("voiceStop").click();
ok("voice stop cancels current speech", speechCancelCount > cancelsBeforeStop);
await new Promise(resolve => window.setTimeout(resolve, 70));
ok("voice stop does not clear pending court turns",
   document.getElementById("stageQuote").textContent.includes("停止播报后开庭仍继续"));

window.handleEvent({
  stage: "claim", id: "macro-pause", agent: "macro", side: "macro", confidence: 0.5,
  text: "暂停与继续", plain: "暂停测试", skills_used: [], evidence: [],
});
document.getElementById("voicePause").click();
ok("voice pause suspends active narration",
   window.speechSynthesis.paused && document.getElementById("voicePause").getAttribute("aria-label").includes("继续"));
document.getElementById("voicePause").click();
ok("voice resume continues active narration", !window.speechSynthesis.paused);
document.getElementById("voiceStop").click();

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
ok("zero-claim reason is visible on the first-screen debate stage",
   document.getElementById("stageQuote").textContent.includes("当前没有足够数据"));
ok("completed research exposes separate follow-up and new-question actions",
   document.getElementById("go").textContent.includes("追问") &&
   !document.getElementById("newQuestion").classList.contains("hidden"));

const agentCardsBeforeFollowUp = document.querySelectorAll("#debate .agent").length;
document.getElementById("q").value = "那波动风险怎么看？";
document.getElementById("go").click();
await new Promise(resolve => window.setTimeout(resolve, 10));
const followUpCall = fetchCalls.at(-1);
const followUpPayload = JSON.parse(fetchCalls.at(-1).options.body);
ok("follow-up uses the dedicated single-agent endpoint",
   followUpCall.url === "/api/follow-up" && followUpPayload.question === "那波动风险怎么看？" &&
   followUpPayload.symbol === "600519.SH" && Array.isArray(followUpPayload.history));
ok("follow-up does not create another multi-agent debate",
   document.querySelectorAll("#debate .agent").length === agentCardsBeforeFollowUp &&
   document.querySelectorAll("#debate .follow-up-answer").length === 1 &&
   document.getElementById("stage").textContent.includes("未启动多 Agent"));
ok("follow-up appends a second visible conversation round",
   document.querySelectorAll("#debate .round-question").length === 2 &&
   document.querySelector('#debate .round-question[data-round="2"]').textContent.includes("那波动风险怎么看") &&
   document.querySelector("#debate .follow-up-answer").textContent.includes("波动仍是主要风险"));

document.getElementById("q").value = "300750.SZ 的流动性风险";
document.getElementById("newQuestion").click();
await new Promise(resolve => window.setTimeout(resolve, 10));
const newQuestionPayload = JSON.parse(fetchCalls.at(-1).options.body);
ok("new-question action starts without prior conversation context",
   newQuestionPayload.topic === "300750.SZ 的流动性风险" &&
   document.querySelectorAll("#debate .round-question").length === 1);

const recognitionCount = recognitions.length;
document.getElementById("voiceInput").click();
const disconnectedRecognition = recognitions.at(-1);
disconnectedRecognition.onerror?.({ error: "network" });
disconnectedRecognition.end();
await new Promise(resolve => window.setTimeout(resolve, 370));
const retriedRecognition = recognitions.at(-1);
ok("voice network errors retry once automatically",
   recognitions.length === recognitionCount + 2 && retriedRecognition.started &&
   document.getElementById("voiceStatus").textContent.includes("重连成功"));
retriedRecognition.onerror?.({ error: "not-allowed" });
retriedRecognition.end();

// A WebView may return fetch headers but never expose the first streamed chunk.
// The page must stop waiting and use the non-streaming endpoint instead.
const stalledFetchCalls = [];
window.fetch = async (url, options = {}) => {
  stalledFetchCalls.push({ url: String(url), options });
  if (String(url).includes("stream=1")) {
    return {
      ok: true,
      body: {
        getReader: () => ({
          read: () => new Promise(() => {}),
          cancel: async () => {},
        }),
      },
    };
  }
  return {
    ok: true,
    json: async () => ({
      result: {
        claims: [], verdicts: [], open_disagreements: [], consensus: [],
        risk_boundaries: ["备用请求已完成"], disclaimer: "仅供研究",
        meta: {
          symbol: "600519.SH", n_claims: 0, n_flags: 0,
          data_status: "insufficient-evidence", audit_engine: [], modes: [],
          skills_manifest: {
            all_skills: [], results: [],
            data: { symbol: "600519.SH", status: "insufficient-evidence", mode: null, dataset_hashes: [] },
          },
        },
      },
    }),
  };
};
document.getElementById("q").value = "600519.SH WebView 流式兼容测试";
document.getElementById("go").click();
await new Promise(resolve => window.setTimeout(resolve, 120));
ok("stalled WebView stream falls back to the regular endpoint",
   stalledFetchCalls.length === 2 &&
   stalledFetchCalls[0].url.includes("stream=1") &&
   stalledFetchCalls[1].url.startsWith("/a2a?topic=") &&
   stalledFetchCalls[1].url.includes("WebView%20%E6%B5%81%E5%BC%8F%E5%85%BC%E5%AE%B9%E6%B5%8B%E8%AF%95"));

// Lingguang's WebView has been observed reaching the server with an invalid
// fetch body (HTTP 422). Retry the same SSE request through XMLHttpRequest,
// which uses the WebView's native HTTP path instead of the injected fetch path.
const compatXhrCalls = [];
class MockCompatXMLHttpRequest {
  constructor() {
    this.readyState = 0;
    this.status = 0;
    this.responseText = "";
    this.headers = {};
  }
  open(method, url) {
    this.method = method;
    this.url = url;
    this.readyState = 1;
  }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(body) {
    compatXhrCalls.push({ method: this.method, url: this.url, body, headers: this.headers });
    this.status = 200;
    this.readyState = 3;
    this.responseText = `data: ${JSON.stringify({
      stage: "result",
      result: {
        claims: [], verdicts: [], open_disagreements: [], consensus: [],
        risk_boundaries: ["XHR 兼容请求已完成"], disclaimer: "仅供研究",
        meta: {
          symbol: "600519.SH", n_claims: 0, n_flags: 0,
          data_status: "insufficient-evidence", audit_engine: [], modes: [],
          skills_manifest: {
            all_skills: [], results: [],
            data: { symbol: "600519.SH", status: "insufficient-evidence", mode: null, dataset_hashes: [] },
          },
        },
      },
    })}\n\n`;
    window.setTimeout(() => {
      this.onprogress?.();
      this.readyState = 4;
      this.onload?.();
    }, 0);
  }
  abort() { this.onabort?.(); }
}
window.XMLHttpRequest = MockCompatXMLHttpRequest;
const rejectedFetchCalls = [];
window.fetch = async (url, options = {}) => {
  rejectedFetchCalls.push({ url: String(url), options });
  return { ok: false, status: 422, body: null, json: async () => ({ detail: "invalid request" }) };
};
document.getElementById("q").value = "600519.SH 灵光请求体兼容测试";
document.getElementById("newQuestion").click();
await new Promise(resolve => window.setTimeout(resolve, 80));
ok("HTTP 422 from WebView fetch retries the live stream through XHR",
   rejectedFetchCalls.length === 1 && compatXhrCalls.length === 1 &&
   compatXhrCalls[0].url.includes("stream=1") &&
   JSON.parse(compatXhrCalls[0].body).topic.includes("灵光请求体兼容测试") &&
   document.getElementById("bounds").textContent.includes("XHR 兼容请求已完成"));

console.log(`\n✔ frontend DOM (quant-terminal): all ${passed} checks green`);
