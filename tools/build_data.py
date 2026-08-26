#!/usr/bin/env python3
"""Build static data files for the UK election model.

Sources:
- Polls: English Wikipedia via MediaWiki API
- 2024 constituency results: House of Commons Library candidate CSV
- Boundaries: ONS ArcGIS FeatureServer, July 2024 BGC (20m generalised)
- Display map: additionally generates a much lighter simplified GeoJSON

Designed for GitHub Actions. It deliberately keeps data acquisition separate from
model logic so the client can fall back to the last valid snapshot.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

POLL_PAGE = "Opinion_polling_for_the_next_United_Kingdom_general_election"
MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
RESULTS_CSV = "https://researchbriefings.files.parliament.uk/documents/CBP-10009/HoC-GE2024-results-by-candidate.csv"
ONS_GEOJSON = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC/"
    "FeatureServer/0/query"
)
UA = "FocusAmerica-UK-election-model/0.5 (+https://angrisanidj.github.io/)"

PARTY_MAP = {
    "lab": "lab", "labour": "lab", "labour party": "lab", "labour and co-operative party": "lab",
    "labour co-op": "lab", "labour (co-op)": "lab",
    "con": "con", "conservative": "con", "conservative party": "con",
    "ld": "ld", "liberal democrat": "ld", "liberal democrats": "ld",
    "ruk": "ref", "ref": "ref", "reform uk": "ref",
    "green": "green", "green party": "green", "scottish green party": "green",
    "snp": "snp", "scottish national party": "snp",
    "pc": "pc", "plaid cymru": "pc",
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def get(url: str, **kwargs: Any) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", UA)
    r = requests.get(url, headers=headers, timeout=45, **kwargs)
    r.raise_for_status()
    return r


def pct(text: str) -> float | None:
    text = text.replace("−", "-").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        return None
    return float(m.group(0))


def clean_text(node: Any) -> str:
    return " ".join(node.stripped_strings).replace("\xa0", " ").strip()


def end_date(fieldwork: str, year: int) -> str | None:
    """Convert e.g. '23–24 Aug', '30 Jul – 4 Aug' to ISO end date."""
    txt = fieldwork.replace("—", "–").replace("−", "–")
    matches = list(re.finditer(r"(\d{1,2})\s+([A-Za-z]{3,9})", txt))
    if not matches:
        # compact range such as 23–24 Aug: capture trailing day before month
        m = re.search(r"(?:\d{1,2}\s*[–-]\s*)?(\d{1,2})\s+([A-Za-z]{3,9})", txt)
        if not m:
            return None
        day = int(m.group(1)); mon = MONTHS.get(m.group(2)[:3].lower())
    else:
        day = int(matches[-1].group(1)); mon = MONTHS.get(matches[-1].group(2)[:3].lower())
    if mon is None:
        return None
    try:
        return datetime(year, mon, day).date().isoformat()
    except ValueError:
        return None


def table_headers(table: Any) -> list[str]:
    tr = table.find("tr")
    if not tr:
        return []
    return [clean_text(c) for c in tr.find_all(["th", "td"])]


def canonical_header(h: str) -> str:
    h = h.lower().replace("\n", " ")
    h = re.sub(r"\[[^\]]+\]", "", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def parse_poll_table(table: Any, year: int) -> list[dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [canonical_header(x) for x in table_headers(table)]
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        if "date" in h and "conduct" in h: idx["date"] = i
        elif h == "pollster": idx["pollster"] = i
        elif h == "client": idx["client"] = i
        elif h == "area": idx["area"] = i
        elif "sample" in h: idx["sample"] = i
        elif h == "lab": idx["lab"] = i
        elif h == "con": idx["con"] = i
        elif h in {"ref", "reform"}: idx["ref"] = i
        elif h in {"ld", "lib dem"}: idx["ld"] = i
        elif h in {"grn", "green"}: idx["green"] = i
        elif h == "snp": idx["snp"] = i
        elif h in {"pc", "plaid"}: idx["pc"] = i
        elif h == "rb": idx["rb"] = i
        elif h.startswith("other"): idx["other"] = i
    required = {"date", "pollster", "area", "lab", "con", "ref", "ld", "green"}
    if not required.issubset(idx):
        return []

    out = []
    for tr in rows[1:]:
        cells = [clean_text(c) for c in tr.find_all(["th", "td"], recursive=False)]
        if len(cells) < max(idx.values()) + 1:
            continue
        fwork = cells[idx["date"]]
        iso = end_date(fwork, year)
        if not iso:
            continue  # skips event rows
        pollster = cells[idx["pollster"]]
        if not pollster or "election" in pollster.lower() or "by-election" in pollster.lower():
            continue
        record: dict[str, Any] = {
            "date": iso,
            "fieldwork": fwork,
            "pollster": re.sub(r"\s*\[[^]]+\]\s*", "", pollster).strip(),
            "client": cells[idx["client"]] if "client" in idx else "",
            "area": cells[idx["area"]].upper(),
            "sample": int((pct(cells[idx["sample"]]) or 0)) if "sample" in idx else 0,
        }
        for p in ("lab", "con", "ref", "ld", "green", "snp", "pc", "rb", "other"):
            record[p] = pct(cells[idx[p]]) if p in idx else None
        if all(record[p] is None for p in ("lab", "con", "ref", "ld", "green")):
            continue
        out.append(record)
    return out


def fetch_polls() -> list[dict[str, Any]]:
    params = {"action": "parse", "page": POLL_PAGE, "prop": "text", "format": "json"}
    payload = get(MEDIAWIKI_API, params=params).json()
    html = payload["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "html.parser")
    current_year: int | None = None
    in_national = False
    polls: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name in {"h2", "h3", "h4"}:
            title = clean_text(el)
            if "National poll results" in title:
                in_national = True
                continue
            if in_national and el.name == "h2" and "National poll results" not in title:
                in_national = False
            m = re.fullmatch(r"(20\d{2})", re.sub(r"\[edit\]", "", title).strip())
            if in_national and m:
                current_year = int(m.group(1))
            continue
        if not in_national or current_year is None:
            continue
        for rec in parse_poll_table(el, current_year):
            key = (rec["date"], rec["pollster"], rec.get("sample"), rec.get("lab"), rec.get("con"), rec.get("ref"))
            if key not in seen:
                seen.add(key); polls.append(rec)

    polls.sort(key=lambda x: x["date"], reverse=True)
    if len(polls) < 20:
        raise RuntimeError(f"Only {len(polls)} national polls parsed; refusing to overwrite a valid snapshot")
    return polls



def infer_recent_end_date(fieldwork: str) -> str | None:
    """Parse a subnational fieldwork date, inferring year only for recent rows."""
    now = datetime.now(timezone.utc).date()
    m = re.search(r"\b(20\d{2})\b", fieldwork)
    years = [int(m.group(1))] if m else [now.year, now.year - 1]
    for year in years:
        iso = end_date(fieldwork, year)
        if not iso:
            continue
        d = datetime.fromisoformat(iso).date()
        if d <= now + timedelta(days=35) and d >= now - timedelta(days=550):
            return iso
    return None


def parse_subnational_table(table: Any, country: str) -> list[dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [canonical_header(x) for x in table_headers(table)]
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        if "date" in h and "conduct" in h: idx["date"] = i
        elif h == "pollster": idx["pollster"] = i
        elif h == "client": idx["client"] = i
        elif "sample" in h: idx["sample"] = i
        elif h == "lab": idx["lab"] = i
        elif h == "con": idx["con"] = i
        elif h in {"ref", "reform"}: idx["ref"] = i
        elif h in {"ld", "lib dem", "lib dems"}: idx["ld"] = i
        elif h in {"grn", "green"}: idx["green"] = i
        elif h == "snp": idx["snp"] = i
        elif h in {"pc", "plaid", "plaid cymru"}: idx["pc"] = i
        elif h == "rb": idx["rb"] = i
        elif h == "alba": idx["other_extra"] = i
        elif h.startswith("other"): idx["other"] = i

    if "date" not in idx or "pollster" not in idx:
        return []
    party_cols = {"lab", "con", "ref", "ld", "green", "snp", "pc"} & set(idx)
    if len(party_cols) < 4:
        return []

    out: list[dict[str, Any]] = []
    for tr in rows[1:]:
        cells = [clean_text(c) for c in tr.find_all(["th", "td"], recursive=False)]
        if len(cells) < max(idx.values()) + 1:
            continue
        fwork = cells[idx["date"]]
        iso = infer_recent_end_date(fwork)
        if not iso:
            continue
        pollster = cells[idx["pollster"]]
        if not pollster or "election" in pollster.lower() or "by-election" in pollster.lower():
            continue
        rec: dict[str, Any] = {
            "country": country,
            "area": country.upper(),
            "date": iso,
            "fieldwork": fwork,
            "pollster": re.sub(r"\s*\[[^]]+\]\s*", "", pollster).strip(),
            "client": cells[idx["client"]] if "client" in idx else "",
            "sample": int((pct(cells[idx["sample"]]) or 0)) if "sample" in idx else 0,
        }
        for p in ("lab", "con", "ref", "ld", "green", "snp", "pc", "rb", "other"):
            rec[p] = pct(cells[idx[p]]) if p in idx else None
        if "other_extra" in idx:
            extra = pct(cells[idx["other_extra"]])
            if extra is not None:
                rec["other"] = (rec["other"] or 0.0) + extra
        out.append(rec)
    return out


def fetch_subnational_polls() -> list[dict[str, Any]]:
    """Read Westminster polling for Scotland and Wales from the main polling page."""
    params = {"action": "parse", "page": POLL_PAGE, "prop": "text", "format": "json"}
    payload = get(MEDIAWIKI_API, params=params).json()
    soup = BeautifulSoup(payload["parse"]["text"]["*"], "html.parser")
    in_subnational = False
    country: str | None = None
    polls: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name in {"h2", "h3", "h4"}:
            title = re.sub(r"\[edit\]", "", clean_text(el), flags=re.I).strip()
            if el.name == "h2":
                if "Sub-national poll results" in title:
                    in_subnational = True
                    country = None
                    continue
                if in_subnational:
                    break
            if in_subnational and title in {"Scotland", "Wales"}:
                country = title
            continue
        if not in_subnational or country not in {"Scotland", "Wales"}:
            continue
        for rec in parse_subnational_table(el, country):
            key = (rec["country"], rec["date"], rec["pollster"], rec.get("sample"),
                   rec.get("lab"), rec.get("con"), rec.get("ref"), rec.get("snp"), rec.get("pc"))
            if key not in seen:
                seen.add(key)
                polls.append(rec)

    polls.sort(key=lambda x: x["date"], reverse=True)
    counts = Counter(p["country"] for p in polls)
    if counts.get("Scotland", 0) < 2 or counts.get("Wales", 0) < 2:
        raise RuntimeError(f"Subnational polling parse too small: {dict(counts)}")
    return polls


def territorial_zone(item: dict[str, Any]) -> str:
    country = (item.get("country") or "").strip()
    if country == "Scotland":
        return "Scotland"
    if country == "Wales":
        return "Wales"
    if country == "England":
        return (item.get("region") or "England").strip() or "England"
    return country or "Other"


def build_territorial_baseline(constituencies: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the certified 2024 constituency baseline by country and English region."""
    groups: dict[str, dict[str, Any]] = {}

    def add(group: str, item: dict[str, Any]) -> None:
        g = groups.setdefault(group, {"valid_votes": 0, "seats": 0, "party_votes": defaultdict(float)})
        vv = int(item.get("valid_votes") or 0)
        if vv <= 0:
            return
        g["valid_votes"] += vv
        g["seats"] += 1
        pv = item.get("party_votes") or {}
        if pv:
            for p, v in pv.items():
                g["party_votes"][p] += float(v)
        else:
            for p, share in (item.get("shares") or {}).items():
                g["party_votes"][p] += vv * float(share) / 100.0

    for item in constituencies:
        country = (item.get("country") or "").strip()
        if country == "Northern Ireland":
            continue
        add("GB", item)
        add(country, item)
        if country == "England":
            add(territorial_zone(item), item)

    out_groups: dict[str, Any] = {}
    for name, g in groups.items():
        total = float(g["valid_votes"])
        shares = {
            p: round(float(v) / total * 100.0, 5)
            for p, v in g["party_votes"].items()
            if total > 0
        }
        out_groups[name] = {
            "valid_votes": int(g["valid_votes"]),
            "seats": int(g["seats"]),
            "shares": shares,
        }

    gb_votes = out_groups.get("GB", {}).get("valid_votes", 0)
    country_weights = {}
    if gb_votes:
        for country in ("England", "Scotland", "Wales"):
            country_weights[country] = round(
                out_groups.get(country, {}).get("valid_votes", 0) / gb_votes, 8
            )

    english_regions = sorted(
        name for name in out_groups
        if name not in {"GB", "England", "Scotland", "Wales"}
    )
    if len(english_regions) != 9:
        raise RuntimeError(f"Expected 9 English regions, got {english_regions}")

    return {
        "groups": out_groups,
        "country_vote_weights": country_weights,
        "english_regions": english_regions,
    }


