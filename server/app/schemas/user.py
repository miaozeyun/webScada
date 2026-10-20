"""用户管理与审计查询 DTO（M8 RBAC，工作包 C；契约 §4.3/§4.4）。

命名约定与 03-接口清单一致：业务数据对象 camelCase（createdAt/newPassword），
role 枚举小写（admin/operator/viewer，与 users.role CHECK 约束同口径）。
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 三级角色（契约 §1 配套闭环 + 03 §1.2）：admin=用户管理/审计/全部工程；
# operator=工程读写/反控/报警确认；viewer=只读
Role = Literal["admin", "operator", "viewer"]


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)  # ≥8 位（§4.3）
    role: Role


class UserUpdate(BaseModel):
    """PUT /users/{id}：仅支持角色调整（改密走独立端点，防误携带）。"""

    role: Role


class UserOut(BaseModel):
    """用户出口；/auth/me 复用（M8 起增加 role 字段，契约 §4.3）。"""

    id: str
    username: str
    role: str
    createdAt: datetime


class UserPasswordReset(BaseModel):
    """admin 重置密码：无需旧密码（§4.3）。"""

    newPassword: str = Field(min_length=8, max_length=128)


class UserListOut(BaseModel):
    total: int
    page: int
    size: int
    items: list[UserOut]


class AuditLogOut(BaseModel):
    """审计日志出口（§4.4）：username 为触发时快照，用户删除后仍可读。"""

    id: int
    userId: str | None = None
    username: str | None = None
    action: str
    targetType: str | None = None
    targetId: str | None = None
    detail: dict | None = None
    ip: str | None = None
    createdAt: datetime


class AuditLogListOut(BaseModel):
    total: int
    page: int
    size: int
    items: list[AuditLogOut]
