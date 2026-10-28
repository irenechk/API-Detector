"""
Data source abstractions for the ML data pipeline.

Each source defines how to connect, fetch, and normalize data
from a specific production system into a common schema.

In production, these would connect to real systems:
  - GatewayLogSource  → Apigee/Kong/NGINX access logs (via S3/Kafka)
  - CMDBSource        → ServiceNow CMDB REST API
  - ScannerSource     → GitGuardian/CodeQL/Qualys scanner DB
  - SyntheticSource   → Built-in generator for dev/demo environments
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data Transfer Objects (canonical schema) ────────────────────────────────

@dataclass
class RawTrafficRecord:
    """A single API request log entry (aggregated window)."""
    api_path: str
    http_method: str
    environment: str
    timestamp: datetime
    request_count: int
    error_4xx_count: int
    error_5xx_count: int
    avg_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    unique_ips: int
    source_system: str = "gateway"


@dataclass
class RawAPIRecord:
    """An API registration/asset record from CMDB or inventory system."""
    endpoint_path: str
    http_method: str
    environment: str
    status: str
    risk_score: int
    data_sensitivity: str
    owner_team: Optional[str] = None
    owner_email: Optional[str] = None
    business_domain: Optional[str] = None
    protocol: str = "HTTPS"
    tls_version: Optional[str] = None
    framework: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    last_traffic_timestamp: Optional[datetime] = None
    deprecation_date: Optional[datetime] = None
    decommission_date: Optional[datetime] = None
    api_metadata: Optional[dict] = None
    tags: Optional[list[str]] = None
    has_workflow: bool = False
    source_system: str = "cmdb"


@dataclass
class RawFindingRecord:
    """A security finding from a vulnerability scanner."""
    api_path: str
    http_method: str
    dimension: str
    severity: str
    title: str
    description: Optional[str] = None
    cvss_score: Optional[float] = None
    status: str = "open"
    source_system: str = "scanner"


# ── Data Source Interface ───────────────────────────────────────────────────

class DataSource(ABC):
    """Abstract base for a data source that feeds the ML pipeline."""

    @abstractmethod
    def fetch_traffic(self, since: datetime) -> list[RawTrafficRecord]:
        ...

    @abstractmethod
    def fetch_apis(self) -> list[RawAPIRecord]:
        ...

    @abstractmethod
    def fetch_findings(self, since: datetime) -> list[RawFindingRecord]:
        ...

    @abstractmethod
    def name(self) -> str:
        ...


# ── Synthetic Source (fallback for dev/demo) ────────────────────────────────

class SyntheticSource(DataSource):
    """Built-in data generator that mirrors seed.py patterns.
    Used when no production data sources are configured."""

    STATUS_TRAFFIC = {
        "active": (100, 5000),
        "deprecated": (10, 100),
        "orphaned": (5, 50),
        "shadow": (50, 200),
        "zombie": (0, 3),
    }
    STATUS_FINDINGS = {
        "active": (0, 2),
        "deprecated": (3, 8),
        "orphaned": (1, 4),
        "shadow": (4, 10),
        "zombie": (5, 12),
    }
    STATUS_RISK = {
        "active": (70, 95),
        "deprecated": (50, 70),
        "orphaned": (40, 75),
        "shadow": (75, 98),
        "zombie": (60, 90),
    }

    def __init__(self):
        import random
        self._rng = random.Random(42)
        self._last_apis: list[RawAPIRecord] = []

    def name(self) -> str:
        return "synthetic"

    def fetch_traffic(self, since: datetime) -> list[RawTrafficRecord]:
        """Generate synthetic traffic mirroring the status label semantics."""
        apis = self._last_apis or self.fetch_apis()
        records = []
        for api in apis:
            low, high = self.STATUS_TRAFFIC.get(api.status, (10, 200))
            base_req = self._rng.randint(low, high)
            end = api.last_traffic_timestamp or since
            for day in range(30):
                records.append(RawTrafficRecord(
                    api_path=api.endpoint_path,
                    http_method=api.http_method,
                    environment=api.environment,
                    timestamp=end - timedelta(days=day),
                    request_count=max(0, int(base_req * (1 + self._rng.gauss(0, 0.1)))),
                    error_4xx_count=int(base_req * self._rng.uniform(0.01, 0.05)),
                    error_5xx_count=int(base_req * self._rng.uniform(0.005, 0.02)),
                    avg_response_time_ms=round(self._rng.uniform(45, 300), 1),
                    p95_response_time_ms=round(self._rng.uniform(120, 750), 1),
                    p99_response_time_ms=round(self._rng.uniform(250, 1800), 1),
                    unique_ips=self._rng.randint(10, 500),
                    source_system="synthetic",
                ))
        return records

    def fetch_apis(self) -> list[RawAPIRecord]:
        """Generate synthetic API records matching the status training generator."""
        from app.ml.data import generate_dataset
        samples = generate_dataset()
        now = datetime.utcnow()

        statuses = ["active"] * 180 + ["deprecated"] * 48 + ["orphaned"] * 32 + ["shadow"] * 20 + ["zombie"] * 20
        self._rng.shuffle(statuses)

        owner_statuses = {"active", "deprecated", "zombie"}
        workflow_statuses = {"zombie"}

        records = []
        for i, s in enumerate(samples):
            status = statuses[i % len(statuses)]
            risk_low, risk_high = self.STATUS_RISK.get(status, (40, 70))
            records.append(RawAPIRecord(
                endpoint_path=s["endpoint_path"],
                http_method=s["http_method"],
                environment=self._rng.choice(["production"] * 6 + ["staging"] * 2 + ["development"]),
                status=status,
                risk_score=self._rng.randint(risk_low, risk_high),
                data_sensitivity=self._rng.choice(["public", "internal", "confidential", "restricted"]),
                owner_team=self._rng.choice(["Payments", "Core Banking", "Digital", "Risk"]) if status in owner_statuses else None,
                business_domain=self._rng.choice(["Payments", "Auth", "Data", "Admin", "Health"]),
                first_seen=now - timedelta(days=self._rng.randint(30, 365)),
                last_seen=now - timedelta(days=self._rng.randint(0, 7)) if status == "active" else now - timedelta(days=self._rng.randint(30, 180)),
                last_traffic_timestamp=now - timedelta(days=self._rng.randint(0, 7)) if status == "active" else now - timedelta(days=self._rng.randint(15, 90)),
                has_workflow=status in workflow_statuses,
                source_system="synthetic",
            ))
        self._last_apis = records
        return records

    def fetch_findings(self, since: datetime) -> list[RawFindingRecord]:
        """Generate findings attached to actual synthetic API records."""
        from app.ml.data import VULN_TYPES as vuln_titles
        apis = self._last_apis or self.fetch_apis()
        findings = []
        for api in apis:
            low, high = self.STATUS_FINDINGS.get(api.status, (0, 3))
            for _ in range(self._rng.randint(low, high)):
                findings.append(RawFindingRecord(
                    api_path=api.endpoint_path,
                    http_method=api.http_method,
                    dimension=self._rng.choice(["auth", "encryption", "input_validation", "cors", "rate_limiting"]),
                    severity=self._rng.choice(["critical", "high", "medium", "low"]),
                    title=self._rng.choice(vuln_titles),
                    cvss_score=round(self._rng.uniform(3.0, 9.5), 1),
                    source_system="synthetic",
                ))
        return findings


# ── Gateway Log Source (Apigee/Kong/NGINX) ─────────────────────────────────

class GatewayLogSource(DataSource):
    """Ingests API traffic data from gateway access logs.

    In production, this reads from:
      - S3 (NGINX/Apigee raw logs, partitioned by date)
      - Kafka topic (real-time aggregated metrics)
      - Elasticsearch (Kibana monitoring indices)

    Configuration (env vars):
      GATEWAY_LOG_TYPE       : "apigee" | "kong" | "nginx" | "s3"
      GATEWAY_LOG_PATH       : S3 URI or file path
      GATEWAY_KAFKA_TOPIC    : Kafka topic for real-time ingestion
    """

    def __init__(self, log_type: str = "apigee", config: Optional[dict] = None):
        self.log_type = log_type
        self.config = config or {}
        self._connected = False

    def name(self) -> str:
        return f"gateway.{self.log_type}"

    def _connect(self):
        """Establish connection to the data source.
        In production this initializes S3 client, Kafka consumer, or ES client."""
        if self._connected:
            return
        log_type = self.log_type
        cfg = self.config

        if log_type == "s3":
            import boto3  # type: ignore
            self._client = boto3.client(
                "s3",
                aws_access_key_id=cfg.get("aws_access_key_id"),
                aws_secret_access_key=cfg.get("aws_secret_access_key"),
                region_name=cfg.get("region", "us-east-1"),
            )
            self._bucket = cfg.get("bucket", "bank-api-logs")
            logger.info("Connected to S3 gateway log bucket: %s", self._bucket)

        elif log_type == "kafka":
            try:
                from confluent_kafka import Consumer  # type: ignore
                self._consumer = Consumer({
                    "bootstrap.servers": cfg.get("bootstrap_servers", "localhost:9092"),
                    "group.id": "zaddp-ml-pipeline",
                    "auto.offset.reset": "earliest",
                })
                self._topic = cfg.get("topic", "api-gateway-metrics")
                logger.info("Connected to Kafka topic: %s", self._topic)
            except ImportError:
                logger.warning("confluent_kafka not installed; using mock")

        elif log_type == "elasticsearch":
            from elasticsearch import Elasticsearch  # type: ignore
            self._es = Elasticsearch(cfg.get("es_hosts", ["http://localhost:9200"]))
            self._index = cfg.get("es_index", "api-gateway-logs-*")
            logger.info("Connected to Elasticsearch index: %s", self._index)

        else:
            logger.info("Gateway source '%s' configured (no connection needed)", log_type)

        self._connected = True

    def fetch_traffic(self, since: datetime) -> list[RawTrafficRecord]:
        self._connect()

        # In production: query the actual data source
        if self.log_type == "s3":
            return self._fetch_from_s3(since)
        elif self.log_type == "kafka":
            return self._fetch_from_kafka(since)
        elif self.log_type == "elasticsearch":
            return self._fetch_from_es(since)

        logger.warning("GatewayLogSource: no data fetched (mock mode returning empty)")
        return []

    def _fetch_from_s3(self, since: datetime) -> list[RawTrafficRecord]:
        """Read access logs from S3, parse into traffic records.
        Expected format: Newline-delimited JSON (JSONL) with date partition prefix."""
        records = []
        prefix = f"logs/year={since.year}/month={since.month:02d}/day="

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    response = self._client.get_object(Bucket=self._bucket, Key=key)
                    body = response["Body"].read().decode("utf-8")

                    for line in body.strip().split("\n"):
                        record = self._parse_gateway_log_line(line)
                        if record:
                            records.append(record)

            logger.info("Fetched %d traffic records from S3 (since %s)", len(records), since)
        except Exception as e:
            logger.error("S3 fetch failed: %s", e)

        return records

    def _fetch_from_kafka(self, since: datetime) -> list[RawTrafficRecord]:
        """Consume metrics from Kafka topic."""
        records = []
        try:
            from confluent_kafka import Consumer
            self._consumer.subscribe([self._topic])
            msg_count = 0
            while msg_count < 1000:
                msg = self._consumer.poll(1.0)
                if msg is None:
                    break
                if msg.error():
                    logger.error("Kafka error: %s", msg.error())
                    break
                record = self._parse_gateway_log_line(msg.value().decode("utf-8"))
                if record:
                    records.append(record)
                    msg_count += 1
            self._consumer.close()
            logger.info("Consumed %d traffic records from Kafka", len(records))
        except ImportError:
            logger.warning("Kafka consumer not available")
        except Exception as e:
            logger.error("Kafka fetch failed: %s", e)
        return records

    def _fetch_from_es(self, since: datetime) -> list[RawTrafficRecord]:
        """Query Elasticsearch for aggregated traffic metrics."""
        records = []
        try:
            query = {
                "query": {
                    "range": {"@timestamp": {"gte": since.isoformat()}}
                },
                "size": 5000,
            }
            resp = self._es.search(index=self._index, body=query)
            for hit in resp["hits"]["hits"]:
                src = hit["_source"]
                records.append(RawTrafficRecord(
                    api_path=src.get("api_path", src.get("path", "/")),
                    http_method=src.get("http_method", "GET"),
                    environment=src.get("environment", "production"),
                    timestamp=datetime.fromisoformat(src.get("@timestamp", since.isoformat())),
                    request_count=int(src.get("request_count", src.get("count", 1))),
                    error_4xx_count=int(src.get("error_4xx_count", 0)),
                    error_5xx_count=int(src.get("error_5xx_count", 0)),
                    avg_response_time_ms=float(src.get("avg_response_time_ms", src.get("latency", 0))),
                    p95_response_time_ms=float(src.get("p95_response_time_ms", 0)),
                    p99_response_time_ms=float(src.get("p99_response_time_ms", 0)),
                    unique_ips=int(src.get("unique_ips", src.get("client_ips", 0))),
                    source_system="elasticsearch",
                ))
            logger.info("Fetched %d traffic records from ES", len(records))
        except Exception as e:
            logger.error("ES fetch failed: %s", e)
        return records

    def _parse_gateway_log_line(self, line: str) -> Optional[RawTrafficRecord]:
        """Parse a single log line from a gateway access log."""
        try:
            data = json.loads(line.strip())
        except json.JSONDecodeError:
            return None

        return RawTrafficRecord(
            api_path=data.get("api_path", data.get("path", data.get("request_uri", "/"))),
            http_method=data.get("http_method", data.get("method", "GET")),
            environment=data.get("environment", data.get("env", "production")),
            timestamp=datetime.fromisoformat(
                data.get("@timestamp", data.get("timestamp", data.get("time", datetime.utcnow().isoformat())))
            ),
            request_count=int(data.get("request_count", data.get("count", 1))),
            error_4xx_count=int(data.get("error_4xx_count", data.get("status_4xx", 0))),
            error_5xx_count=int(data.get("error_5xx_count", data.get("status_5xx", 0))),
            avg_response_time_ms=float(data.get("avg_response_time_ms", data.get("latency", data.get("response_time", 0)))),
            p95_response_time_ms=float(data.get("p95_response_time_ms", 0)),
            p99_response_time_ms=float(data.get("p99_response_time_ms", 0)),
            unique_ips=int(data.get("unique_ips", data.get("client_ip_count", data.get("unique_clients", 0)))),
            source_system=f"gateway.{self.log_type}",
        )

    def fetch_apis(self) -> list[RawAPIRecord]:
        logger.warning("GatewayLogSource does not provide API metadata")
        return []

    def fetch_findings(self, since: datetime) -> list[RawFindingRecord]:
        logger.warning("GatewayLogSource does not provide security findings")
        return []


# ── CMDB Source (ServiceNow) ────────────────────────────────────────────────

class CMDBSource(DataSource):
    """Ingests API asset metadata from CMDB (ServiceNow).

    In production, connects via:
      - ServiceNow REST API (Table API for cmdb_ci_api)
      - Configuration management DB (direct SQL)

    Configuration (env vars):
      CMDB_API_URL   : ServiceNow instance URL
      CMDB_API_USER  : ServiceNow username
      CMDB_API_PASS  : ServiceNow password
      CMDB_TABLE     : CMDB table name (default: cmdb_ci_api)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._connected = False

    def name(self) -> str:
        return "cmdb.servicenow"

    def _connect(self):
        if self._connected:
            return
        api_url = self.config.get("api_url", os.getenv("CMDB_API_URL"))
        username = self.config.get("api_user", os.getenv("CMDB_API_USER"))
        password = self.config.get("api_pass", os.getenv("CMDB_API_PASS"))
        self._table = self.config.get("table", os.getenv("CMDB_TABLE", "cmdb_ci_api"))

        if api_url and username and password:
            import requests
            self._session = requests.Session()
            self._session.auth = (username, password)
            self._base_url = api_url.rstrip("/")
            logger.info("Connected to ServiceNow CMDB: %s (table: %s)", self._base_url, self._table)
        else:
            logger.warning("CMDB not configured (set CMDB_API_URL, CMDB_API_USER, CMDB_API_PASS)")

        self._connected = True

    def fetch_apis(self) -> list[RawAPIRecord]:
        self._connect()
        records = []
        svc_now_url = self.config.get("api_url", os.getenv("CMDB_API_URL"))

        if svc_now_url:
            try:
                import requests
                url = f"{svc_now_url.rstrip('/')}/api/now/table/{self._table}"
                params = {"sysparm_limit": 5000, "sysparm_fields": "name,install_status,u_environment,u_risk_score,u_data_sensitivity,owned_by,business_unit,short_description,sys_created_on,sys_updated_on,u_protocol,u_tls_version"}
                resp = self._session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("result", []):
                    records.append(self._parse_cmdb_record(item))
                logger.info("Fetched %d API records from ServiceNow", len(records))

            except Exception as e:
                logger.error("ServiceNow CMDB fetch failed: %s", e)
        else:
            logger.warning("No CMDB configured, returning empty API list")

        return records

    def _parse_cmdb_record(self, item: dict) -> RawAPIRecord:
        """Map ServiceNow CMDB fields to canonical schema."""
        import re
        path = item.get("name", "/unknown")
        method = "GET"
        if re.search(r"(create|save|post|add|register)", path, re.IGNORECASE):
            method = "POST"
        elif re.search(r"(update|edit|modify)", path, re.IGNORECASE):
            method = "PUT"
        elif re.search(r"(delete|remove)", path, re.IGNORECASE):
            method = "DELETE"

        now = datetime.utcnow()
        return RawAPIRecord(
            endpoint_path=path,
            http_method=method,
            environment=item.get("u_environment", "production"),
            status=item.get("install_status", "active"),
            risk_score=int(item.get("u_risk_score", 50)),
            data_sensitivity=item.get("u_data_sensitivity", "internal"),
            owner_team=item.get("business_unit"),
            business_domain=item.get("short_description"),
            protocol=item.get("u_protocol", "HTTPS"),
            tls_version=item.get("u_tls_version"),
            first_seen=self._parse_sn_datetime(item.get("sys_created_on")) or now,
            last_seen=self._parse_sn_datetime(item.get("sys_updated_on")) or now,
            source_system="cmdb.servicenow",
        )

    @staticmethod
    def _parse_sn_datetime(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def fetch_traffic(self, since: datetime) -> list[RawTrafficRecord]:
        return []

    def fetch_findings(self, since: datetime) -> list[RawFindingRecord]:
        return []


# ── Scanner Source (GitGuardian / Qualys) ───────────────────────────────────

class ScannerSource(DataSource):
    """Ingests security findings from vulnerability scanners.

    In production, connects via:
      - GitGuardian API (for secret leaks in repos)
      - CodeQL API (for code-level vulnerabilities)
      - Qualys/Tenable API (for infrastructure scans)
    """

    def __init__(self, scanner_type: str = "gitguardian", config: Optional[dict] = None):
        self.scanner_type = scanner_type
        self.config = config or {}

    def name(self) -> str:
        return f"scanner.{self.scanner_type}"

    def fetch_findings(self, since: datetime) -> list[RawFindingRecord]:
        api_key = self.config.get("api_key", os.getenv(f"{self.scanner_type.upper()}_API_KEY"))
        api_url = self.config.get("api_url", os.getenv(f"{self.scanner_type.upper()}_API_URL"))

        if not api_key or not api_url:
            logger.warning("%s not configured", self.scanner_type)
            return []

        try:
            import requests
            headers = {"Authorization": f"Bearer {api_key}"}
            params = {"since": since.isoformat(), "limit": 1000}
            resp = requests.get(f"{api_url.rstrip('/')}/api/v1/findings", headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            records = []
            for finding in data.get("results", data.get("findings", [])):
                records.append(self._parse_finding(finding))

            logger.info("Fetched %d findings from %s", len(records), self.scanner_type)
            return records

        except ImportError:
            logger.warning("requests not installed")
        except Exception as e:
            logger.error("%s fetch failed: %s", self.scanner_type, e)

        return []

    def _parse_finding(self, finding: dict) -> RawFindingRecord:
        return RawFindingRecord(
            api_path=finding.get("path", finding.get("api_path", "/unknown")),
            http_method=finding.get("http_method", "GET"),
            dimension=finding.get("dimension", finding.get("category", "unknown")),
            severity=finding.get("severity", finding.get("criticality", "medium")),
            title=finding.get("title", finding.get("name", "Unknown Finding")),
            description=finding.get("description"),
            cvss_score=float(finding["cvss_score"]) if finding.get("cvss_score") else None,
            status=finding.get("status", "open"),
            source_system=f"scanner.{self.scanner_type}",
        )

    def fetch_traffic(self, since: datetime) -> list[RawTrafficRecord]:
        return []

    def fetch_apis(self) -> list[RawAPIRecord]:
        return []


# ── Source Factory ──────────────────────────────────────────────────────────

def get_data_source(source_type: str = "auto", config: Optional[dict] = None) -> DataSource:
    """Factory: create the best available data source.

    Resolution order:
      1. If source_type is specified (gateway, cmdb, scanner), create that.
      2. If 'auto', check environment variables for configured sources.
      3. Fall back to SyntheticSource.
    """
    if source_type == "gateway":
        log_type = config.get("log_type", os.getenv("GATEWAY_LOG_TYPE", "apigee"))
        return GatewayLogSource(log_type=log_type, config=config)

    if source_type == "cmdb":
        return CMDBSource(config=config)

    if source_type == "scanner":
        scanner_type = config.get("scanner_type", os.getenv("SCANNER_TYPE", "gitguardian"))
        return ScannerSource(scanner_type=scanner_type, config=config)

    if source_type == "synthetic":
        return SyntheticSource()

    if source_type == "auto":
        if os.getenv("GATEWAY_LOG_TYPE"):
            log_type = os.getenv("GATEWAY_LOG_TYPE", "s3")
            return GatewayLogSource(log_type=log_type)
        if os.getenv("CMDB_API_URL"):
            return CMDBSource()
        if os.getenv("GITGUARDIAN_API_KEY"):
            return ScannerSource(scanner_type="gitguardian")
        logger.info("No production data sources configured, using synthetic fallback")
        return SyntheticSource()

    raise ValueError(f"Unknown data source: {source_type}")


import os
