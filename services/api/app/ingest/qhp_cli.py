"""`abyss-qhp [--states MA,RI]` — load marketplace plans and their cost sharing.

Downloads the two CMS Public Use Files, streams them straight out of the zips,
and deletes the archives. Restricting to a few states keeps the table small;
without `--states` it loads all 50, which is still only ~300k benefit rows.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from .. import db
from . import fetch, qhp

PUF_BASE = "https://download.cms.gov/marketplace-puf"
BATCH = 5_000


def ingest(conn, year: str, states: set[str] | None) -> None:
    with tempfile.TemporaryDirectory(prefix="abyss-qhp-") as tmp:
        tmpdir = Path(tmp)

        attrs = tmpdir / "plan-attributes.zip"
        print(f"  downloading plan attributes ({year})...", flush=True)
        size = fetch.download(f"{PUF_BASE}/{year}/plan-attributes-puf.zip", attrs)
        print(f"  {size / 1e6:.1f} MB", flush=True)

        conn.execute("DELETE FROM qhp_plan")
        batch: list[tuple] = []
        n_plans = 0
        for row in qhp.parse_plan_attributes(attrs, states):
            batch.append(row)
            n_plans += 1
            if len(batch) >= BATCH:
                conn.executemany(
                    """INSERT OR REPLACE INTO qhp_plan (plan_id, state, issuer_id, issuer_name,
                         marketing_name, metal_level, plan_type, hsa_eligible, deductible,
                         deductible_family, oop_max, oop_max_family, business_year)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    batch,
                )
                batch.clear()
        if batch:
            conn.executemany(
                """INSERT OR REPLACE INTO qhp_plan (plan_id, state, issuer_id, issuer_name,
                     marketing_name, metal_level, plan_type, hsa_eligible, deductible,
                     deductible_family, oop_max, oop_max_family, business_year)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                batch,
            )
        conn.commit()
        attrs.unlink()
        print(f"  {n_plans:,} plans", flush=True)

        bencs = tmpdir / "bencs.zip"
        print("  downloading benefits and cost sharing...", flush=True)
        size = fetch.download(f"{PUF_BASE}/{year}/benefits-and-cost-sharing-puf.zip", bencs)
        print(f"  {size / 1e6:.1f} MB (375 MB unzipped, streamed)", flush=True)

        conn.execute("DELETE FROM plan_benefit")
        batch.clear()
        n_benefits = 0
        for row in qhp.parse_benefits(bencs, states):
            batch.append(row)
            n_benefits += 1
            if len(batch) >= BATCH:
                conn.executemany(
                    """INSERT OR REPLACE INTO plan_benefit
                       (plan_id, category, kind, amount, after_deductible, covered, excluded_from_oop)
                       VALUES (?,?,?,?,?,?,?)""",
                    batch,
                )
                batch.clear()
                if n_benefits % 100_000 < BATCH:
                    print(f"  {n_benefits:,} benefit rows...", flush=True)
        if batch:
            conn.executemany(
                """INSERT OR REPLACE INTO plan_benefit
                   (plan_id, category, kind, amount, after_deductible, covered, excluded_from_oop)
                   VALUES (?,?,?,?,?,?,?)""",
                batch,
            )
        conn.commit()
        bencs.unlink()
        print(f"  {n_benefits:,} benefit rows", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest CMS QHP marketplace plan data")
    ap.add_argument("--year", default="2026")
    ap.add_argument("--states", default=None, help="comma-separated, e.g. MA,RI,NH")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)

    states = {s.strip().upper() for s in args.states.split(",")} if args.states else None
    conn = db.connect(args.db)
    db.init_db(conn)

    print(f"=== QHP {args.year}" + (f" ({', '.join(sorted(states))})" if states else " (all states)") + " ===")
    ingest(conn, args.year, states)

    plans = conn.execute("SELECT COUNT(*) FROM qhp_plan").fetchone()[0]
    priced = conn.execute(
        "SELECT COUNT(DISTINCT plan_id) FROM plan_benefit WHERE kind IN ('copay','coinsurance','no_charge')"
    ).fetchone()[0]
    print(f"done: {plans:,} plans, {priced:,} with usable cost sharing")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
