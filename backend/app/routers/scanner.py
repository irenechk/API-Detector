import httpx
import os
import re
import secrets
import uuid
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.schemas import APIResponse

# ML classifiers (loaded lazily)
_ml_classifier = None
_ml_enhanced_classifier = None

def _get_ml_classifier():
    global _ml_classifier
    if _ml_classifier is None:
        try:
            from app.ml.classifier import APIClassifier
            _ml_classifier = APIClassifier.load()
            if not _ml_classifier._fitted:
                logging.getLogger(__name__).warning("ML model not found, using rule-based fallback")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to load ML model: {e}")
            _ml_classifier = None
    return _ml_classifier


def _get_enhanced_ml_classifier():
    global _ml_enhanced_classifier
    if _ml_enhanced_classifier is None:
        try:
            from app.ml.enhanced_classifier import EnhancedAPIClassifier
            _ml_enhanced_classifier = EnhancedAPIClassifier.load()
            if not _ml_enhanced_classifier._fitted:
                logging.getLogger(__name__).warning("Enhanced ML model not found, using rule-based fallback")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to load enhanced ML model: {e}")
            _ml_enhanced_classifier = None
    return _ml_enhanced_classifier

router = APIRouter(prefix="/api/v1/scanner", tags=["scanner"])

# In-memory store for scan results
scan_results: list[dict] = []


class ScanRequest(BaseModel):
    url: str


ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


class TrafficSample(BaseModel):
    timestamp: datetime
    request_count: int = Field(default=0, ge=0)
    error_4xx_count: int = Field(default=0, ge=0)
    error_5xx_count: int = Field(default=0, ge=0)
    avg_response_time_ms: float = Field(default=0, ge=0)


