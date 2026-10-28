"""
Training data generator for API classification ML models.

Generates a diverse set of labeled API endpoint examples by applying
the existing rule-based security analysis to a wide range of paths.
This creates the training dataset for the ML models to learn from.
"""

import re
import random
from typing import Optional

random.seed(42)

# ── Label generation (mirrors scanner's analyze_endpoint_security) ──────────

VULN_TYPES = [
    "Exposed Admin Interface",
    "Sensitive Data Exposure",
    "Insecure Direct Object Reference (IDOR)",
    "Authentication Bypass",
    "Mass Assignment / API Abuse",
    "Missing Rate Limiting",
    "GraphQL Introspection Enabled",
    "API Documentation Leakage",
    "File Operation Abuse",
    "CORS Misconfiguration",
    "Information Disclosure",
]

API_CATEGORIES = [
    "authentication", "user_management", "data_crud", "admin",
    "system_health", "file_operations", "configuration", "reporting",
    "notifications", "search", "messaging", "payment", "analytics",
    "integration", "unknown",
]


def classify_vulnerabilities(path: str, method: str) -> list[str]:
    """Determine which vulnerability types apply to an endpoint (rule-based)."""
    path_lower = path.lower()
    vulns = []

    if any(kw in path_lower for kw in ["/admin", "/internal", "/debug", "/console", "/manager"]):
        vulns.append("Exposed Admin Interface")
    if any(kw in path_lower for kw in ["/users", "/accounts", "/customers", "/profile", "/config", "/env", "/.env", "/backup", "/db", "/database", "/logs", "/secret", "/token", "/key"]):
        vulns.append("Sensitive Data Exposure")
    if re.search(r'/\d+|/\{[^}]+\}|/[\w-]+/(?:id|userId|accountId|docId|fileId)', path_lower):
        vulns.append("Insecure Direct Object Reference (IDOR)")
    if any(kw in path_lower for kw in ["/login", "/auth", "/oauth", "/token", "/signin", "/auth0", "/saml", "/callback"]):
        vulns.append("Authentication Bypass")
    if any(kw in path_lower for kw in ["/update", "/edit", "/save", "/create", "/add", "/modify", "/bulk", "/batch", "/import", "/upload"]):
        vulns.append("Mass Assignment / API Abuse")
    if any(kw in path_lower for kw in ["/login", "/signup", "/register", "/forgot", "/reset", "/verify", "/otp"]):
        vulns.append("Missing Rate Limiting")
    if "/graphql" in path_lower:
        vulns.append("GraphQL Introspection Enabled")
    if any(kw in path_lower for kw in ["/swagger", "/openapi", "/docs", "/redoc", "/api-docs"]):
        vulns.append("API Documentation Leakage")
    if any(kw in path_lower for kw in ["/download", "/upload", "/file", "/document", "/attachment", "/export", "/import"]):
        vulns.append("File Operation Abuse")
    if any(kw in path_lower for kw in ["/api/", "/auth", "/token", "/user", "/admin", "/account", "/data", "/config"]):
        vulns.append("CORS Misconfiguration")
    if any(kw in path_lower for kw in ["/health", "/status", "/metrics", "/healthz", "/readyz", "/info"]):
        vulns.append("Information Disclosure")

    return vulns


def classify_severity(vulns: list[str]) -> str:
    """Determine overall severity from vulnerability list."""
    severity_map = {
        "Exposed Admin Interface": "critical",
        "Sensitive Data Exposure": "critical",
        "Insecure Direct Object Reference (IDOR)": "high",
        "Authentication Bypass": "high",
        "Mass Assignment / API Abuse": "high",
        "GraphQL Introspection Enabled": "high",
        "File Operation Abuse": "high",
        "Missing Rate Limiting": "medium",
        "API Documentation Leakage": "medium",
        "CORS Misconfiguration": "medium",
        "Information Disclosure": "low",
    }
    severities = [severity_map.get(v, "low") for v in vulns]
    for s in ("critical", "high", "medium", "low"):
        if s in severities:
            return s
    return "low"


