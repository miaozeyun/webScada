"""报警接口 DTO（M8 重写，契约 §4.1）：单行状态机出参 + ack 入出参 + 旧前端上报兼容入参。

状态值域（单行状态机）：triggered | acked | cleared；
AlarmRecordIn.status 仍为旧值域 active|recovered（废弃兼容端点专用，映射 trigger/clear）。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class AlarmRecordIn(BaseModel):
    """旧前端上报入参（POST /alarm-records 废弃兼容路径专用；M8 前端已停用该上报）。"""

    ruleId: str = Field(min_length=1, max_length=64)
    variableKey: str = Field(min_length=1, max_length=128)
    level: str = Field(pattern="^(info|warn|critical)$")
    message: str = Field(min_length=1, max_length=512)
    value: str | None = None
    status: str = Field(pattern="^(active|recovered)$")


class AlarmOut(BaseModel):
    """报警列表条目（03 §2.7 M8 修订）。

    ackedBy 为确认人 username（列表展示口径，可读性好）；
    ack 接口出参 AckOut.ackedBy 按契约示例为 user id 串，两者语义不同勿混用。
    """

    id: int
    ruleId: str
    variableKey: str
    level: str
    message: str
    value: str | None
    status: str
    triggeredAt: datetime
    ackedAt: datetime | None = None
    ackedBy: str | None = None
    ackedNote: str | None = None
    clearedAt: datetime | None = None


class AckBody(BaseModel):
    """确认入参：处理说明可选（≤256 字符）。"""

    note: str | None = Field(default=None, max_length=256)


class AckOut(BaseModel):
    """ack 出参（03 §2.7 示例：ackedBy 为 user id 串）。"""

    id: int
    status: str
    ackedAt: datetime
    ackedBy: str
    ackedNote: str | None = None
