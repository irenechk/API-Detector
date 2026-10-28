use std::env;
use std::fs;
use std::path::PathBuf;

use anyhow::{Context, Result};
use serde::Deserialize;

#[derive(Debug, Clone)]
pub struct Config {
    pub server: String,
    pub token: Option<String>,
    pub host: String,
    pub timeout_seconds: u64,
    pub max_endpoints: usize,
    pub include_ports: Vec<u16>,
    pub exclude_ports: Vec<u16>,
    pub scan_html: bool,
    pub probe_common: bool,
    pub insecure: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: "http://localhost:8000".to_string(),
            token: None,
            host: "127.0.0.1".to_string(),
            timeout_seconds: 3,
            max_endpoints: 2000,
            include_ports: Vec::new(),
            exclude_ports: vec![22, 3306, 5432, 6379, 27017],
            scan_html: true,
            probe_common: false,
            insecure: false,
        }
    }
}

#[derive(Debug, Default, Deserialize)]
struct FileConfig {
    server: Option<String>,
    token: Option<String>,
    host: Option<String>,
    timeout_seconds: Option<u64>,
    max_endpoints: Option<usize>,
    include_ports: Option<Vec<u16>>,
    exclude_ports: Option<Vec<u16>>,
    scan_html: Option<bool>,
    probe_common: Option<bool>,
    insecure: Option<bool>,
}

pub fn config_path() -> Option<PathBuf> {
    if let Ok(path) = env::var("ZADDP_CONFIG") {
        return Some(PathBuf::from(path));
    }
    dirs::config_dir().map(|dir| dir.join("zaddp").join("config.toml"))
}

impl Config {
    pub fn load() -> Result<Self> {
        let mut config = Self::default();

        if let Some(path) = config_path() {
            if path.exists() {
                let raw = fs::read_to_string(&path)
                    .with_context(|| format!("failed to read config {}", path.display()))?;
                let file: FileConfig = toml::from_str(&raw)
                    .with_context(|| format!("invalid config {}", path.display()))?;
                config.apply_file(file);
            }
        }

        if let Ok(server) = env::var("ZADDP_URL") {
            if !server.trim().is_empty() {
                config.server = server;
            }
        }
        if let Ok(token) = env::var("ZADDP_TOKEN") {
            if !token.trim().is_empty() {
                config.token = Some(token);
            }
        }
        if let Ok(host) = env::var("ZADDP_SCAN_HOST") {
            if !host.trim().is_empty() {
                config.host = host;
            }
        }

        config.server = config.server.trim_end_matches('/').to_string();
        Ok(config)
    }

    fn apply_file(&mut self, file: FileConfig) {
        if let Some(value) = file.server {
            self.server = value;
        }
        if let Some(value) = file.token {
            self.token = Some(value);
        }
        if let Some(value) = file.host {
            self.host = value;
        }
        if let Some(value) = file.timeout_seconds {
            self.timeout_seconds = value;
        }
        if let Some(value) = file.max_endpoints {
            self.max_endpoints = value;
        }
        if let Some(value) = file.include_ports {
            self.include_ports = value;
        }
        if let Some(value) = file.exclude_ports {
            self.exclude_ports = value;
        }
        if let Some(value) = file.scan_html {
            self.scan_html = value;
        }
        if let Some(value) = file.probe_common {
            self.probe_common = value;
        }
        if let Some(value) = file.insecure {
            self.insecure = value;
        }
    }

    pub fn allowed_port(&self, port: u16) -> bool {
        if self.include_ports.is_empty() {
            !self.exclude_ports.contains(&port)
        } else {
            self.include_ports.contains(&port)
        }
    }
}
