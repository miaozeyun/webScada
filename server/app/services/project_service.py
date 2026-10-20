"""工程服务：CRUD、乐观锁保存、导入导出流水线。

PUT 流水线（03-接口清单 §2.3）：schemaVersion → 体积 → 凭证空值保留合并（02 §4.3 规则⑤，
先于结构校验以保留"缺省/null"语义）→ 结构 → 引用 → project.id 一致性 → 409 乐观锁 →
凭证加密 → 覆盖 doc / revision+1。
导入流水线（§2.4）：schemaVersion → 体积 → 凭证一律置空（规则③）→ 结构 → 引用 →
重写 project.id（G9）→ 新建工程 revision=1（不覆盖已有工程）。
"""
import copy
import uuid as uuidlib
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Project, User
from app.services import doc_service
from app.utils import sanitize as sz
from app.utils.encrypt import encrypt, looks_encrypted


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def get_project(db: AsyncSession, project_id: str) -> Project:
    try:
        pid = uuidlib.UUID(project_id)
    except ValueError:
        raise AppError("NOT_FOUND", "工程不存在", 404) from None
    project = await db.get(Project, pid)
    if project is None:
        raise AppError("NOT_FOUND", "工程不存在", 404)
    return project


async def create_project(db: AsyncSession, owner: User, name: str, description: str | None) -> Project:
    pid = uuidlib.uuid4()
    doc = doc_service.blank_doc(str(pid), name, author=owner.username)
    project = Project(
        id=pid,
        name=name,
        description=description,
        doc=doc,
        revision=1,
        owner_id=owner.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(
    db: AsyncSession, keyword: str | None, page: int, size: int
) -> tuple[int, list[Project]]:
    """列表不含 doc（03-接口清单 §2.3）。"""
    base = select(Project)
    if keyword:
        base = base.where(Project.name.ilike(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = (
        await db.scalars(
            base.order_by(Project.updated_at.desc()).offset((page - 1) * size).limit(size)
        )
    ).all()
    return int(total), list(items)


async def update_doc(db: AsyncSession, project: Project, doc_raw: dict, base_revision: int) -> Project:
    """整体保存：校验流水线 + 乐观锁 + 凭证治理，revision+1。doc_raw 会被就地修改。"""
    doc_service.check_schema_version(doc_raw)
    doc_service.check_size(doc_raw)

    # 凭证空值保留合并（先于结构校验：Pydantic 会丢失"缺省 vs null"的区分）
    # 库内旧 doc 的敏感字段为 FER1: 密文，缺省/空串时原样透传
    stored_raw = project.doc if isinstance(project.doc, dict) else {}
    sz.merge_sensitive_fields(doc_raw, stored_raw)

    model = doc_service.validate_structure(doc_raw)
    doc_service.validate_references(model)

    # project.id 与库内一致（02 §2.13 规则 4：保存时必须一致，导入时重写）
    if doc_raw.get("project", {}).get("id") != str(project.id):
        raise AppError(
            "project_id_mismatch",
            "doc.project.id 与当前工程不一致",
            422,
        )

    # 乐观锁（G2）：先做友好预检，最终以下方原子 UPDATE 的 revision 条件为准
    # （复查 major 修复：预检与 commit 之间存在 await 切换点，并发 PUT 会 TOCTOU 丢失更新）
    if base_revision != project.revision:
        raise AppError(
            "REVISION_CONFLICT",
            "文档已被他人修改，请刷新后重试",
            409,
            currentRevision=project.revision,
        )

    # 非空明文凭证 → Fernet 密文（可解密的密文透传跳过，见 encrypt.looks_encrypted）
    _encrypt_doc_credentials(doc_raw)

    # 原子更新：WHERE revision = baseRevision，rowcount=0 即并发冲突（SQL 层杜绝丢失更新）
    stmt = (
        update(Project)
        .where(Project.id == project.id, Project.revision == base_revision)
        .values(
            doc=doc_raw,
            revision=base_revision + 1,
            # doc 是唯一事实来源：工程名列随 doc.project.name 同步（列表不含 doc，避免显示旧名）
            name=model.project.name,
            description=model.project.description,
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        current = await db.scalar(select(Project.revision).where(Project.id == project.id))
        raise AppError(
            "REVISION_CONFLICT",
            "文档已被他人修改，请刷新后重试",
            409,
            currentRevision=current or project.revision,
        )
    await db.commit()
    await db.refresh(project)
    return project


async def import_project(db: AsyncSession, owner: User, doc_raw: dict) -> Project:
    """导入总是新建工程（不覆盖、不去重）；凭证一律置空需重填（02 §4.3 规则③）。
    顺序遵循 02 §5.2：schemaVersion → 体积 → 结构 → 引用 → 凭证置空 → 重写 id → 入库
    （先校验后置空：非法凭证类型不会被置空洗白，而是按结构校验报 422 带字段路径）。"""
    doc_service.check_schema_version(doc_raw)
    doc_service.check_size(doc_raw)
    model = doc_service.validate_structure(doc_raw)
    doc_service.validate_references(model)
    sz.clear_credentials_for_import(doc_raw)

    # 重写为新库 id 并重置时间戳（G9：DB 主键由服务端生成；doc 内部 id 保留）
    new_id = uuidlib.uuid4()
    now = doc_service._now_iso()
    doc_raw["project"]["id"] = str(new_id)
    doc_raw["project"]["createdAt"] = now
    doc_raw["project"]["updatedAt"] = now

    project = Project(
        id=new_id,
        name=model.project.name,
        description=model.project.description,
        doc=doc_raw,
        revision=1,
        owner_id=owner.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project: Project) -> None:
    """删除：share_links / alarm_records 由外键 ON DELETE CASCADE 级联（M0 无在线连接；
    M4+ 运行态级联热清理在此挂接）。"""
    await db.delete(project)
    await db.commit()


def export_doc(project: Project) -> dict:
    """导出 = 脱敏后 doc（G7：JSON body，前端 Blob 下载命名）。"""
    return sz.sanitize_doc_for_output(project.doc)


def doc_for_api(project: Project) -> dict:
    """GET 工程详情返回脱敏 doc（G6：所有出口脱敏）。"""
    return sz.sanitize_doc_for_output(project.doc)


def _encrypt_doc_credentials(doc: dict) -> None:
    """就地加密全部非空明文敏感字段（保存前最后一步；可解密的密文透传跳过）。"""
    for ds, config in sz.iter_datasource_configs(doc):
        for container, key in sz._iter_sensitive_fields(ds, config):
            value = container.get(key)
            if isinstance(value, str) and value and not looks_encrypted(value):
                container[key] = encrypt(value)
