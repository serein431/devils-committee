"""Cover real-but-rarely-hit paths coverage flagged: the honest 'thin_data'
verdict (证据不足 ≠ 通过), compliance.enforce_dict, and every MockLLM audit
phrasing. These are genuine product behaviors, not filler."""
import asyncio

from backend import compliance, llm
from backend.skills.runner import SkillRunner
from backend.agents import AuditAgent
from backend.models import Claim, Evidence


def test_thin_data_is_reported_not_silently_passed():
    """A thin sample with weak IC must surface as thin_data, never as a clean pass
    (mirrors the real survivorship auditor's 'never write missing evidence as pass')."""
    runner = SkillRunner()
    fe = {"ranked_factors": [{"name": "x", "ic": 0.03, "ir": 0.5, "n_obs": 20}],
          "total_return_in_window": 0.1}
    surv = runner._survivorship_mock("TEST", fe)
    assert surv["conclusion"] == "insufficient_evidence" and surv["missing_evidence"]

    # AuditAgent must map that to a thin_data verdict on the factor claim
    agent = AuditAgent(runner, llm.MockLLM())
    claim = Claim(id="bull-1", agent="Bull", side="bull", text="t",
                  evidence=[Evidence(skill="skill-factor-ranking-sage", summary="s")],
                  skills_used=["skill-factor-ranking-sage"])
    # monkeypatch the runner's survivorship to return our crafted thin result
    runner.audit_survivorship = lambda symbol, fp: surv                       # type: ignore
    runner.audit_hpo = lambda symbol, fp: {"overfit_signals": [], "skill": "h"}  # type: ignore
    verdicts = asyncio.run(agent.audit("TEST", [claim], fe))
    v = next(x for x in verdicts if x.claim_id == "bull-1")
    assert v.status == "thin_data"
    assert v.plain and "证据太少" in v.plain            # honest beginner phrasing


def test_enforce_dict_scrubs_and_adds_disclaimer():
    out = compliance.enforce_dict({"a": "建议买入这只票", "b": ["目标价 300", "ok"],
                                   "c": {"d": "strong buy"}})
    assert compliance.REDACTION in out["a"]
    assert compliance.REDACTION in out["b"][0] and out["b"][1] == "ok"
    assert compliance.REDACTION in out["c"]["d"]
    assert out["disclaimer"]


def test_mock_audit_reason_covers_every_status():
    m = llm.MockLLM()
    for status in ("pass", "selection_bias", "bad_data", "suspected_overfit", "thin_data"):
        txt = m.audit_reason(status=status, symbol="600519", detail={})
        assert isinstance(txt, str) and txt
    # unknown status still returns a string, never raises
    assert m.audit_reason(status="???", symbol="X", detail={})
