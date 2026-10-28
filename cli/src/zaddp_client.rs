use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::config::Config;
use crate::discovery::Endpoint;

#[derive(Serialize)]
struct AnalyzeRequest<'a> {
    client: ClientInfo,
    endpoints: &'a [Endpoint],
}

#[derive(Serialize)]
struct ClientInfo {
    name: &'static str,
    version: &'static str,
}

#[derive(Deserialize)]
struct AnalyzeEnvelope {
    success: bool,
    data: Option<AnalyzeData>,
    message: Option<String>,
    error: Option<String>,
}

#[derive(Deserialize)]
struct AnalyzeData {
    results: Vec<AnalyzeResult>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AnalyzeResult {
    pub path: String,
    pub method: String,
    pub url: Option<String>,
    pub service: Option<String>,
    pub source: Option<String>,
    pub confidence: Option<String>,
    pub security: Value,
    pub ml_enhanced: Value,
    pub status_prediction: Option<Value>,
}

pub fn analyze(config: &Config, endpoints: &[Endpoint]) -> Result<Vec<AnalyzeResult>> {
    let client = http_client(config)?;
    let url = format!("{}/api/v1/scanner/analyze", config.server);
    let mut request = client.post(&url).json(&AnalyzeRequest {
        client: ClientInfo {
            name: "zaddp-cli",
            version: env!("CARGO_PKG_VERSION"),
        },
        endpoints,
    });
    if let Some(token) = &config.token {
        request = request.bearer_auth(token);
    }

    let response = request
        .send()
        .with_context(|| format!("could not reach ZADDP server at {}", config.server))?;
    let status = response.status();
    let body = response.text().unwrap_or_default();
    if !status.is_success() {
        bail!("ZADDP server returned {status}: {body}");
    }

    let envelope: AnalyzeEnvelope =
        serde_json::from_str(&body).context("invalid analyze response from ZADDP server")?;
    if !envelope.success {
        return Err(anyhow!(
            "{}",
            envelope
                .error
                .or(envelope.message)
                .unwrap_or_else(|| "analysis failed".to_string())
        ));
    }

    Ok(envelope
        .data
        .ok_or_else(|| anyhow!("analysis response has no data"))?
        .results)
}

pub fn get_json(config: &Config, path: &str) -> Result<Value> {
    let client = http_client(config)?;
    let url = format!("{}{}", config.server, path);
    let mut request = client.get(&url);
    if let Some(token) = &config.token {
        request = request.bearer_auth(token);
    }
    let response = request
        .send()
        .with_context(|| format!("could not reach ZADDP server at {}", config.server))?;
    let status = response.status();
    let body = response.text().unwrap_or_default();
    if !status.is_success() {
        bail!("ZADDP server returned {status}: {body}");
    }
    serde_json::from_str(&body).context("invalid JSON response from ZADDP server")
}

fn http_client(config: &Config) -> Result<Client> {
    Client::builder()
        .timeout(Duration::from_secs(config.timeout_seconds.max(30)))
        .danger_accept_invalid_certs(config.insecure)
        .user_agent(format!("zaddp-cli/{}", env!("CARGO_PKG_VERSION")))
        .build()
        .context("failed to build HTTP client")
}
