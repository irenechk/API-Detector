import uuid
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import require_admin
from app.database import get_db
from app.ml.enhanced_classifier import ApiFeatures, predict_api_status
from app.ml.governance import (
    generate_model_card,
    get_drift_detector,
    get_model_registry,
    record_audit_event,
)
from app.models import API
from app.schemas import APIResponse

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


class BaselineRequest(BaseModel):
    predictions: Optional[list[dict]] = None
    limit: int = 500


def _api_query():
    return select(API).options(
        selectinload(API.traffic_metrics),
        selectinload(API.security_findings),
        selectinload(API.decommission_workflow),
    )


def _public_version(version) -> dict:
    payload = version.to_dict()
    payload.pop("model_path", None)
    return payload


@router.get("/status/{api_id}")
async def get_status_prediction(
    api_id: str,
    include_features: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    try:
        uid = uuid.UUID(api_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid API ID")

    result = await db.execute(_api_query().where(API.id == uid))
    api = result.scalar_one_or_none()
    if not api:
        raise HTTPException(status_code=404, detail="API not found")

    prediction = predict_api_status(api)
    if prediction.get("status") == "unknown":
        raise HTTPException(status_code=503, detail="Status model is not available")

    get_drift_detector().record_prediction(prediction)

    data = {
        "api_id": str(api.id),
        "current_status": api.status,
        "prediction": prediction,
    }
    if include_features:
        data["features"] = asdict(ApiFeatures.from_db(api))
    return APIResponse(data=data)


@router.get("/models")
async def list_models(model_type: Optional[str] = Query(None)):
    versions = get_model_registry().list_versions(model_type)
    models = [_public_version(version) for version in versions]
    return APIResponse(data={"total": len(models), "models": models})


@router.get("/models/{model_type}/{version}/card", response_class=PlainTextResponse)
async def get_model_card(model_type: str, version: str):
    card = generate_model_card(model_type, version)
    if card.startswith("# No model registered"):
        raise HTTPException(status_code=404, detail="Model version not found")
    return card


@router.post("/models/{model_type}/{version}/promote")
async def promote_model(
    model_type: str,
    version: str,
    user: dict = Depends(require_admin),
):
    registry = get_model_registry()
    matches = [v for v in registry.list_versions(model_type) if v.version == version]
    if not matches:
        raise HTTPException(status_code=404, detail="Model version not found")

    registry.promote_to_champion(version, model_type)
    record_audit_event(
        "promote_model",
        str(user.get("email", "unknown")),
        {"model_type": model_type, "version": version},
    )
    return APIResponse(message=f"Promoted {model_type} {version} to champion")


@router.get("/monitoring/drift")
async def get_drift():
    detector = get_drift_detector()
    return APIResponse(data={
        "threshold": detector.threshold,
        "buffered_predictions": detector.buffered_count(),
        "latest": detector.latest_report(),
    })


@router.post("/monitoring/baseline")
async def set_drift_baseline(
    payload: BaselineRequest,
    user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    predictions = payload.predictions
    if not predictions:
        result = await db.execute(_api_query().limit(max(1, min(payload.limit, 2000))))
        predictions = []
        for api in result.scalars().all():
            prediction = predict_api_status(api)
            if prediction.get("status") != "unknown":
                predictions.append(prediction)

    if not predictions:
        raise HTTPException(status_code=400, detail="No predictions available for baseline")

    get_drift_detector().set_baseline(predictions)
    record_audit_event(
        "set_drift_baseline",
        str(user.get("email", "unknown")),
        {"samples": len(predictions)},
    )
    return APIResponse(
        message="Drift baseline updated",
        data={"samples": len(predictions)},
    )
