"""Never send OAuth requests or credential-bearing breadcrumbs to telemetry."""


def is_oauth(value) -> bool:
    text = str(value).lower()
    return any(
        part in text
        for part in (
            "api.login.yahoo.com",
            "/api/me/yahoo",
            "/api/auth/callback/yahoo",
            "/api/yahoo/connect",
        )
    )


def before_send(event, hint):
    if is_oauth(event.get("request", {}).get("url", "")):
        return None
    breadcrumbs = event.get("breadcrumbs", {})
    if isinstance(breadcrumbs, dict):
        breadcrumbs["values"] = [
            b for b in breadcrumbs.get("values", []) if not is_oauth(b)
        ]
    return event
