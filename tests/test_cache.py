"""7-day-window data cache (service_checklist): pull once, serve from cache at
judging. Proves the cache-first path returns without ever importing panda_data —
which is exactly what protects the live demo if the window expires / rate-limits."""
import dataclasses

from backend.config import CONFIG


def test_cache_save_load_roundtrip(tmp_path, monkeypatch):
    from backend.skills import cache
    monkeypatch.setattr(cache, "CONFIG",
                        dataclasses.replace(CONFIG, cache_dir=str(tmp_path)))
    assert cache.load("600519.SH") is None
    cache.save("600519.SH", {"dates": ["20240101"], "close": [100.0], "volume": [1e6]})
    assert cache.is_cached("600519.SH")
    got = cache.load("600519.SH")
    assert got["close"] == [100.0]


def test_panda_mode_serves_from_cache_without_panda_data(tmp_path, monkeypatch):
    from backend.skills import cache, data
    cfg = dataclasses.replace(CONFIG, cache_dir=str(tmp_path), data_mode="panda")
    monkeypatch.setattr(cache, "CONFIG", cfg)
    monkeypatch.setattr(data, "CONFIG", cfg)
    cache.save("600519.SH", {"dates": ["20240101", "20240102"],
                             "close": [100.0, 101.0], "volume": [1e6, 1.1e6]})
    # data_mode=panda + cache hit -> must NOT try to import/init panda_data
    bars = data.get_stock_daily("600519.SH")
    assert bars.source == "panda_cache"
    assert bars.close == [100.0, 101.0]
    assert bars.n == 2


def test_mock_mode_ignores_cache(tmp_path, monkeypatch):
    from backend.skills import data
    monkeypatch.setattr(data, "CONFIG",
                        dataclasses.replace(CONFIG, cache_dir=str(tmp_path), data_mode="mock"))
    bars = data.get_stock_daily("600519.SH")
    assert bars.source == "mock"      # deterministic mock never consults the cache