def map_party(abbrev: str, full: str) -> str:
    a = (abbrev or "").strip().lower()
    f = (full or "").strip().lower()
    return PARTY_MAP.get(a) or PARTY_MAP.get(f) or "other"


def fetch_constituencies() -> list[dict[str, Any]]:
    text = get(RESULTS_CSV).content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    grouped: dict[str, dict[str, Any]] = {}
    for row in reader:
        ons = (row.get("ONS ID") or "").strip()
        if not ons:
            continue
        item = grouped.setdefault(ons, {
            "id": ons,
            "name": (row.get("Constituency name") or "").strip(),
            "region": (row.get("Region name") or "").strip(),
            "country": (row.get("Country name") or "").strip(),
            "shares": defaultdict(float),
            "candidates": [],
        })
        # Commons Library stores Share as a fraction (e.g. 0.488696 = 48.8696%).
        # Use votes as the source of truth and keep the reported share only as a
        # cross-check. This avoids unit mistakes if the CSV format is ever reused.
        reported_share = pct(row.get("Share", ""))
        if reported_share is not None and abs(reported_share) <= 1.000001:
            reported_share *= 100.0
        votes = int((pct(row.get("Votes", "")) or 0))
        pid = map_party(row.get("Party abbreviation", ""), row.get("Party name", ""))
        item["candidates"].append({
            "party": pid,
            "party_name": (row.get("Party name") or "").strip(),
            "candidate": " ".join(filter(None, [(row.get("Candidate first name") or "").strip(), (row.get("Candidate surname") or "").strip()])),
            "votes": votes,
            "reported_share": reported_share,
        })

    out: list[dict[str, Any]] = []
    for item in grouped.values():
        candidates = sorted(item.pop("candidates"), key=lambda x: x["votes"], reverse=True)
        total_votes = sum(c["votes"] for c in candidates)
        if total_votes <= 0:
            raise RuntimeError(f"No valid votes found for {item['name']} ({item['id']})")

        shares: defaultdict[str, float] = defaultdict(float)
        party_votes: defaultdict[str, int] = defaultdict(int)
        for candidate in candidates:
            share = candidate["votes"] / total_votes * 100.0
            party_votes[candidate["party"]] += candidate["votes"]
            reported = candidate.pop("reported_share", None)
            if reported is not None and abs(reported - share) > 0.25:
                raise RuntimeError(
                    f"Share validation failed for {item['name']}: "
                    f"reported={reported:.3f} derived={share:.3f}"
                )
            candidate["share"] = round(share, 3)
            shares[candidate["party"]] += share

        item.pop("shares", None)
        item["shares"] = {k: round(v, 3) for k, v in shares.items()}
        item["valid_votes"] = total_votes
        item["party_votes"] = dict(party_votes)
        share_total = sum(item["shares"].values())
        if not 99.5 <= share_total <= 100.5:
            raise RuntimeError(
                f"Vote shares for {item['name']} sum to {share_total:.3f}, expected about 100"
            )

        item["winner2024"] = candidates[0]["party"] if candidates else "other"
        item["winner2024_name"] = candidates[0]["party_name"] if candidates else ""
        item["winner2024_candidate"] = candidates[0]["candidate"] if candidates else ""
        item["majority2024"] = (candidates[0]["votes"] - candidates[1]["votes"]) if len(candidates) > 1 else 0
        item["top_candidates_2024"] = candidates[:4]
        out.append(item)

    out.sort(key=lambda x: x["name"])
    if len(out) != 650:
        raise RuntimeError(f"Expected 650 constituencies, got {len(out)}")

    # Hard integrity checks against the certified 2024 result. With the party
    # mapping used by the model, all Northern Ireland parties, independents and
    # the Speaker are grouped as 'other'. If this changes, stop the build rather
    # than silently feeding a bad baseline into the forecast.
    expected_winners = {
        "lab": 411, "con": 121, "ld": 72, "snp": 9, "ref": 5,
        "green": 4, "pc": 4, "other": 24,
    }
    actual_winners = Counter(item["winner2024"] for item in out)
    actual_compact = {k: actual_winners.get(k, 0) for k in expected_winners}
    if actual_compact != expected_winners or sum(actual_winners.values()) != 650:
        raise RuntimeError(
            f"2024 winner validation failed: expected {expected_winners}, got {dict(actual_winners)}"
        )

    gb_count = sum(1 for item in out if "northern ireland" not in item["country"].lower())
    if gb_count != 632:
        raise RuntimeError(f"Expected 632 GB constituencies and 18 NI, got GB={gb_count}, NI={650-gb_count}")

    return out


