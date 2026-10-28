mod config;
mod discovery;
mod local_analyze;
mod manifest;
mod openapi;
mod output;
mod zaddp_client;

use std::path::PathBuf;
use std::process::ExitCode;

use anyhow::{bail, Result};
use clap::{Parser, Subcommand};
use serde_json::Value;

use crate::config::Config;

#[derive(Parser)]
#[command(
    name = "zaddp",
    version,
    about = "Discover local API services and analyze them with a ZADDP server"
)]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    Scan(Box<ScanArgs>),
    Doctor(DoctorArgs),
    Version,
}

#[derive(Parser, Default)]
struct ScanArgs {
    #[arg(long)]
    server: Option<String>,
    #[arg(long)]
    token: Option<String>,
    #[arg(long)]
    host: Option<String>,
    #[arg(long = "target")]
    targets: Vec<String>,
    #[arg(long, value_delimiter = ',')]
    include_ports: Option<Vec<u16>>,
    #[arg(long, value_delimiter = ',')]
    exclude_ports: Option<Vec<u16>>,
    #[arg(long)]
    timeout: Option<u64>,
    #[arg(long)]
    max_endpoints: Option<usize>,
    #[arg(long)]
    manifest: Option<PathBuf>,
    #[arg(long)]
    traffic_log: Option<PathBuf>,
    #[arg(long)]
    json: bool,
    #[arg(long, short)]
    output: Option<PathBuf>,
    #[arg(long)]
    min_severity: Option<String>,
    #[arg(long)]
    fail_on: Option<String>,
    #[arg(long)]
    insecure: bool,
    #[arg(long)]
    probe_common: bool,
    #[arg(long)]
    no_html: bool,
}

#[derive(Parser)]
struct DoctorArgs {
    #[arg(long)]
    server: Option<String>,
    #[arg(long)]
    token: Option<String>,
    #[arg(long)]
    insecure: bool,
}

fn main() -> ExitCode {
    match run() {
        Ok(code) => code,
        Err(error) => {
            eprintln!("error: {error:#}");
            ExitCode::from(2)
        }
    }
}

fn run() -> Result<ExitCode> {
    let cli = Cli::parse();
    match cli.command.unwrap_or_else(|| Command::Scan(Box::default())) {
        Command::Scan(args) => scan(*args),
        Command::Doctor(args) => doctor(args),
        Command::Version => {
            println!("zaddp {}", env!("CARGO_PKG_VERSION"));
            Ok(ExitCode::SUCCESS)
        }
    }
}

fn scan(args: ScanArgs) -> Result<ExitCode> {
    let config = merged_config(&args)?;
    let mut discovered = discovery::discover(&config.host, &config, &args.targets)?;

    if let Some(path) = &args.manifest {
        let stats = manifest::apply(manifest::load(path)?, &mut discovered.endpoints);
        eprintln!(
            "Manifest: {} endpoints matched, {} unmatched",
            stats.matched, stats.unmatched
        );
    }

    if let Some(path) = &args.traffic_log {
        let matched = manifest::apply_nginx_log(path, &mut discovered.endpoints)?;
        eprintln!("Traffic log: {matched} requests matched");
    }

    if discovered.endpoints.is_empty() {
        bail!("no HTTP endpoints discovered; start a local API, use --target, or add --manifest");
    }

    eprintln!(
        "Discovered {} endpoints across {} services",
        discovered.endpoints.len(),
        discovered.services.len()
    );

    let results: Vec<zaddp_client::AnalyzeResult> = if args.server.is_some() {
        match zaddp_client::analyze(&config, &discovered.endpoints) {
            Ok(results) => results,
            Err(e) => {
                eprintln!("Remote analysis failed ({e:#}), falling back to local analysis");
                let local_results = local_analyze::analyze_local(&discovered.endpoints)?;
                local_results
                    .into_iter()
                    .filter_map(|v| serde_json::from_value(v).ok())
                    .collect()
            }
        }
    } else {
        match local_analyze::analyze_local(&discovered.endpoints) {
            Ok(local_results) => local_results
                .into_iter()
                .filter_map(|v| serde_json::from_value(v).ok())
                .collect(),
            Err(e) => {
                eprintln!("Local analysis unavailable ({e:#}), trying remote server at {}", config.server);
                zaddp_client::analyze(&config, &discovered.endpoints)?
            }
        }
    };
    let should_fail = args.fail_on.as_deref().is_some_and(|threshold| {
        results.iter().any(|result| {
            output::severity_rank(output::severity(result)) >= output::severity_rank(threshold)
        })
    });

    let mut filtered = results;
    output::filter_by_severity(&mut filtered, args.min_severity.as_deref());
    let report = output::Report::new(&config.server, discovered.services, filtered);
    output::print(&report, args.json, args.output.as_deref())?;

    if should_fail {
        Ok(ExitCode::from(1))
    } else {
        Ok(ExitCode::SUCCESS)
    }
}

fn doctor(args: DoctorArgs) -> Result<ExitCode> {
    let mut config = Config::load()?;
    if let Some(server) = args.server {
        config.server = server.trim_end_matches('/').to_string();
    }
    if let Some(token) = args.token {
        config.token = Some(token);
    }
    if args.insecure {
        config.insecure = true;
    }

    let health = zaddp_client::get_json(&config, "/api/v1/health")?;
    let models = zaddp_client::get_json(&config, "/api/v1/ml/models").ok();
    let model_count = models.and_then(|value| {
        value
            .get("data")
            .and_then(|data| data.get("total"))
            .and_then(Value::as_u64)
            .map(|count| count as usize)
    });
    output::print_doctor(&config.server, &health, model_count);
    Ok(ExitCode::SUCCESS)
}

fn merged_config(args: &ScanArgs) -> Result<Config> {
    let mut config = Config::load()?;
    if let Some(server) = &args.server {
        config.server = server.trim_end_matches('/').to_string();
    }
    if let Some(token) = &args.token {
        config.token = Some(token.clone());
    }
    if let Some(host) = &args.host {
        config.host = host.clone();
    }
    if let Some(ports) = &args.include_ports {
        config.include_ports = ports.clone();
    }
    if let Some(ports) = &args.exclude_ports {
        config.exclude_ports = ports.clone();
    }
    if let Some(timeout) = args.timeout {
        config.timeout_seconds = timeout;
    }
    if let Some(max_endpoints) = args.max_endpoints {
        config.max_endpoints = max_endpoints;
    }
    if args.insecure {
        config.insecure = true;
    }
    if args.probe_common {
        config.probe_common = true;
    }
    if args.no_html {
        config.scan_html = false;
    }
    Ok(config)
}
