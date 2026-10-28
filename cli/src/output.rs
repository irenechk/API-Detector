use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use comfy_table::{ContentArrangement, Table};
use serde::Serialize;
use serde_json::Value;

use crate::discovery::Service;
use crate::zaddp_client::AnalyzeResult;

#[derive(Serialize)]
pub struct Report {
    pub tool: ToolInfo,
    pub server: String,
    pub scanned_at: DateTime<Utc>,
    pub services: Vec<Service>,
    pub summary: Summary,
    pub results: Vec<AnalyzeResult>,
}

#[derive(Serialize)]
pub struct ToolInfo {
    pub name: &'static str,
    pub version: &'static str,
}

#[derive(Serialize, Default)]
pub struct Summary {
    pub services: usize,
    pub endpoints: usize,
    pub critical: usize,
    pub high: usize,
    pub medium: usize,
    pub low: usize,
    pub statuses: BTreeMap<String, usize>,
}

impl Report {
    pub fn new(server: &str, services: Vec<Service>, results: Vec<AnalyzeResult>) -> Self {
        let summary = summarize(&services, &results);
        Self {
            tool: ToolInfo {
                name: "zaddp",
                version: env!("CARGO_PKG_VERSION"),
            },
            server: server.to_string(),
            scanned_at: Utc::now(),
            services,
            summary,
            results,
        }
    }
}

fn summarize(services: &[Service], results: &[AnalyzeResult]) -> Summary {
    let mut summary = Summary {
        services: services.len(),
        endpoints: results.len(),
        ..Summary::default()
    };
    for result in results {
        match severity(result) {
            "critical" => summary.critical += 1,
            "high" => summary.high += 1,
            "medium" => summary.medium += 1,
            "low" => summary.low += 1,
            _ => {}
        }
        if let Some(status) = result
            .status_prediction
            .as_ref()
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str)
        {
            *summary.statuses.entry(status.to_string()).or_insert(0) += 1;
        }
    }
    summary
}

pub fn filter_by_severity(results: &mut Vec<AnalyzeResult>, minimum: Option<&str>) {
    let Some(minimum) = minimum else {
        return;
    };
    let threshold = severity_rank(minimum);
    results.retain(|result| severity_rank(severity(result)) >= threshold);
}

pub fn print(report: &Report, json: bool, output: Option<&Path>) -> Result<()> {
    if json {
        let text = serde_json::to_string_pretty(report)?;
        if let Some(path) = output {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).ok();
            }
            fs::write(path, &text)
                .with_context(|| format!("failed to write {}", path.display()))?;
            println!("Wrote report to {}", path.display());
        } else {
            println!("{text}");
        }
        return Ok(());
    }

    if report.results.is_empty() {
        println!("No endpoints analyzed.");
        return Ok(());
    }

    let mut table = Table::new();
    table.set_content_arrangement(ContentArrangement::Dynamic);
    table.set_header(vec![
        "SERVICE", "METHOD", "PATH", "CATEGORY", "SEVERITY", "RISK", "STATUS", "VULNS",
    ]);
    for result in &report.results {
        let category = result
            .ml_enhanced
            .get("category")
            .and_then(Value::as_str)
            .unwrap_or("-");
        let risk = result
            .ml_enhanced
            .get("risk_score")
            .and_then(Value::as_i64)
            .map(|value| value.to_string())
            .unwrap_or_else(|| "-".to_string());
        let status = result
            .status_prediction
            .as_ref()
            .and_then(|value| value.get("status"))
            .and_then(Value::as_str)
            .unwrap_or("-");
        let vulnerabilities = result
            .security
            .get("vulnerabilities")
            .and_then(Value::as_array)
            .map(|items| items.len())
            .unwrap_or(0);
        table.add_row(vec![
            result.service.as_deref().unwrap_or("-").to_string(),
            result.method.clone(),
            result.path.clone(),
            category.to_string(),
            severity(result).to_uppercase(),
            risk,
            status.to_string(),
            vulnerabilities.to_string(),
        ]);
    }

    println!("{table}");
    println!(
        "{} services, {} endpoints: {} critical, {} high, {} medium, {} low",
        report.summary.services,
        report.summary.endpoints,
        report.summary.critical,
        report.summary.high,
        report.summary.medium,
        report.summary.low
    );
    if !report.summary.statuses.is_empty() {
        let statuses: Vec<String> = report
            .summary
            .statuses
            .iter()
            .map(|(status, count)| format!("{status}={count}"))
            .collect();
        println!("Lifecycle predictions: {}", statuses.join(", "));
    }

    if let Some(path) = output {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).ok();
        }
        let text = serde_json::to_string_pretty(report)?;
        fs::write(path, text).with_context(|| format!("failed to write {}", path.display()))?;
        println!("Wrote JSON report to {}", path.display());
    }

    Ok(())
}

pub fn severity(result: &AnalyzeResult) -> &str {
    result
        .ml_enhanced
        .get("severity")
        .and_then(Value::as_str)
        .or_else(|| {
            result
                .security
                .get("overall_severity")
                .and_then(Value::as_str)
        })
        .unwrap_or("unknown")
}

pub fn severity_rank(value: &str) -> usize {
    match value.to_ascii_lowercase().as_str() {
        "critical" => 4,
        "high" => 3,
        "medium" => 2,
        "low" => 1,
        "info" => 0,
        _ => 0,
    }
}

#[allow(dead_code)]
pub fn exceeds_threshold(report: &Report, threshold: &str) -> bool {
    let threshold = severity_rank(threshold);
    report
        .results
        .iter()
        .any(|result| severity_rank(severity(result)) >= threshold)
}

pub fn print_doctor(server: &str, health: &Value, model_count: Option<usize>) {
    println!("ZADDP server: {server}");
    let status = health
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let version = health
        .get("version")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    println!("Health: {status} (version {version})");
    if let Some(count) = model_count {
        println!("Registered ML models: {count}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranks_severities() {
        assert!(severity_rank("critical") > severity_rank("high"));
        assert!(severity_rank("high") > severity_rank("medium"));
        assert_eq!(severity_rank("unknown"), 0);
    }
}
