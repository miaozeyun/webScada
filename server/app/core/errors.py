"""统一错误信封（G20）：
- 所有错误响应体形如 {"code": "...", "message": "...", ...附加字段}
- 校验失败一律 422，附 errors: [{path, message}]（字段路径如 pages[0].components[2].bindings[0].variableId）
- 不设 400/422 双口径
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 常用 HTTP 状态码 → 业务错误码映射（可被 AppError 显式覆盖）
_HTTP_CODE_MAP = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
}


class AppError(Exception):
    """业务错误：抛出后由全局处理器转为统一信封。"""

    def __init__(self, code: str, message: str, status_code: int = 400, **extra):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra
        super().__init__(message)


def _loc_to_path(loc: tuple) -> str:
    """把 Pydantic 的 loc 元组转为契约规定的字段路径格式：pages[0].components[2].xxx。"""
    parts = []
    for item in loc:
        parts.append(f"[{item}]" if isinstance(item, int) else (f".{item}" if parts else str(item)))
    return "".join(parts)


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        body = {"code": exc.code, "message": exc.message, **exc.extra}
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"path": _loc_to_path(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"code": "validation_error", "message": "参数校验失败", "errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code, "HTTP_ERROR")
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(status_code=exc.status_code, content={"code": code, "message": detail})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # 兜底：未预期异常不向外泄漏堆栈细节
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "服务内部错误"})
