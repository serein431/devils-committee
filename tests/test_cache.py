import hashlib
import json
from pathlib import Path

from backend.skills.cache import DatasetCache, cache_key, file_sha256


class _BytesFrame:
    def __init__(self, payload: bytes, rows: int = 2):
        self.payload = payload
        self.rows = rows

    def __len__(self):
        return self.rows

    def to_parquet(self, path, index=False):
        assert index is False
        Path(path).write_bytes(self.payload)


def test_cache_key_uses_all_inputs_and_canonical_json():
    params = {"symbol": ["600519.SH"], "fields": [], "st": True}
    canonical = json.dumps(
        {
            "method": "get_stock_daily",
            "params": params,
            "sdk_version": "0.0.12",
            "data_version": "panda-2026-07",
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert cache_key(
        "get_stock_daily",
        params,
        "0.0.12",
        "panda-2026-07",
    ) == expected
    assert cache_key(
        "get_stock_daily",
        {"st": True, "fields": [], "symbol": ["600519.SH"]},
        "0.0.12",
        "panda-2026-07",
    ) == expected


def test_cache_save_load_roundtrip_verifies_artifact(tmp_path):
    cache = DatasetCache(tmp_path, data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"], "start_date": "20240101"}
    frame = _BytesFrame(b"verified parquet bytes", rows=2)

    saved = cache.save(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
        frame,
    )
    loaded = cache.load(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
    )

    assert saved.mode == "live"
    assert saved.rows == 2
    assert saved.sha256 == file_sha256(Path(saved.path))
    assert loaded is not None
    assert loaded.mode == "cache"
    assert loaded.path == saved.path
    assert loaded.sha256 == saved.sha256
    assert loaded.rows == 2


def test_cache_hash_mismatch_is_a_miss(tmp_path):
    cache = DatasetCache(tmp_path, data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"]}
    saved = cache.save(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
        _BytesFrame(b"original"),
    )
    Path(saved.path).write_bytes(b"tampered")

    assert cache.load(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
    ) is None


def test_cache_corrupt_metadata_is_a_miss(tmp_path):
    cache = DatasetCache(tmp_path, data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"]}
    saved = cache.save(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
        _BytesFrame(b"original"),
    )
    Path(saved.path).with_suffix(".json").write_text("not-json", encoding="utf-8")

    assert cache.load(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
    ) is None
