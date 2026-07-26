from datetime import date

from backend import research_request
from backend.research_request import ResearchRequest, normalize_symbol, symbol_from_text


def test_normalizes_supported_a_share_symbols():
    assert normalize_symbol("600519") == ("600519.SH", "cn")
    assert normalize_symbol("sz300750") == ("300750.SZ", "cn")
    assert normalize_symbol("601318.SH") == ("601318.SH", "cn")


def test_marks_hk_and_us_as_unsupported():
    assert normalize_symbol("00700.HK") == ("00700.HK", "unsupported")
    assert normalize_symbol("WXYZ") == ("WXYZ", "unsupported")
    assert normalize_symbol("AI") == ("AI", "unsupported")


def test_text_a_share_suffix_overrides_prefix():
    assert symbol_from_text("研究 SH600519.SZ") == ("600519.SZ", "cn")


def test_text_symbol_does_not_match_inside_longer_identifier():
    assert symbol_from_text("研究 abcSH600519.SZdef") == ("UNKNOWN", "unknown")


def test_text_symbol_allows_chinese_adjacency():
    assert symbol_from_text("分析600519怎么样") == ("600519.SH", "cn")
    assert symbol_from_text("看看300750.SZ风险") == ("300750.SZ", "cn")


def test_text_symbol_skips_non_ticker_words():
    assert symbol_from_text("BUY WXYZ NOW") == ("WXYZ", "unsupported")
    assert symbol_from_text("SELL QWER") == ("QWER", "unsupported")
    assert symbol_from_text("the ETF for ZZZZ") == ("ZZZZ", "unsupported")
    assert symbol_from_text("分析 AI 行业") == ("UNKNOWN", "unknown")


def test_text_symbol_rejects_invalid_suffix_continuation():
    assert symbol_from_text("研究 SH600519.SZX") == ("UNKNOWN", "unknown")


def test_text_symbol_rejects_non_a_share_exchange_suffix():
    assert symbol_from_text("研究 600519.HK") == ("UNKNOWN", "unknown")


def test_text_symbol_rejects_repeated_dot_suffix():
    assert symbol_from_text("研究 600519..SZ") == ("UNKNOWN", "unknown")


def test_text_symbol_rejects_hyphenated_suffix():
    assert symbol_from_text("研究 SH600519.-SZ") == ("UNKNOWN", "unknown")


def test_text_symbol_rejects_five_digit_a_share_code():
    assert symbol_from_text("研究 60063.SZ") == ("UNKNOWN", "unknown")


def test_text_symbol_allows_sentence_ending_dot_runs():
    assert symbol_from_text("研究 600519.SZ.") == ("600519.SZ", "cn")
    assert symbol_from_text("研究 600519.SZ...") == ("600519.SZ", "cn")


def test_text_symbol_rejects_dollar_suffix():
    assert symbol_from_text("研究 600519.$SZ") == ("UNKNOWN", "unknown")


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


def test_default_end_date_moves_weekend_to_previous_weekday(monkeypatch):
    class Saturday(date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 25)

    monkeypatch.setattr(research_request, "date", Saturday)

    req = ResearchRequest.from_payload({"topic": "分析 600519"})

    assert req.end_date == "20260724"


def test_unknown_text_does_not_become_a_fake_symbol():
    req = ResearchRequest.from_payload({"topic": "帮我看看这个东西"})
    assert req.symbol == "UNKNOWN"
    assert req.supported is False
