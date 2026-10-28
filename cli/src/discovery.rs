use std::collections::BTreeSet;
use std::process::Command;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use regex::Regex;
use reqwest::blocking::{Client, Response};
use reqwest::redirect::Policy;
use serde::{Deserialize, Serialize};
use url::Url;

use crate::openapi;

const OPENAPI_PATHS: &[&str] = &[
    "/openapi.json",
    "/v3/api-docs",
    "/swagger.json",
    "/api-docs",
    "/openapi.yaml",
    "/swagger.yaml",
];

const COMMON_ENDPOINTS: &[&str] = &[
    "/api/v1/health",
    "/api/v1/status",
    "/api/v1/users",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/config",
    "/api/v1/settings",
    "/api/v1/data",
    "/api/v1/metrics",
    "/api/v1/analytics",
    "/api/v1/notifications",
    "/graphql",
    "/api/graphql",
    "/swagger.json",
    "/openapi.json",
    "/.well-known/openid-configuration",
    "/health",
    "/healthz",
    "/readyz",
    "/api/v1/accounts",
    "/api/v1/payments",
    "/api/v1/transactions",
    "/api/v1/reports",
    "/api/v1/inventory",
    "/api/v1/dashboard",
    "/api/v1/search",
    "/api/v1/export",
    "/api/v1/import",
];

