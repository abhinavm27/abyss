"""`abyss-ingest <domain> [...]` — pull a hospital's MRF into the local DB.

Flow per hospital:

    cms-hpt.txt  ->  mrf-url  ->  stream download  ->  parse in place  ->  delete raw

The raw file is deleted as soon as it is parsed. BMC's CSV is 483 MB
uncompressed and this machine has ~11 GB free, so nothing uncompressed is ever
written to disk: zip members are streamed straight into the parser.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .. import db
from ..ingest import fetch, parse_csv, parse_json
from ..ingest.normalize import INSERT_SQL, ParseStats

BATCH = 5_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pick_member(zf: zipfile.ZipFile) -> str:
    """Choose the data file inside a zip, ignoring macOS resource forks."""
    candidates = [
        n
        for n in zf.namelist()
        if not n.startswith("__MACOSX/")
        and not Path(n).name.startswith("._")
        and Path(n).suffix.lower() in {".csv", ".json"}
    ]
    if not candidates:
        raise ValueError(f"no .csv or .json member in zip: {zf.namelist()[:5]}")
    # Largest member is the charge file; smaller ones are readmes or dictionaries.
    return max(candidates, key=lambda n: zf.getinfo(n).file_size)


def _resolve_source(raw: Path):
    """Return (kind, opener) for a downloaded file, transparently entering zips.

    `opener` yields a fresh binary stream each call, so a parser can read the
    header and then re-read for the data without buffering the whole file.
    """
    if zipfile.is_zipfile(raw):
        with zipfile.ZipFile(raw) as zf:
            member = _pick_member(zf)
        kind = "json" if member.lower().endswith(".json") else "csv"

        def opener():
            zf = zipfile.ZipFile(raw)
            stream = zf.open(member)
            # Close the archive when the member stream closes, so repeated
            # opener() calls don't leak file handles.
            original_close = stream.close

            def close():
                try:
                    original_close()
                finally:
                    zf.close()

            stream.close = close  # type: ignore[method-assign]
            return stream

        return kind, opener, member

    kind = "json" if raw.suffix.lower() == ".json" else "csv"
    return kind, (lambda: raw.open("rb")), raw.name


def ingest_domain(conn, domain: str, keep_raw: bool = False,
                  match: str | None = None) -> list[dict]:
    """Ingest every hospital a domain publishes.

    A health system lists all of its hospitals in one cms-hpt.txt — 14 for Mass
    General Brigham and Beth Israel Lahey — so one domain is many hospitals.
    """
    print(f"\n=== {domain} ===", flush=True)
    pointers = fetch.discover(domain)
    total = len(pointers)
    if match:
        # A system can span states — Trinity Health of New England publishes
        # five hospitals of which only Mercy, in Springfield, is in
        # Massachusetts. Without a filter the other four come along too.
        needle = match.lower()
        pointers = [p for p in pointers if needle in (p.location_name or "").lower()]
    print(
        f"  {len(pointers)} hospital(s)"
        + (f" matching {match!r} of {total} published here" if match else " published here"),
        flush=True,
    )

    results = []
    for pointer in pointers:
        try:
            results.append(ingest_one(conn, domain, pointer, keep_raw))
        except Exception as exc:
            name = pointer.location_name or pointer.mrf_url[-60:]
            print(f"  FAILED {name}: {type(exc).__name__}: {str(exc)[:110]}",
                  file=sys.stderr, flush=True)
    return results


def ingest_one(conn, domain: str, pointer, keep_raw: bool = False) -> dict:
    label = pointer.location_name or domain
    print(f"\n  -- {label} --", flush=True)

    suffix = Path(pointer.mrf_url.split("?")[0]).suffix or ".bin"
    started = _now()

    with tempfile.TemporaryDirectory(prefix="abyss-mrf-") as tmp:
        raw = Path(tmp) / f"{domain.replace('.', '_')}{suffix}"

        def progress(n: int) -> None:
            if n % (16 << 20) < (1 << 20):
                print(f"  downloaded {n / 1e6:.0f} MB", flush=True)

        size = fetch.download(pointer.mrf_url, raw, on_progress=progress)
        print(f"  downloaded {size / 1e6:.1f} MB", flush=True)

        kind, opener, member = _resolve_source(raw)
        print(f"  format: {kind} ({member})", flush=True)

        mod = parse_json if kind == "json" else parse_csv
        header = mod.read_header(opener)

        # The pointer's location-name identifies the *site*; the file's own
        # hospital_name is the filing entity, which is shared across sites.
        # Boston Children's publishes nine campuses that all call themselves
        # "Boston Children's Hospital" internally, so preferring the header
        # produced nine identical rows in the app.
        name = (
            pointer.location_name
            or header.get("hospital_name")
            or domain
        )
        address = header.get("hospital_address")
        last_updated = header.get("last_updated_on")

        # Keyed on the MRF url, not the domain: one domain publishes many
        # hospitals, so the domain is no longer a unique identity.
        cur = conn.execute(
            """INSERT INTO hospital (name, ein, address, domain, source_page_url,
                                     mrf_url, last_updated_on, ingested_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(mrf_url) DO UPDATE SET
                 name=excluded.name, ein=excluded.ein, address=excluded.address,
                 source_page_url=excluded.source_page_url, domain=excluded.domain,
                 last_updated_on=excluded.last_updated_on, ingested_at=excluded.ingested_at
               RETURNING id""",
            (
                name,
                fetch.guess_ein(pointer.mrf_url),
                address,
                domain,
                pointer.source_page_url,
                pointer.mrf_url,
                last_updated,
                _now(),
            ),
        )
        hospital_id = cur.fetchone()[0]
        conn.execute("DELETE FROM rate WHERE hospital_id = ?", (hospital_id,))
        conn.commit()

        stats = ParseStats()
        batch: list[tuple] = []
        for rate in mod.parse(opener, stats):
            batch.append(rate.as_row(hospital_id))
            if len(batch) >= BATCH:
                conn.executemany(INSERT_SQL, batch)
                batch.clear()
                if stats.rows_written % 100_000 < BATCH:
                    print(f"  {stats.rows_written:,} rows...", flush=True)
        if batch:
            conn.executemany(INSERT_SQL, batch)
        conn.commit()

        if keep_raw:
            kept = Path.cwd() / raw.name
            kept.write_bytes(raw.read_bytes())
            print(f"  kept raw at {kept}", flush=True)

    conn.execute(
        """INSERT INTO ingest_run (hospital_id, mrf_url, bytes_, rows_written,
                                   rows_skipped, skip_reasons, started_at, finished_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            hospital_id,
            pointer.mrf_url,
            size,
            stats.rows_written,
            stats.rows_skipped,
            stats.summary(),
            started,
            _now(),
        ),
    )
    conn.commit()

    estimable = conn.execute(
        "SELECT COUNT(*) FROM rate WHERE hospital_id=? AND estimable=1", (hospital_id,)
    ).fetchone()[0]
    print(
        f"  {name}: {stats.rows_written:,} rows written "
        f"({estimable:,} estimable), flagged: {stats.summary()}",
        flush=True,
    )
    return {"hospital_id": hospital_id, "name": name, "rows": stats.rows_written}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest hospital price transparency files")
    ap.add_argument("domains", nargs="+", help="hospital domains, e.g. ajh.org")
    ap.add_argument("--db", default=None, help="path to abyss.db")
    ap.add_argument("--keep-raw", action="store_true", help="keep the downloaded MRF")
    ap.add_argument("--match", default=None,
                    help="only ingest hospitals whose name contains this text")
    args = ap.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)

    failures = 0
    for domain in args.domains:
        try:
            ingest_domain(conn, domain, keep_raw=args.keep_raw, match=args.match)
        except Exception as exc:  # one bad hospital must not abort the rest
            failures += 1
            # The hospital row is written before parsing, so a parse failure
            # would otherwise leave a hospital with no rates showing in the app.
            conn.execute(
                """DELETE FROM hospital WHERE domain = ?
                   AND NOT EXISTS (SELECT 1 FROM rate WHERE hospital_id = hospital.id)""",
                (domain,),
            )
            conn.commit()
            print(f"  FAILED {domain}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    print("\nrebuilding search index...", flush=True)
    db.rebuild_fts(conn)

    # Without statistics SQLite picks idx_rate_estimable over idx_rate_code for
    # a price lookup — estimable=1 matches most of the table while a code
    # matches a few hundred rows. At 25M rows that turned a 0.6 s lookup into
    # 96 s. Invisible at small scale, fatal at real scale.
    print("collecting query statistics...", flush=True)
    conn.execute("ANALYZE")
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM rate").fetchone()[0]
    hospitals = conn.execute("SELECT COUNT(*) FROM hospital").fetchone()[0]
    print(f"done: {total:,} rates across {hospitals} hospitals ({failures} failed)")
    conn.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
