from backend.research_request import ResearchRequest, normalize_symbol


def test_normalizes_supported_a_share_symbols():
    assert normalize_symbol("600519") == ("600519.SH", "cn")
    assert normalize_symbol("sz300750") == ("300750.SZ", "cn")
    assert normalize_symbol("601318.SH") == ("601318.SH", "cn")


def test_marks_hk_and_us_as_unsupported():
    assert normalize_symbol("00700.HK") == ("00700.HK", "unsupported")
    assert normalize_symbol("NVDA") == ("NVDA", "unsupported")


def test_payload_fields_override_text_defaults():
    req = ResearchRequest.from_payload({
        "topic": "分析 600519",
        "symbol": "300750.SZ",
        "question": "流动性风险如何？",
        "start_date": "20240101",
        "end_date": "20260724",
        "portfolio_value": 500000.0,
        "spread_bps": 8.0,
    })
    assert req.symbol == "300750.SZ"
    assert req.question == "流动性风险如何？"
    assert req.portfolio_value == 500000.0
    assert req.spread_bps == 8.0
    assert req.supported is True


def test_unknown_text_does_not_become_a_fake_symbol():
    req = ResearchRequest.from_payload({"topic": "帮我看看这个东西"})
    assert req.symbol == "UNKNOWN"
    assert req.supported is False
