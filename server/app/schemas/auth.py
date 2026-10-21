"""认证接口 DTO。

命名约定（与 03-接口清单示例一致）：OAuth 相关沿用 snake_case（access_token），
业务数据对象用 camelCase（createdAt/updatedAt）。
"""
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    # 阶段二 Task 3：勾选才签发 refresh token（7 天免重登）；缺省 False 保持旧行为
    rememberMe: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    # rememberMe=True 时签发；明文仅此一次返回（库内只存 sha256）
    refresh_token: str | None = None


class RefreshRequest(BaseModel):
    refreshToken: str = Field(min_length=16, max_length=128)


class RefreshResponse(BaseModel):
    """轮换响应：全新 access + refresh（旧 refresh 一次性消费）。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒
    refresh_token: str


class LogoutRequest(BaseModel):
    """登出请求体（可选）：带 refreshToken 则服务端一并吊销该记住我终端。"""

    refreshToken: str | None = Field(default=None, min_length=16, max_length=128)


class UserOut(BaseModel):
    id: str
    username: str
    createdAt: datetime


class ChangePasswordRequest(BaseModel):
    oldPassword: str = Field(min_length=1, max_length=128)
    # 新密码最少 8 位（03-接口清单 §2.2）
    newPassword: str = Field(min_length=8, max_length=128)
