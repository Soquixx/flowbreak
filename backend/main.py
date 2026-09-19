from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from playwright.sync_api import sync_playwright


app = FastAPI(
    title="FlowBreak API",
    description="Autonomous web application failure hunter",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    url: HttpUrl


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/scan")
def scan_website(request: ScanRequest) -> dict[str, Any]:
    url = str(request.url)

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="Only HTTP and HTTPS URLs are supported.",
        )

    console_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()

            def handle_console(message) -> None:
                if message.type == "error":
                    console_errors.append(message.text)

            def handle_request_failed(request_event) -> None:
                failed_requests.append(
                    {
                        "url": request_event.url,
                        "method": request_event.method,
                        "failure": request_event.failure,
                    }
                )

            page.on("console", handle_console)
            page.on("requestfailed", handle_request_failed)

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            title = page.title()
            final_url = page.url

            links = page.locator("a").evaluate_all(
                """
                elements => elements.map(a => ({
                    text: (a.innerText || a.textContent || "").trim(),
                    href: a.href
                })).filter(x => x.href)
                """
            )

            buttons = page.locator("button").evaluate_all(
                """
                elements => elements.map(button => ({
                    text: (
                        button.innerText ||
                        button.textContent ||
                        ""
                    ).trim(),
                    type: button.type || "button"
                }))
                """
            )

            forms = page.locator("form").count()

            inputs = page.locator(
                "input, textarea, select"
            ).count()

            screenshot_path = "scan_result.png"

            page.screenshot(
                path=screenshot_path,
                full_page=True,
            )

            browser.close()

            return {
                "success": True,
                "target_url": url,
                "final_url": final_url,
                "title": title,
                "status_code": response.status if response else None,
                "links": links[:100],
                "buttons": buttons[:100],
                "forms": forms,
                "interactive_inputs": inputs,
                "console_errors": console_errors,
                "failed_requests": failed_requests,
                "screenshot": screenshot_path,
            }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Scan failed: {exc}",
        ) from exc