const ALLOWED_METHODS: &[&str] = &[
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
];

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TrafficSample {
    pub timestamp: DateTime<Utc>,
    pub request_count: u64,
    pub error_4xx_count: u64,
    pub error_5xx_count: u64,
    pub avg_response_time_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Endpoint {
    pub path: String,
    pub method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub service: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub owner: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub has_workflow: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_seen: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub risk_score: Option<u8>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub traffic: Vec<TrafficSample>,
}

impl Endpoint {
    pub fn key(&self) -> String {
        format!("{} {}", self.method, self.path)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Service {
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub spec: Option<String>,
    pub endpoints: usize,
}

#[derive(Debug, Default)]
pub struct DiscoveryResult {
    pub services: Vec<Service>,
    pub endpoints: Vec<Endpoint>,
}

pub fn discover(
    host: &str,
    config: &crate::config::Config,
    targets: &[String],
) -> Result<DiscoveryResult> {
    let mut result = DiscoveryResult::default();
    let mut seen = BTreeSet::new();

    if !targets.is_empty() {
        for target in targets {
            let base = normalize_target(target)?;
            discover_service(&base, config, &mut result, &mut seen)?;
        }
        return Ok(result);
    }

    let ports = listening_ports().context("failed to enumerate local TCP listeners")?;
    if ports.is_empty() {
        return Err(anyhow!(
            "no listening TCP ports found; use --target, --include-ports, or --host"
        ));
    }

    for port in ports {
        if !config.allowed_port(port) {
            continue;
        }
        let base = format!("{}://{}:{}", "http", host.trim_matches('/'), port);
        discover_service(&base, config, &mut result, &mut seen)?;
    }

    Ok(result)
}

fn normalize_target(target: &str) -> Result<String> {
    let with_scheme = if target.starts_with("http://") || target.starts_with("https://") {
        target.to_string()
    } else {
        format!("http://{target}")
    };
    let parsed =
        Url::parse(&with_scheme).with_context(|| format!("invalid target URL: {target}"))?;
    let host = parsed
        .host_str()
        .ok_or_else(|| anyhow!("target URL has no host: {target}"))?;
    let port = parsed.port_or_known_default().unwrap_or(80);
    Ok(format!("{}://{}:{}", parsed.scheme(), host, port))
}

fn discover_service(
    base: &str,
    config: &crate::config::Config,
    result: &mut DiscoveryResult,
    seen: &mut BTreeSet<String>,
) -> Result<()> {
    let timeout = Duration::from_secs(config.timeout_seconds.max(1));
    let client = Client::builder()
        .timeout(timeout)
        .redirect(Policy::limited(5))
        .danger_accept_invalid_certs(config.insecure)
        .user_agent(format!("zaddp/{}", env!("CARGO_PKG_VERSION")))
        .build()?;

    let (probe_base, root) = match probe(client.clone(), base) {
        Some(value) => value,
        None => return Ok(()),
    };

    let mut endpoints = Vec::new();
    let mut spec_used = None;

    for spec_path in OPENAPI_PATHS {
        let Some(text) = fetch_text(&client, &format!("{probe_base}{spec_path}")) else {
            continue;
        };
        if text.len() > 10_000_000 {
            continue;
        }
        if let Ok(spec_endpoints) = openapi::parse(&text, &probe_base) {
            if !spec_endpoints.is_empty() {
                endpoints = spec_endpoints;
                spec_used = Some(spec_path.to_string());
                break;
            }
        }
    }

    if endpoints.is_empty() && config.scan_html {
        if let Ok(body) = root.text() {
            endpoints = crawl_html(&body, &probe_base);
            if config.probe_common {
                for path in COMMON_ENDPOINTS {
                    if body.contains(path) {
                        endpoints.push(Endpoint {
                            path: path.to_string(),
                            method: "GET".to_string(),
                            url: Some(format!("{probe_base}{path}")),
                            service: Some(probe_base.clone()),
                            source: Some("common_pattern".to_string()),
                            confidence: Some("low".to_string()),
                            ..Endpoint::default()
                        });
                    }
                }
            }
        }
    }

    let mut service_endpoints = 0;
    for mut endpoint in endpoints {
        endpoint.service = Some(probe_base.clone());
        if endpoint.url.is_none() {
            endpoint.url = Some(format!("{probe_base}{}", endpoint.path));
        }
        let key = endpoint.key();
        if seen.insert(format!("{probe_base}|{key}")) {
            result.endpoints.push(endpoint);
            service_endpoints += 1;
        }
        if result.endpoints.len() >= config.max_endpoints {
            break;
        }
    }

    result.services.push(Service {
        url: probe_base,
        spec: spec_used,
        endpoints: service_endpoints,
    });

    Ok(())
}

fn probe(client: Client, base: &str) -> Option<(String, Response)> {
    let url = Url::parse(base).ok()?;
    if url.scheme() == "https" {
        let resp = client.get(base).send().ok()?;
        return Some((base.trim_end_matches('/').to_string(), resp));
    }

    for scheme in ["http", "https"] {
        let candidate = format!(
            "{scheme}://{}",
            &base[base.find("://").map(|i| i + 3).unwrap_or(0)..]
        );
        if let Ok(resp) = client.get(&candidate).send() {
            return Some((candidate.trim_end_matches('/').to_string(), resp));
        }
    }
    None
}

fn fetch_text(client: &Client, url: &str) -> Option<String> {
    let resp = client.get(url).send().ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let content_type = resp
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !content_type.contains("json")
        && !content_type.contains("yaml")
        && !content_type.contains("text/plain")
        && !content_type.is_empty()
    {
        return None;
    }
    resp.text().ok()
}

fn crawl_html(body: &str, base: &str) -> Vec<Endpoint> {
    let mut endpoints = Vec::new();
    let mut seen = BTreeSet::new();

    let href = Regex::new(
        r#"(?i)href=["']([^"']*(?:/api/|/v\d/|/rest/|/graphql|/swagger|/openapi|/docs|/health|/status)[^"']*)["']"#,
    )
    .expect("valid href regex");
    let script = Regex::new(r#"(?i)["']([^"']*(?:/api/|/v\d/|/rest/|/graphql)[^"']*)["']"#)
        .expect("valid script regex");

    for (pattern, source, confidence) in [
        (&href, "html_link", "high"),
        (&script, "script_hardcoded", "medium"),
    ] {
        for captures in pattern.captures_iter(body) {
            let raw = captures.get(1).map(|value| value.as_str()).unwrap_or("");
            let path = normalize_path(raw);
            if path.is_empty() || !seen.insert(path.clone()) {
                continue;
            }
            let method = infer_method(&path);
            endpoints.push(Endpoint {
                url: Some(format!("{base}{path}")),
                path,
                method,
                service: Some(base.to_string()),
                source: Some(source.to_string()),
                confidence: Some(confidence.to_string()),
                ..Endpoint::default()
            });
        }
    }

    endpoints
}

fn normalize_path(raw: &str) -> String {
    let mut value = raw.trim().to_string();
    if value.contains("://") {
        if let Ok(url) = Url::parse(&value) {
            value = url.path().to_string();
        }
    }
    value = value
        .split('?')
        .next()
        .unwrap_or("")
        .split('#')
        .next()
        .unwrap_or("")
        .to_string();
    if !value.starts_with('/') {
        value.insert(0, '/');
    }
    if value.len() < 2 {
        String::new()
    } else {
        value
    }
}

fn infer_method(path: &str) -> String {
    let lower = path.to_ascii_lowercase();
    if ["delete", "remove", "destroy"]
        .iter()
        .any(|keyword| lower.contains(keyword))
    {
        "DELETE".to_string()
    } else if ["update", "edit", "modify", "put"]
        .iter()
        .any(|keyword| lower.contains(keyword))
    {
        "PUT".to_string()
    } else if [
        "submit", "create", "save", "post", "add", "register", "login",
    ]
    .iter()
    .any(|keyword| lower.contains(keyword))
    {
        "POST".to_string()
    } else {
        "GET".to_string()
    }
}

#[cfg(target_os = "linux")]
pub fn listening_ports() -> Result<Vec<u16>> {
    let mut ports = BTreeSet::new();
    for path in ["/proc/net/tcp", "/proc/net/tcp6"] {
        let Ok(contents) = std::fs::read_to_string(path) else {
            continue;
        };
        for line in contents.lines().skip(1) {
            let fields: Vec<&str> = line.split_whitespace().collect();
            if fields.len() < 4 || fields[3] != "0A" {
                continue;
            }
            let Some(port_hex) = fields[1].rsplit(':').next() else {
                continue;
            };
            if let Ok(port) = u16::from_str_radix(port_hex, 16) {
                ports.insert(port);
            }
        }
    }
    Ok(ports.into_iter().collect())
}

#[cfg(target_os = "macos")]
pub fn listening_ports() -> Result<Vec<u16>> {
    let output = Command::new("lsof")
        .args(["-nP", "-iTCP", "-sTCP:LISTEN"])
        .output()
        .context("lsof is required for local discovery on macOS")?;
    let text = String::from_utf8_lossy(&output.stdout);
    let pattern = Regex::new(r":(\d+)\s+\(LISTEN\)")?;
    let mut ports = BTreeSet::new();
    for captures in pattern.captures_iter(&text) {
        if let Some(value) = captures.get(1) {
            if let Ok(port) = value.as_str().parse::<u16>() {
                ports.insert(port);
            }
        }
    }
    Ok(ports.into_iter().collect())
}

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
pub fn listening_ports() -> Result<Vec<u16>> {
    Err(anyhow!(
        "local listener discovery is supported on Linux and macOS; use --target"
    ))
}

impl Default for Endpoint {
    fn default() -> Self {
        Self {
            path: String::new(),
            method: "GET".to_string(),
            url: None,
            service: None,
            source: None,
            confidence: None,
            owner: None,
            has_workflow: None,
            last_seen: None,
            risk_score: None,
            traffic: Vec::new(),
        }
    }
}

pub fn known_method(method: &str) -> bool {
    ALLOWED_METHODS.contains(&method.to_ascii_lowercase().as_str())
}
