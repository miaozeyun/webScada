"""图片上传（编辑器图片/轮播组件直传，M9 后续增量）。

契约：
- POST /api/v1/uploads（multipart file，operator/admin）→ {url, name, size}
- GET  /api/v1/uploads/{name} 匿名可读（分享页 /s/{token} 匿名加载同一图片）

设计取舍：
- 文件落盘（UPLOAD_DIR，compose 命名卷持久化），不入 doc JSONB——图片体积会突破 2MB doc 上限
- 文件名 uuid hex + 扩展名，不可猜测；仅接受四类位图，SVG 一律拒绝（可含脚本，防直开 XSS）
- 内容按魔数校验，不信任客户端 Content-Type；GET 加 nosniff
- 返回相对 URL（/api/v1/uploads/…）：vite 代理与 nginx 反向代理同口径，前后端无需区分部署形态
"""
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_operator
from app.core.config import settings
from app.core.errors import AppError
from app.db.models import User

router = APIRouter(prefix="/uploads", tags=["uploads"])

# 白名单：扩展名 ← 魔数前缀（校验内容真实类型，拒绝伪装 Content-Type）
_MAGIC: list[tuple[str, bytes]] = [
    (".png", b"\x89PNG\r\n\x1a\n"),
    (".jpg", b"\xff\xd8\xff"),
    (".gif", b"GIF87a"),
    (".gif", b"GIF89a"),
]
_WEBP_RIFF = b"RIFF"
_WEBP_TAG = b"WEBP"

_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")


class UploadOut(BaseModel):
    url: str
    name: str
    size: int


def _detect_ext(data: bytes) -> str | None:
    for ext, magic in _MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == _WEBP_RIFF and data[8:12] == _WEBP_TAG:
        return ".webp"
    return None


def _upload_root() -> Path:
    return Path(settings.UPLOAD_DIR)


@router.post("", response_model=UploadOut)
async def upload_image(
    file: UploadFile = File(...),
    _user: User = Depends(require_operator),
) -> UploadOut:
    """上传图片：≤ UPLOAD_MAX_BYTES，仅 png/jpg/gif/webp。"""
    limit = settings.UPLOAD_MAX_BYTES
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError("file_too_large", f"图片超过上限（{limit // (1024 * 1024)}MB）", 413)
    if not data:
        raise AppError("invalid_file", "图片内容为空", 422)
    ext = _detect_ext(data)
    if ext is None:
        raise AppError("invalid_file", "仅支持 PNG / JPG / GIF / WEBP 图片", 422)

    name = f"{uuid.uuid4().hex}{ext}"
    root = _upload_root()
    await run_in_threadpool(root.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool((root / name).write_bytes, data)
    return UploadOut(url=f"/api/v1/uploads/{name}", name=name, size=len(data))


@router.get("/{name}")
async def get_upload(name: str) -> FileResponse:
    """读取上传图片（匿名可读：分享页不携带登录态）。"""
    if not _NAME_RE.match(name):
        raise AppError("NOT_FOUND", "图片不存在", 404)
    path = _upload_root() / name
    if not path.is_file():
        raise AppError("NOT_FOUND", "图片不存在", 404)
    # 文件名内容寻址（uuid），可长缓存
    return FileResponse(
        path,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