def classify_api_category(path: str, method: str) -> str:
    """Infer API category from path patterns."""
    p = path.lower()
    m = method.upper()

    if any(kw in p for kw in ["/login", "/auth", "/oauth", "/signin", "/logout", "/register", "/reset", "/verify"]):
        return "authentication"
    if any(kw in p for kw in ["/users", "/accounts", "/profiles", "/customers", "/members"]):
        return "user_management"
    if any(kw in p for kw in ["/search", "/query", "/suggest"]):
        return "search"
    if any(kw in p for kw in ["/graphql"]):
        return "messaging"
    if any(kw in p for kw in ["/webhook", "/callback", "/events", "/notifications", "/push", "/subscribe", "/ws"]):
        return "notifications"
    if any(kw in p for kw in ["/reports", "/analytics", "/dashboard", "/metrics", "/stats", "/scoreboard"]):
        return "analytics"
    if any(kw in p for kw in ["/pay", "/payment", "/checkout", "/invoice", "/billing", "/subscription", "/pricing"]):
        return "payment"
    if any(kw in p for kw in ["/health", "/status", "/healthz", "/readyz", "/ping", "/version"]):
        return "system_health"
    if any(kw in p for kw in ["/admin", "/internal", "/console", "/debug", "/manager", "/control"]):
        return "admin"
    if any(kw in p for kw in ["/config", "/settings", "/env", "/preferences", "/options"]):
        return "configuration"
    if any(kw in p for kw in ["/upload", "/download", "/file", "/document", "/attachment", "/export", "/import", "/media"]):
        return "file_operations"
    if any(kw in p for kw in ["/create", "/add", "/new", "/save", "/update", "/edit", "/modify", "/delete", "/remove"]):
        return "data_crud"
    if any(kw in p for kw in ["/inventory", "/item", "/product", "/catalog", "/store", "/order", "/cart"]):
        return "data_crud"
    if any(kw in p for kw in ["/api/", "/v1/", "/v2/", "/rest/"]):
        return "integration"

    return "unknown"


def estimate_risk_score(path: str, method: str, vulns: list[str], severity: str) -> int:
    """Estimate a risk score (0-100) based on severity and vulnerability count."""
    base = {"critical": 70, "high": 50, "medium": 30, "low": 10}.get(severity, 10)
    vuln_bonus = min(len(vulns) * 8, 30)
    score = base + vuln_bonus

    # Path-specific adjustments
    if re.search(r'/\d{5,}', path):  # long numeric IDs = more exploitable
        score += 5
    if "/admin" in path.lower() and severity in ("critical", "high"):
        score += 10
    if method.upper() in ("POST", "PUT", "DELETE", "PATCH"):
        score += 5  # Mutating methods are riskier

    return min(score, 100)


# ── Diverse path generators ─────────────────────────────────────────────────

METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


