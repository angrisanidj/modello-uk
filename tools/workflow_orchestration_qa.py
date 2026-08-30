#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"ERROR: {label}: missing {needle!r}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise SystemExit(
            f"ERROR: {label}: forbidden stale orchestration marker {needle!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)

    update = (root / ".github/workflows/update-data.yml").read_text(encoding="utf-8")
    social = (root / ".github/workflows/update-social-cards.yml").read_text(
        encoding="utf-8"
    )
    review = (root / ".github/workflows/review-poll-updates.yml").read_text(
        encoding="utf-8"
    )

    require(update, 'cron: "15 5 * * *"', "production schedule")
    require(social, 'cron: "35 5,17 * * *"', "social-card fallback schedule")
    require(review, 'cron: "5 */3 * * *"', "poll-review schedule")
    require(
        review,
        "gh workflow run update-data.yml --ref main",
        "review→production dispatch",
    )

    require(update, "actions: write", "production workflow permissions")
    trigger = "gh workflow run update-social-cards.yml --ref main"
    require(update, trigger, "production→social explicit dispatch")
    deploy = "- name: Deploy to GitHub Pages"
    require(update, deploy, "production deployment")
    if update.index(trigger) < update.index(deploy):
        raise SystemExit(
            "ERROR: social-card dispatch must happen after the Pages deployment step"
        )

    forbid(social, "workflow_run:", "social-card trigger")
    forbid(social, "github.event.workflow_run", "social-card job condition")

    print("Workflow orchestration QA PASSED")
    print(" - reviewer schedule: every 3h at :05 UTC")
    print(" - production schedule: 05:15 UTC")
    print(" - social fallback schedule: 05:35/17:35 UTC")
    print(" - production→social: explicit workflow_dispatch after successful deploy")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
