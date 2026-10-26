"""工程管理接口（03-接口清单 §2.3/§2.4/§2.5 不变式；M8 角色收敛与审计见契约 §4.7）。

M8 RBAC（§4.7 团队协作口径）：
- PUT /projects/{id}、POST /projects/import：operator/admin（owner 校验仅 DELETE 收紧）
- DELETE /projects/{id}：admin 或 owner（operator 非 owner 403；viewer 恒 403）
- 写路径落审计 project_save（create/save/import），audit_service 自建短会话
"""
import json
import time
import uuid as uuidlib

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_operator,
    require_project_edit,
    require_project_view,
)
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import Project, User
from app.schemas.project import (
    ImportBody,
    ProjectClone,
    ProjectCreate,
    ProjectListItem,
    ProjectListOut,
    ProjectOut,
    ProjectSaveOut,
    ProjectUpdate,
)
from app.services import audit_service, project_service

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
                id=str(p.id), name=p.name, description=p.description, revision=p.revision, updatedAt=p.updated_at,
                # 首页缩略图（卡片视图）：编辑器保存前写入 doc.project.thumbnail，此处直接读出
                thumbnail=(p.doc or {}).get("project", {}).get("thumbnail") if isinstance(p.doc, dict) else None,
            )
            for p in items
        ],
    )


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    # 创建不携带 doc（G7）：服务端生成空白模板；viewer 只读不可创建（03 §1.2 角色口径）
    project = await project_service.create_project(db, user, body.name, body.description)
    await audit_service.audit(
        request, user, "project_save", target_type="project", target_id=str(project.id),
        detail={"op": "create", "name": project.name},
    )
    return _to_out(project, with_doc=False)


@router.post("/{project_id}/clone", response_model=ProjectOut, status_code=201)
async def clone_project(
    project_id: str,
    body: ProjectClone,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """按模板克隆工程（阶段三）：新工程 id/名称，doc（含凭证密文）原样复制。

    OEM「一套模板 → N 台设备」的最小闭环：第 2 台起不再重做画面/绑定/报警。
    """
    require_project_view(user, project_id)
    source = await project_service.get_project(db, project_id)
    project = await project_service.clone_project(db, source, user, body.name)
    await audit_service.audit(
        request, user, "project_save", target_type="project", target_id=str(project.id),
        detail={"op": "clone", "sourceId": str(source.id), "name": project.name},
    )
    return _to_out(project, with_doc=False)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    require_project_view(user, project_id)  # 任意角色可读（显式闸门，预留行级扩展）
    project = await project_service.get_project(db, project_id)
    return _to_out(project, with_doc=True)


@router.get("/{project_id}/variables/values")
async def get_variable_values(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑器调试值快照（03 §3.13 P0）：与运行态 WS snapshot 帧的 data 同构。

    服务端闭环前的工程（hub 未加载）返回空 values——编辑器自行回落浏览器直连模式。
    """
    require_project_view(user, project_id)
    await project_service.get_project(db, project_id)  # 404 校验
    try:  # 惰性 import：hub 缺席（测试 mini app）时降级空快照
        from app.services import hub as hub_mod

        values = hub_mod.hub.pool(uuidlib.UUID(project_id))
    except Exception:  # noqa: BLE001
        values = {}
    return {"ts": int(time.time() * 1000), "values": values}


@router.put("/{project_id}", response_model=ProjectSaveOut)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectSaveOut:
    require_project_edit(user, project_id)  # viewer 403；operator/admin 可编辑任意工程（§4.7）
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
    await audit_service.audit(
        request, user, "project_save", target_type="project", target_id=str(project.id),
        detail={"op": "save", "name": project.name, "revision": project.revision},
    )
    return ProjectSaveOut(revision=project.revision, updatedAt=project.updated_at, warnings=warnings)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await project_service.get_project(db, project_id)
    # M8 收紧（§4.7）：admin 恒可删；operator 仅 owner；viewer 恒 403（只读口径）。
    # 删除不落审计：action 七类枚举无 project_delete（契约 §6.3 冻结），留痕缺口已记入偏差说明
    if user.role == "viewer" or (user.role != "admin" and project.owner_id != user.id):
        raise AppError("FORBIDDEN", "仅管理员或工程属主可删除该工程", 403)
    await project_service.delete_project(db, project)
    return Response(status_code=204)


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """导出（G7）：JSON body，前端 Blob 触发下载；凭证已脱敏（G6）。"""
    require_project_view(user, project_id)
    project = await project_service.get_project(db, project_id)
    doc = project_service.export_doc(project)
    # 响应头不使用非 ASCII 文件名（latin-1 编码限制），命名由前端负责
    return JSONResponse(content=doc, headers={"Content-Disposition": 'attachment; filename="project.json"'})


@router.post("/import", response_model=ProjectOut, status_code=201)
async def import_project(
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    """导入（G7）：支持 multipart 文件上传或 JSON body {"doc": {...}} 两种形态；operator/admin（§4.7）。"""
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

    project = await project_service.import_project(db, user, doc_raw)
    await audit_service.audit(
        request, user, "project_save", target_type="project", target_id=str(project.id),
        detail={"op": "import", "name": project.name},
    )
    return _to_out(project, with_doc=False)
