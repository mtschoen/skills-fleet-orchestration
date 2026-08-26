"""Shared Chart.js runtime helpers for the plot-*.py scripts.

Holds the Chart.js + date-fns adapter version constants, the CDN/inline
download plumbing, and the HTML-template fill helpers. Each plotter
still owns its own HTML template and chart config; only the bits that
would literally duplicate (and must stay in sync across plotters when
Chart.js updates) live here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CHARTJS_CDN_URL = "https://cdn.jsdelivr.net/npm/chart.js@4"
TIME_ADAPTER_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/"
    "chartjs-adapter-date-fns.bundle.min.js"
)

CHARTJS_INLINE_VERSION = "4.4.7"
CHARTJS_INLINE_URL = (
    f"https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_INLINE_VERSION}/dist/"
    "chart.umd.min.js"
)
TIME_ADAPTER_INLINE_VERSION = "3.0.0"
TIME_ADAPTER_INLINE_URL = (
    f"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@{TIME_ADAPTER_INLINE_VERSION}/"
    "dist/chartjs-adapter-date-fns.bundle.min.js"
)


def cached_download(url: str, cache_filename: str) -> bytes:
    """Return bytes of `url`, caching to ~/.cache/cost-estimator/<cache_filename>."""
    import urllib.request

    cache_directory = Path.home() / ".cache" / "cost-estimator"
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_directory / cache_filename
    if cache_path.is_file():
        return cache_path.read_bytes()
    print(f"  fetching {url} -> {cache_path}", file=sys.stderr)
    with urllib.request.urlopen(url) as response:
        payload = response.read()
    cache_path.write_bytes(payload)
    return payload


def chartjs_script_tags(inline: bool, want_time_adapter: bool) -> tuple[str, str]:
    """Build the (chartjs_script_tag, time_adapter_script_tag) pair.

    With `inline=True`, the returned tags embed the downloaded JS
    bytes directly. With `inline=False`, they reference the CDN URLs.
    If `want_time_adapter=False`, the time adapter tag is the empty
    string.
    """
    if inline:
        chartjs_bytes = cached_download(
            CHARTJS_INLINE_URL,
            f"chart.js-{CHARTJS_INLINE_VERSION}.umd.min.js",
        )
        chartjs_tag = f"<script>{chartjs_bytes.decode('utf-8')}</script>"
    else:
        chartjs_tag = f'<script src="{CHARTJS_CDN_URL}"></script>'

    if not want_time_adapter:
        return chartjs_tag, ""

    if inline:
        adapter_bytes = cached_download(
            TIME_ADAPTER_INLINE_URL,
            f"chartjs-adapter-date-fns-{TIME_ADAPTER_INLINE_VERSION}.bundle.min.js",
        )
        adapter_tag = f"<script>{adapter_bytes.decode('utf-8')}</script>"
    else:
        adapter_tag = f'<script src="{TIME_ADAPTER_CDN_URL}"></script>'

    return chartjs_tag, adapter_tag


def json_for_script(value: object, *, default=None) -> str:
    """JSON-encode a value for embedding inside a <script> block.

    Escapes `</` as `<\\/` so a `</script>` substring inside any string
    field (e.g. a model id like `<synthetic>`) cannot break out of the
    surrounding script element. `<\\/` is valid JSON per RFC 8259.
    """
    return json.dumps(value, default=default).replace("</", "<\\/")


def fill_html_template(template: str, **fields) -> str:
    """Fill an HTML report template with pre-sanitized fields.

    Sanitization happens at the argument site, where the context is
    known: text fields go through html.escape, JSON payloads through
    json_for_script, and markup fields (script tags built from the
    pinned constants above) are inserted as-is.
    """
    return template.format(**fields)
