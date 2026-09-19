from __future__ import annotations
import re
from typing import Any

NOISE_CONSOLE_PATTERNS = (
    "Failed to load resource:",
)

NOISE_URL_PATTERNS = (
    "/favicon.ico",
)

def is_noise_console_error(message: str) -> bool:
    return any(
        pattern.lower() in message.lower()
        for pattern in NOISE_CONSOLE_PATTERNS
    )

def is_noise_http_error(
    error: dict[str, Any],
) -> bool:
    url = str(error.get("url", "")).lower()

    return any(
        pattern in url
        for pattern in NOISE_URL_PATTERNS
    )


def clean_console_errors(
    errors: list[str],
) -> list[str]:
    cleaned = []

    for error in errors:
        if not error:
            continue

        if is_noise_console_error(error):
            continue

        cleaned.append(error.strip())

    return cleaned


def clean_http_errors(
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        error
        for error in errors
        if not is_noise_http_error(error)
    ]


def normalize_page_error(
    message: str,
) -> str:
    message = message.strip()

    message = re.split(
        r"\n\s*at\s+",
        message,
        maxsplit=1,
    )[0]

    return message.strip()


def is_flow_failed_console(
    message: str,
) -> bool:
    return bool(
        re.match(
            r"^[A-Z0-9_]+_FLOW_FAILED:",
            message.strip(),
        )
    )


def choose_severity(
    issue_type: str,
    status: int | None = None,
) -> str:

    if issue_type == "page_error":
        return "critical"

    if issue_type == "http_error":

        if status is not None:

            if status >= 500:
                return "critical"

            if status in {401, 403}:
                return "high"

            if status >= 400:
                return "high"

        return "high"

    if issue_type == "action_error":
        return "high"

    return "medium"


def classify_result(
    result: dict[str, Any],
) -> list[dict[str, Any]]:

    if result.get("status") != "FAIL":
        return []

    candidates: list[dict[str, Any]] = []

    evidence = result.get(
        "evidence",
        {},
    )

    http_errors = clean_http_errors(
        evidence.get("http_errors", [])
    )

    page_errors = evidence.get(
        "page_errors",
        []
    )

    console_errors = clean_console_errors(
        evidence.get("console_errors", [])
    )

    for http_error in http_errors:

        url = str(
            http_error.get("url", "")
        )

        method = str(
            http_error.get(
                "method",
                "GET",
            )
        ).upper()

        status = http_error.get(
            "status"
        )

        normalized_url = url.split(
            "?",
            1,
        )[0]

        signature = (
            f"http:{method}:"
            f"{normalized_url}:"
            f"{status}"
        )

        candidates.append(
            {
                "type": "http_error",
                "signature": signature,
                "title": (
                    f"{method} "
                    f"{normalized_url} "
                    f"returned {status}"
                ),
                "severity": choose_severity(
                    "http_error",
                    status,
                ),
                "evidence": {
                    "url": url,
                    "method": method,
                    "status": status,
                    "status_text": http_error.get(
                        "status_text"
                    ),
                },
            }
        )

    # Page-level JavaScript errors

    for page_error in page_errors:

        normalized = normalize_page_error(
            str(page_error)
        )

        if not normalized:
            continue

        candidates.append(
            {
                "type": "page_error",
                "signature": (
                    f"page:"
                    f"{normalized.lower()}"
                ),
                "title": normalized,
                "severity": choose_severity(
                    "page_error"
                ),
                "evidence": {
                    "message": normalized,
                },
            }
        )

    # Action errors

    action_error = evidence.get(
        "action_error"
    )

    if action_error:

        candidates.append(
            {
                "type": "action_error",
                "signature": (
                    f"action:"
                    f"{str(action_error).lower()}"
                ),
                "title": str(action_error),
                "severity": choose_severity(
                    "action_error"
                ),
                "evidence": {
                    "message": str(
                        action_error
                    ),
                },
            }
        )

    for console_error in console_errors:

        if is_flow_failed_console(
            console_error
        ):

            if http_errors:
                continue

        normalized = console_error.strip()

        if not normalized:
            continue

        candidates.append(
            {
                "type": "console_error",
                "signature": (
                    f"console:"
                    f"{normalized.lower()}"
                ),
                "title": normalized,
                "severity": choose_severity(
                    "console_error"
                ),
                "evidence": {
                    "message": normalized,
                },
            }
        )

    return candidates


def build_issues(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    grouped: dict[
        str,
        dict[str, Any],
    ] = {}

    for result in results:

        candidates = classify_result(
            result
        )

        for candidate in candidates:

            signature = candidate[
                "signature"
            ]

            if signature not in grouped:

                issue_number = (
                    len(grouped) + 1
                )

                grouped[signature] = {
                    "id": (
                        f"ISSUE-"
                        f"{issue_number:03d}"
                    ),
                    "type": candidate[
                        "type"
                    ],
                    "signature": signature,
                    "title": candidate[
                        "title"
                    ],
                    "severity": candidate[
                        "severity"
                    ],
                    "occurrences": 0,
                    "actions": [],
                    "evidence": [],
                }

            issue = grouped[
                signature
            ]

            issue[
                "occurrences"
            ] += 1

            description = result.get(
                "description"
            )

            if (
                description
                and description
                not in issue["actions"]
            ):
                issue["actions"].append(
                    description
                )

            evidence = candidate.get(
                "evidence",
                {},
            )

            if evidence not in issue[
                "evidence"
            ]:
                issue["evidence"].append(
                    evidence
                )

    return list(
        grouped.values()
    )