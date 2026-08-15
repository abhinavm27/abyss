"""Streaming parser for the CMS JSON machine-readable file (v2.x / v3.0.0).

Shape, verified against Anna Jaques Hospital's published file:

    { "hospital_name": ..., "last_updated_on": ..., "version": "3.0.0",
      "standard_charge_information": [
        { "description": ...,
          "code_information": [ {"code": "1664", "type": "APR-DRG"} ],
          "standard_charges": [
            { "setting": "inpatient", "billing_class": "facility",
              "minimum": 129919.64, "maximum": 129919.64,
              "gross_charge": ..., "discounted_cash": ...,
              "payers_information": [
                { "payer_name": "Bcbs", "plan_name": "All Commercial Plans",
                  "methodology": "fee schedule",
                  "standard_charge_dollar": 129919.64 } ] } ] } ] }

Streamed with ijson rather than json.load: these files reach hundreds of MB and
this machine is short on both RAM headroom and disk.
"""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from typing import BinaryIO, Callable

import ijson

from .normalize import ParseStats, Rate, norm_code_type, norm_setting, to_float

# Parsers take an opener rather than a path so the same code streams a plain
# file or a member inside a zip. BMC's CSV is 483 MB uncompressed; extracting it
# to disk first is not an option on this machine.
Opener = Callable[[], BinaryIO]

# When a record carries several codes (a CPT plus a revenue code, say), price it
# under the most clinically specific one. Users and the model both ask in these
# terms; revenue and local chargemaster codes are bookkeeping.
CODE_PREFERENCE = ["HCPCS", "MS-DRG", "APR-DRG", "NDC", "ICD", "CDM", "REV"]


class _BomStripped:
    """Drop a leading UTF-8 BOM from a binary stream.

    Anna Jaques (and others) emit a BOM before the opening brace. ijson is a
    strict lexer and rejects it outright. The CSV path gets this for free from
    the `utf-8-sig` codec; the JSON path has to do it by hand.

    Only `read`/`close` are implemented — all ijson needs.
    """

    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh
        head = fh.read(3)
        self._pending = b"" if head == codecs.BOM_UTF8 else head

    def read(self, size: int = -1) -> bytes:
        if not self._pending:
            return self._fh.read(size)
        if size is None or size < 0:
            data, self._pending = self._pending + self._fh.read(), b""
            return data
        if len(self._pending) >= size:
            data, self._pending = self._pending[:size], self._pending[size:]
            return data
        data = self._pending + self._fh.read(size - len(self._pending))
        self._pending = b""
        return data

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_header(opener: Opener) -> dict:
    """Pull the top-level metadata without loading the charge array.

    Walks the event stream and stops at `standard_charge_information`. Only
    top-level scalars are kept, so nested blocks (attestation, license) are
    skipped by the dotted-prefix test.
    """
    header: dict = {}
    with _BomStripped(opener()) as fh:
        for prefix, event, value in ijson.parse(fh, use_float=True):
            if prefix == "standard_charge_information" and event == "start_array":
                break
            if event in ("string", "number", "boolean") and prefix and "." not in prefix:
                header[prefix] = value
            elif prefix == "hospital_address.item" and event == "string":
                header.setdefault("hospital_address", value)
    return header


def _primary_code(code_information: list | None) -> tuple[str | None, str | None]:
    if not code_information:
        return None, None
    candidates = []
    for entry in code_information:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        ctype = norm_code_type(entry.get("type"))
        if code:
            candidates.append((str(code).strip(), ctype))
    if not candidates:
        return None, None
    for preferred in CODE_PREFERENCE:
        for code, ctype in candidates:
            if ctype == preferred:
                return code, ctype
    return candidates[0]


def parse(opener: Opener, stats: ParseStats) -> Iterator[Rate]:
    """Yield one Rate per payer entry, plus one per charge block that has none.

    A charge block with no `payers_information` still carries gross and cash
    prices (common for drug/NDC lines), which are useful to an uninsured or
    high-deductible patient, so it is kept with a null payer.
    """
    with _BomStripped(opener()) as fh:
        for item in ijson.items(fh, "standard_charge_information.item", use_float=True):
            if not isinstance(item, dict):
                stats.skip("record-not-object")
                continue

            description = item.get("description")
            code, code_type = _primary_code(item.get("code_information"))
            charges = item.get("standard_charges") or []
            if not charges:
                stats.skip("no-standard-charges")
                continue

            for charge in charges:
                if not isinstance(charge, dict):
                    stats.skip("charge-not-object")
                    continue

                setting = norm_setting(charge.get("setting"))
                billing_class = charge.get("billing_class")
                gross = to_float(charge.get("gross_charge"))
                cash = to_float(charge.get("discounted_cash"))
                lo = to_float(charge.get("minimum"))
                hi = to_float(charge.get("maximum"))

                payers = charge.get("payers_information") or []
                if not payers:
                    if gross is None and cash is None:
                        stats.skip("no-payer-and-no-price")
                        continue
                    stats.rows_written += 1
                    yield Rate(
                        code=code,
                        code_type=code_type,
                        description=description,
                        setting=setting,
                        billing_class=billing_class,
                        payer_name=None,
                        plan_name=None,
                        methodology=None,
                        negotiated_dollar=None,
                        gross_charge=gross,
                        discounted_cash=cash,
                        min_rate=lo,
                        max_rate=hi,
                    )
                    continue

                for payer in payers:
                    if not isinstance(payer, dict):
                        stats.skip("payer-not-object")
                        continue
                    dollar = to_float(payer.get("standard_charge_dollar"))
                    methodology = payer.get("methodology")
                    if dollar is None:
                        # Legitimate: CMS lets hospitals publish a formula
                        # instead of a dollar figure. Kept, flagged non-estimable.
                        stats.skip(f"non-dollar:{str(methodology or 'unspecified').lower()}")
                    stats.rows_written += 1
                    yield Rate(
                        code=code,
                        code_type=code_type,
                        description=description,
                        setting=setting,
                        billing_class=billing_class,
                        payer_name=payer.get("payer_name"),
                        plan_name=payer.get("plan_name"),
                        methodology=methodology,
                        negotiated_dollar=dollar,
                        gross_charge=gross,
                        discounted_cash=cash,
                        min_rate=lo,
                        max_rate=hi,
                    )
