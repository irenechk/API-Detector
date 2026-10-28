use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::Deserialize;

use crate::discovery::{Endpoint, TrafficSample};

#[derive(Debug, Default, Deserialize)]
pub struct Manifest {
    #[serde(default)]
    pub endpoints: Vec<ManifestEndpoint>,
}

#[derive(Debug, Deserialize)]
pub struct ManifestEndpoint {
    pub path: String,
    pub method: String,
    pub owner: Option<String>,
    pub has_workflow: Option<bool>,
    pub last_seen: Option<DateTime<Utc>>,
    pub risk_score: Option<u8>,
    #[serde(default)]
    pub traffic: Vec<TrafficSample>,
}

#[derive(Debug, Default)]
pub struct ApplyStats {
    pub matched: usize,
    pub unmatched: usize,
}

pub fn load(path: &Path) -> Result<Manifest> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read manifest {}", path.display()))?;
    if path.extension().and_then(|value| value.to_str()) == Some("toml") {
        return toml::from_str(&raw)
            .with_context(|| format!("invalid TOML manifest {}", path.display()));
    }
    serde_json::from_str(&raw)
        .or_else(|_| toml::from_str(&raw))
        .with_context(|| format!("invalid JSON/TOML manifest {}", path.display()))
}

pub fn apply(manifest: Manifest, endpoints: &mut [Endpoint]) -> ApplyStats {
    let mut stats = ApplyStats::default();
    for entry in manifest.endpoints {
        let mut matched = false;
        for endpoint in endpoints.iter_mut() {
            if !method_matches(&entry.method, &endpoint.method)
                || !path_matches(&entry.path, &endpoint.path)
            {
                continue;
            }
            matched = true;
            if entry.owner.is_some() {
                endpoint.owner = entry.owner.clone();
            }
            if entry.has_workflow.is_some() {
                endpoint.has_workflow = entry.has_workflow;
            }
            if entry.last_seen.is_some() {
                endpoint.last_seen = entry.last_seen;
            }
            if entry.risk_score.is_some() {
                endpoint.risk_score = entry.risk_score;
            }
            endpoint.traffic.extend(entry.traffic.clone());
            break;
        }
        if matched {
            stats.matched += 1;
        } else {
            stats.unmatched += 1;
        }
    }
    stats
}

pub fn apply_nginx_log(path: &Path, endpoints: &mut [Endpoint]) -> Result<usize> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read traffic log {}", path.display()))?;
    let pattern = Regex::new(
        r#"^\S+ \S+ \S+ \[([^\]]+)\] "(\S+) (\S+)[^"]*" (\d{3}) \S+(?: "[^"]*" "[^"]*")?(?: (\S+))?$"#,
    )?;

    let mut buckets: BTreeMap<(String, String, String), Bucket> = BTreeMap::new();
    let mut matched_records = 0;
    for line in raw.lines() {
        let Some(captures) = pattern.captures(line) else {
            continue;
        };
        let timestamp = DateTime::parse_from_str(
            captures.get(1).map(|value| value.as_str()).unwrap_or(""),
            "%d/%b/%Y:%H:%M:%S %z",
        )
        .map(|value| value.with_timezone(&Utc))
        .ok();
        let Some(timestamp) = timestamp else {
            continue;
        };
        let method = captures.get(2).map(|value| value.as_str()).unwrap_or("");
        let request_path = captures.get(3).map(|value| value.as_str()).unwrap_or("");
        let status = captures
            .get(4)
            .and_then(|value| value.as_str().parse::<u16>().ok())
            .unwrap_or(0);
        let response_time = captures
            .get(5)
            .and_then(|value| value.as_str().parse::<f64>().ok())
            .map(|seconds| seconds * 1000.0)
            .unwrap_or(0.0);

        let Some(endpoint) = endpoints.iter().find(|endpoint| {
            method_matches(method, &endpoint.method) && path_matches(&endpoint.path, request_path)
        }) else {
            continue;
        };

        matched_records += 1;
        let hour = timestamp.format("%Y-%m-%dT%H").to_string();
        let key = (endpoint.path.clone(), endpoint.method.clone(), hour);
        let entry = buckets.entry(key).or_insert_with(|| Bucket {
            timestamp,
            requests: 0,
            errors_4xx: 0,
            errors_5xx: 0,
            response_time_total: 0.0,
        });
        if timestamp > entry.timestamp {
            entry.timestamp = timestamp;
        }
        entry.requests += 1;
        match status {
            400..=499 => entry.errors_4xx += 1,
            500..=599 => entry.errors_5xx += 1,
            _ => {}
        }
        entry.response_time_total += response_time;
    }

    for endpoint in endpoints.iter_mut() {
        let mut samples: Vec<TrafficSample> = buckets
            .iter()
            .filter(|((path, method, _), _)| path == &endpoint.path && method == &endpoint.method)
            .map(|(_, bucket)| TrafficSample {
                timestamp: bucket.timestamp,
                request_count: bucket.requests,
                error_4xx_count: bucket.errors_4xx,
                error_5xx_count: bucket.errors_5xx,
                avg_response_time_ms: if bucket.requests == 0 {
                    0.0
                } else {
                    bucket.response_time_total / bucket.requests as f64
                },
            })
            .collect();
        samples.sort_by_key(|sample| sample.timestamp);
        endpoint.traffic.extend(samples);
        if endpoint.traffic.len() > 2000 {
            endpoint.traffic.truncate(2000);
        }
    }

    Ok(matched_records)
}

