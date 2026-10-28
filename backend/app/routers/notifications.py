from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
import uuid

from app.database import get_db
from app.models import API, PendingQuarantine, DecommissionWorkflow
from app.schemas import APIResponse, PendingQuarantineItem

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/pending-quarantines")
async def list_pending_quarantines(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PendingQuarantine)
        .options(selectinload(PendingQuarantine.api))
        .where(PendingQuarantine.dismissed_at.is_(None))
        .order_by(PendingQuarantine.detected_at.desc())
    )
    pending = result.scalars().all()

    items = []
    for pq in pending:
        api = pq.api
        if not api:
            continue
        items.append(PendingQuarantineItem(
            id=str(pq.id),
            api_id=str(pq.api_id),
            endpoint_path=api.endpoint_path,
            http_method=api.http_method,
            environment=api.environment,
            risk_score=api.risk_score,
            owner_team=api.owner_team,
            reason=pq.reason,
            detected_at=pq.detected_at,
        ))

    return APIResponse(data=items)


@router.post("/pending-quarantines/{pq_id}/approve")
async def approve_quarantine(pq_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(pq_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pending quarantine ID")

    result = await db.execute(
        select(PendingQuarantine)
        .options(selectinload(PendingQuarantine.api))
        .where(PendingQuarantine.id == uid)
    )
    pq = result.scalar_one_or_none()

    if not pq:
        raise HTTPException(status_code=404, detail="Pending quarantine not found")
    if pq.dismissed_at:
        raise HTTPException(status_code=400, detail="Pending quarantine already dismissed")

    api = pq.api
    if not api:
        raise HTTPException(status_code=404, detail="Associated API not found")

    api.status = "zombie"
    api.risk_score = min(100, api.risk_score + 20)

    wf_result = await db.execute(
        select(DecommissionWorkflow).where(DecommissionWorkflow.api_id == api.id)
    )
    workflow = wf_result.scalar_one_or_none()

    if not workflow:
        workflow = DecommissionWorkflow(
            api_id=api.id,
            current_stage="quarantined",
            quarantined_at=datetime.utcnow(),
            quarantined_by="user-action",
            grace_period_days=30,
            auto_decommission_date=datetime.utcnow() + timedelta(days=30),
        )
        db.add(workflow)
    else:
        workflow.current_stage = "quarantined"
        workflow.quarantined_at = datetime.utcnow()
        workflow.quarantined_by = "user-action"

    await db.delete(pq)
    await db.commit()

    return APIResponse(message="API quarantined successfully", data={
        "id": str(api.id),
        "endpoint_path": api.endpoint_path,
        "status": api.status,
    })


@router.post("/pending-quarantines/{pq_id}/dismiss")
async def dismiss_pending_quarantine(pq_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = uuid.UUID(pq_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pending quarantine ID")

    result = await db.execute(
        select(PendingQuarantine).where(PendingQuarantine.id == uid)
    )
    pq = result.scalar_one_or_none()

    if not pq:
        raise HTTPException(status_code=404, detail="Pending quarantine not found")
    if pq.dismissed_at:
        raise HTTPException(status_code=400, detail="Already dismissed")

    pq.dismissed_at = datetime.utcnow()
    await db.commit()

    return APIResponse(message="Pending quarantine dismissed", data={
        "id": str(pq.id),
        "api_id": str(pq.api_id),
    })
