#!/usr/bin/env python3
"""
Shadow MRP update watcher for modello-UK.

Runs alongside the normal polling-data refresh, but never changes the model and
never promotes an external MRP automatically.  It checks official publication
pages for a newer UK Westminster MRP from the providers we currently care
about (More in Common, YouGov, Focaldata).  When a genuinely newer candidate is
found it can send a one-off email via SMTP and persists a small review queue in
``data/mrp-update-watch.json``.

The network check is deliberately non-fatal in production.  The GitHub Actions
step is also marked continue-on-error; ``--self-test`` is used as the hard code
integrity check.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

V0926_MRP_WATCHER = "shadow-official-provider-discovery-one-shot-email"
V0926_MRP_WATCHER_PROVIDERS = "more-in-common-yougov-focaldata"
V0926_MRP_WATCHER_POLICY = "detect-and-notify-never-auto-adopt"

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "mrp-update-watch.json"
UA = (
    "FocusAmerica-UK-election-model/0.9.26 MRP-shadow-watcher "
    "(+https://angrisanidj.github.io/modello-uk/)"
)

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 1,
    "mode": "shadow_only",
    "policy": "detect_and_notify_never_auto_adopt",
    "providers": {
        "more_in_common": {
            "display_name": "More in Common",
            "baseline_date": "2026-07-19",
            "baseline_title": "The Final MRP of Keir Starmer’s Premiership",
            "baseline_url": "https://www.moreincommon.org.uk/research/the-final-mrp-of-keir-starmers-premiership/",
            "latest_alerted_date": "2026-07-19",
            "latest_alerted_title": "The Final MRP of Keir Starmer’s Premiership",
            "latest_alerted_url": "https://www.moreincommon.org.uk/research/the-final-mrp-of-keir-starmers-premiership/",
        },
        "yougov": {
            "display_name": "YouGov",
            "baseline_date": "2025-09-26",
            "baseline_title": "YouGov MRP shows a Reform UK government a near-certainty if an election were held tomorrow",
            "baseline_url": "https://yougov.com/en-gb/articles/53059-yougov-mrp-shows-a-reform-uk-government-a-near-certainty-if-an-election-were-held-tomorrow",
            "latest_alerted_date": "2025-09-26",
            "latest_alerted_title": "YouGov MRP shows a Reform UK government a near-certainty if an election were held tomorrow",
            "latest_alerted_url": "https://yougov.com/en-gb/articles/53059-yougov-mrp-shows-a-reform-uk-government-a-near-certainty-if-an-election-were-held-tomorrow",
        },
        "focaldata": {
            "display_name": "Focaldata",
            "baseline_date": "2025-02-03",
            "baseline_title": "Focaldata / Hope Not Hate UK general election MRP",
            "baseline_url": "https://www.focaldata.com/blog/focaldata-hope-not-hate-uk-general-election-mrp",
            "latest_alerted_date": "2025-02-03",
            "latest_alerted_title": "Focaldata / Hope Not Hate UK general election MRP",
            "latest_alerted_url": "https://www.focaldata.com/blog/focaldata-hope-not-hate-uk-general-election-mrp",
        },
    },
    "events": {},
}


@dataclass(frozen=True)
class Provider:
    key: str
    display_name: str
    discovery_url: str


PROVIDERS = (
    Provider("more_in_common", "More in Common", "https://www.moreincommon.org.uk/research/"),
    Provider("yougov", "YouGov", "https://yougov.com/search?q=MRP&q_type=articles"),
    Provider("focaldata", "Focaldata", "https://www.focaldata.com/reports"),
)


@dataclass(frozen=True)
class Candidate:
    provider: str
    provider_name: str
    title: str
    published: date
    url: str

    @property
    def fingerprint(self) -> str:
        blob = f"{self.provider}|{self.published.isoformat()}|{self.url}".encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:24]


def _deepcopy_default() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_STATE, ensure_ascii=False))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _deepcopy_default()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        state = _deepcopy_default()
    # Forward-fill provider baselines without erasing review history.
    state.setdefault("schema_version", 1)
    state.setdefault("mode", "shadow_only")
    state.setdefault("policy", "detect_and_notify_never_auto_adopt")
    state.setdefault("providers", {})
    state.setdefault("events", {})
    for key, value in DEFAULT_STATE["providers"].items():
        cur = state["providers"].setdefault(key, {})
        for k, v in value.items():
            cur.setdefault(k, v)
    return state


def write_state_if_changed(path: Path, before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before == after:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def fetch_html(url: str, attempts: int = 3, timeout: int = 25) -> str:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
                timeout=timeout,
            )
            r.raise_for_status()
            text = r.text
            if len(text) < 500:
                raise RuntimeError(f"HTML response too small ({len(text)} chars)")
            return text
        except Exception as exc:  # network is intentionally non-fatal
            last = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_date_text(text: str) -> date | None:
    s = normalize_space(text)
    # ISO date, including datetime prefixes.
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})(?!\d)", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 19 Jul 2026 / 19 July 2026 / 19th July 2026
    m = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(20\d{2})\b",
        s,
        flags=re.I,
    )
    if m:
        mon = MONTHS.get(m.group(2).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                pass

    # September 26, 2025 / February 3, 2025
    m = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b",
        s,
        flags=re.I,
    )
    if m:
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                pass
    return None


def is_westminster_mrp(provider: str, title: str, url: str) -> bool:
    t = normalize_space(title).lower()
    u = url.lower()
    if "mrp" not in t:
        return False

    # Explicit non-Westminster models.  We want a new GB/Westminster geography,
    # not devolved, local, mayoral or foreign MRPs.
    excluded = (
        "holyrood", "scottish parliament", "senedd", "welsh parliament",
        "local election", "local elections", "london local", "london mrp",
        "borough", "mayoral", "australia", "australian", "canada", "canadian",
        "germany", "german", "denmark", "danish", "spain", "spanish",
        "european election", "cost of living groups",
    )
    if any(x in t for x in excluded):
        return False

    if provider == "more_in_common":
        # The MiC research archive is UK-specific.  A title containing MRP is
        # sufficient once devolved/local/foreign models have been excluded.
        # Articles that merely *use* an MRP without announcing one generally do
        # not put MRP in the title, so this catches month-named future releases
        # such as "August MRP" without hard-coding their naming scheme.
        return True

    if provider == "yougov":
        # YouGov search is global.  Require UK political context in addition to
        # MRP to avoid alerts for Canada/Australia/etc.
        uk_context = (
            "reform", "labour", "conservative", "westminster", "uk general election",
            "britain", "election", "parliament",
        )
        return ("/en-gb/" in u or "yougov.co.uk/politics/" in u) and any(x in t for x in uk_context)

    if provider == "focaldata":
        return any(x in t for x in ("uk general election", "westminster", "reform", "labour"))

    return False


def _candidate_date_from_node(node: Any) -> date | None:
    # Search the card/container first, then increasingly broad parents.
    cur = node
    for _ in range(5):
        if cur is None:
            break
        dt = parse_date_text(normalize_space(cur.get_text(" ", strip=True)))
        if dt:
            return dt
        cur = getattr(cur, "parent", None)
    return None


def _date_from_article_page(html: str) -> date | None:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"name": "date"},
        {"name": "publish_date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            dt = parse_date_text(str(tag.get("content")))
            if dt:
                return dt
    for tag in soup.find_all("time"):
        dt = parse_date_text(str(tag.get("datetime") or tag.get_text(" ", strip=True)))
        if dt:
            return dt
    # Keep the fallback bounded to header-ish text so unrelated dates in article
    # copy are less likely to be mistaken for publication dates.
    text = normalize_space(soup.get_text(" ", strip=True))[:5000]
    return parse_date_text(text)


def discover_provider(provider: Provider) -> tuple[list[Candidate], dict[str, Any]]:
    html = fetch_html(provider.discovery_url)
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, Candidate] = {}
    article_fetches = 0

    for a in soup.find_all("a", href=True):
        title = normalize_space(a.get_text(" ", strip=True))
        if len(title) < 8:
            continue
        url = urljoin(provider.discovery_url, str(a.get("href")))
        if not is_westminster_mrp(provider.key, title, url):
            continue
        dt = _candidate_date_from_node(a)
        if dt is None and article_fetches < 12:
            try:
                dt = _date_from_article_page(fetch_html(url, attempts=2, timeout=20))
                article_fetches += 1
            except Exception:
                article_fetches += 1
        if dt is None:
            continue
        c = Candidate(provider.key, provider.display_name, title, dt, url)
        candidates[c.fingerprint] = c

    rows = sorted(candidates.values(), key=lambda c: (c.published, c.title), reverse=True)
    return rows, {
        "provider": provider.key,
        "discovery_url": provider.discovery_url,
        "status": "ok",
        "candidate_count": len(rows),
        "latest_candidate_date": rows[0].published.isoformat() if rows else None,
        "latest_candidate_title": rows[0].title if rows else None,
        "latest_candidate_url": rows[0].url if rows else None,
    }


def smtp_settings() -> dict[str, Any]:
    to_raw = (os.getenv("MRP_ALERT_TO") or "").strip()
    recipients = [x.strip() for x in re.split(r"[,;]", to_raw) if x.strip()]
    username = (os.getenv("MRP_ALERT_SMTP_USERNAME") or "").strip()
    password = os.getenv("MRP_ALERT_SMTP_PASSWORD") or ""
    host = (os.getenv("MRP_ALERT_SMTP_HOST") or "smtp.gmail.com").strip()
    port = int((os.getenv("MRP_ALERT_SMTP_PORT") or "465").strip())
    sender = (os.getenv("MRP_ALERT_FROM") or username).strip()
    return {
        "recipients": recipients,
        "username": username,
        "password": password,
        "host": host,
        "port": port,
        "sender": sender,
        "configured": bool(recipients and username and password and host and sender),
    }


def send_email(candidates: list[Candidate]) -> tuple[bool, str]:
    cfg = smtp_settings()
    if not cfg["configured"]:
        return False, (
            "SMTP not configured: set MRP_ALERT_TO, MRP_ALERT_SMTP_USERNAME and "
            "MRP_ALERT_SMTP_PASSWORD (host/port default to Gmail SMTP)."
        )

    subject_prefix = (os.getenv("MRP_ALERT_SUBJECT_PREFIX") or "[modello-UK]").strip()
    if len(candidates) == 1:
        subject = f"{subject_prefix} nuovo MRP rilevato: {candidates[0].provider_name}"
    else:
        subject = f"{subject_prefix} {len(candidates)} nuovi aggiornamenti MRP rilevati"

    lines = [
        "Il controllo shadow del modello UK ha rilevato un MRP Westminster più recente.",
        "",
        "IMPORTANTE: nessun dato è stato applicato automaticamente al modello.",
        "L'aggiornamento è in attesa di revisione metodologica/manuale.",
        "",
    ]
    for c in candidates:
        lines.extend([
            f"Provider: {c.provider_name}",
            f"Data: {c.published.isoformat()}",
            f"Titolo: {c.title}",
            f"URL: {c.url}",
            "",
        ])
    lines.append("Il watcher viene eseguito in shadow insieme all'aggiornamento dei sondaggi.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(cfg["recipients"])
    msg["Date"] = email.utils.format_datetime(datetime.now(timezone.utc))
    msg.set_content("\n".join(lines))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=30) as smtp:
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)
        return True, "email sent"
    except Exception as exc:
        return False, f"email send failed: {type(exc).__name__}: {exc}"


def append_step_summary(lines: Iterable[str]) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


def run(state_path: Path, dry_run: bool = False) -> int:
    before = load_state(state_path)
    state = json.loads(json.dumps(before, ensure_ascii=False))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    scans: list[dict[str, Any]] = []
    newly_detected: list[Candidate] = []

    for provider in PROVIDERS:
        try:
            rows, meta = discover_provider(provider)
            scans.append(meta)
            pstate = state["providers"][provider.key]
            threshold = date.fromisoformat(str(pstate.get("latest_alerted_date") or pstate["baseline_date"]))
            for c in rows:
                if c.published <= threshold:
                    continue
                event = state["events"].get(c.fingerprint)
                if event and event.get("alert_sent") is True:
                    continue
                newly_detected.append(c)
                if event is None:
                    state["events"][c.fingerprint] = {
                        "provider": c.provider,
                        "provider_name": c.provider_name,
                        "published_date": c.published.isoformat(),
                        "title": c.title,
                        "url": c.url,
                        "first_detected_at_utc": now,
                        "alert_sent": False,
                        "review_status": "pending_manual_review",
                        "auto_applied_to_model": False,
                    }
        except Exception as exc:
            scans.append({
                "provider": provider.key,
                "discovery_url": provider.discovery_url,
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(f"MRP WATCHER warning [{provider.display_name}]: {exc}", file=sys.stderr)

    # Deduplicate candidates across repeated links/cards.
    unique = {c.fingerprint: c for c in newly_detected}
    newly_detected = sorted(unique.values(), key=lambda c: (c.published, c.provider), reverse=True)

    email_ok = False
    email_status = "no new MRP"
    if newly_detected:
        print("MRP WATCHER: NEW WESTMINSTER MRP CANDIDATE(S) DETECTED")
        for c in newly_detected:
            print(f"  - {c.provider_name} | {c.published.isoformat()} | {c.title} | {c.url}")
        if dry_run:
            email_status = "dry-run: email not sent"
        else:
            email_ok, email_status = send_email(newly_detected)
            print("MRP WATCHER email:", email_status)

        if email_ok:
            # Mark each event and advance provider-specific one-shot threshold to
            # the newest successfully alerted MRP. This prevents daily repeats.
            by_provider: dict[str, list[Candidate]] = {}
            for c in newly_detected:
                ev = state["events"][c.fingerprint]
                ev["alert_sent"] = True
                ev["alert_sent_at_utc"] = now
                by_provider.setdefault(c.provider, []).append(c)
            for key, rows in by_provider.items():
                newest = max(rows, key=lambda c: c.published)
                pstate = state["providers"][key]
                pstate["latest_alerted_date"] = newest.published.isoformat()
                pstate["latest_alerted_title"] = newest.title
                pstate["latest_alerted_url"] = newest.url
    else:
        print("MRP WATCHER: no newer UK Westminster MRP detected.")

    # Preserve only meaningful state changes.  Network scan timestamps are not
    # written, so a normal daily check does not generate a pointless git commit.
    changed = False if dry_run else write_state_if_changed(state_path, before, state)

    summary = [
        "### Shadow MRP update watcher",
        "",
        f"- Mode: **shadow only** (never auto-adopts an external MRP)",
        f"- New MRP candidates: **{len(newly_detected)}**",
        f"- Email: **{email_status}**",
        f"- Persistent state changed: **{changed}**",
        "",
        "Provider scans:",
    ]
    for row in scans:
        if row.get("status") == "ok":
            summary.append(
                f"- {row['provider']}: OK; latest visible candidate "
                f"{row.get('latest_candidate_date') or 'n/a'} — {row.get('latest_candidate_title') or 'none'}"
            )
        else:
            summary.append(f"- {row['provider']}: unavailable (non-blocking)")
    if newly_detected:
        summary.extend(["", "Pending manual review:"])
        for c in newly_detected:
            summary.append(f"- {c.provider_name}, {c.published.isoformat()}: {c.title} — {c.url}")
    append_step_summary(summary)
    return 0


def self_test() -> int:
    # Date parsing.
    assert parse_date_text("19 Jul 2026") == date(2026, 7, 19)
    assert parse_date_text("19th July 2026") == date(2026, 7, 19)
    assert parse_date_text("September 26, 2025") == date(2025, 9, 26)
    assert parse_date_text("2026-08-27T10:00:00Z") == date(2026, 8, 27)

    # Positive and negative title classification.
    assert is_westminster_mrp(
        "more_in_common", "The Final MRP of Keir Starmer's Premiership",
        "https://www.moreincommon.org.uk/research/x/",
    )
    assert not is_westminster_mrp(
        "more_in_common", "More in Common's 2026 London MRP",
        "https://www.moreincommon.org.uk/research/x/",
    )
    assert is_westminster_mrp(
        "yougov", "YouGov MRP shows a Reform UK government a near-certainty if an election were held tomorrow",
        "https://yougov.com/en-gb/articles/123-test",
    )
    assert not is_westminster_mrp(
        "yougov", "Final YouGov MRP of the 2026 Holyrood election shows the SNP falling short",
        "https://yougov.com/en-gb/articles/123-test",
    )
    assert is_westminster_mrp(
        "focaldata", "Focaldata / Hope Not Hate UK general election MRP",
        "https://www.focaldata.com/blog/test",
    )

    # Card extraction / date logic using synthetic official-style HTML.
    html = """
    <article><a href='/research/new-final-mrp/'>The Final MRP of a new premiership</a>
    <span>27 Aug 2026</span></article>
    """
    soup = BeautifulSoup(html, "html.parser")
    a = soup.find("a")
    assert a is not None
    assert _candidate_date_from_node(a) == date(2026, 8, 27)

    # State merge keeps current baselines.
    state = load_state(Path("/definitely/not/a/real/state/file.json"))
    assert state["mode"] == "shadow_only"
    assert state["providers"]["more_in_common"]["baseline_date"] == "2026-07-19"

    print("MRP shadow watcher self-test: PASSED")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return run(Path(args.state), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
