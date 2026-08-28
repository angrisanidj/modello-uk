#!/usr/bin/env python3
"""Fail-fast static QA for the modello-UK frontend.

Uses only the Python standard library so it can run in GitHub Actions without
adding frontend dependencies. JavaScript syntax is checked separately by
`node --check` in the workflow.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


class FrontendParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.assets: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "script" and a.get("src"):
            self.assets.append(("script", a["src"]))
        elif tag == "link" and "stylesheet" in a.get("rel", "").split() and a.get("href"):
            self.assets.append(("style", a["href"]))


def local_asset(url: str) -> bool:
    parts = urlsplit(url)
    return not parts.scheme and not parts.netloc and not url.startswith(("data:", "//"))


def cache_version(url: str) -> str | None:
    query = urlsplit(url).query
    for bit in query.split("&"):
        if bit.startswith("v=") and len(bit) > 2:
            return bit[2:]
    return None


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--readme", default="README.md")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    index = root / args.index
    readme = root / args.readme
    errors: list[str] = []

    if not index.is_file():
        print(f"ERROR: missing {index}", file=sys.stderr)
        return 1

    html = index.read_text(encoding="utf-8")
    parser = FrontendParser()
    parser.feed(html)

    duplicates = sorted(k for k, n in Counter(parser.ids).items() if n > 1)
    if duplicates:
        fail(errors, "duplicate HTML ids: " + ", ".join(duplicates))

    required_ids = {
        "refreshBtn", "pollTrendSvg", "pollTrendTooltip", "seatTable",
        "mapWrap", "ukMap", "mapGeoLayoutBtn", "mapHexLayoutBtn",
        "detailName", "detailZoomBtn", "detailCopyBtn",
    }
    missing_ids = sorted(required_ids - set(parser.ids))
    if missing_ids:
        fail(errors, "missing required DOM ids: " + ", ".join(missing_ids))

    local = [(kind, url) for kind, url in parser.assets if local_asset(url)]
    if not local:
        fail(errors, "no local CSS/JS assets found in index.html")

    missing_assets: list[str] = []
    versions: dict[str, str] = {}
    unversioned: list[str] = []
    for kind, url in local:
        rel = urlsplit(url).path.lstrip("/")
        if not (root / rel).is_file():
            missing_assets.append(rel)
        if rel.endswith((".css", ".js")):
            ver = cache_version(url)
            if ver is None:
                unversioned.append(url)
            else:
                versions[url] = ver
    if missing_assets:
        fail(errors, "missing local assets referenced by index.html: " + ", ".join(sorted(set(missing_assets))))
    if unversioned:
        fail(errors, "local CSS/JS without ?v= cache-buster: " + ", ".join(unversioned))

    unique_versions = sorted(set(versions.values()))
    if len(unique_versions) != 1:
        fail(errors, "inconsistent CSS/JS cache versions: " + repr(unique_versions))
    elif readme.is_file():
        text = readme.read_text(encoding="utf-8")
        m = re.search(r"UI v(\d+\.\d+\.\d+)", text)
        if not m:
            fail(errors, "README does not expose a parseable 'UI vX.Y.Z' version")
        elif m.group(1) != unique_versions[0]:
            fail(errors, f"README UI version {m.group(1)} != asset cache version {unique_versions[0]}")

    expected_scripts = {"scripts/app.js", "scripts/map-performance.js", "scripts/interpretation.js"}
    referenced_scripts = {urlsplit(url).path.lstrip("/") for kind, url in local if kind == "script"}
    missing_scripts = sorted(expected_scripts - referenced_scripts)
    if missing_scripts:
        fail(errors, "required scripts not referenced by index.html: " + ", ".join(missing_scripts))

    app_path = root / "scripts/app.js"
    if app_path.is_file():
        app = app_path.read_text(encoding="utf-8")
        accessibility_markers = (
            'tabindex="-1" role="button"',
            "$('#ukMap').addEventListener('keydown'",
            "event.key==='Enter'||event.key===' '",
        )
        for marker in accessibility_markers:
            if marker not in app:
                fail(errors, f"map keyboard accessibility regression: missing {marker!r}")

    if errors:
        print("Frontend QA FAILED", file=sys.stderr)
        for e in errors:
            print(f" - {e}", file=sys.stderr)
        return 1

    print("Frontend QA PASSED")
    print(f" - HTML ids: {len(parser.ids)} unique")
    print(f" - local CSS/JS assets: {len(local)}")
    if unique_versions:
        print(f" - cache/UI version: {unique_versions[0]}")
    print(" - constituency map: keyboard contract present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
