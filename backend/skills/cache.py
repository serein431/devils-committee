"""Content-addressed local cache for verified PandaData datasets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import DatasetArtifact


def cache_key(
    method: str,
    params: dict[str, Any],
    sdk_version: str,
    data_version: str,
) -> str:
    """Return a deterministic key for one exact dataset request."""
    body = json.dumps(
        {
            "method": method,
            "params": params,
            "sdk_version": sdk_version,
            "data_version": data_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash a file without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetCache:
    """Store Parquet data with separately verified canonical metadata."""

    def __init__(self, root: str | Path, data_version: str) -> None:
        self.root = Path(root)
        self.data_version = data_version

    def load(
        self,
        name: str,
        method: str,
        params: dict[str, Any],
        sdk_version: str,
    ) -> DatasetArtifact | None:
        key = cache_key(method, params, sdk_version, self.data_version)
        meta_path = self.root / name / f"{key}.json"
        data_path = self.root / name / f"{key}.parquet"
        if not meta_path.is_file() or not data_path.is_file():
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                return None
            if meta.get("name") != name or meta.get("method") != method:
                return None
            if meta.get("params") != params:
                return None
            if meta.get("sdk_version") != sdk_version:
                return None
            if meta.get("data_version") != self.data_version:
                return None
            if file_sha256(data_path) != meta.get("sha256"):
                return None
            return DatasetArtifact(
                name=name,
                method=method,
                params=params,
                path=str(data_path),
                sha256=str(meta["sha256"]),
                rows=int(meta["rows"]),
                mode="cache",
                fetched_at=str(meta["fetched_at"]),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save(
        self,
        name: str,
        method: str,
        params: dict[str, Any],
        sdk_version: str,
        frame: Any,
    ) -> DatasetArtifact:
        key = cache_key(method, params, sdk_version, self.data_version)
        target = self.root / name
        target.mkdir(parents=True, exist_ok=True)
        data_path = target / f"{key}.parquet"
        data_temp = target / f"{key}.parquet.tmp"
        meta_path = target / f"{key}.json"
        meta_temp = target / f"{key}.json.tmp"

        try:
            frame.to_parquet(data_temp, index=False)
            data_temp.replace(data_path)
            artifact = DatasetArtifact(
                name=name,
                method=method,
                params=params,
                path=str(data_path),
                sha256=file_sha256(data_path),
                rows=len(frame),
                mode="live",
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
            metadata = {
                **artifact.to_dict(),
                "sdk_version": sdk_version,
                "data_version": self.data_version,
            }
            meta_temp.write_text(
                json.dumps(
                    metadata,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            meta_temp.replace(meta_path)
            return artifact
        finally:
            for temporary in (data_temp, meta_temp):
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