def fetch_geometry() -> dict[str, Any]:
    params = {
        "where": "1=1", "outFields": "*", "returnGeometry": "true",
        "outSR": "4326", "f": "geojson",
    }
    geo = get(ONS_GEOJSON, params=params).json()
    if geo.get("type") != "FeatureCollection" or len(geo.get("features", [])) < 650:
        raise RuntimeError("ONS GeoJSON did not return the expected 650+ features")
    return geo



MAP_SIMPLIFY_TOLERANCE = 0.0025  # degrees; ~sub-pixel at the dashboard map scale
MAP_COORD_DECIMALS = 5


def _sq_seg_dist(p: list[float], a: list[float], b: list[float]) -> float:
    """Squared 2D distance from p to segment a-b in lon/lat space."""
    x, y = a[0], a[1]
    dx, dy = b[0] - x, b[1] - y
    if dx or dy:
        t = ((p[0] - x) * dx + (p[1] - y) * dy) / (dx * dx + dy * dy)
        if t > 1:
            x, y = b[0], b[1]
        elif t > 0:
            x += dx * t
            y += dy * t
    dx, dy = p[0] - x, p[1] - y
    return dx * dx + dy * dy


def _simplify_open(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Iterative Douglas-Peucker: avoids recursion on long coastline rings."""
    n = len(points)
    if n <= 2:
        return points[:]
    sq_tol = tolerance * tolerance
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        first, last = stack.pop()
        max_dist = sq_tol
        index = -1
        a, b = points[first], points[last]
        for i in range(first + 1, last):
            d = _sq_seg_dist(points[i], a, b)
            if d > max_dist:
                index, max_dist = i, d
        if index >= 0:
            keep[index] = True
            if index - first > 1:
                stack.append((first, index))
            if last - index > 1:
                stack.append((index, last))
    return [p for i, p in enumerate(points) if keep[i]]


def _round_point(p: list[float]) -> list[float]:
    return [round(float(p[0]), MAP_COORD_DECIMALS), round(float(p[1]), MAP_COORD_DECIMALS)]


def _simplify_ring(ring: list[list[float]]) -> list[list[float]]:
    if len(ring) <= 5:
        return [_round_point(p) for p in ring]
    closed = ring[0][:2] == ring[-1][:2]
    core = ring[:-1] if closed else ring[:]
    if len(core) < 4:
        return [_round_point(p) for p in ring]

    # Treat a ring as a closed chain by rotating to a stable point far from the
    # centroid, then simplify the two arcs separately. This avoids the usual
    # Douglas-Peucker problem where identical first/last points collapse a ring.
    cx = sum(p[0] for p in core) / len(core)
    cy = sum(p[1] for p in core) / len(core)
    anchor = max(range(len(core)), key=lambda i: (core[i][0]-cx)**2 + (core[i][1]-cy)**2)
    rotated = core[anchor:] + core[:anchor]
    half = max(2, len(rotated)//2)
    a = _simplify_open(rotated[:half+1], MAP_SIMPLIFY_TOLERANCE)
    b = _simplify_open(rotated[half:] + [rotated[0]], MAP_SIMPLIFY_TOLERANCE)
    simplified = a[:-1] + b[:-1]

    # A polygon ring needs at least three unique vertices + closure.
    unique = []
    for p in simplified:
        if not unique or p[:2] != unique[-1][:2]:
            unique.append(p)
    if len(unique) < 3:
        unique = core
    rounded = [_round_point(p) for p in unique]
    if rounded[0] != rounded[-1]:
        rounded.append(rounded[0][:])
    return rounded


def _vertex_count_geometry(geom: dict[str, Any] | None) -> int:
    if not geom:
        return 0
    if geom.get("type") == "Polygon":
        return sum(len(r) for r in geom.get("coordinates", []))
    if geom.get("type") == "MultiPolygon":
        return sum(len(r) for p in geom.get("coordinates", []) for r in p)
    return 0


def simplify_geometry_for_web(geo: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Create a minimal-property, reduced-vertex map file for browser rendering."""
    before = 0
    after = 0
    features = []
    for feature in geo.get("features", []):
        geom = feature.get("geometry") or {}
        before += _vertex_count_geometry(geom)
        typ = geom.get("type")
        if typ == "Polygon":
            coords = [_simplify_ring(r) for r in geom.get("coordinates", [])]
        elif typ == "MultiPolygon":
            coords = [[_simplify_ring(r) for r in poly] for poly in geom.get("coordinates", [])]
        else:
            coords = geom.get("coordinates", [])
        new_geom = {"type": typ, "coordinates": coords}
        after += _vertex_count_geometry(new_geom)

        props = feature.get("properties") or {}
        code = (
            props.get("PCON24CD") or props.get("PCON24CDH")
            or props.get("PCONCD") or props.get("GSS_CODE")
            or props.get("code") or props.get("id") or ""
        )
        name = (
            props.get("PCON24NM") or props.get("PCONNM")
            or props.get("NAME") or props.get("name") or ""
        )
        features.append({
            "type": "Feature",
            "properties": {"PCON24CD": code, "PCON24NM": name},
            "geometry": new_geom,
        })

    if len(features) < 650:
        raise RuntimeError(f"Simplified map has only {len(features)} features")
    if before and after >= before:
        raise RuntimeError("Map simplification did not reduce the vertex count")

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "source": "ONS BGC 20m; display-only simplification by build_data.py",
            "tolerance_degrees": MAP_SIMPLIFY_TOLERANCE,
            "coordinate_decimals": MAP_COORD_DECIMALS,
            "vertices_before": before,
            "vertices_after": after,
        },
    }, {"vertices_before": before, "vertices_after": after}

