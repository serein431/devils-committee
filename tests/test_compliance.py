"""Compliance is a scored criterion (15) AND a disqualifier guard (18).
These tests lock down that no banned language survives the gate."""
from backend import compliance
from backend.models import Claim, Evidence, AuditVerdict, DisagreementPoint, DebateResult


def test_scrub_removes_buy_sell_and_targets():
    bad = "我建议买入这只票，目标价 300，收益率 50%，strong buy"
    out = compliance.scrub(bad)
    assert "建议买入" not in out
    assert "目标价" not in out
    assert "收益率 50%" not in out
    assert "strong buy" not in out.lower()
    assert compliance.REDACTION in out


def test_find_violations_flags_each_pattern():
    assert compliance.find_violations("必涨") == ["必涨"]
    assert compliance.find_violations("推荐买入") == ["推荐买"]
    assert compliance.find_violations("这是中性的分析") == []


def test_enforce_scrubs_nested_result_and_sets_disclaimer():
    r = DebateResult(
        topic="x",
        claims=[Claim(id="bull-1", agent="Bull", side="bull",
                      text="建议买入，稳赚不赔",
                      evidence=[Evidence(skill="s", summary="目标价 100")])],
        verdicts=[AuditVerdict(claim_id="bull-1", status="pass",
                               reason="推荐持有", remediation="必涨")],
        open_disagreements=[DisagreementPoint(topic="t", bull_view="包赚",
                                              bear_view="ok")],
        risk_boundaries=["收益率 20%"],
    )
    out = compliance.enforce(r)
    assert compliance.REDACTION in out.claims[0].text
    assert compliance.REDACTION in out.claims[0].evidence[0].summary
    assert compliance.REDACTION in out.verdicts[0].reason
    assert compliance.REDACTION in out.open_disagreements[0].bull_view
    assert compliance.REDACTION in out.risk_boundaries[0]
    assert out.disclaimer
    assert out.meta["compliance"]["gate"] == "passed"


def test_neutral_text_is_untouched():
    good = "多因子打分给出正向排序，审计发现小样本因子存疑。"
    assert compliance.scrub(good) == good
