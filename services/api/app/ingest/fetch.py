"""Locate and download a hospital's machine-readable file.

CMS requires hospitals to publish a pointer file at the root of their domain
(https://<domain>/cms-hpt.txt) naming the MRF's URL. That indirection is what
lets ABYSS add a hospital by domain name alone.
"""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from pathlib import Path

import httpx

USER_AGENT = "abyss-price-transparency/0.1 (+public MRF ingest)"
TIMEOUT = httpx.Timeout(30.0, read=120.0)


def _ssl_context() -> ssl.SSLContext:
    """TLS context that reaches real hospital web servers.

    Two accommodations, neither of which weakens verification:

    * The operating system's trust store is used instead of Python's bundled
      one. baystatehealth.org presents a chain macOS trusts but certifi does
      not, so `curl` reached it and httpx raised CERTIFICATE_VERIFY_FAILED.
      Matching the OS is what a browser does.
    * Legacy renegotiation is permitted. Several hosts (ajh.org among them) run
      stacks that require it, and OpenSSL 3 refuses by default.

    Certificates are still fully verified either way.
    """
    try:
        import truststore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # fall back to the bundled roots
        ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    return ctx


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        verify=_ssl_context(),
    )


@dataclass
class HptPointer:
    location_name: str | None
    source_page_url: str | None
    mrf_url: str
    domain: str


def _parse_hpt(text: str, domain: str) -> list[HptPointer]:
    """Parse a cms-hpt.txt into one pointer per hospital.

    A health system publishes every one of its hospitals in a single file:
    Mass General Brigham and Beth Israel Lahey list 14 each, UMass Memorial 9,
    Tufts 5, Baystate 4. The lines repeat in blocks — location-name,
    source-page-url, mrf-url, contact details — so a new block starts whenever a
    key that has already been seen appears again.

    Reading only the first block, as this used to, meant ingesting one hospital
    out of fourteen and silently believing that was the whole system.
    """
    pointers: list[HptPointer] = []
    current: dict[str, str] = {}

    def flush() -> None:
        url = current.get("mrf-url", "").strip()
        if url:
            pointers.append(
                HptPointer(
                    location_name=current.get("location-name") or None,
                    source_page_url=current.get("source-page-url") or None,
                    mrf_url=url,
                    domain=domain,
                )
            )

    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("_", "-")
        if key in current:  # a repeated key means the next hospital has begun
            flush()
            current = {}
        current[key] = value.strip()
    flush()

    if not pointers:
        raise ValueError(f"{domain}: cms-hpt.txt has no mrf-url line")
    return pointers


def discover(domain: str) -> list[HptPointer]:
    """Read <domain>/cms-hpt.txt and return every hospital it lists."""
    domain = domain.strip().replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{domain}/cms-hpt.txt"
    with _client() as c:
        r = c.get(url)
        r.raise_for_status()
        return _parse_hpt(r.text, domain)


def download(url: str, dest: Path, on_progress=None) -> int:
    """Stream a URL to disk, returning bytes written.

    Streamed rather than held in memory: this machine has ~11 GB free and some
    MRFs are hundreds of MB compressed. The caller is responsible for deleting
    `dest` once parsed.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with _client() as c:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
                    total += len(chunk)
                    if on_progress:
                        on_progress(total)
    return total


def guess_ein(url: str) -> str | None:
    """CMS names MRFs `<ein>_<hospital-name>_standardcharges.<ext>`."""
    m = re.search(r"/(\d{9})_", url)
    return m.group(1) if m else None
