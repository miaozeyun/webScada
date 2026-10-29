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

from loguru import logger
from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

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


async def clone_project(db: AsyncSession, source: Project, owner: User, name: str) -> Project:
    """按模板克隆新工程（阶段三）：新 id + 新名称 + 新 revision，doc 其余内容原样复制。

    - 数据源配置/凭证密文一并复制（同一 DATASOURCE_SECRET 可解，克隆后无需重填）
    - 缩略图不复制（新工程首次保存时重新生成）
    - 变量 key 不改名：新工程是独立命名空间，OEM「一模板 N 台设备」正是这个语义
    """
    doc = copy.deepcopy(source.doc if isinstance(source.doc, dict) else {})
    new_id = uuidlib.uuid4()
    now = _now_utc().isoformat().replace("+00:00", "Z")
    meta = doc.setdefault("project", {})
    meta["id"] = str(new_id)
    meta["name"] = name
    meta["author"] = owner.username
    meta["createdAt"] = now
    meta["updatedAt"] = now
    meta.pop("thumbnail", None)

    doc_service.check_schema_version(doc)
    doc_service.check_size(doc)
    model = doc_service.validate_structure(doc)
    doc_service.validate_references(model)
    _encrypt_doc_credentials(doc)

    project = Project(
        id=new_id,
        name=name,
        description=source.description,
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
    """列表不含 doc（03-接口清单 §2.3）：load_only 裁掉 doc JSONB 大列
    （≤2MB/工程，20 行最坏 ~40MB 反序列化全压列表首屏），缩略图走 list_thumbnails 路径投影。"""
    base = select(Project).options(
        load_only(
            Project.id, Project.name, Project.description, Project.revision,
            Project.pinned, Project.readonly, Project.owner_id, Project.updated_at,
        )
    )
    if keyword:
        base = base.where(Project.name.ilike(f"%{keyword}%"))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    # 置顶恒在最前：pinned DESC, updated_at DESC（分页在全局排序后切，置顶工程不会因翻页丢失）
    items = (
        await db.scalars(
            base.order_by(Project.pinned.desc(), Project.updated_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()
    return int(total), list(items)


async def set_pinned(db: AsyncSession, project_id: str, pinned: bool) -> Project:
    """台账置顶开关：只改 pinned，不触碰 doc/revision/updated_at。

    - 不参与 revision 乐观锁：置顶不会把他人保存顶成 409；
    - 显式把 updated_at 设为原值：Project.updated_at 配了 onupdate=now()，普通 ORM 赋值
      会把「置顶」误当成内容更新，取消置顶后工程会错误地排到未置顶列表首位。
    """
    project = await get_project(db, project_id)
    if project.pinned != pinned:
        await db.execute(
            update(Project)
            .where(Project.id == project.id)
            .values(pinned=pinned, updated_at=Project.updated_at)
        )
        await db.commit()
        await db.refresh(project)
    return project


async def list_thumbnails(db: AsyncSession, ids: list[uuidlib.UUID]) -> dict[uuidlib.UUID, str | None]:
    """首页缩略图（卡片视图）：只投影 doc.project.thumbnail 一个标量，不反序列化整个 doc。
    按方言分派（JSONVariant 同款做法）：PG 走 jsonb 路径 astext，SQLite 单测走 json_extract。"""
    if not ids:
        return {}
    if db.get_bind().dialect.name == "postgresql":
        # 列声明是 JSON().with_variant(JSONB())：variant 只在 DDL/编译期切换，
        # 表达式层 [] 仍按基类型 JSON 解析（无 .astext）——须显式 cast 成 JSONB 再取路径
        expr = cast(Project.doc, PG_JSONB)["project"]["thumbnail"].astext
    else:
        expr = func.json_extract(Project.doc, "$.project.thumbnail")
    rows = (await db.execute(select(Project.id, expr).where(Project.id.in_(ids)))).all()
    return {pid: (thumb if isinstance(thumb, str) and thumb else None) for pid, thumb in rows}


async def update_doc(db: AsyncSession, project: Project, doc_raw: dict, base_revision: int) -> Project:
    """整体保存：校验流水线 + 乐观锁 + 凭证治理，revision+1。doc_raw 会被就地修改。"""
    # 演示只读（2026-10-29）：服务层再兜一道，防止绕过 API 层的调用点写入演示工程
    if project.readonly:
        raise AppError("PROJECT_READONLY", "演示工程只读：修改不会保存，请先复制工程再编辑", 403)
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
    # 运行态热更新（M8 工作包 A 钩子）：hub.set_doc + collector.sync 差量重建，值流不中断（03 §3.8）
    await _runtime_hot_reload(project.id, project.doc)
    # 规则变更收口：删除/停用的规则不得留下永不恢复的活动报警（sys_comm 系统报警除外）。
    # 失败只记日志，不回滚已保存的 doc（保存成功优先）。
    try:
        from app.services import alarm_service  # 惰性：避免模块级交叉依赖

        cleared = await alarm_service.reconcile_rules(db, project.id, project.doc)
        if cleared:
            logger.info("保存后规则收口：project={} 清除 {} 条残留报警", project.id, len(cleared))
    except Exception as exc:  # noqa: BLE001 — 收口失败不影响保存结果
        logger.warning("保存后规则收口失败（project={}）：{}", project.id, exc)
    return project


async def import_project(db: AsyncSession, owner: User, doc_raw: dict, readonly: bool = False) -> Project:
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
        readonly=readonly,
        owner_id=owner.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # 导入即上线（M8 钩子）：新工程直接装配采集与值池
    await _runtime_hot_reload(project.id, project.doc)
    return project


async def delete_project(db: AsyncSession, project: Project) -> None:
    """删除：share_links / alarm_records 由外键 ON DELETE CASCADE 级联；
    运行态级联热清理（M8 钩子）：hub.remove + collector.remove + 在线连接 error(PROJECT_REMOVED)。"""
    await db.delete(project)
    await db.commit()
    try:  # 跨包惰性 import（契约 §6.4）：运行态层缺席时不影响删除主流程
        from app.services import collector, hub, notify, ws_manager

        hub.hub.remove(project.id)
        await collector.collector.remove(project.id)
        await ws_manager.manager.broadcast_project_removed(project.id)
        notify.invalidate_project_channels(project.id)  # 删除即失效通知渠道缓存
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"工程删除运行态清理失败 project={project.id}：{type(exc).__name__} {exc}")


async def _runtime_hot_reload(project_id: uuidlib.UUID, doc: dict) -> None:
    """保存/导入成功后的运行态热更新钩子：hub 重建索引（保留存续变量现值）+ collector 差量重建
    + 通知渠道缓存失效（阶段二 Task 4：保存后新渠道即时生效，不等 TTL）。
    失败仅告警不回滚（保存已提交，运行态可在下次保存/重启恢复）。"""
    try:  # 跨包惰性 import（契约 §6.4）
        from app.services import collector, hub, notify

        hub.hub.set_doc(project_id, doc)
        await collector.collector.sync(project_id, doc)
        notify.invalidate_project_channels(project_id)
        logger.info(f"运行态热更新完成 project={project_id} 数据源任务={len(collector.collector._projects.get(project_id, {}))}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"运行态热更新失败 project={project_id}：{type(exc).__name__} {exc}")


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
    # settings.notify.channels[] 钉钉 secret（工厂可用阶段二 Task 4）
    for ch in sz.iter_notify_channels(doc):
        if ch.get("kind") != "dingtalk":
            continue
        value = ch.get("secret")
        if isinstance(value, str) and value and not looks_encrypted(value):
            ch["secret"] = encrypt(value)
