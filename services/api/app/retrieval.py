"""Finding the right price row.

Exact-code lookup first, lexical search second. Deliberately not embeddings:
the join key here is a billing code, and a semantically-near-but-wrong match
(pricing a shoulder MRI when the user asked about a knee) is worse than
returning nothing in a product whose whole claim is price accuracy.

`resolve` gives a deterministic path from plain language to a code, so the app
still answers common questions when the language model is unavailable.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from statistics import median

# Consumer phrasing -> HCPCS. Every code here was verified present and priced
# in the ingested data; this is a grounded shortcut list, not a guess at what a
# code set ought to contain. The language model handles anything not listed.
PROCEDURE_ALIASES: dict[str, str] = {
    "mri knee": "73721",
    "knee mri": "73721",
    "mri of knee": "73721",
    "mri lower extremity joint": "73721",
    "mri brain": "70551",
    "brain mri": "70551",
    "head mri": "70551",
    "mri lumbar spine": "72148",
    "mri lower back": "72148",
    "back mri": "72148",
    "ct abdomen pelvis": "74177",
    "ct scan abdomen": "74177",
    "cat scan abdomen": "74177",
    "colonoscopy": "45378",
    "office visit": "99213",
    "doctor visit": "99213",
}

CODE_IN_TEXT = re.compile(r"\b(\d{4,5}|[A-Z]\d{4})\b")

# FTS5 treats these as operators; a raw user phrase must be sanitised first.
FTS_UNSAFE = re.compile(r"[^\w\s]")

# Dropped before alias matching so "MRI of my knee" reduces to {mri, knee}.
STOPWORDS = {
    "a", "an", "the", "of", "my", "for", "is", "it", "to", "on", "in", "at",
    "what", "whats", "how", "much", "does", "do", "cost", "costs", "price",
    "me", "i", "would", "will", "much", "about", "get", "getting", "have",
    "need", "scan", "test", "much", "pay", "paying", "with", "and",
}


def _tokens(text: str) -> set[str]:
    return {t for t in FTS_UNSAFE.sub(" ", text.lower()).split() if t and t not in STOPWORDS}


@dataclass
class Resolution:
    """The outcome of mapping plain language to a billing code.

    `confident` is the important field. A lexical-search hit is a *suggestion*:
    charge descriptions are terse and supply-heavy, so searching "knee" finds
    implant hardware long before it finds imaging. Pricing an unconfident match
    produces a confident, fully-cited answer to a question the user did not ask,
    which is the worst failure this system can have. Those go back as candidates
    for the user to confirm instead.
    """

    code: str | None
    code_type: str | None
    how: str
    confident: bool
    candidates: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []


@dataclass
class HospitalPrice:
    hospital_id: int
    hospital: str
    address: str | None
    mrf_url: str | None
    source_page_url: str | None
    last_updated_on: str | None
    description: str | None
    code: str
    code_type: str | None
    count: int
    low: float
    typical: float
    high: float

    def as_dict(self) -> dict:
        return {
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "description": self.description,
            "code": self.code,
            "code_type": self.code_type,
            "address": self.address,
            "rate_count": self.count,
            "low": round(self.low, 2),
            "typical": round(self.typical, 2),
            "high": round(self.high, 2),
            "citation": {
                "mrf_url": self.mrf_url,
                "source_page_url": self.source_page_url,
                "last_updated_on": self.last_updated_on,
            },
        }


def normalise_query(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def resolve_code(conn: sqlite3.Connection, query: str) -> Resolution:
    """Map a plain-language query to a billing code.

    Order: explicit code in the text, then the alias table (token-based, so
    "MRI of my knee" matches "mri knee"), then lexical search — the last of
    which is returned unconfident, as candidates.
    """
    for candidate in CODE_IN_TEXT.findall(query.upper()):
        # Deliberately not filtered to estimable rows: a code that exists but is
        # formula-priced must still resolve, so the caller can say *why* there
        # is no price rather than claiming the code is unknown.
        row = conn.execute(
            "SELECT code, code_type FROM rate WHERE code = ? LIMIT 1", (candidate,)
        ).fetchone()
        if row:
            return Resolution(row["code"], row["code_type"], "code-in-query", True)

    q_tokens = _tokens(query)
    best: tuple[int, str] | None = None
    for phrase, code in PROCEDURE_ALIASES.items():
        p_tokens = _tokens(phrase)
        if p_tokens and p_tokens <= q_tokens:
            if best is None or len(p_tokens) > best[0]:
                best = (len(p_tokens), code)
    if best:
        return Resolution(best[1], "HCPCS", "alias", True)

    hits = search(conn, query, limit=5)
    if hits:
        return Resolution(
            hits[0]["code"], hits[0]["code_type"], "text-search", False, candidates=hits
        )

    return Resolution(None, None, "unresolved", False)


def search(conn: sqlite3.Connection, text: str, limit: int = 10) -> list[dict]:
    """Lexical search over charge descriptions.

    A fallback, not the primary path — descriptions are terse and clinical
    ("Mri jnt of lwr extre w/o dye"), so this matches far better on hardware and
    supply lines than on the words a patient would actually say.
    """
    words = [t for t in _tokens(text) if len(t) > 2]
    if not words:
        return []

    # Ranked by BM25, not by how many contract rows a code happens to have.
    # Ordering by row count made the most *common* items win over the most
    # relevant ones — "lower extremity" returned antibiotics, because ubiquitous
    # drug lines outnumber imaging lines by orders of magnitude.
    # bm25() is only usable in a query directly against the FTS table, so the
    # ranking happens in a CTE and the join comes after. The inner LIMIT keeps
    # this bounded over 1.4M rows while still spanning plenty of distinct codes.
    sql = """WITH hits AS (
               SELECT rowid, bm25(rate_fts) AS relevance
               FROM rate_fts WHERE rate_fts MATCH ?
               ORDER BY relevance LIMIT 4000
             )
             SELECT r.code, r.code_type, r.description,
                    COUNT(*) n, MIN(h.relevance) AS relevance
             FROM hits h JOIN rate r ON r.id = h.rowid
             WHERE r.estimable = 1 AND r.code IS NOT NULL
             GROUP BY r.code, r.code_type
             ORDER BY relevance
             LIMIT ?"""

    # Require every word first; fall back to any-word only if that finds nothing.
    joiners = [" AND ", " OR "] if len(words) > 1 else [" AND "]
    for joiner in joiners:
        try:
            rows = conn.execute(sql, (joiner.join(words), limit)).fetchall()
        except sqlite3.OperationalError:
            continue
        if rows:
            return [dict(r) for r in rows]
    return []


def prices_for_code(
    conn: sqlite3.Connection, code: str, code_type: str | None = None
) -> list[HospitalPrice]:
    """Per-hospital price summary for one billing code.

    Only estimable rows are aggregated — formula-priced rows carry no dollar
    figure and must not influence a min, max or median.
    """
    sql = """SELECT r.hospital_id, h.name, h.address, h.mrf_url, h.source_page_url,
                    h.last_updated_on,
                    r.code, r.code_type, r.description, r.negotiated_dollar
             FROM rate r JOIN hospital h ON h.id = r.hospital_id
             WHERE r.code = ? AND r.estimable = 1"""
    params: list = [code]
    if code_type:
        sql += " AND r.code_type = ?"
        params.append(code_type)

    grouped: dict[int, list] = {}
    meta: dict[int, sqlite3.Row] = {}
    for row in conn.execute(sql, params):
        grouped.setdefault(row["hospital_id"], []).append(row["negotiated_dollar"])
        meta.setdefault(row["hospital_id"], row)

    out: list[HospitalPrice] = []
    for hid, values in grouped.items():
        m = meta[hid]
        out.append(
            HospitalPrice(
                hospital_id=hid,
                hospital=m["name"],
                address=m["address"],
                mrf_url=m["mrf_url"],
                source_page_url=m["source_page_url"],
                last_updated_on=m["last_updated_on"],
                description=m["description"],
                code=m["code"],
                code_type=m["code_type"],
                count=len(values),
                low=min(values),
                typical=median(values),
                high=max(values),
            )
        )
    out.sort(key=lambda p: p.typical)
    return out


def billed_reference(conn: sqlite3.Connection, code: str, hospital_id: int | None = None):
    """What one hospital (or all of them) publishes for a code, for bill checking.

    Returns the negotiated spread, the gross charge and the cash price
    separately — never blended. A bill's "total charges" line is the gross
    charge, while what an insurer actually allows is the negotiated rate, and
    the two differ by multiples. Comparing one against the other is the easiest
    way to tell somebody they were overcharged when they were not.
    """
    where = "WHERE r.code = ?"
    params: list = [code]
    if hospital_id is not None:
        where += " AND r.hospital_id = ?"
        params.append(hospital_id)

    row = conn.execute(
        f"""SELECT COUNT(r.negotiated_dollar) AS n,
                   MIN(r.negotiated_dollar)   AS lo,
                   MAX(r.negotiated_dollar)   AS hi,
                   AVG(r.negotiated_dollar)   AS avg_rate,
                   MIN(r.gross_charge)        AS gross_lo,
                   MAX(r.gross_charge)        AS gross_hi,
                   MIN(r.discounted_cash)     AS cash_lo,
                   MAX(r.discounted_cash)     AS cash_hi,
                   MAX(r.description)         AS description
            FROM rate r
            {where} AND r.estimable = 1 AND r.negotiated_dollar > 0""",
        params,
    ).fetchone()
    if not row or not row["n"]:
        return None

    rates = [
        r[0]
        for r in conn.execute(
            f"""SELECT r.negotiated_dollar FROM rate r
                {where} AND r.estimable = 1 AND r.negotiated_dollar > 0
                ORDER BY r.negotiated_dollar""",
            params,
        ).fetchall()
    ]
    return {
        "count": row["n"],
        "low": row["lo"],
        "high": row["hi"],
        "median": _median(rates),
        "gross_low": row["gross_lo"],
        "gross_high": row["gross_hi"],
        "cash_low": row["cash_lo"],
        "cash_high": row["cash_hi"],
        "description": row["description"],
        "rates": rates,
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2


def cost_share_for(
    conn: sqlite3.Connection, catalog_conn: sqlite3.Connection | None,
    qhp_plan_id: str | None, code: str,
):
    """The member's plan rule for the category this billing code falls under.

    Returns None when no plan is linked or when the code cannot be classified —
    the estimator then falls back to the blended deductible/coinsurance the
    member typed in. That fallback is normal for employer coverage, which is
    never in the marketplace files.

    Use `cost_share_status` rather than this alone when the caller needs to know
    *why* it got None. A plan that carries per-service rules but has none for
    this code is a different situation from a plan that only has a blended rate,
    and conflating them understates what the member owes.
    """
    return cost_share_status(conn, catalog_conn, qhp_plan_id, code)[0]


def cost_share_status(
    conn: sqlite3.Connection, catalog_conn: sqlite3.Connection | None,
    qhp_plan_id: str | None, code: str,
):
    """(cost_share, status) where status is one of:

    `applied`      — a rule for this exact service was found and used.
    `no_plan`      — nothing is linked, so the blended figures are all there is.
    `unclassified` — the plan has per-service rules but this code maps to no
                     category, so none of them apply.
    `uncovered`    — the code maps to a category the plan has no rule for.

    `plan_benefit` (per-service rules parsed from an SBC) lives in the member's
    own state database; `rate` (code_type/setting, to classify the code) lives
    in the hospital knowledge catalog. `conn` and `catalog_conn` are usually two
    different SQLite files, not two handles on the same one.
    """
    if not qhp_plan_id:
        return None, "no_plan"

    from .estimator import ServiceCostShare
    from .ingest.qhp import category_for_code

    # The code system and the setting both change the answer: a DRG is an
    # inpatient stay, and the same surgical CPT is a different benefit depending
    # on where it happens. Indexed by idx_rate_code, so this is a point lookup.
    row = None
    if catalog_conn is not None:
        row = catalog_conn.execute(
            "SELECT code_type, setting FROM rate WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
    category = category_for_code(
        code,
        row["code_type"] if row else None,
        row["setting"] if row else None,
    )
    if not category:
        return None, "unclassified"

    rule = conn.execute(
        "SELECT kind, amount, after_deductible FROM plan_benefit WHERE plan_id = ? AND category = ?",
        (qhp_plan_id, category),
    ).fetchone()
    if not rule or rule["kind"] == "unknown":
        return None, "uncovered"

    return (
        ServiceCostShare(
            kind=rule["kind"],
            amount=rule["amount"],
            after_deductible=bool(rule["after_deductible"]),
            category=category,
        ),
        "applied",
    )


def formula_priced_count(conn: sqlite3.Connection, code: str) -> int:
    """How many payers publish this code as a formula rather than a dollar.

    Surfaced to the user so a thin result reads as "the hospital didn't publish
    a price" rather than "ABYSS couldn't find one".
    """
    return conn.execute(
        "SELECT COUNT(*) FROM rate WHERE code = ? AND estimable = 0 AND payer_name IS NOT NULL",
        (code,),
    ).fetchone()[0]


def cash_prices_for_code(conn: sqlite3.Connection, code: str) -> list[dict]:
    """Discounted cash prices — what an uninsured or out-of-network patient pays."""
    rows = conn.execute(
        """SELECT h.name AS hospital, MIN(r.discounted_cash) lo, MAX(r.discounted_cash) hi
           FROM rate r JOIN hospital h ON h.id = r.hospital_id
           WHERE r.code = ? AND r.discounted_cash IS NOT NULL AND r.discounted_cash > 0
           GROUP BY h.id ORDER BY lo""",
        (code,),
    ).fetchall()
    return [{"hospital": r["hospital"], "low": round(r["lo"], 2), "high": round(r["hi"], 2)} for r in rows]
