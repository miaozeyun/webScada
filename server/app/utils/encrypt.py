"""数据源凭证 Fernet 加密（G6）。

存储约定：doc 中已加密的敏感字段带 "FER1:" 前缀（密文 base64）；
- encrypt 跳过已带前缀的值（凭证合并会把库内密文原样透传，防二次加密）
- decrypt 校验前缀并解密
- 所有对外出口（GET/导出/分享快照）统一脱敏为空串，密文永不出库
"""
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "FER1:"

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.DATASOURCE_SECRET:
            raise RuntimeError("DATASOURCE_SECRET 未配置（生成方式见 .env.example）")
        try:
            _fernet = Fernet(settings.DATASOURCE_SECRET.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"DATASOURCE_SECRET 不是合法的 Fernet 密钥: {exc}") from exc
    return _fernet


def ensure_key() -> None:
    """启动自检：密钥必须已配置且合法（fail fast，容器启动期暴露配置错误）。"""
    _get_fernet()


def encrypt(plain: str) -> str:
    return _PREFIX + _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(stored: str) -> str:
    if not stored.startswith(_PREFIX):
        raise ValueError("凭证字段不是合法的密文（缺少 FER1: 前缀）")
    try:
        return _get_fernet().decrypt(stored[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("凭证解密失败（DATASOURCE_SECRET 已变更？需在各数据源面板重填）") from exc


def looks_encrypted(value: str) -> bool:
    """判断值是否为可解密的密文。

    不只看前缀：若用户真实明文凭证恰好以 "FER1:" 开头，仅凭前缀会误判为密文而跳过加密，
    导致明文落库且采集器永远解不开（复查 minor 修复）。此处尝试真实解密判定。
    """
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return False
    try:
        _get_fernet().decrypt(value[len(_PREFIX):].encode("ascii"))
        return True
    except Exception:  # noqa: BLE001 - 解不开即视为明文
        return False
