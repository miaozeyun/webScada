"""工程管理接口（03-接口清单 §2.3/§2.4/§2.5 不变式 + §2.8/§2.9 属后续阶段）。"""
import json

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import Project, User
from app.schemas.project import (
    ImportBody,
    ProjectCreate,
    ProjectListItem,
    ProjectListOut,
    ProjectOut,
    ProjectSaveOut,
    ProjectUpdate,
)
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(project: Project, *, with_doc: bool) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        name=project.name,
        description=project.description,
        revision=project.revision,
        createdAt=project.created_at,
        updatedAt=project.updated_at,
        # 所有出口脱敏（G6）
        doc=project_service.doc_for_api(project) if with_doc else None,
    )


@router.get("", response_model=ProjectListOut)
async def list_projects(
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectListOut:
    total, items = await project_service.list_projects(db, keyword, page, size)
    return ProjectListOut(
        total=total,
        page=page,
        size=size,
        items=[
            ProjectListItem(
                id=str(p.id), name=p.name, description=p.description, revision=p.revision, updatedAt=p.updated_at
            )
            for p in items
        ],
    )


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    # 创建不携带 doc（G7）：服务端生成空白模板
    project = await project_service.create_project(db, user, body.name, body.description)
    return _to_out(project, with_doc=False)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await project_service.get_project(db, project_id)
    return _to_out(project, with_doc=True)


@router.put("/{project_id}", response_model=ProjectSaveOut)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectSaveOut:
    from app.services import doc_service

    project = await project_service.get_project(db, project_id)
    warnings: list[str] = []
    try:
        # 先做一次结构校验收集告警（update_doc 内会再走完整流水线）
        model = doc_service.validate_structure(body.doc)
        warnings = doc_service.collect_warnings(model)
    except AppError:
        warnings = []  # 校验失败路径不需要告警
    project = await project_service.update_doc(db, project, body.doc, body.baseRevision)
    return ProjectSaveOut(revision=project.revision, updatedAt=project.updated_at, warnings=warnings)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await project_service.get_project(db, project_id)
    await project_service.delete_project(db, project)
    return Response(status_code=204)


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """导出（G7）：JSON body，前端 Blob 触发下载；凭证已脱敏（G6）。"""
    project = await project_service.get_project(db, project_id)
    doc = project_service.export_doc(project)
    # 响应头不使用非 ASCII 文件名（latin-1 编码限制），命名由前端负责
    return JSONResponse(content=doc, headers={"Content-Disposition": 'attachment; filename="project.json"'})


@router.post("/import", response_model=ProjectOut, status_code=201)
async def import_project(
    request: Request,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """导入（G7）：支持 multipart 文件上传或 JSON body {"doc": {...}} 两种形态。"""
    content_type = request.headers.get("content-type", "")

    doc_raw: dict | None = None
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise AppError("validation_error", "multipart 导入需携带 file 字段", 422)
        try:
            doc_raw = json.loads((await upload.read()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError("invalid_json", "导入文件不是合法的 UTF-8 JSON", 422) from None
    else:
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 与 multipart 路径同错误码（复查 minor 修复：不设双口径）
            raise AppError("invalid_json", "导入文件不是合法的 UTF-8 JSON", 422) from None
        try:
            payload = ImportBody.model_validate(raw)
        except Exception:
            raise AppError("validation_error", "JSON body 需为 {\"doc\": {...}}", 422) from None
        doc_raw = payload.doc

    if not isinstance(doc_raw, dict):
        raise AppError("validation_error", "doc 必须为 JSON 对象", 422)

    project = await project_service.import_project(db, _user, doc_raw)
    return _to_out(project, with_doc=False)
