"""Read-only access to the hospital price knowledge engine.

Published machine-readable-file rates are evidence about facility prices. They
do not establish insurance network status, clinical suitability, or a member's
out-of-pocket cost, so those decisions remain outside this adapter.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Protocol


class KnowledgeCatalogError(RuntimeError):
    """The configured knowledge catalog could not provide a trustworthy result."""


@dataclass(frozen=True, slots=True)
class PublishedHospitalRate:
    hospital_id: int
    hospital: str
    address: str | None
    description: str | None
    procedure_code: str
    code_type: str | None
    rate_count: int
    low: float
    typical: float
    high: float
    mrf_url: str | None
    source_page_url: str | None
    published_at: str | None
    retrieved_at: str
    confidence: float = 1.0
    verification_status: str = "source_backed"
    consent_requirement: str = "none_public_catalog"
    network_status: str = "unknown"

    def as_dict(self) -> dict:
        return {
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "address": self.address,
            "description": self.description,
            "procedure_code": self.procedure_code,
            "code_type": self.code_type,
            "rate_count": self.rate_count,
            "low": self.low,
            "typical": self.typical,
            "high": self.high,
            "source": {
                "mrf_url": self.mrf_url,
                "source_page_url": self.source_page_url,
                "published_at": self.published_at,
                "retrieved_at": self.retrieved_at,
            },
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "consent_requirement": self.consent_requirement,
            "network_status": self.network_status,
        }


class HospitalKnowledgeCatalog(Protocol):
    source_name: str

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]: ...


class NoHospitalKnowledgeCatalog:
    """Default for unit tests and installations without a catalog configured."""

    source_name = "not_configured"

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]:
        return []


class SQLiteHospitalKnowledgeCatalog:
    """Query the knowledge engine's SQLite catalog without mutating it."""

    source_name = "hospital_price_transparency_knowledge_engine"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise KnowledgeCatalogError(f"knowledge catalog not found: {self.db_path}")
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise KnowledgeCatalogError("knowledge catalog could not be opened read-only") from exc
        conn.row_factory = sqlite3.Row
        return conn

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]:
        sql = """SELECT r.hospital_id, h.name, h.address, h.mrf_url,
                        h.source_page_url, h.last_updated_on, r.code,
                        r.code_type, r.description, r.negotiated_dollar
                 FROM rate r JOIN hospital h ON h.id = r.hospital_id
                 WHERE r.code = ? AND r.estimable = 1
                   AND r.negotiated_dollar IS NOT NULL"""
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (code,)).fetchall()
        except sqlite3.Error as exc:
            raise KnowledgeCatalogError("knowledge catalog query failed") from exc

        grouped: dict[int, list[float]] = {}
        metadata: dict[int, sqlite3.Row] = {}
        for row in rows:
            grouped.setdefault(row["hospital_id"], []).append(float(row["negotiated_dollar"]))
            metadata.setdefault(row["hospital_id"], row)

        retrieved_at = datetime.now(UTC).isoformat()
        results: list[PublishedHospitalRate] = []
        for hospital_id, values in grouped.items():
            item = metadata[hospital_id]
            results.append(PublishedHospitalRate(
                hospital_id=hospital_id,
                hospital=item["name"],
                address=item["address"],
                description=item["description"],
                procedure_code=item["code"],
                code_type=item["code_type"],
                rate_count=len(values),
                low=round(min(values), 2),
                typical=round(median(values), 2),
                high=round(max(values), 2),
                mrf_url=item["mrf_url"],
                source_page_url=item["source_page_url"],
                published_at=item["last_updated_on"],
                retrieved_at=retrieved_at,
            ))
        return sorted(results, key=lambda item: (item.typical, item.hospital))
