use std::collections::BTreeSet;

use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::discovery::{known_method, Endpoint};

pub fn parse(text: &str, base: &str) -> Result<Vec<Endpoint>> {
    let document: Value = serde_json::from_str(text)
        .or_else(|_| serde_yaml::from_str(text))
        .map_err(|_| anyhow!("response is not valid OpenAPI JSON or YAML"))?;

    let paths = document
        .get("paths")
        .and_then(Value::as_object)
        .ok_or_else(|| anyhow!("document has no paths object"))?;

    let prefix = server_prefix(&document);
    let mut endpoints = Vec::new();
    let mut seen = BTreeSet::new();

    for (raw_path, item) in paths {
        if !raw_path.starts_with('/') {
            continue;
        }
        let Some(operations) = item.as_object() else {
            continue;
        };
        let path = format!("{}{}", prefix, raw_path);
        for (method, operation) in operations {
            if operation.is_null() || !known_method(method) {
                continue;
            }
            let method = method.to_ascii_uppercase();
            if !seen.insert(format!("{method} {path}")) {
                continue;
            }
            endpoints.push(Endpoint {
                url: Some(format!("{base}{path}")),
                path: path.clone(),
                method,
                service: Some(base.to_string()),
                source: Some("openapi".to_string()),
                confidence: Some("high".to_string()),
                ..Endpoint::default()
            });
        }
    }

    endpoints.sort_by(|left, right| {
        left.path
            .cmp(&right.path)
            .then_with(|| left.method.cmp(&right.method))
    });
    Ok(endpoints)
}

fn server_prefix(document: &Value) -> String {
    let raw = document
        .get("servers")
        .and_then(Value::as_array)
        .and_then(|servers| servers.first())
        .and_then(|server| server.get("url"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| {
            document
                .get("basePath")
                .and_then(Value::as_str)
                .map(str::to_string)
        });

    let Some(raw) = raw else {
        return String::new();
    };

    let path = if raw.starts_with("http://") || raw.starts_with("https://") {
        url::Url::parse(&raw)
            .map(|url| url.path().to_string())
            .unwrap_or_default()
    } else {
        raw
    };

    let trimmed = path.trim_end_matches('/');
    if trimmed.is_empty() || trimmed == "/" {
        String::new()
    } else if trimmed.starts_with('/') {
        trimmed.to_string()
    } else {
        format!("/{trimmed}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_openapi_3_paths_and_server_prefix() {
        let spec = r#"{
            "openapi": "3.0.0",
            "servers": [{"url": "/api/v1"}],
            "paths": {
                "/users": {"get": {}, "post": {}},
                "/users/{id}": {"get": {}, "parameters": []}
            }
        }"#;

        let endpoints = parse(spec, "http://127.0.0.1:8000").unwrap();
        let keys: Vec<String> = endpoints
            .iter()
            .map(|endpoint| format!("{} {}", endpoint.method, endpoint.path))
            .collect();
        assert!(keys.contains(&"GET /api/v1/users".to_string()));
        assert!(keys.contains(&"POST /api/v1/users".to_string()));
        assert!(keys.contains(&"GET /api/v1/users/{id}".to_string()));
        assert_eq!(
            endpoints[0].url.as_deref(),
            Some("http://127.0.0.1:8000/api/v1/users")
        );
    }

    #[test]
    fn parses_swagger_2_base_path() {
        let spec = r#"{
            "swagger": "2.0",
            "basePath": "/v2",
            "paths": {"/accounts": {"get": {}}}
        }"#;

        let endpoints = parse(spec, "http://localhost:9000").unwrap();
        assert_eq!(endpoints.len(), 1);
        assert_eq!(endpoints[0].path, "/v2/accounts");
    }

    #[test]
    fn rejects_documents_without_paths() {
        assert!(parse("{\"openapi\":\"3.0.0\"}", "http://localhost").is_err());
    }
}
