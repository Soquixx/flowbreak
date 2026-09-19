from __future__ import annotations
from pathlib import Path
from playwright.sync_api import Page

EVIDENCE_DIR = (
    Path(__file__).resolve().parent / "evidence"
)

EVIDENCE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

def save_screenshot(
    page: Page,
    filename: str,
) -> str:
    """
    Save a screenshot and return the API-relative URL.
    """
    path = EVIDENCE_DIR / filename

    page.screenshot(
        path=str(path),
        full_page=True,
    )

    return f"/evidence/{filename}"