def _gen_auth_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/register",
        "/api/v1/auth/refresh", "/api/v1/auth/verify", "/api/v1/auth/reset-password",
        "/api/v1/oauth/authorize", "/api/v1/oauth/token", "/api/v1/oauth/callback",
        "/auth/saml/login", "/auth/saml/callback", "/auth/azure-ad/callback",
        "/api/v1/auth/otp/request", "/api/v1/auth/otp/validate",
        "/api/v1/auth/mfa/enable", "/api/v1/auth/mfa/verify",
        "/api/v1/auth/signin", "/api/v1/auth/signout", "/auth0/callback",
        "/api/v1/token/refresh", "/api/v1/token/validate", "/api/v1/token/revoke",
        "/api/v1/register", "/api/v1/forgot-password", "/api/v1/reset-password",
        "/api/v1/verify-email", "/api/v1/session/validate",
        "/login", "/logout", "/signin", "/signup",
        "/api/auth/callback", "/api/auth/session", "/api/auth/csrf",
        "/api/v1/auth/webauthn/register", "/api/v1/auth/webauthn/authenticate",
        "/api/v1/sso/login", "/api/v1/sso/callback",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_user_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/users", "/api/v1/users/123", "/api/v1/users/123/profile",
        "/api/v1/users/123/settings", "/api/v1/users/123/roles",
        "/api/v1/users/123/permissions", "/api/v1/users/123/activity",
        "/api/v1/users/batch", "/api/v1/users/search",
        "/api/v1/accounts", "/api/v1/accounts/456",
        "/api/v1/accounts/456/transactions", "/api/v1/accounts/456/balance",
        "/api/v1/customers", "/api/v1/customers/789",
        "/api/v1/customers/789/orders", "/api/v1/customers/search",
        "/api/v1/profiles/me", "/api/v1/profiles/123",
        "/api/v1/members", "/api/v1/members/456",
        "/api/v1/team/123/members", "/api/v1/organization/456/users",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_admin_paths() -> list[tuple[str, str]]:
    paths = [
        "/admin", "/admin/dashboard", "/admin/users", "/admin/settings",
        "/admin/logs", "/admin/config", "/admin/cache/clear",
        "/admin/database/migrate", "/admin/database/backup",
        "/admin/analytics", "/admin/reports", "/admin/audit-log",
        "/internal/health", "/internal/metrics", "/internal/config",
        "/internal/services", "/internal/debug/pprof",
        "/internal/debug/vars", "/internal/debug/routes",
        "/debug", "/debug/console", "/debug/trace",
        "/console", "/manager", "/manager/control",
        "/api/v1/admin/users", "/api/v1/admin/settings",
        "/api/v1/admin/features", "/api/v1/admin/notifications",
        "/api/v1/internal/health", "/api/v1/internal/config",
        "/control-panel", "/control-panel/users",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_data_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/items", "/api/v1/items/123", "/api/v1/items/123/update",
        "/api/v1/items/create", "/api/v1/items/bulk", "/api/v1/items/delete",
        "/api/v1/inventory", "/api/v1/inventory/456", "/api/v1/inventory/update",
        "/api/v1/inventory/bulk-import",
        "/api/v1/products", "/api/v1/products/789",
        "/api/v1/products/789/variants", "/api/v1/products/search",
        "/api/v1/products/create", "/api/v1/products/bulk-update",
        "/api/v1/orders", "/api/v1/orders/12345", "/api/v1/orders/create",
        "/api/v1/orders/12345/status", "/api/v1/orders/batch",
        "/api/v1/documents", "/api/v1/documents/abc-def",
        "/api/v1/records", "/api/v1/records/42", "/api/v1/records/update",
        "/api/v1/records/batch-delete", "/api/v1/records/import",
        "/api/v1/entries", "/api/v1/entries/create",
        "/api/v1/catalog/items", "/api/v1/catalog/categories",
        "/api/v1/tasks", "/api/v1/tasks/123", "/api/v1/tasks/create",
        "/api/v1/schedules", "/api/v1/schedules/456",
        "/api/v1/events", "/api/v1/events/789", "/api/v1/events/create",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_config_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/config", "/api/v1/config/app", "/api/v1/config/database",
        "/api/v1/config/cache", "/api/v1/config/mail",
        "/api/v1/settings", "/api/v1/settings/general",
        "/api/v1/settings/security", "/api/v1/settings/notifications",
        "/api/v1/preferences", "/api/v1/preferences/123",
        "/api/v1/features", "/api/v1/features/flags",
        "/api/v1/environment", "/api/v1/environment/variables",
        "/.env", "/api/v1/.env", "/config/env",
        "/api/v1/options", "/api/v1/configuration",
        "/api/v1/tenant/123/settings", "/api/v1/workspace/settings",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_health_paths() -> list[tuple[str, str]]:
    paths = [
        "/health", "/healthz", "/readyz", "/livez",
        "/api/v1/health", "/api/v1/status", "/api/v1/version",
        "/api/v1/metrics", "/api/v1/ping",
        "/status", "/status/health", "/status/version",
        "/api/v1/info", "/api/v1/info/version",
        "/metrics", "/api/metrics",
        "/api/v1/uptime", "/api/v1/healthchecks",
        "/system/health", "/system/status",
    ]
    return [(p, "GET") for p in paths]


def _gen_file_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/files/upload", "/api/v1/files/download",
        "/api/v1/files/abc-123", "/api/v1/files/delete",
        "/api/v1/documents/upload", "/api/v1/documents/download",
        "/api/v1/documents/xyz-789",
        "/api/v1/attachments", "/api/v1/attachments/upload",
        "/api/v1/images/upload", "/api/v1/images/123",
        "/api/v1/export/csv", "/api/v1/export/pdf",
        "/api/v1/export/reports/123",
        "/api/v1/import/csv", "/api/v1/import/bulk",
        "/api/v1/media/upload", "/api/v1/media/123",
        "/api/v1/backup", "/api/v1/backup/create",
        "/api/v1/backup/restore", "/api/v1/backup/download",
        "/download/report.pdf", "/download/export.csv",
        "/upload", "/upload/file",
    ]
    return [(p, random.choice(["GET", "POST", "PUT"])) for p in paths]


