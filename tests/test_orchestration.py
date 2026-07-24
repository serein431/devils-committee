"""End-to-end engine tests: real collaboration (not a chain), independent audit,
reproducibility, the <=20-min budget wiring, and compliance always last."""
import asyncio

from backend.orchestration import DebateOrchestrator, _extract_symbol, GLOBAL_BUDGET_SEC


def test_symbol_extraction():
    assert _extract_symbol("帮我理解 600519 的多空") == "600519.SH"
    assert _extract_symbol("看看 000001 平安银行") == "000001.SZ"
    assert _extract_symbol("bull and bear for AAPL please") == "AAPL"


def test_symbol_extraction_common_user_formats():
    """Real users type sh/sz prefixes and lead with English words like BUY."""
    assert _extract_symbol("sh600519") == "600519.SH"
    assert _extract_symbol("sz000001") == "000001.SZ"
    assert _extract_symbol("SH600519 怎么样") == "600519.SH"
    assert _extract_symbol("BUY AAPL NOW") == "AAPL"      # not 'BUY'
    assert _extract_symbol("SELL TSLA") == "TSLA"          # not 'SELL'
    assert _extract_symbol("the ETF for NVDA") == "NVDA"   # skip ETF stopword


def test_debate_produces_four_sides_and_audits_each():
    r = asyncio.run(DebateOrchestrator().run("600519 多空理由"))
    sides = {c.side for c in r.claims}
    assert sides == {"bull", "bear", "macro", "risk"}
    # every claim gets an independent verdict — audit is not skipped
    assert {v.claim_id for v in r.verdicts} == {c.id for c in r.claims}


def test_killer_feature_stamps_a_claim_red():
    """The differentiator: the audit agent independently catches a weak claim and
    stamps it red — and every flag carries a concrete, honest remediation."""
    r = asyncio.run(DebateOrchestrator().run("600519 多空理由"))
    flags = r.audit_flags()
    assert flags, "audit should catch at least one weak claim on this topic"
    valid = {"selection_bias", "suspected_overfit", "bad_data", "thin_data"}
    assert all(f.status in valid for f in flags)
    assert all(f.remediation for f in flags)   # never a bare 'you're wrong'
    assert all(f.audit_skill for f in flags)    # grounded in a named audit skill


def test_audit_can_also_fully_pass():
    """Not a hardcoded gotcha: some topics survive the audit clean."""
    r = asyncio.run(DebateOrchestrator().run("TSLA bull bear"))
    assert r.meta["n_flags"] == 0


def test_reproducible_across_runs():
    a = asyncio.run(DebateOrchestrator().run("600519 多空"))
    b = asyncio.run(DebateOrchestrator().run("600519 多空"))
    assert a.meta["n_flags"] == b.meta["n_flags"]
    assert [c.text for c in a.claims] == [c.text for c in b.claims]


def test_disagreement_map_is_grounded_in_the_audit():
    """The map reflects THIS debate: a bad-data symbol shows the data topic OPEN
    with the concrete defect; a clean symbol shows it as consensus."""
    dirty = asyncio.run(DebateOrchestrator().run("600519 多空"))
    clean = asyncio.run(DebateOrchestrator().run("TSLA 多空"))
    d_data = next(p for p in dirty.open_disagreements if p.topic == "证据本身干不干净")
    c_data = next(p for p in clean.open_disagreements if p.topic == "证据本身干不干净")
    assert dirty.meta["n_flags"] > 0 and d_data.status == "open"
    assert clean.meta["n_flags"] == 0 and c_data.status == "consensus"
    # liquidity view carries real numbers, not a template
    liq = next(p for p in dirty.open_disagreements if "流动性" in p.topic)
    assert "bps" in liq.bear_view and "天" in liq.bear_view


def test_skills_manifest_traces_every_conclusion_to_a_skill_and_data():
    """18 requires explainability: each conclusion links back to a skill + data."""
    r = asyncio.run(DebateOrchestrator().run("600519 多空"))
    man = r.meta["skills_manifest"]
    assert man["data"]["symbol"] == "600519.SH" and man["data"]["n_bars"] > 0
    # every arguing role's cited skills are listed and attributed
    assert man["evidence_skills"] and all("used_by" in e for e in man["evidence_skills"])
    assert "skill-factor-ranking-sage" in man["all_skills"]
    # audit skills carry provenance so a judge can tell mock from real QuantSkills
    for a in man["audit_skills"]:
        assert a["provenance"] and a["verdict_for"]


def test_plain_language_layer_for_beginners():
    """15 命门: every claim and every audit flag carries a jargon-free takeaway."""
    r = asyncio.run(DebateOrchestrator().run("600519 多空"))
    assert all(c.plain for c in r.claims), "each claim needs a beginner one-liner"
    for v in r.audit_flags():
        assert v.plain, "each flag needs a beginner analogy"
        # analogy must avoid the raw jargon term it explains
        if v.status == "selection_bias":
            assert "存活偏差" not in v.plain and "同学" in v.plain
    # audit_claims surfaces it too
    ac = asyncio.run(DebateOrchestrator().audit_claims("600519 审计"))
    assert all("claim_plain" in a for a in ac["audits"])


def test_output_always_carries_disclaimer_and_boundaries():
    r = asyncio.run(DebateOrchestrator().run("AAPL bull bear"))
    assert r.disclaimer
    assert any("不构成" in b for b in r.risk_boundaries)


def test_stance_is_machine_checkable_never_advises():
    """15 可信度 & 18 失格红线: a caller can programmatically confirm no advice."""
    r = asyncio.run(DebateOrchestrator().run("600519 多空")).to_dict()
    assert r["meta"]["gives_investment_advice"] is False
    assert r["meta"]["recommendation"] is None
    ac = asyncio.run(DebateOrchestrator().audit_claims("600519 审计"))
    assert ac["gives_investment_advice"] is False and ac["recommendation"] is None


def test_budget_is_under_20_minutes():
    assert GLOBAL_BUDGET_SEC <= 20 * 60


def test_audit_claims_skill_matches_the_agent_card():
    """The Agent Card advertises `audit_claims` — it must actually return per-claim
    verdicts with reasoning, not silently run a full debate."""
    r = asyncio.run(DebateOrchestrator().audit_claims("审计 600519 的多空论据"))
    assert r["symbol"] == "600519.SH"
    assert {a["claim_id"] for a in r["audits"]} == {"bull-1", "bear-1", "macro-1", "risk-1"}
    valid = {"pass", "selection_bias", "suspected_overfit", "bad_data", "thin_data"}
    assert all(a["status"] in valid for a in r["audits"])
    assert all(a["provenance"] in ("mock", "mock-fallback", "real-cli") for a in r["audits"])
    assert r["disclaimer"]
    # compliance holds on this lighter path too
    from backend import compliance
    for a in r["audits"]:
        assert not compliance.find_violations(a["reason"] + a["claim"])