def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> int:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    status: dict[str, Any] = {"generated_at": stamp}
    successes = 0

    try:
        polls = fetch_polls()
        write_json(DATA / "polls.json", {
            "meta": {"source": "Wikipedia / MediaWiki API", "generated_at": stamp, "fallback": False},
            "polls": polls,
        })
        status["polls"] = len(polls); successes += 1
    except Exception as exc:
        status["polls_error"] = str(exc)
        print(f"warning: polls not refreshed: {exc}", file=sys.stderr)

    try:
        subnational = fetch_subnational_polls()
        write_json(DATA / "subnational-polls.json", {
            "meta": {
                "source": "Wikipedia / MediaWiki API — Westminster sub-national polls",
                "generated_at": stamp,
                "countries": ["Scotland", "Wales"],
            },
            "polls": subnational,
        })
        sub_counts = Counter(p["country"] for p in subnational)
        status["subnational_polls"] = dict(sub_counts)
        successes += 1
    except Exception as exc:
        status["subnational_polls_error"] = str(exc)
        print(f"warning: subnational polls not refreshed: {exc}", file=sys.stderr)

    try:
        constituencies = fetch_constituencies()
        write_json(DATA / "constituencies-2024.json", {
            "meta": {"source": "House of Commons Library CBP-10009", "generated_at": stamp, "generated": True},
            "constituencies": constituencies,
        })
        territorial = build_territorial_baseline(constituencies)
        territorial["meta"] = {
            "source": "House of Commons Library CBP-10009, aggregated from 2024 valid votes",
            "generated_at": stamp,
        }
        write_json(DATA / "territorial-baseline.json", territorial)
        status["constituencies"] = len(constituencies)
        status["english_regions"] = len(territorial.get("english_regions", []))
        successes += 1
    except Exception as exc:
        status["constituencies_error"] = str(exc)
        print(f"warning: constituencies not refreshed: {exc}", file=sys.stderr)

    try:
        geo = fetch_geometry()
        geo["meta"] = {"source": "ONS — Westminster Parliamentary Constituencies (July 2024) BGC", "generated_at": stamp}
        write_json(DATA / "constituencies-2024.geojson", geo)

        display_geo, map_stats = simplify_geometry_for_web(geo)
        display_geo["meta"]["generated_at"] = stamp
        write_json(DATA / "constituencies-map.geojson", display_geo)

        status["features"] = len(geo.get("features", []))
        status["map_features"] = len(display_geo.get("features", []))
        status.update(map_stats)
        status["map_display_bytes"] = (DATA / "constituencies-map.geojson").stat().st_size
        status["map_full_bytes"] = (DATA / "constituencies-2024.geojson").stat().st_size
        successes += 1
    except Exception as exc:
        status["geometry_error"] = str(exc)
        print(f"warning: geometry not refreshed: {exc}", file=sys.stderr)

    write_json(DATA / "build-meta.json", status)
    if successes == 0:
        raise RuntimeError("No source could be refreshed; existing snapshots were left untouched")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build_data.py failed: {exc}", file=sys.stderr)
        raise