class AnalyzeEndpoint(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    method: str = "GET"
    url: Optional[str] = None
    service: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[str] = None
    owner: Optional[str] = None
    has_workflow: Optional[bool] = None
    last_seen: Optional[datetime] = None
    risk_score: Optional[int] = Field(default=None, ge=0, le=100)
    traffic: list[TrafficSample] = Field(default_factory=list, max_length=2000)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        value = value.strip().split("?", 1)[0]
        if not value.startswith("/"):
            raise ValueError("path must start with /")
        return value

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in ALLOWED_METHODS:
            raise ValueError(f"unsupported HTTP method: {value}")
        return value


class AnalyzeRequest(BaseModel):
    client: Optional[dict] = None
    endpoints: list[AnalyzeEndpoint] = Field(min_length=1, max_length=5000)


def _require_scanner_token(authorization: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("SCANNER_API_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing scanner API token")
    provided = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid scanner API token")


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _predict_status(endpoint: AnalyzeEndpoint, security: dict, ml_result: dict) -> Optional[dict]:
    if (
        endpoint.owner is None
        and endpoint.has_workflow is None
        and endpoint.last_seen is None
        and not endpoint.traffic
    ):
        return None

    from app.ml.data_pipeline.features import compute_traffic_features
    from app.ml.data_pipeline.sources import RawTrafficRecord
    from app.ml.enhanced_classifier import get_status_predictor

    predictor = get_status_predictor()
    if predictor is None:
        return None

    now = datetime.utcnow()
    records = [
        RawTrafficRecord(
            api_path=endpoint.path,
            http_method=endpoint.method,
            environment="unknown",
            timestamp=_naive_utc(sample.timestamp),
            request_count=sample.request_count,
            error_4xx_count=sample.error_4xx_count,
            error_5xx_count=sample.error_5xx_count,
            avg_response_time_ms=sample.avg_response_time_ms,
            p95_response_time_ms=0,
            p99_response_time_ms=0,
            unique_ips=0,
            source_system="zaddp-cli",
        )
        for sample in endpoint.traffic
    ]
    traffic_features = compute_traffic_features(records, endpoint.path, endpoint.method, now=now)

    vulnerabilities = security.get("vulnerabilities", [])
    features = {
        **traffic_features,
        "risk_score": endpoint.risk_score if endpoint.risk_score is not None else int(ml_result.get("risk_score", 0)),
        "findings_count": len(vulnerabilities),
        "critical_findings": sum(1 for finding in vulnerabilities if finding.get("severity") == "critical"),
        "high_findings": sum(1 for finding in vulnerabilities if finding.get("severity") == "high"),
        "days_since_last_seen": (
            max(0, (now - _naive_utc(endpoint.last_seen)).days) if endpoint.last_seen else 999
        ),
        "has_owner": int(bool(endpoint.owner)),
        "has_workflow": int(bool(endpoint.has_workflow)),
    }

    prediction = predictor.predict(features)
    if prediction.get("status") == "unknown":
        return None
    return prediction


def analyze_endpoint(path: str, method: str) -> tuple[dict, dict]:
    return analyze_endpoint_security(path, method), analyze_with_enhanced_ml(path, method)


def analyze_endpoint_security(path: str, method: str) -> dict:
    """Analyze an endpoint for potential unauthorized access vulnerabilities."""
    path_lower = path.lower()
    vulnerabilities = []

    # Check for admin/internal endpoints exposed to public
    if any(kw in path_lower for kw in ["/admin", "/internal", "/debug", "/console", "/manager"]):
        vulnerabilities.append({
            "type": "Exposed Admin Interface",
            "severity": "critical",
            "description": "Administrative or internal interface exposed on a publicly accessible endpoint. Attackers can attempt to access admin panels, debug consoles, or management interfaces without authentication.",
            "attack_vector": f"Send a GET request to {path}. If no authentication is enforced, you gain access to administrative functionality. Try common default credentials like admin:admin, admin:password.",
            "exploit_example": f"curl -X {method} {path} -H 'Authorization: Basic YWRtaW46YWRtaW4='",
        })

    # Check for sensitive data exposure
    if any(kw in path_lower for kw in ["/users", "/accounts", "/customers", "/profile", "/config", "/env", "/.env", "/backup", "/db", "/database", "/logs", "/secret", "/token", "/key"]):
        vulnerabilities.append({
            "type": "Sensitive Data Exposure",
            "severity": "critical",
            "description": "Endpoint path suggests it may expose sensitive data such as user information, configuration, environment variables, database credentials, or secrets.",
            "attack_vector": f"Access {path} directly. If no authorization is enforced, you can extract sensitive data like user lists, config files, environment variables with API keys, database credentials, or tokens.",
            "exploit_example": f"curl -X {method} {path} -v",
        })

    # Pre-compute for IDOR to avoid backslash-in-fstring issues (< Python 3.12)
    id_example_1 = re.sub(r'\d+', '1', path)
    id_example_1337 = re.sub(r'\d+', '1337', path)
    if re.search(r'/\d+|/\{[^}]+\}|/[\w-]+/(?:id|userId|accountId|docId|fileId)', path_lower):
        vulnerabilities.append({
            "type": "Insecure Direct Object Reference (IDOR)",
            "severity": "high",
            "description": "Endpoint uses sequential or predictable identifiers. If authorization is not properly enforced, an attacker can access other users' data by simply changing the ID.",
            "attack_vector": f"Get one valid ID from the response, then increment/decrement it to access other records. Example: try {id_example_1} then {{id_example_1.replace('1', '2')}}.",
            "exploit_example": f"curl -X {method} {id_example_1337} -v",
        })

    # Check for authentication bypass vectors
    if any(kw in path_lower for kw in ["/login", "/auth", "/oauth", "/token", "/signin", "/auth0", "/saml", "/callback"]):
        vulnerabilities.append({
            "type": "Authentication Bypass",
            "severity": "high",
            "description": "Authentication or token endpoint. May be vulnerable to brute force, token prediction, missing rate limiting, or insecure OAuth flows.",
            "attack_vector": f"Send crafted requests to {path}. Test for: missing rate limiting (rapid-fire requests), SQL injection in login fields, JWT 'none' algorithm attack, OAuth CSRF, or token interception over HTTP.",
            "exploit_example": f"curl -X POST {path} -d 'username=admin&password=admin' -v",
        })

    # Check for mass assignment / API abuse
    exploit_body = '{"role":"admin","is_admin":true}'
    if any(kw in path_lower for kw in ["/update", "/edit", "/save", "/create", "/add", "/modify", "/bulk", "/batch", "/import", "/upload"]):
        vulnerabilities.append({
            "type": "Mass Assignment / API Abuse",
            "severity": "high",
            "description": "Data modification endpoint. May allow manipulating fields that should be read-only (e.g., is_admin, role, balance) via mass assignment.",
            "attack_vector": f"Send a {method} request to {path} with extra parameters. Try adding 'role': 'admin', 'is_admin': true, 'balance': 999999 to the request body to see if they get accepted.",
            "exploit_example": f"curl -X {method} {path} -H 'Content-Type: application/json' -d '{exploit_body}'",
        })

    # Check for missing rate limiting on auth endpoints
    if any(kw in path_lower for kw in ["/login", "/signup", "/register", "/forgot", "/reset", "/verify", "/otp"]):
        vulnerabilities.append({
            "type": "Missing Rate Limiting",
            "severity": "medium",
            "description": "Authentication-related endpoint may lack rate limiting, making it susceptible to brute force attacks, credential stuffing, or OTP enumeration.",
            "attack_vector": f"Send rapid sequential requests to {path}. If no rate limiting is in place, you can brute force passwords, enumerate valid usernames, or spam OTP requests.",
            "exploit_example": f"for i in $(seq 1 1000); do curl -X POST {path} -d 'username=admin&password=$i' -s -o /dev/null -w '%{{http_code}}'; done",
        })

    # Check for GraphQL introspection
    if "/graphql" in path_lower:
        vulnerabilities.append({
            "type": "GraphQL Introspection Enabled",
            "severity": "high",
            "description": "GraphQL endpoint may have introspection enabled, allowing attackers to query the entire schema and discover all available queries, mutations, and data types.",
            "attack_vector": f"Send an introspection query to {path}. If enabled, the response reveals the full GraphQL schema including all queries, mutations, subscriptions, and their return types.",
            "exploit_example": f"curl -X POST {path} -H 'Content-Type: application/json' -d '{{\"query\":\"query {{__schema{{types{{name fields{{name}}}}}}}}\"}}'",
        })

    # Check for debug/info leakage
    if any(kw in path_lower for kw in ["/swagger", "/openapi", "/docs", "/redoc", "/api-docs"]):
        vulnerabilities.append({
            "type": "API Documentation Leakage",
            "severity": "medium",
            "description": "API documentation endpoint exposed. While documentation is useful, it reveals the full attack surface including all endpoints, parameters, request/response schemas.",
            "attack_vector": f"Access {path} to discover the complete API surface. Use the documentation to find undocumented endpoints, understand authentication requirements, and identify potential vulnerabilities.",
            "exploit_example": f"curl -X GET {path} -v | jq '.paths | keys'",
        })

    # Check for file operations  
    if any(kw in path_lower for kw in ["/download", "/upload", "/file", "/document", "/attachment", "/export", "/import"]):
        vulnerabilities.append({
            "type": "File Operation Abuse",
            "severity": "high",
            "description": "File operation endpoint. May be vulnerable to path traversal, arbitrary file upload, SSRF, or XXE injection.",
            "attack_vector": f"Test for path traversal by sending '../' sequences in file paths. Try uploading malicious files, or using SSRF to access internal services. Test for XXE in XML uploads.",
            "exploit_example": f"curl -X {method} {path}/../../../etc/passwd -v",
        })

    # Check for CORS misconfiguration (only for endpoints dealing with sensitive data)
    if any(kw in path_lower for kw in ["/api/", "/auth", "/token", "/user", "/admin", "/account", "/data", "/config"]):
        vulnerabilities.append({
            "type": "CORS Misconfiguration",
            "severity": "medium",
            "description": "API endpoint may have permissive CORS headers allowing cross-origin requests from any domain, enabling attackers to exfiltrate data from authenticated user sessions.",
            "attack_vector": f"Send an OPTIONS request to {path} with Origin: https://evil.com. If the response includes Access-Control-Allow-Origin: * or reflects the origin header, an attacker can make cross-origin requests from their malicious site.",
            "exploit_example": f"curl -X OPTIONS {path} -H 'Origin: https://evil.com' -H 'Access-Control-Request-Method: GET' -v",
        })

    # Check for health/status endpoints
    if any(kw in path_lower for kw in ["/health", "/status", "/metrics", "/healthz", "/readyz", "/info"]):
        vulnerabilities.append({
            "type": "Information Disclosure",
            "severity": "low",
            "description": "Health or status endpoint. May leak system information including server version, framework details, dependency versions, and infrastructure metadata.",
            "attack_vector": f"Access {path} to gather intelligence about the target. Server banners, version strings, and dependency info can be used to find known vulnerabilities in specific versions.",
            "exploit_example": f"curl -X {method} {path} -v",
        })

    # Determine overall severity
    severities = [v["severity"] for v in vulnerabilities]
    if "critical" in severities:
        overall_severity = "critical"
    elif "high" in severities:
        overall_severity = "high"
    elif "medium" in severities:
        overall_severity = "medium"
    else:
        overall_severity = "low"

    return {
        "vulnerabilities": vulnerabilities,
        "overall_severity": overall_severity,
    }


def analyze_with_ml(path: str, method: str) -> dict:
    """Analyze an endpoint using the original ML classifier."""
    classifier = _get_ml_classifier()
    if classifier and classifier._fitted:
        return classifier.predict(path, method)
    from app.ml.data import classify_vulnerabilities, classify_severity, classify_api_category, estimate_risk_score
    vulns = classify_vulnerabilities(path, method)
    return {
        "category": classify_api_category(path, method),
        "category_confidence": 1.0,
        "vulnerabilities": vulns,
        "vulnerability_confidences": {v: 1.0 for v in vulns},
        "severity": classify_severity(vulns),
        "severity_confidence": 1.0,
        "risk_score": estimate_risk_score(path, method, vulns, classify_severity(vulns)),
        "ml_model_version": "rule-based-fallback",
    }


def analyze_with_enhanced_ml(path: str, method: str) -> dict:
    """Analyze an endpoint using the enhanced ML classifier (multi-output GradientBoosting)."""
    classifier = _get_enhanced_ml_classifier()
    if classifier and classifier._fitted:
        return classifier.predict(path, method)
    from app.ml.data import classify_vulnerabilities, classify_severity, classify_api_category, estimate_risk_score
    vulns = classify_vulnerabilities(path, method)
    return {
        "category": classify_api_category(path, method),
        "category_confidence": 1.0,
        "vulnerabilities": vulns,
        "vulnerability_confidences": {v: 1.0 for v in vulns},
        "severity": classify_severity(vulns),
        "severity_confidence": 1.0,
        "risk_score": estimate_risk_score(path, method, vulns, classify_severity(vulns)),
        "ml_model_version": "enhanced-rule-based-fallback",
    }


@router.post("/analyze")
async def analyze_endpoints(
    request: AnalyzeRequest,
    _: None = Depends(_require_scanner_token),
):
    results = []
    for endpoint in request.endpoints:
        security = analyze_endpoint_security(endpoint.path, endpoint.method)
        enhanced_ml = analyze_with_enhanced_ml(endpoint.path, endpoint.method)
        results.append({
            "path": endpoint.path,
            "method": endpoint.method,
            "url": endpoint.url,
            "service": endpoint.service,
            "source": endpoint.source,
            "confidence": endpoint.confidence,
            "security": security,
            "ml_enhanced": enhanced_ml,
            "status_prediction": _predict_status(endpoint, security, enhanced_ml),
        })

    return APIResponse(data={
        "total": len(results),
        "results": results,
    })


async def scan_url_for_apis(target_url: str) -> list[dict]:
    discovered = []
    seen = set()

    parsed = urlparse(target_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(target_url)
            html = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {str(e)}")

    # Pattern 1: Look for API-like paths in href attributes
    api_patterns = re.findall(
        r'href=["\']([^"\']*(?:/api/|/v\d/|/rest/|/graphql|/swagger|/openapi|/docs|/health|/status)[^"\']*)["\']',
        html, re.IGNORECASE
    )
    for path in api_patterns:
        full_url = urljoin(target_url, path)
        if full_url not in seen:
            seen.add(full_url)
            relative = urlparse(full_url).path
            method = "GET"
            if re.search(r'(submit|create|save|post|add|register|login)', relative, re.IGNORECASE):
                method = "POST"
            elif re.search(r'(update|edit|modify|put)', relative, re.IGNORECASE):
                method = "PUT"
            elif re.search(r'(delete|remove|destroy)', relative, re.IGNORECASE):
                method = "DELETE"
            discovered.append({
                "endpoint_path": relative,
                "http_method": method,
                "source": "html_link",
                "confidence": "high",
            })

    # Pattern 2: Look for API-like patterns in script content
    script_patterns = re.findall(
        r'(?:["\']([^"\']*(?:/api/|/v\d/|/rest/|/graphql)[^"\']*)["\'])',
        html, re.IGNORECASE
    )
    for path in script_patterns:
        clean = path.split("?")[0].split("#")[0]
        if clean not in seen and len(clean) > 5:
            seen.add(clean)
            method = "GET"
            if re.search(r'(submit|create|save|post)', clean, re.IGNORECASE):
                method = "POST"
            discovered.append({
                "endpoint_path": clean,
                "http_method": method,
                "source": "script_hardcoded",
                "confidence": "medium",
            })

    # Pattern 3: Look for common API endpoint patterns in text content
    common_endpoints = [
        "/api/v1/health", "/api/v1/status", "/api/v1/users", "/api/v1/auth/login",
        "/api/v1/auth/logout", "/api/v1/config", "/api/v1/settings", "/api/v1/data",
        "/api/v1/metrics", "/api/v1/analytics", "/api/v1/notifications",
        "/graphql", "/api/graphql", "/swagger.json", "/openapi.json",
        "/.well-known/openid-configuration", "/health", "/healthz", "/readyz",
        "/api/v1/accounts", "/api/v1/payments", "/api/v1/transactions",
        "/api/v1/reports", "/api/v1/inventory", "/api/v1/dashboard",
        "/api/v1/search", "/api/v1/export", "/api/v1/import",
        "/api/v2/", "/api/v3/",
    ]
    for endpoint in common_endpoints:
        if endpoint not in seen and endpoint in html.lower():
            seen.add(endpoint)
            discovered.append({
                "endpoint_path": endpoint,
                "http_method": "GET",
                "source": "common_pattern",
                "confidence": "low",
            })

    return discovered


@router.post("/scan")
async def scan_website(request: ScanRequest):
    target_url = request.url.strip()

    if not target_url.startswith(("http://", "https://")):
        target_url = f"https://{target_url}"

    parsed = urlparse(target_url)
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL provided")

    discovered = await scan_url_for_apis(target_url)

    results = []
    for api in discovered:
        path = api["endpoint_path"]
        method = api["http_method"]
        
        security, enhanced_ml = analyze_endpoint(path, method)

        result = {
            "id": str(uuid.uuid4()),
            "scan_url": target_url,
            "endpoint_path": path,
            "http_method": method,
            "source": api["source"],
            "confidence": api["confidence"],
            "discovered_at": datetime.utcnow().isoformat(),
            "imported": False,
            "security": security,
            "ml_enhanced": enhanced_ml,
        }
        results.append(result)
        scan_results.append(result)

    return APIResponse(data={
        "scan_url": target_url,
        "total_found": len(results),
        "results": results,
    })


@router.get("/results")
async def get_scan_results():
    return APIResponse(data={
        "total": len(scan_results),
        "results": scan_results,
    })


@router.delete("/results")
async def clear_scan_results():
    scan_results.clear()
    return APIResponse(data={
        "total": 0,
        "results": [],
    })