#[derive(Debug)]
struct Bucket {
    timestamp: DateTime<Utc>,
    requests: u64,
    errors_4xx: u64,
    errors_5xx: u64,
    response_time_total: f64,
}

pub fn path_matches(template: &str, actual: &str) -> bool {
    let left = normalize(template);
    let right = normalize(actual);
    if left == right {
        return true;
    }
    if left.contains('{') && segment_match(&left, &right) {
        return true;
    }
    if right.contains('{') && segment_match(&right, &left) {
        return true;
    }
    false
}

fn segment_match(template: &str, actual: &str) -> bool {
    let template_parts: Vec<&str> = template.split('/').collect();
    let actual_parts: Vec<&str> = actual.split('/').collect();
    if template_parts.len() != actual_parts.len() {
        return false;
    }
    template_parts
        .iter()
        .zip(actual_parts.iter())
        .all(|(left, right)| {
            if left.starts_with('{') && left.ends_with('}') {
                !right.is_empty()
            } else {
                left == right
            }
        })
}

fn normalize(path: &str) -> String {
    let path = path.split('?').next().unwrap_or("").trim();
    if path.len() > 1 {
        path.trim_end_matches('/').to_string()
    } else {
        path.to_string()
    }
}

fn method_matches(expected: &str, actual: &str) -> bool {
    expected.eq_ignore_ascii_case(actual)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn endpoint(path: &str, method: &str) -> Endpoint {
        Endpoint {
            path: path.to_string(),
            method: method.to_string(),
            ..Endpoint::default()
        }
    }

    #[test]
    fn matches_templated_paths() {
        assert!(path_matches("/api/v1/users/{id}", "/api/v1/users/123"));
        assert!(path_matches("/api/v1/users/123", "/api/v1/users/{id}"));
        assert!(!path_matches("/api/v1/users/{id}", "/api/v1/accounts/123"));
        assert!(!path_matches(
            "/api/v1/users/{id}",
            "/api/v1/users/123/extra"
        ));
    }

    #[test]
    fn applies_manifest_by_path_and_method() {
        let mut endpoints = vec![endpoint("/api/v1/users/{id}", "GET")];
        let manifest = Manifest {
            endpoints: vec![ManifestEndpoint {
                path: "/api/v1/users/42".to_string(),
                method: "get".to_string(),
                owner: Some("identity".to_string()),
                has_workflow: Some(true),
                last_seen: None,
                risk_score: Some(70),
                traffic: vec![],
            }],
        };
        let stats = apply(manifest, &mut endpoints);
        assert_eq!(stats.matched, 1);
        assert_eq!(endpoints[0].owner.as_deref(), Some("identity"));
        assert_eq!(endpoints[0].risk_score, Some(70));
    }

    #[test]
    fn parses_nginx_combined_log() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("access.log");
        fs::write(
            &path,
            "127.0.0.1 - - [27/Oct/2026:12:00:00 +0000] \"GET /api/v1/users/42 HTTP/1.1\" 200 512 \"-\" \"curl/8.0\" 0.042\n",
        )
        .unwrap();
        let mut endpoints = vec![endpoint("/api/v1/users/{id}", "GET")];
        let matched = apply_nginx_log(&path, &mut endpoints).unwrap();
        assert_eq!(matched, 1);
        assert_eq!(endpoints[0].traffic.len(), 1);
        assert_eq!(endpoints[0].traffic[0].request_count, 1);
        assert!(endpoints[0].traffic[0].avg_response_time_ms > 40.0);
    }

    #[test]
    fn parses_utc_timestamp() {
        let parsed = chrono::DateTime::parse_from_rfc3339("2026-10-27T12:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(
            parsed,
            Utc.with_ymd_and_hms(2026, 10, 27, 12, 0, 0).unwrap()
        );
    }
}
