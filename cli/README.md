# zaddp

Local service discovery and [ZADDP](https://github.com/gatik1234err/zombieapi) analysis CLI. The CLI finds listening HTTP services on your machine, extracts API endpoints (via OpenAPI/Swagger or HTML/script crawling), and sends them to a running ZADDP server for security classification, risk scoring, and optional lifecycle prediction.

## Install

### Homebrew (macOS/Linux)

```sh
brew tap gatik1234err/zaddp
brew install zaddp
```

### APT (Debian/Ubuntu)

```sh
curl -fsSL https://gatik1234err.github.io/zaddp-apt/zaddp.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/zaddp.gpg

echo "deb [signed-by=/usr/share/keyrings/zaddp.gpg] https://gatik1234err.github.io/zaddp-apt stable main" \
  | sudo tee /etc/apt/sources.list.d/zaddp.list

sudo apt update
sudo apt install zaddp
```

### From GitHub Releases

Download the `.deb` (Linux) or archive (macOS) for your platform from [GitHub Releases](https://github.com/gatik1234err/zombieapi/releases).

## Quick start

```sh
# Check connectivity to your local ZADDP server
zaddp doctor

# Discover local services and analyze them
zaddp scan

# Point to a remote ZADDP server
zaddp scan --server https://zaddp.example.com

# Scan a specific target instead of all listeners
zaddp scan --target http://127.0.0.1:8080

# Add lifecycle context from CMDB/manifest and nginx traffic logs
zaddp scan --manifest zaddp-manifest.json --traffic-log /var/log/nginx/access.log

# Fail CI on high/critical findings
zaddp scan --fail-on high

# Export a report
zaddp scan --json --output report.json
```

## Commands

| Command | Description |
| --- | --- |
| `zaddp scan` | Discover local HTTP listeners and analyze discovered endpoints. |
| `zaddp doctor` | Check server health and registered ML models. |
| `zaddp version` | Print the CLI version. |

## Discovery

1. Enumerates TCP listeners (`/proc/net/tcp` on Linux, `lsof` on macOS).
2. Probes each listener for HTTP/HTTPS.
3. Fetches OpenAPI/Swagger specs from common paths (`/openapi.json`, `/v3/api-docs`, `/swagger.json`, etc.).
4. Falls back to HTML/script crawling to discover API-like paths.
5. Normalizes paths, infers methods, and deduplicates per service.

Use `--include-ports 8080,9000` or `--exclude-ports 5432,6379` to control discovery. Use `--target` to bypass local listener discovery entirely.

## Manifest and traffic logs

### Manifest (JSON or TOML)

```json
{
  "endpoints": [
    {
      "path": "/api/v1/users/42",
      "method": "GET",
      "owner": "identity-team",
      "has_workflow": true,
      "last_seen": "2026-10-20T10:00:00Z",
      "risk_score": 40
    }
  ]
}
```

The CLI matches by exact path or by OpenAPI-style templates like `/api/v1/users/{id}`. Only endpoints with lifecycle data produce `status_prediction` results.

### Traffic logs (nginx combined)

```sh
zaddp scan --traffic-log /var/log/nginx/access.log
```

Requests are matched by method and path/template and aggregated into hourly buckets before being sent to the ZADDP server for status prediction.

## Configuration

Config file: `~/.config/zaddp/config.toml`

```toml
server = "http://localhost:8000"
timeout_seconds = 3
max_endpoints = 2000
exclude_ports = [5432, 6379]
probe_common = false
scan_html = true
```

Environment variables:
- `ZADDP_URL`
- `ZADDP_TOKEN`
- `ZADDP_SCAN_HOST`
- `ZADDP_CONFIG`

## Security

- The CLI never sends POST/PUT/PATCH/DELETE bodies or exploits discovered vulnerabilities.
- By default it only analyzes `127.0.0.1` and ignores common database/cache ports.
- If `SCANNER_API_TOKEN` is set on the ZADDP server, pass `ZADDP_TOKEN` or `--token` to authenticate `POST /api/v1/scanner/analyze`.
- Use `--insecure` only for local development with self-signed certificates.
