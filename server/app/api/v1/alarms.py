"""报警记录接口（M5）：前端报警引擎触发/恢复时上报，供历史查询。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import AlarmRecord, User
from app.schemas.alarm import AlarmRecordIn, AlarmRecordOut
from app.services import project_service

router = APIRouter(tags=["alarms"])


def _to_row(body: AlarmRecordIn) -> dict:
    return {
        "rule_id": body.ruleId,
        "variable_key": body.variableKey,
        "level": body.level,
        "message": body.message,
        "value": body.value,
        "status": body.status,
        "triggered_at": datetime.now(timezone.utc),
        "recovered_at": datetime.now(timezone.utc) if body.status == "recovered" else None,
    }


@router.post("/projects/{project_id}/alarm-records", status_code=201)
async def add_alarm_record(
    project_id: str,
    body: AlarmRecordIn,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project = await project_service.get_project(db, project_id)  # 存在性/属主校验
    db.add(AlarmRecord(project_id=project.id, **_to_row(body)))
    await db.commit()


@router.get("/projects/{project_id}/alarm-records", response_model=list[AlarmRecordOut])
async def list_alarm_records(
    project_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlarmRecordOut]:
    project = await project_service.get_project(db, project_id)
    rows = (
        await db.execute(
            select(AlarmRecord)
            .where(AlarmRecord.project_id == project.id)
            .order_by(AlarmRecord.triggered_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()
    return [
        AlarmRecordOut(
            id=r.id, ruleId=r.rule_id, variableKey=r.variable_key, level=r.level,
            message=r.message, value=r.value, status=r.status,
            triggeredAt=r.triggered_at, recoveredAt=r.recovered_at,
        )
        for r in rows
    ]
