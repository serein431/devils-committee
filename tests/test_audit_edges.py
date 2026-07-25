"""Cover honest thin-data audits, compliance and every mock audit phrase."""

from backend import compliance, llm


def test_enforce_dict_scrubs_and_adds_disclaimer():
    out = compliance.enforce_dict({"a": "建议买入这只票", "b": ["目标价 300", "ok"],
                                   "c": {"d": "strong buy"}})
    assert compliance.REDACTION in out["a"]
    assert compliance.REDACTION in out["b"][0] and out["b"][1] == "ok"
    assert compliance.REDACTION in out["c"]["d"]
    assert out["disclaimer"]


def test_mock_audit_reason_covers_every_status():
    m = llm.MockLLM()
    for status in (
        "pass",
        "selection_bias",
        "bad_data",
        "suspected_overfit",
        "thin_data",
        "missing_evidence",
    ):
        txt = m.audit_reason(status=status, symbol="600519", detail={})
        assert isinstance(txt, str) and txt
    # unknown status still returns a string, never raises
    assert m.audit_reason(status="???", symbol="X", detail={})
