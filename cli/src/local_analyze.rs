use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;

use crate::discovery::Endpoint;

#[derive(Serialize)]
struct InferRequest {
    endpoints: Vec<Endpoint>,
    manifest_mode: bool,
}

#[derive(Deserialize)]
struct InferResponse {
    results: Vec<Value>,
}

fn find_python() -> Option<String> {
    for candidate in ["python3", "python"] {
        if Command::new(candidate)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return Some(candidate.to_string());
        }
    }
    None
}

fn find_infer_script() -> Option<PathBuf> {
    let mut candidates = vec![
        PathBuf::from("/usr/lib/zaddp/infer.py"),
        PathBuf::from("/usr/local/lib/zaddp/infer.py"),
    ];
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("../lib/zaddp/infer.py"));
            candidates.push(dir.join("infer.py"));
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("cli/infer/infer.py"));
        candidates.push(cwd.join("infer/infer.py"));
    }
    for c in candidates {
        if c.exists() {
            return Some(c);
        }
    }
    None
}

pub fn analyze_local(endpoints: &[Endpoint]) -> Result<Vec<Value>> {
    let python = find_python().context("python3 not found; install Python 3.11+")?;
    let script = find_infer_script().context("local inference script not found")?;
    
    let input = serde_json::to_string(&InferRequest {
        endpoints: endpoints.to_vec(),
        manifest_mode: true,
    })?;
    
    let output = Command::new(python)
        .arg(&script)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .and_then(|mut child| {
            use std::io::Write;
            if let Some(mut stdin) = child.stdin.take() {
                let _ = stdin.write_all(input.as_bytes());
            }
            child.wait_with_output()
        })
        .context("failed to run local inference")?;
    
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("local inference failed: {}", stderr);
    }
    
    let resp: InferResponse = serde_json::from_slice(&output.stdout)
        .context("invalid inference response")?;
    Ok(resp.results)
}
