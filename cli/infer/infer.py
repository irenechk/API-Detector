#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

def main():
    try:
        from app.ml.enhanced_classifier import (
            get_enhanced_classifier,
            classify_endpoint_enhanced,
            get_status_predictor,
            ApiFeatures,
        )
        from app.ml.data import classify_vulnerabilities, classify_severity, classify_api_category, estimate_risk_score
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    
    req = json.load(sys.stdin)
    endpoints = req.get("endpoints", [])
    classifier = get_enhanced_classifier()
    
    results = []
    for ep in endpoints:
        path = ep["path"]
        method = ep.get("method", "GET")
        
        # Security analysis (rule-based)
        vulnerabilities_detail = []
        path_lower = path.lower()
        if any(kw in path_lower for kw in ["/admin", "/internal", "/debug", "/console", "/manager"]):
            vulnerabilities_detail.append({
                "type": "Exposed Admin Interface",
                "severity": "critical",
                "description": "Administrative or internal interface exposed on a publicly accessible endpoint.",
                "attack_vector": f"Send a GET request to {path}.",
                "exploit_example": f"curl -X {method} {path}",
            })
        if any(kw in path_lower for kw in ["/users", "/accounts", "/customers", "/profile", "/config", "/env", "/.env", "/backup", "/db", "/database", "/logs", "/secret", "/token", "/key"]):
            vulnerabilities_detail.append({
                "type": "Sensitive Data Exposure",
                "severity": "critical",
                "description": "Endpoint path suggests it may expose sensitive data.",
                "attack_vector": f"Access {path} directly.",
                "exploit_example": f"curl -X {method} {path}",
            })
        import re
        if re.search(r'/\d+|/\{[^}]+\}|/[\w-]+/(?:id|userId|accountId|docId|fileId)', path_lower):
            vulnerabilities_detail.append({
                "type": "Insecure Direct Object Reference (IDOR)",
                "severity": "high",
                "description": "Endpoint uses predictable identifiers.",
                "attack_vector": f"Try changing IDs to access other records.",
                "exploit_example": f"curl -X {method} {path.replace('{', '').replace('}', '')}1",
            })
        if any(kw in path_lower for kw in ["/login", "/auth", "/oauth", "/token", "/signin", "/auth0"]):
            vulnerabilities_detail.append({
                "type": "Authentication Bypass",
                "severity": "high",
                "description": "Authentication endpoint may be vulnerable.",
                "attack_vector": f"Test for brute force and auth bypass.",
                "exploit_example": f"curl -X POST {path} -d 'username=admin&password=admin'",
            })
        if any(kw in path_lower for kw in ["/update", "/edit", "/save", "/create", "/add", "/modify", "/bulk", "/batch", "/import", "/upload"]):
            vulnerabilities_detail.append({
                "type": "Mass Assignment / API Abuse",
                "severity": "high",
                "description": "Data modification endpoint may allow manipulating read-only fields.",
                "attack_vector": f"Add extra fields like role:admin to request body.",
                "exploit_example": f"curl -X {method} {path} -H 'Content-Type: application/json' -d '{{\"role\":\"admin\"}}'",
            })
        if any(kw in path_lower for kw in ["/login", "/signup", "/register", "/forgot", "/reset", "/verify", "/otp"]):
            vulnerabilities_detail.append({
                "type": "Missing Rate Limiting",
                "severity": "medium",
                "description": "Authentication endpoint may lack rate limiting.",
                "attack_vector": "Brute force or credential stuffing possible.",
                "exploit_example": f"curl -X POST {path}",
            })
        if "/graphql" in path_lower:
            vulnerabilities_detail.append({
                "type": "GraphQL Introspection Enabled",
                "severity": "high",
                "description": "GraphQL introspection may be enabled.",
                "attack_vector": "Query __schema to discover all operations.",
                "exploit_example": f"curl -X POST {path} -H 'Content-Type: application/json' -d '{{\"query\":\"{{__schema{{types{{name}}}}}}\"}}'",
            })
        if any(kw in path_lower for kw in ["/swagger", "/openapi", "/docs", "/redoc", "/api-docs"]):
            vulnerabilities_detail.append({
                "type": "API Documentation Leakage",
                "severity": "medium",
                "description": "API documentation exposed.",
                "attack_vector": "Discover full API surface from docs.",
                "exploit_example": f"curl -X GET {path}",
            })
        if any(kw in path_lower for kw in ["/download", "/upload", "/file", "/document", "/attachment", "/export", "/import"]):
            vulnerabilities_detail.append({
                "type": "File Operation Abuse",
                "severity": "high",
                "description": "File operations may be vulnerable to path traversal/upload attacks.",
                "attack_vector": "Test path traversal and malicious uploads.",
                "exploit_example": f"curl -X {method} {path}/../../../etc/passwd",
            })
        if any(kw in path_lower for kw in ["/api/", "/auth", "/token", "/user", "/admin", "/account", "/data", "/config"]):
            vulnerabilities_detail.append({
                "type": "CORS Misconfiguration",
                "severity": "medium",
                "description": "May have permissive CORS headers.",
                "attack_vector": "Cross-origin requests from malicious sites possible.",
                "exploit_example": f"curl -X OPTIONS {path} -H 'Origin: https://evil.com'",
            })
        if any(kw in path_lower for kw in ["/health", "/status", "/metrics", "/healthz", "/readyz", "/info"]):
            vulnerabilities_detail.append({
                "type": "Information Disclosure",
                "severity": "low",
                "description": "Health/status endpoints may leak system info.",
                "attack_vector": "Gather intelligence on stack and versions.",
                "exploit_example": f"curl -X GET {path}",
            })
        
        severities = [v["severity"] for v in vulnerabilities_detail]
        if "critical" in severities:
            overall_severity = "critical"
        elif "high" in severities:
            overall_severity = "high"
        elif "medium" in severities:
            overall_severity = "medium"
        else:
            overall_severity = "low"
        
        security = {
            "vulnerabilities": vulnerabilities_detail,
            "overall_severity": overall_severity,
        }
        
        # ML classification
        if classifier and getattr(classifier, "_fitted", False):
            ml_enhanced = classifier.predict(path, method)
        else:
            vulns = classify_vulnerabilities(path, method)
            ml_enhanced = {
                "category": classify_api_category(path, method),
                "category_confidence": 1.0,
                "severity": classify_severity(vulns),
                "severity_confidence": 1.0,
                "vulnerabilities": vulns,
                "vulnerability_confidences": {v: 1.0 for v in vulns},
                "risk_score": estimate_risk_score(path, method, vulns, classify_severity(vulns)),
                "ml_model_version": "enhanced-rule-based-fallback",
                "method": method,
            }
        
        # Status prediction if lifecycle data provided
        status_prediction = None
        if ep.get("owner") or ep.get("has_workflow") is not None or ep.get("last_seen") or ep.get("traffic"):
            predictor = get_status_predictor()
            if predictor:
                from datetime import datetime
                from app.ml.data_pipeline.features import compute_traffic_features
                from app.ml.data_pipeline.sources import RawTrafficRecord
                now = datetime.utcnow()
                records = []
                for t in ep.get("traffic", []):
                    try:
                        ts = t.get("timestamp")
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                            except:
                                ts = now
                        else:
                            ts = now
                        records.append(RawTrafficRecord(
                            api_path=path,
                            http_method=method,
                            environment="unknown",
                            timestamp=ts,
                            request_count=int(t.get("request_count", 0)),
                            error_4xx_count=int(t.get("error_4xx_count", 0)),
                            error_5xx_count=int(t.get("error_5xx_count", 0)),
                            avg_response_time_ms=float(t.get("avg_response_time_ms", 0)),
                            p95_response_time_ms=0,
                            p99_response_time_ms=0,
                            unique_ips=0,
                            source_system="zaddp-cli",
                        ))
                    except:
                        pass
                traffic_features = compute_traffic_features(records, path, method, now=now)
                features = {
                    **traffic_features,
                    "risk_score": ep.get("risk_score", ml_enhanced.get("risk_score", 0)),
                    "findings_count": len(vulnerabilities_detail),
                    "critical_findings": sum(1 for f in vulnerabilities_detail if f.get("severity") == "critical"),
                    "high_findings": sum(1 for f in vulnerabilities_detail if f.get("severity") == "high"),
                    "days_since_last_seen": 999,
                    "has_owner": int(bool(ep.get("owner"))),
                    "has_workflow": int(bool(ep.get("has_workflow"))),
                }
                if ep.get("last_seen"):
                    try:
                        ls = ep["last_seen"]
                        if isinstance(ls, str):
                            ls_dt = datetime.fromisoformat(ls.replace("Z", "+00:00")).replace(tzinfo=None)
                            features["days_since_last_seen"] = max(0, (now - ls_dt).days)
                    except:
                        pass
                pred = predictor.predict(features)
                if pred.get("status") != "unknown":
                    status_prediction = pred
        
        results.append({
            "path": path,
            "method": method.upper(),
            "url": ep.get("url"),
            "service": ep.get("service"),
            "source": ep.get("source"),
            "confidence": ep.get("confidence"),
            "security": security,
            "ml_enhanced": ml_enhanced,
            "status_prediction": status_prediction,
        })
    
    print(json.dumps({"results": results}))

if __name__ == "__main__":
    main()
