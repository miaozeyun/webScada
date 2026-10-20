"""分享链接接口 DTO（M6；M8 终审对齐 03-接口清单 §2.6：expiresAt 入参、url/revokedAt 出参、refreshedAt）。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShareCreate(BaseModel):
    """分享有效期入参（03 §2.6：`expiresAt` 为 ISO8601 或 null=永不过期）。

    - expiresAt：契约字段，优先生效
    - expiresHours：M6 旧字段，兼容保留（仅当 expiresAt 未传时按 now+hours 换算）
    - extra=forbid：未知字段拒绝（422），防拼写错误静默落空
    """

    model_config = ConfigDict(extra="forbid")

    expiresAt: datetime | None = None
    expiresHours: int | None = Field(default=None, ge=1, le=24 * 365)


class ShareOut(BaseModel):
    """创建出参（03 §2.6 201 示例）：url 为 /s/{token} 前端路由绝对地址；新建恒 revokedAt=null。"""

    token: str
    url: str
    expiresAt: datetime | None
    revokedAt: datetime | None = None
    createdAt: datetime


class ShareItem(ShareOut):
    """管理端列表项（03 §2.6 GET /projects/{id}/shares）：额外含 lastAccessAt（泄露排查，首次访问前 null）。"""

    lastAccessAt: datetime | None = None


class ShareRefreshOut(BaseModel):
    """refresh 出参（03 §2.6）：仅 token + refreshedAt（快照刷新时间）。"""

    token: str
    refreshedAt: datetime


class ShareDoc(BaseModel):
    """公开访问返回（03 §2.6）：收窄到 {projectId, createdAt, doc}；快照 doc 凭证恒为空（G5/G6）。"""

    projectId: str
    createdAt: datetime
    doc: dict
