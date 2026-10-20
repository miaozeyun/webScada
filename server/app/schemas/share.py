"""分享链接接口 DTO（M6）。"""
from datetime import datetime

from pydantic import BaseModel, Field


class ShareCreate(BaseModel):
    """expiresHours 为空 = 永不过期。"""
    expiresHours: int | None = Field(default=None, ge=1, le=24 * 365)


class ShareOut(BaseModel):
    token: str
    expiresAt: datetime | None
    createdAt: datetime


class ShareDoc(BaseModel):
    """公开访问返回：脱敏快照 doc（数据源凭证恒为空，G5/G6）。"""
    projectName: str
    doc: dict
