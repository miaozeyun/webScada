"""认证接口 DTO。

命名约定（与 03-接口清单示例一致）：OAuth 相关沿用 snake_case（access_token），
业务数据对象用 camelCase（createdAt/updatedAt）。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class UserOut(BaseModel):
    id: str
    username: str
    createdAt: datetime


class ChangePasswordRequest(BaseModel):
    oldPassword: str = Field(min_length=1, max_length=128)
    # 新密码最少 8 位（03-接口清单 §2.2）
    newPassword: str = Field(min_length=8, max_length=128)
