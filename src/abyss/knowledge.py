"""Read-only access to the hospital price knowledge engine.

Published machine-readable-file rates are evidence about facility prices. They
do not establish insurance network status, clinical suitability, or a member's
out-of-pocket cost, so those decisions remain outside this adapter.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable, Protocol


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
    catalog_ingested_at: str | None = None
    source_retrieved_at: str | None = None
    source_finished_at: str | None = None
    parser_version: str | None = None
    freshness_status: str = "unknown"
    freshness_age_days: int | None = None
    catalog_source: str = "hospital_price_transparency_knowledge_engine"

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
                "catalog": self.catalog_source,
                "mrf_url": self.mrf_url,
                "source_page_url": self.source_page_url,
                "published_at": self.published_at,
                "catalog_ingested_at": self.catalog_ingested_at,
                "source_retrieved_at": self.source_retrieved_at,
                "source_finished_at": self.source_finished_at,
                "parser_version": self.parser_version,
                "result_retrieved_at": self.retrieved_at,
            },
            "freshness": {
                "status": self.freshness_status,
                "age_days": self.freshness_age_days,
                "evaluated_at": self.retrieved_at,
            },
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "consent_requirement": self.consent_requirement,
            "network_status": self.network_status,
        }


class HospitalKnowledgeCatalog(Protocol):
    source_name: str

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]: ...

    def catalog_status(self) -> dict: ...


class NoHospitalKnowledgeCatalog:
    """Default for unit tests and installations without a catalog configured."""

    source_name = "not_configured"

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]:
        return []

    def catalog_status(self) -> dict:
        return {"status": "not_configured", "hospitals": 0, "rates": 0}


class SeededHospitalKnowledgeCatalog:
    """Explicitly synthetic fallback for demos without a configured database."""

    source_name = "seeded_synthetic_seattle_hospital_catalog"

    def catalog_status(self) -> dict:
        return {"status": "synthetic_fixture", "hospitals": 1, "rates": 1}

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]:
        normalized_code = code.strip().upper()
        if normalized_code != "73721":
            return []
        observed_at = "2026-08-15T00:00:00+00:00"
        return [PublishedHospitalRate(
            hospital_id=1,
            hospital="Seattle General (synthetic)",
            address="Seattle, WA",
            description="MRI knee without contrast",
            procedure_code=normalized_code,
            code_type="HCPCS",
            rate_count=1,
            low=550.0,
            typical=550.0,
            high=550.0,
            mrf_url=None,
            source_page_url=None,
            published_at=None,
            retrieved_at=observed_at,
            catalog_ingested_at=observed_at,
            freshness_status="synthetic_fixture",
            freshness_age_days=None,
            confidence=1.0,
            verification_status="source_backed_synthetic",
            catalog_source=self.source_name,
        )]


class SQLiteHospitalKnowledgeCatalog:
    """Query the knowledge engine's SQLite catalog without mutating it."""

    source_name = "hospital_price_transparency_knowledge_engine"

    _REQUIRED_COLUMNS = {
        "hospital": {
            "id", "name", "address", "mrf_url", "source_page_url",
            "last_updated_on", "ingested_at",
        },
        "rate": {
            "hospital_id", "code", "code_type", "description",
            "negotiated_dollar", "estimable",
        },
        "source_manifest": {
            "id", "hospital_id", "retrieved_at", "finished_at", "parser_version",
            "status",
        },
    }

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        stale_after: timedelta = timedelta(days=180),
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._clock = clock or (lambda: datetime.now(UTC))
        self.stale_after = stale_after
        self._validate()

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise KnowledgeCatalogError(f"knowledge catalog not found: {self.db_path}")
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error as exc:
            raise KnowledgeCatalogError("knowledge catalog could not be opened read-only") from exc
        conn.row_factory = sqlite3.Row
        return conn

    def _validate(self) -> None:
        """Fail during configuration, rather than during a user's care request."""
        try:
            with self._connect() as conn:
                for table, required in self._REQUIRED_COLUMNS.items():
                    columns = {
                        row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
                    }
                    missing = sorted(required - columns)
                    if missing:
                        raise KnowledgeCatalogError(
                            f"knowledge catalog table {table} is missing columns: "
                            f"{', '.join(missing)}"
                        )
        except sqlite3.Error as exc:
            raise KnowledgeCatalogError("knowledge catalog schema could not be read") from exc

    @staticmethod
    def _source_timestamp(item: sqlite3.Row) -> datetime | None:
        for field in (
            "manifest_finished_at",
            "manifest_retrieved_at",
            "ingested_at",
            "last_updated_on",
        ):
            value = item[field]
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        return None

    def catalog_status(self) -> dict:
        """Cheap check of whether the catalog is actually usable, for health checks.

        `COUNT(*) FROM rate` is a full scan of millions of rows — the same
        problem the state database's health check had. Read the row count
        ANALYZE already recorded in `sqlite_stat1` instead. `hospital` is a
        handful of rows and safe to count directly.
        """
        try:
            with self._connect() as conn:
                hospitals = conn.execute("SELECT COUNT(*) FROM hospital").fetchone()[0]
                stat_row = conn.execute(
                    "SELECT stat FROM sqlite_stat1 WHERE tbl = 'rate' LIMIT 1"
                ).fetchone()
                rates = int(str(stat_row[0]).split()[0]) if stat_row and stat_row[0] else 0
        except (sqlite3.Error, KnowledgeCatalogError) as exc:
            return {"status": "unavailable", "hospitals": 0, "rates": 0, "detail": str(exc)}
        if hospitals == 0 or rates == 0:
            return {"status": "empty", "hospitals": hospitals, "rates": rates}
        return {"status": "ready", "hospitals": hospitals, "rates": rates}

    def prices_for_code(self, code: str) -> list[PublishedHospitalRate]:
        normalized_code = code.strip().upper()
        if not normalized_code:
            return []
        sql = """WITH latest_manifest AS (
                     SELECT sm.*
                     FROM source_manifest sm
                     JOIN (
                         SELECT hospital_id, MAX(id) AS id
                         FROM source_manifest
                         WHERE status = 'success' AND hospital_id IS NOT NULL
                         GROUP BY hospital_id
                     ) latest ON latest.id = sm.id
                 )
                 SELECT r.hospital_id, h.name, h.address, h.mrf_url,
                        h.source_page_url, h.last_updated_on, h.ingested_at,
                        r.code, r.code_type, r.description, r.negotiated_dollar,
                        sm.retrieved_at AS manifest_retrieved_at,
                        sm.finished_at AS manifest_finished_at,
                        sm.parser_version AS manifest_parser_version
                 FROM rate r JOIN hospital h ON h.id = r.hospital_id
                 LEFT JOIN latest_manifest sm ON sm.hospital_id = h.id
                 WHERE r.code = ? AND r.estimable = 1
                   AND r.negotiated_dollar IS NOT NULL"""
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, (normalized_code,)).fetchall()
        except sqlite3.Error as exc:
            raise KnowledgeCatalogError("knowledge catalog query failed") from exc

        grouped: dict[int, list[float]] = {}
        metadata: dict[int, sqlite3.Row] = {}
        for row in rows:
            grouped.setdefault(row["hospital_id"], []).append(float(row["negotiated_dollar"]))
            metadata.setdefault(row["hospital_id"], row)

        retrieved = self._clock().astimezone(UTC)
        retrieved_at = retrieved.isoformat()
        results: list[PublishedHospitalRate] = []
        for hospital_id, values in grouped.items():
            item = metadata[hospital_id]
            source_timestamp = self._source_timestamp(item)
            freshness_age_days = (
                max(0, (retrieved - source_timestamp).days)
                if source_timestamp is not None else None
            )
            freshness_status = "unknown"
            if source_timestamp is not None:
                freshness_status = (
                    "stale" if retrieved - source_timestamp > self.stale_after else "current"
                )
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
                catalog_ingested_at=item["ingested_at"],
                source_retrieved_at=item["manifest_retrieved_at"],
                source_finished_at=item["manifest_finished_at"],
                parser_version=item["manifest_parser_version"],
                freshness_status=freshness_status,
                freshness_age_days=freshness_age_days,
            ))
        return sorted(results, key=lambda item: (item.typical, item.hospital))