def _gen_doc_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/docs", "/api/v1/swagger", "/api/v1/openapi.json",
        "/api/v1/redoc", "/api-docs", "/api-docs/v1",
        "/swagger", "/swagger.json", "/swagger-ui",
        "/openapi.json", "/openapi.yaml", "/openapi.yml",
        "/docs", "/docs/api",
        "/api/v1/api-docs", "/api/v1/swagger.json",
        "/redoc",
    ]
    return [(p, "GET") for p in paths]


def _gen_graphql_paths() -> list[tuple[str, str]]:
    paths = [
        "/graphql", "/api/graphql", "/api/v1/graphql",
        "/graphql/playground", "/graphql/voyager",
        "/api/graphql/batch", "/api/graphql/subscriptions",
        "/graphql/explorer", "/graphql/schema",
        "/v1/graphql", "/v2/graphql",
    ]
    return [(p, random.choice(["GET", "POST"])) for p in paths]


def _gen_secret_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/secrets", "/api/v1/secrets/123",
        "/api/v1/secrets/validate", "/api/v1/secrets/rotate",
        "/api/v1/keys", "/api/v1/keys/abc",
        "/api/v1/keys/generate", "/api/v1/keys/revoke",
        "/api/v1/tokens", "/api/v1/tokens/generate",
        "/api/v1/tokens/validate", "/api/v1/tokens/revoke",
        "/api/v1/api-keys", "/api/v1/api-keys/create",
        "/api/v1/api-keys/revoke", "/api/v1/api-keys/validate",
        "/api/v1/credentials", "/api/v1/credentials/rotate",
        "/api/v1/certificates", "/api/v1/certificates/renew",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_payment_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/payments", "/api/v1/payments/123",
        "/api/v1/payments/create", "/api/v1/payments/charge",
        "/api/v1/payments/refund", "/api/v1/payments/webhook",
        "/api/v1/checkout", "/api/v1/checkout/session",
        "/api/v1/invoices", "/api/v1/invoices/456",
        "/api/v1/billing", "/api/v1/billing/plan",
        "/api/v1/subscriptions", "/api/v1/subscriptions/789",
        "/api/v1/pricing", "/api/v1/pricing/plans",
        "/api/v1/wallet", "/api/v1/wallet/balance",
        "/api/v1/transactions", "/api/v1/transactions/12345",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_security_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/security/findings", "/api/v1/security/findings/123",
        "/api/v1/security/scan", "/api/v1/security/report",
        "/api/v1/security/vulnerabilities",
        "/api/v1/security/cve/2024-12345",
        "/api/v1/audit/logs", "/api/v1/audit/logs/search",
        "/api/v1/audit/events", "/api/v1/compliance/check",
        "/api/v1/compliance/report", "/api/v1/security/score",
        "/api/v1/rbac/roles", "/api/v1/rbac/permissions",
        "/api/v1/rbac/roles/123/users",
        "/api/v1/policies", "/api/v1/policies/access-control",
        "/api/v1/rate-limits", "/api/v1/rate-limits/config",
        "/api/v1/waf/rules", "/api/v1/waf/logs",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_notification_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/notifications", "/api/v1/notifications/123",
        "/api/v1/notifications/send", "/api/v1/notifications/templates",
        "/api/v1/push/devices", "/api/v1/push/send",
        "/api/v1/email/send", "/api/v1/email/templates",
        "/api/v1/sms/send", "/api/v1/sms/verify",
        "/api/v1/webhooks", "/api/v1/webhooks/123",
        "/api/v1/webhooks/trigger", "/api/v1/webhooks/logs",
        "/api/v1/events/publish", "/api/v1/events/subscribe",
        "/api/v1/messages", "/api/v1/messages/send",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_analytics_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/analytics/events", "/api/v1/analytics/pageviews",
        "/api/v1/analytics/users", "/api/v1/analytics/realtime",
        "/api/v1/reports/daily", "/api/v1/reports/monthly",
        "/api/v1/reports/custom", "/api/v1/reports/123/export",
        "/api/v1/dashboard", "/api/v1/dashboard/stats",
        "/api/v1/dashboard/widgets", "/api/v1/scoreboard",
        "/api/v1/metrics/traffic", "/api/v1/metrics/errors",
        "/api/v1/metrics/latency", "/api/v1/metrics/usage",
        "/api/v1/tracking/events", "/api/v1/tracking/identify",
    ]
    return [(p, random.choice(METHODS)) for p in paths]


