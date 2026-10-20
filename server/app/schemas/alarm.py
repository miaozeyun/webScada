"""报警记录接口 DTO（M5）：运行数据由前端报警引擎上报。"""
from datetime import datetime

from pydantic import BaseModel, Field


class AlarmRecordIn(BaseModel):
    ruleId: str = Field(min_length=1, max_length=64)
    variableKey: str = Field(min_length=1, max_length=128)
    level: str = Field(pattern="^(info|warn|critical)$")
    message: str = Field(min_length=1, max_length=512)
    value: str | None = None
    status: str = Field(pattern="^(active|recovered)$")


class AlarmRecordOut(BaseModel):
    id: int
    ruleId: str
    variableKey: str
    level: str
    message: str
    value: str | None
    status: str
    triggeredAt: datetime
    recoveredAt: datetime | None
