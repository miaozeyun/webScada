"""工程管理接口 DTO。

PUT 的 doc 与导入的 doc 均以原始 dict 传入（结构校验统一在 doc_service 流水线执行，
以便区分"字段缺省/null"实现凭证空值保留合并，并输出 G20 规定的字段路径错误体）。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    # project.name ≤ 128 字符（G33，与 doc 内 ProjectMeta.name 同一口径）
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)


class ProjectUpdate(BaseModel):
    doc: dict  # 原始 ProjectDoc（服务端流水线校验）
    baseRevision: int = Field(ge=1)  # 乐观锁（G2）


class ImportBody(BaseModel):
    doc: dict  # 导出文件内容原样（前端 FileReader 读文件后 POST JSON）


class ProjectOut(BaseModel):
    """工程详情（含脱敏后 doc）/ 创建返回。"""
    id: str
    name: str
    description: str | None
    revision: int
    createdAt: datetime
    updatedAt: datetime
    doc: dict | None = None


class ProjectListItem(BaseModel):
    """列表项（不含 doc，03-接口清单 §2.3）。"""
    id: str
    name: str
    description: str | None
    revision: int
    updatedAt: datetime


class ProjectListOut(BaseModel):
    total: int
    page: int
    size: int
    items: list[ProjectListItem]


class ProjectSaveOut(BaseModel):
    revision: int
    updatedAt: datetime
    """非阻断告警（02 §2.13 规则 7：单页组件 > 200 时附 warnings 不阻断）"""
    warnings: list[str] = Field(default_factory=list)
