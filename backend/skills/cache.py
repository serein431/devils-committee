"""Content-addressed local cache for verified PandaData datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fcntl

from .contracts import DatasetArtifact


_SAFE_DATASET_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_IN_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_IN_PROCESS_LOCKS_GUARD = threading.Lock()


def _validate_dataset_name(name: str) -> None:
    if not isinstance(name, str) or _SAFE_DATASET_NAME.fullmatch(name) is None:
        raise ValueError("invalid dataset name")


def _in_process_lock(lock_path: Path) -> threading.Lock:
    identity = str(lock_path.resolve())
    with _IN_PROCESS_LOCKS_GUARD:
        return _IN_PROCESS_LOCKS.setdefault(identity, threading.Lock())


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

    def _dataset_dir(self, name: str) -> Path:
        _validate_dataset_name(name)
        root = self.root.resolve()
        target = self.root / name
        if target.is_symlink():
            raise ValueError("unsafe dataset path")
        try:
            target.resolve().relative_to(root)
        except ValueError:
            raise ValueError("unsafe dataset path") from None
        return target

    def load(
        self,
        name: str,
        method: str,
        params: dict[str, Any],
        sdk_version: str,
    ) -> DatasetArtifact | None:
        target = self._dataset_dir(name)
        key = cache_key(method, params, sdk_version, self.data_version)
        meta_path = target / f"{key}.json"
        data_path = target / f"{key}.parquet"
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
        target = self._dataset_dir(name)
        key = cache_key(method, params, sdk_version, self.data_version)
        target.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("unsafe dataset path")
        data_path = target / f"{key}.parquet"
        meta_path = target / f"{key}.json"
        lock_path = target / f"{key}.lock"
        writer_id = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"
        data_temp = target / f"{key}.parquet.tmp-{writer_id}"
        meta_temp = target / f"{key}.json.tmp-{writer_id}"

        try:
            process_lock = _in_process_lock(lock_path)
            with process_lock, lock_path.open("a+b") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    frame.to_parquet(data_temp, index=False)
                    digest = file_sha256(data_temp)
                    data_temp.replace(data_path)
                    artifact = DatasetArtifact(
                        name=name,
                        method=method,
                        params=params,
                        path=str(data_path),
                        sha256=digest,
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
                    if file_sha256(data_path) != digest:
                        raise OSError("cache verification failed")
                    return artifact
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            for temporary in (data_temp, meta_temp):
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