def _gen_search_paths() -> list[tuple[str, str]]:
    paths = [
        "/api/v1/search", "/api/v1/search/query",
        "/api/v1/search/suggest", "/api/v1/search/autocomplete",
        "/api/v1/search/advanced", "/api/v1/search/filter",
        "/search", "/search/query", "/search/suggestions",
        "/api/v1/query", "/api/v1/explore",
        "/api/v1/discover", "/api/v1/recommendations",
    ]
    return [(p, random.choice(["GET", "POST"])) for p in paths]


def generate_dataset() -> list[dict]:
    """Generate a complete labeled dataset of API endpoints."""
    random.seed(42)
    generators = [
        _gen_auth_paths, _gen_user_paths, _gen_admin_paths,
        _gen_data_paths, _gen_config_paths, _gen_health_paths,
        _gen_file_paths, _gen_doc_paths, _gen_graphql_paths,
        _gen_secret_paths, _gen_payment_paths, _gen_security_paths,
        _gen_notification_paths, _gen_analytics_paths, _gen_search_paths,
    ]

    samples = []
    for gen in generators:
        for path, method in gen():
            vulns = classify_vulnerabilities(path, method)
            severity = classify_severity(vulns)
            category = classify_api_category(path, method)
            risk_score = estimate_risk_score(path, method, vulns, severity)

            samples.append({
                "endpoint_path": path,
                "http_method": method,
                "category": category,
                "vulnerabilities": vulns,
                "severity": severity,
                "risk_score": risk_score,
            })

    random.shuffle(samples)
    return samples


if __name__ == "__main__":
    ds = generate_dataset()
    print(f"Generated {len(ds)} training samples")
    # Show distribution
    from collections import Counter
    sev_counts = Counter(s["severity"] for s in ds)
    cat_counts = Counter(s["category"] for s in ds)
    vuln_counts = Counter(v for s in ds for v in s["vulnerabilities"])
    print(f"\nSeverity distribution: {dict(sev_counts)}")
    print(f"\nCategory distribution: {dict(cat_counts)}")
    print(f"\nVulnerability distribution: {dict(vuln_counts)}")
