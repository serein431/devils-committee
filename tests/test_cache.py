import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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


class _SlowFrame(_BytesFrame):
    def __init__(self, payload: bytes, delay: float = 0.05):
        super().__init__(payload)
        self.delay = delay

    def to_parquet(self, path, index=False):
        super().to_parquet(path, index=index)
        time.sleep(self.delay)


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


def test_concurrent_saves_same_key_commit_matching_data_and_metadata(tmp_path):
    cache = DatasetCache(tmp_path, data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"]}
    start = threading.Barrier(2)

    def save(payload):
        start.wait(timeout=5)
        return cache.save(
            "daily",
            "get_stock_daily",
            params,
            "0.0.12",
            _SlowFrame(payload),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        artifacts = list(executor.map(save, (b"writer-one", b"writer-two")))

    final_path = Path(artifacts[0].path)
    metadata = json.loads(final_path.with_suffix(".json").read_text(encoding="utf-8"))
    final_hash = file_sha256(final_path)

    assert len(artifacts) == 2
    assert metadata["sha256"] == final_hash
    assert cache.load(
        "daily",
        "get_stock_daily",
        params,
        "0.0.12",
    ) is not None


@pytest.mark.parametrize("name", ["../outside", "/tmp/absolute-dataset", "nested/name"])
def test_cache_rejects_unsafe_dataset_names_before_access(tmp_path, name):
    cache = DatasetCache(tmp_path / "cache", data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"]}

    with pytest.raises(ValueError, match="dataset name"):
        cache.load(name, "get_stock_daily", params, "0.0.12")
    with pytest.raises(ValueError, match="dataset name"):
        cache.save(
            name,
            "get_stock_daily",
            params,
            "0.0.12",
            _BytesFrame(b"must-not-write"),
        )


def test_cache_rejects_dataset_directory_symlink_escape(tmp_path):
    root = tmp_path / "cache"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "daily").symlink_to(outside, target_is_directory=True)
    cache = DatasetCache(root, data_version="panda-2026-07")
    params = {"symbol": ["600519.SH"]}

    with pytest.raises(ValueError, match="dataset path"):
        cache.load("daily", "get_stock_daily", params, "0.0.12")
    with pytest.raises(ValueError, match="dataset path"):
        cache.save(
            "daily",
            "get_stock_daily",
            params,
            "0.0.12",
            _BytesFrame(b"must-not-write"),
        )
    assert list(outside.iterdir()) == []
