from __future__ import annotations
from typing import Any
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from playwright.sync_api import sync_playwright
from evidence import EVIDENCE_DIR, save_screenshot
from issue_engine import build_issues

app = FastAPI(
    title="FlowBreak API",
    description="Autonomous web application failure hunter",
    version="0.2.0",
)

app.mount(
    "/evidence",
    StaticFiles(directory=EVIDENCE_DIR),
    name="evidence",
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


class ExploreRequest(BaseModel):
    url: HttpUrl
    max_actions: int = 25


def validate_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400,
            detail="Only HTTP and HTTPS URLs are supported.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# BASIC SCANNER

@app.post("/api/scan")
def scan_website(
    request: ScanRequest,
) -> dict[str, Any]:

    url = str(request.url)
    validate_url(url)

    console_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True
            )

            page = browser.new_page()

            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )

            page.on(
                "requestfailed",
                lambda request_event: failed_requests.append(
                    {
                        "url": request_event.url,
                        "method": request_event.method,
                        "failure": request_event.failure,
                    }
                ),
            )

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            title = page.title()
            final_url = page.url

            links = page.locator(
                "a"
            ).evaluate_all(
                """
                elements => elements
                    .map(a => ({
                        text: (
                            a.innerText ||
                            a.textContent ||
                            ""
                        ).trim(),
                        href: a.href
                    }))
                    .filter(x => x.href)
                """
            )

            buttons = page.locator(
                "button"
            ).evaluate_all(
                """
                elements => elements
                    .map(button => ({
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
                "status_code": (
                    response.status
                    if response
                    else None
                ),
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

# OBSERVERS
def attach_observers(
    page,
    console_errors: list[str],
    page_errors: list[str],
    failed_requests: list[dict[str, Any]],
    http_errors: list[dict[str, Any]],
) -> None:

    def handle_console(message) -> None:
        if message.type == "error":
            console_errors.append(message.text)

    def handle_page_error(error) -> None:
        page_errors.append(str(error))

    def handle_request_failed(
        request_event,
    ) -> None:

        failed_requests.append(
            {
                "url": request_event.url,
                "method": request_event.method,
                "failure": request_event.failure,
            }
        )

    def handle_response(response) -> None:

        if response.status >= 400:
            http_errors.append(
                {
                    "url": response.url,
                    "method": response.request.method,
                    "status": response.status,
                    "status_text": response.status_text,
                }
            )

    page.on(
        "console",
        handle_console,
    )

    page.on(
        "pageerror",
        handle_page_error,
    )

    page.on(
        "requestfailed",
        handle_request_failed,
    )

    page.on(
        "response",
        handle_response,
    )

# ACTION RESULT
def make_action_result(
    action_type: str,
    description: str,
    start_url: str,
    page,
    console_errors: list[str],
    page_errors: list[str],
    failed_requests: list[dict[str, Any]],
    http_errors: list[dict[str, Any]],
    action_error: str | None = None,
) -> dict[str, Any]:

    problems: list[str] = []

    if action_error:
        problems.append(action_error)

    if console_errors:
        problems.append(
            f"{len(console_errors)} console error(s)"
        )

    if page_errors:
        problems.append(
            f"{len(page_errors)} page error(s)"
        )

    if failed_requests:
        problems.append(
            f"{len(failed_requests)} failed request(s)"
        )

    if http_errors:
        problems.append(
            f"{len(http_errors)} HTTP error response(s)"
        )

    failed = len(problems) > 0

    return {
        "action_type": action_type,
        "description": description,
        "start_url": start_url,
        "end_url": page.url,
        "status": (
            "FAIL"
            if failed
            else "PASS"
        ),
        "problems": problems,
        "evidence": {
            "console_errors": console_errors,
            "page_errors": page_errors,
            "failed_requests": failed_requests,
            "http_errors": http_errors,
            "action_error": action_error,
        },
    }

# BUTTON EXPLORATION

def explore_button(
    browser,
    target_url: str,
    button_index: int,
    button_text: str,
) -> dict[str, Any]:

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []
    http_errors: list[dict[str, Any]] = []

    page = browser.new_page()

    attach_observers(
        page,
        console_errors,
        page_errors,
        failed_requests,
        http_errors,
    )

    action_error = None

    try:
        page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        buttons = page.get_by_role(
            "button",
            name=button_text,
        )

        if buttons.count() == 0:
            action_error = (
                "Button disappeared during exploration."
            )
        else:
            buttons.first.click(
                timeout=5_000
            )

            page.wait_for_timeout(1_000)

    except Exception as exc:
        action_error = str(exc)

    result = make_action_result(
        action_type="button",
        description=(
            f'Click button "{button_text}"'
        ),
        start_url=target_url,
        page=page,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        http_errors=http_errors,
        action_error=action_error,
    )

    if result["status"] == "FAIL":
        try:
            screenshot_url = save_screenshot(
                page,
                f"button_{button_index + 1:03d}.png",
            )

            result["evidence"]["screenshot"] = (
                screenshot_url
            )

        except Exception:
            pass

    page.close()

    return result

# LINK EXPLORATION

def explore_link(
    browser,
    target_url: str,
    link_index: int,
    link_text: str,
    href: str,
) -> dict[str, Any]:

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []
    http_errors: list[dict[str, Any]] = []

    page = browser.new_page()

    attach_observers(
        page,
        console_errors,
        page_errors,
        failed_requests,
        http_errors,
    )

    action_error = None

    try:
        page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        links = page.get_by_role(
            "link",
            name=link_text,
        )

        if links.count() == 0:
            action_error = (
                "Link disappeared during exploration."
            )
        else:
            links.first.click(
                timeout=5_000
            )

            page.wait_for_timeout(1_000)

    except Exception as exc:
        action_error = str(exc)

    result = make_action_result(
        action_type="link",
        description=(
            f'Click link "{link_text}"'
        ),
        start_url=target_url,
        page=page,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        http_errors=http_errors,
        action_error=action_error,
    )

    if result["status"] == "FAIL":
        try:
            screenshot_url = save_screenshot(
                page,
                f"link_{link_index + 1:03d}.png",
            )

            result["evidence"]["screenshot"] = (
                screenshot_url
            )

        except Exception:
            pass

    page.close()

    return result
# FORM EXPLORATION

def explore_form(
    browser,
    target_url: str,
    form_index: int,
) -> dict[str, Any]:

    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, Any]] = []
    http_errors: list[dict[str, Any]] = []

    page = browser.new_page()

    attach_observers(
        page,
        console_errors,
        page_errors,
        failed_requests,
        http_errors,
    )

    action_error = None

    try:
        page.goto(
            target_url,
            wait_until="domcontentloaded",
            timeout=30_000,
        )

        forms = page.locator("form")

        if forms.count() <= form_index:
            action_error = (
                "Form disappeared during exploration."
            )

        else:
            form = forms.nth(form_index)

            for input_element in form.locator(
                "input, textarea, select"
            ).all():

                try:
                    tag_name = input_element.evaluate(
                        "(element) => "
                        "element.tagName.toLowerCase()"
                    )

                    if tag_name == "select":
                        options = input_element.locator(
                            "option"
                        )

                        if options.count() > 0:
                            input_element.select_option(
                                index=0
                            )

                        continue

                    input_type = (
                        input_element.get_attribute(
                            "type"
                        )
                        or "text"
                    )

                    if input_type in {
                        "hidden",
                        "submit",
                        "button",
                        "reset",
                        "checkbox",
                        "radio",
                        "file",
                    }:
                        continue

                    if input_type == "email":
                        value = (
                            "flowbreak@example.com"
                        )

                    elif input_type == "password":
                        value = "FlowBreak123!"

                    elif tag_name == "textarea":
                        value = "123 Test Street"

                    elif input_type == "search":
                        value = "laptop"

                    else:
                        value = "test"

                    input_element.fill(value)

                except Exception:
                    continue

            submit_button = form.locator(
                "button[type='submit'], "
                "input[type='submit']"
            )

            if submit_button.count() > 0:
                submit_button.first.click(
                    timeout=5_000
                )

            else:
                form.press(
                    "Enter",
                    timeout=5_000,
                )

            page.wait_for_timeout(1_000)

    except Exception as exc:
        action_error = str(exc)

    result = make_action_result(
        action_type="form",
        description=(
            f"Submit form #{form_index + 1}"
        ),
        start_url=target_url,
        page=page,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        http_errors=http_errors,
        action_error=action_error,
    )

    if result["status"] == "FAIL":
        try:
            screenshot_url = save_screenshot(
                page,
                f"form_{form_index + 1:03d}.png",
            )

            result["evidence"]["screenshot"] = (
                screenshot_url
            )

        except Exception:
            pass

    page.close()

    return result

# AUTONOMOUS EXPLORER

@app.post("/api/explore")
def explore_website(
    request: ExploreRequest,
) -> dict[str, Any]:

    target_url = str(request.url)
    validate_url(target_url)

    max_actions = max(
        1,
        min(request.max_actions, 50),
    )

    results: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:

            browser = playwright.chromium.launch(
                headless=True
            )

            # Initial discovery

            discovery_page = browser.new_page()

            discovery_page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            buttons = (
                discovery_page
                .locator("button:visible")
                .evaluate_all(
                    """
                    elements => elements
                        .map((button, index) => ({
                            index,
                            text: (
                                button.innerText ||
                                button.textContent ||
                                ""
                            ).trim()
                        }))
                        .filter(x => x.text)
                    """
                )
            )

            links = (
                discovery_page
                .locator("a:visible")
                .evaluate_all(
                    """
                    elements => elements
                        .map((a, index) => ({
                            index,
                            text: (
                                a.innerText ||
                                a.textContent ||
                                ""
                            ).trim(),
                            href: a.href
                        }))
                        .filter(x => x.text && x.href)
                    """
                )
            )

            form_count = (
                discovery_page
                .locator("form")
                .count()
            )

            discovery_page.close()

            actions_run = 0

            # Explore buttons
            for button in buttons:

                if actions_run >= max_actions:
                    break

                result = explore_button(
                    browser=browser,
                    target_url=target_url,
                    button_index=actions_run,
                    button_text=button["text"],
                )

                results.append(result)
                actions_run += 1
            # Explore internal links

            target_host = urlparse(
                target_url
            ).netloc

            for link in links:

                if actions_run >= max_actions:
                    break

                link_host = urlparse(
                    link["href"]
                ).netloc

                if (
                    link_host
                    and link_host != target_host
                ):
                    continue

                result = explore_link(
                    browser=browser,
                    target_url=target_url,
                    link_index=actions_run,
                    link_text=link["text"],
                    href=link["href"],
                )

                results.append(result)
                actions_run += 1

            for form_index in range(
                form_count
            ):

                if actions_run >= max_actions:
                    break

                result = explore_form(
                    browser=browser,
                    target_url=target_url,
                    form_index=form_index,
                )

                results.append(result)
                actions_run += 1

            browser.close()
            # Build normalized issues

            raw_failures = [
                result
                for result in results
                if result["status"] == "FAIL"
            ]

            issues = build_issues(
                results
            )

            return {
                "success": True,
                "target_url": target_url,
                "actions_discovered": (
                    len(buttons)
                    + len(links)
                    + form_count
                ),
                "actions_executed": len(results),
                "raw_failures": len(raw_failures),
                "unique_issues": len(issues),
                "passes": (
                    len(results)
                    - len(raw_failures)
                ),
                "issues": issues,
                "results": results,
            }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Exploration failed: {exc}",
        ) from exc