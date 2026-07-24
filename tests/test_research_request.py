from backend.research_request import ResearchRequest, normalize_symbol, symbol_from_text


def test_normalizes_supported_a_share_symbols():
    assert normalize_symbol("600519") == ("600519.SH", "cn")
    assert normalize_symbol("sz300750") == ("300750.SZ", "cn")
    assert normalize_symbol("601318.SH") == ("601318.SH", "cn")


def test_marks_hk_and_us_as_unsupported():
    assert normalize_symbol("00700.HK") == ("00700.HK", "unsupported")
    assert normalize_symbol("NVDA") == ("NVDA", "unsupported")


def test_text_a_share_suffix_overrides_prefix():
    assert symbol_from_text("研究 SH600519.SZ") == ("600519.SZ", "cn")


def test_text_symbol_does_not_match_inside_longer_identifier():
    assert symbol_from_text("研究 abcSH600519.SZdef") == ("UNKNOWN", "unknown")


def test_payload_fields_override_text_defaults():
    req = ResearchRequest.from_payload({
        "topic": "分析 600519",
        "symbol": "300750.SZ",
        "question": "流动性风险如何？",
        "start_date": "20240101",
        "end_date": "20260724",
        "portfolio_value": 500000,
        "spread_bps": "8.0",
    })
    assert req.symbol == "300750.SZ"
    assert req.question == "流动性风险如何？"
    assert req.start_date == "20240101"
    assert req.end_date == "20260724"
    assert req.portfolio_value == 500000.0
    assert isinstance(req.portfolio_value, float)
    assert req.spread_bps == 8.0
    assert isinstance(req.spread_bps, float)
    assert req.supported is True


def test_unknown_text_does_not_become_a_fake_symbol():
    req = ResearchRequest.from_payload({"topic": "帮我看看这个东西"})
    assert req.symbol == "UNKNOWN"
    assert req.supported is False
