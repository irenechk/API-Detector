"""
Data pipeline for real API data ingestion and feature computation.

Replaces synthetic training data with production bank data sources:
  - Gateway logs (Apigee/Kong/NGINX)
  - CMDB (ServiceNow/Asset DB)
  - Secret scanners (GitGuardian/CodeQL)
  - Vulnerability scanners (Qualys/Tenable)
"""

from app.ml.data_pipeline.sources import (
    DataSource,
    GatewayLogSource,
    CMDBSource,
    ScannerSource,
    SyntheticSource,
    get_data_source,
)
from app.ml.data_pipeline.features import (
    compute_api_features,
    compute_traffic_features,
    compute_risk_features,
    compute_governance_features,
    build_training_record,
)
from app.ml.data_pipeline.pipeline import (
    TrainingDataPipeline,
    build_status_training_data,
)
