"""License key 骨架（M8 阶段 2，commercial-beta 门槛项之一）。

设计口径（与 README「开源核心免费 + 企业版收费」一致）：
- **未配置 LICENSE_KEY = 开源核心模式**：全功能可用，规模上限取 settings（WS_MAX_CONNECTIONS 等），
  不做任何功能裁剪——开源承诺不受影响。
- 配置 LICENSE_KEY = 企业授权模式：离线签名校验（HMAC-SHA256），licensee/有效期/规模上限生效；
  过期或篡改 → 降级回开源核心上限并告警（不宕机，监控不中断是第一原则）。

key 格式：`WS1.<base64url(payload_json)>.<base64url(hmac_sha256)>`
签发工具（企业版交付）：`python -m app.core.license issue --licensee 客户名 --days 365 --max-variables 20000`
（HMAC 密钥即 DATASOURCE_SECRET 同级的企业密钥 LICENSE_SIGNING_SECRET，只存在于签发方与产品侧配置。）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class LicenseInfo:
    licensee: str          # 授权对象（公司/个人名）
    expires_at: int        # epoch 秒；0 = 永久
    max_variables: int     # 变量规模上限（0 = 不限 → 取 settings 基线）
    max_connections: int   # WS 并发上限（0 = 不限 → 取 settings 基线）

    @property
    def expired(self) -> bool:
        return self.expires_at != 0 and self.expires_at < time.time()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload_b64: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest())


def issue_license(
    licensee: str, *, days: int = 365, max_variables: int = 0, max_connections: int = 0, secret: str | None = None
) -> str:
    """签发（仅企业交付工具使用；产品运行侧只需 verify）。days=0 表示永久。"""
    secret = secret or settings.LICENSE_SIGNING_SECRET
    if not secret:
        raise RuntimeError("LICENSE_SIGNING_SECRET 未配置，无法签发")
    payload = {
        "licensee": licensee,
        "expiresAt": int(time.time()) + days * 86400 if days > 0 else 0,
        "maxVariables": max_variables,
        "maxConnections": max_connections,
    }
    payload_b64 = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    return f"WS1.{payload_b64}.{_sign(payload_b64, secret)}"


def parse_license(key: str) -> LicenseInfo | None:
    """校验并解析；格式错/签名不符返回 None（调用方按未授权降级，不抛异常）。"""
    key = (key or "").strip()
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != "WS1":
        return None
    secret = settings.LICENSE_SIGNING_SECRET
    if not secret:
        return None
    expected = _sign(parts[1], secret)
    if not hmac.compare_digest(expected, parts[2]):
        return None
    try:
        payload = json.loads(_b64d(parts[1]))
        return LicenseInfo(
            licensee=str(payload["licensee"])[:128],
            expires_at=int(payload["expiresAt"]),
            max_variables=max(0, int(payload.get("maxVariables") or 0)),
            max_connections=max(0, int(payload.get("maxConnections") or 0)),
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


def effective_limits(info: LicenseInfo | None) -> tuple[int, int]:
    """生效规模上限：(max_connections, max_variables)。license 值为 0/缺席时回落 settings 基线。"""
    ws_cap = settings.WS_MAX_CONNECTIONS
    var_cap = settings.COLLECTOR_MAX_VARIABLES_PER_PROJECT
    if info is not None and not info.expired:
        if info.max_connections > 0:
            ws_cap = min(ws_cap, info.max_connections)
        if info.max_variables > 0:
            var_cap = min(var_cap, info.max_variables)
    return ws_cap, var_cap


def load_runtime_license() -> tuple[LicenseInfo | None, str]:
    """启动时加载：返回 (info, 状态描述)。状态 ∈ valid / expired / invalid / open-source。"""
    key = settings.LICENSE_KEY
    if not key:
        return None, "open-source"
    info = parse_license(key)
    if info is None:
        return None, "invalid"
    if info.expired:
        return info, "expired"
    return info, "valid"


if __name__ == "__main__":  # 签发 CLI（python -m app.core.license issue ...）
    import argparse

    ap = argparse.ArgumentParser(prog="license")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_issue = sub.add_parser("issue", help="签发 license key")
    p_issue.add_argument("--licensee", required=True)
    p_issue.add_argument("--days", type=int, default=365, help="有效天数，0=永久")
    p_issue.add_argument("--max-variables", type=int, default=0, help="变量上限，0=按产品基线")
    p_issue.add_argument("--max-connections", type=int, default=0, help="WS 并发上限，0=按产品基线")
    args = ap.parse_args()
    print(issue_license(
        args.licensee, days=args.days,
        max_variables=args.max_variables, max_connections=args.max_connections,
    ))
