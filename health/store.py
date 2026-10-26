"""
health/store.py
Histórico persistente en ficheros JSON Lines (una línea JSON por registro), sin base de datos.

- checks.jsonl:   cada revisión realmente ejecutada contra Oracle.
- requests.jsonl: cada vez que alguien pregunta (con o sin caché), qué revisión se le devolvió.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "health"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HealthStore:
    def __init__(self, directory: str | Path | None = None):
        self._dir = Path(directory or os.environ.get("SIMBA_HEALTH_DIR", DEFAULT_DIR))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._checks = self._dir / "checks.jsonl"
        self._requests = self._dir / "requests.jsonl"
        self._lock = threading.Lock()

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # línea truncada por un corte: se ignora
        return records

    @staticmethod
    def _append(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def save_check(self, overall: str, summary: str, findings: list[dict], raw: dict[str, Any]) -> int:
        with self._lock:
            checks = self._read(self._checks)
            check_id = (checks[-1]["id"] + 1) if checks else 1
            self._append(self._checks, {
                "id": check_id, "created_at": _now_iso(), "overall": overall,
                "summary": summary, "findings": findings, "raw": raw,
            })
            return check_id

    def latest_check(self) -> Optional[dict[str, Any]]:
        with self._lock:
            checks = self._read(self._checks)
        if not checks:
            return None
        last = checks[-1]
        return {k: last[k] for k in ("id", "created_at", "overall", "summary", "findings")}

    def log_request(self, requested_by: str, check_id: int, from_cache: bool) -> None:
        with self._lock:
            self._append(self._requests, {
                "asked_at": _now_iso(), "requested_by": requested_by,
                "check_id": check_id, "from_cache": bool(from_cache),
            })

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Últimas peticiones con la revisión que se devolvió (sin datos crudos), la más reciente primero."""
        limit = max(1, min(int(limit), 200))
        with self._lock:
            checks = {c["id"]: c for c in self._read(self._checks)}
            requests = self._read(self._requests)
        result = []
        for req in reversed(requests):
            check = checks.get(req["check_id"])
            if not check:
                continue
            result.append({
                "asked_at": req["asked_at"],
                "requested_by": req["requested_by"],
                "from_cache": req["from_cache"],
                "check_id": check["id"],
                "check_created_at": check["created_at"],
                "overall": check["overall"],
                "summary": check["summary"],
                "findings": check["findings"],
            })
            if len(result) >= limit:
                break
        return result
