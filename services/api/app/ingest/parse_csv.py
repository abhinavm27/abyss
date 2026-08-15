"""Parser for the CMS flat-CSV machine-readable file (v2.x / v3.0.0, "tall").

Layout, verified against Boston Medical Center's published file:

    row 0  hospital metadata column names  (hospital_name, last_updated_on, ...)
    row 1  hospital metadata values
    row 2  data column headers
    row 3+ data

Data columns of interest:

    description
    code|1, code|1|type, code|2, code|2|type, ...   (repeating pairs)
    setting, drug_unit_of_measurement, drug_type_of_measurement
    standard_charge|gross, standard_charge|discounted_cash
    payer_name, plan_name
    standard_charge|negotiated_dollar
    standard_charge|negotiated_percentage, standard_charge|negotiated_algorithm
    standard_charge|methodology
    standard_charge|min, standard_charge|max

Both CMS layouts are handled. In the "tall" layout each payer is its own row, so
one CSV row maps to one Rate. The "wide" layout folds payer and plan into the
column names instead (`standard_charge|Aetna|PPO|negotiated_dollar`), giving
every payer its own set of columns — Emerson Hospital publishes 17 payers this
way, 68 columns. One wide row therefore yields up to one Rate per payer.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from typing import BinaryIO, Callable

from .normalize import ParseStats, Rate, norm_code_type, norm_setting, to_float

Opener = Callable[[], BinaryIO]

# `standard_charge|<payer>|<plan>|negotiated_dollar` — the wide layout.
WIDE_COLUMN = re.compile(r"^standard_charge\|.+\|.+\|negotiated_", re.I)

CSV_FIELD_LIMIT = 10 * 1024 * 1024  # attestation cells run to several KB

# Baystate writes "standard_charge | negotiated_dollar" with spaces around the
# pipe, where everyone else writes "standard_charge|negotiated_dollar".
# Stripping only the whole header left those columns unmatched, so three
# Baystate hospitals ingested 2.4 million rows with no price on any of them.
_PIPE_SPACING = re.compile(r"\s*\|\s*")


def _norm_spacing(header: str | None) -> str:
    """Collapse whitespace around pipes, preserving case."""
    return _PIPE_SPACING.sub("|", (header or "").strip())


def _norm_header(header: str | None) -> str:
    """Lookup key for a column: pipe spacing collapsed and lowercased."""
    return _norm_spacing(header).lower()


class WideLayoutUnsupported(RuntimeError):
    """Raised when a wide file cannot be read even by the wide parser."""


def _wide_payers(headers: list[str]) -> dict[tuple[str, str], dict[str, int]]:
    """Map (payer, plan) -> {field: column index} for the wide layout.

    Wide columns are `standard_charge|<payer>|<plan>|<field>`, four
    pipe-separated parts. Emerson Hospital publishes 17 payers this way, which
    is 68 columns; the payer part is occasionally empty (`|​|HPHC`), so it is
    kept as-is rather than assumed present.
    """
    payers: dict[tuple[str, str], dict[str, int]] = {}
    for i, header in enumerate(headers):
        # Case is preserved for the payer and plan, which are displayed to the
        # member and matched against their own plan's payer name.
        parts = _norm_spacing(header).split("|")
        if len(parts) != 4 or parts[0].lower() != "standard_charge":
            continue
        key = (parts[1], parts[2])
        payers.setdefault(key, {})[parts[3].lower()] = i
    return payers


def _text_stream(fh: BinaryIO) -> io.TextIOWrapper:
    # utf-8-sig: several hospitals emit a BOM, which otherwise corrupts the
    # first header cell and silently breaks every column lookup.
    return io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace", newline="")


def read_header(opener: Opener) -> dict:
    """Return the hospital metadata from the first two rows."""
    csv.field_size_limit(CSV_FIELD_LIMIT)
    with opener() as fh:
        reader = csv.reader(_text_stream(fh))
        try:
            keys = next(reader)
            values = next(reader)
        except StopIteration:
            return {}
    header = {}
    for k, v in zip(keys, values):
        k = k.strip()
        # The attestation paragraph is itself a column name; skip anything that
        # is plainly prose rather than a field.
        if not k or len(k) > 80:
            continue
        header[k.lower()] = v.strip()
    return header


def _code_columns(headers: list[str]) -> list[tuple[int, int]]:
    """Find (code_index, type_index) pairs for code|1, code|2, ... ."""
    idx = {_norm_header(h): i for i, h in enumerate(headers)}
    pairs = []
    n = 1
    while True:
        c = idx.get(f"code|{n}")
        t = idx.get(f"code|{n}|type")
        if c is None:
            break
        pairs.append((c, t))
        n += 1
    return pairs


def _pick_code(row: list[str], pairs: list[tuple[int, int]]) -> tuple[str | None, str | None]:
    """Choose the most clinically specific code present on the row."""
    from .parse_json import CODE_PREFERENCE

    found = []
    for c_i, t_i in pairs:
        code = row[c_i].strip() if c_i < len(row) else ""
        ctype = norm_code_type(row[t_i]) if t_i is not None and t_i < len(row) else None
        if code:
            found.append((code, ctype))
    if not found:
        return None, None
    for preferred in CODE_PREFERENCE:
        for code, ctype in found:
            if ctype == preferred:
                return code, ctype
    return found[0]


def parse(opener: Opener, stats: ParseStats) -> Iterator[Rate]:
    csv.field_size_limit(CSV_FIELD_LIMIT)
    with opener() as fh:
        reader = csv.reader(_text_stream(fh))
        try:
            next(reader)  # metadata keys
            next(reader)  # metadata values
            headers = next(reader)
        except StopIteration:
            return

        if any(WIDE_COLUMN.match(h or "") for h in headers):
            yield from _parse_wide(reader, headers, stats)
            return

        idx = {_norm_header(h): i for i, h in enumerate(headers)}
        code_pairs = _code_columns(headers)

        def cell(row: list[str], name: str) -> str | None:
            i = idx.get(name)
            if i is None or i >= len(row):
                return None
            v = row[i].strip()
            return v or None

        if "description" not in idx:
            raise ValueError("CSV has no `description` column; unrecognised layout")

        for row in reader:
            if not row or not any(c.strip() for c in row):
                continue

            code, code_type = _pick_code(row, code_pairs)
            dollar = to_float(cell(row, "standard_charge|negotiated_dollar"))
            methodology = cell(row, "standard_charge|methodology")

            if dollar is None:
                pct = cell(row, "standard_charge|negotiated_percentage")
                algo = cell(row, "standard_charge|negotiated_algorithm")
                if pct or algo:
                    # The hospital published a formula instead of a price. Kept,
                    # flagged non-estimable, never interpolated into a number.
                    stats.skip("non-dollar:percentage" if pct else "non-dollar:algorithm")
                elif cell(row, "payer_name"):
                    stats.skip("payer-row-without-price")

            stats.rows_written += 1
            yield Rate(
                code=code,
                code_type=code_type,
                description=cell(row, "description"),
                setting=norm_setting(cell(row, "setting")),
                billing_class=cell(row, "billing_class"),
                payer_name=cell(row, "payer_name"),
                plan_name=cell(row, "plan_name"),
                methodology=methodology,
                negotiated_dollar=dollar,
                gross_charge=to_float(cell(row, "standard_charge|gross")),
                discounted_cash=to_float(cell(row, "standard_charge|discounted_cash")),
                min_rate=to_float(cell(row, "standard_charge|min")),
                max_rate=to_float(cell(row, "standard_charge|max")),
            )


def _parse_wide(reader, headers: list[str], stats: ParseStats) -> Iterator[Rate]:
    """Read the wide payer-per-column CSV layout.

    Instead of one row per payer, every payer gets its own set of columns and a
    single row carries all of them. One CSV row therefore produces up to one
    Rate per payer — but only for payers that actually priced that line, since
    emitting an empty row for all seventeen would bury the real ones.
    """
    payers = _wide_payers(headers)
    if not payers:
        raise WideLayoutUnsupported("wide layout detected but no payer columns could be parsed")

    idx = {_norm_header(h): i for i, h in enumerate(headers)}
    code_pairs = _code_columns(headers)

    def cell(row: list[str], name: str) -> str | None:
        i = idx.get(name)
        if i is None or i >= len(row):
            return None
        return row[i].strip() or None

    def at(row: list[str], i: int | None) -> str | None:
        if i is None or i >= len(row):
            return None
        return row[i].strip() or None

    if "description" not in idx:
        raise ValueError("CSV has no `description` column; unrecognised layout")

    for row in reader:
        if not row or not any(c.strip() for c in row):
            continue

        code, code_type = _pick_code(row, code_pairs)
        description = cell(row, "description")
        setting = norm_setting(cell(row, "setting"))
        billing_class = cell(row, "billing_class")
        gross = to_float(cell(row, "standard_charge|gross"))
        cash = to_float(cell(row, "standard_charge|discounted_cash"))
        lo = to_float(cell(row, "standard_charge|min"))
        hi = to_float(cell(row, "standard_charge|max"))

        for (payer, plan), fields in payers.items():
            dollar = to_float(at(row, fields.get("negotiated_dollar")))
            pct = at(row, fields.get("negotiated_percentage"))
            algo = at(row, fields.get("negotiated_algorithm"))
            methodology = at(row, fields.get("methodology"))

            # This payer did not price this line at all.
            if dollar is None and not pct and not algo:
                continue

            if dollar is None:
                # Published as a formula rather than a dollar amount — kept,
                # flagged non-estimable, never interpolated into a number.
                stats.skip("non-dollar:percentage" if pct else "non-dollar:algorithm")

            stats.rows_written += 1
            yield Rate(
                code=code,
                code_type=code_type,
                description=description,
                setting=setting,
                billing_class=billing_class,
                payer_name=payer or None,
                plan_name=plan or None,
                methodology=methodology,
                negotiated_dollar=dollar,
                gross_charge=gross,
                discounted_cash=cash,
                min_rate=lo,
                max_rate=hi,
            )
