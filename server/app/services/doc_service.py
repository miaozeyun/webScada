"""doc 校验流水线与模板：schemaVersion → 体积 → 结构（Pydantic）→ 引用完整性。

顺序与错误体遵循 03-接口清单 §2.3/§2.4 与 02 §2.13/§4.3：
- 校验失败统一 422，错误体 {code, message, errors: [{path, message}]}（G20）
- schemaVersion 接受兼容窗口 v ∈ [CURRENT-SCHEMA_COMPAT_WINDOW, CURRENT]
  （M8 契约 §7.2；G8：版本迁移唯一实现点在前端 migrateDoc()，服务端窗口仅灰度缓冲，
  入库前仍按 CURRENT 结构校验——N-1 与 CURRENT 结构兼容「只增不改」是提版前置条件）
"""
import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core.config import settings
from app.core.errors import AppError, _loc_to_path
from app.schemas.doc import ComponentNode, ProjectDoc

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def serialized_size(doc: dict) -> int:
    return len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def check_schema_version(doc_raw: dict) -> None:
    """schemaVersion 兼容窗口校验（M8 契约 §7.2，文案区分过低/过高）。

    - 接受 v ∈ [CURRENT - SCHEMA_COMPAT_WINDOW, CURRENT]；
    - v < 下限：422，文案指引前端 migrateDoc 导入入口（过低）；
    - v > CURRENT：422，文案提示升级服务端（过高，禁止静默降级）；
    - 缺失/非整数（含 bool——bool 是 int 子类，True==1 不得冒充 CURRENT）→ 422。
    """
    v = doc_raw.get("schemaVersion")
    current = settings.CURRENT_SCHEMA_VERSION
    if isinstance(v, bool) or not isinstance(v, int):
        raise AppError(
            "version_unsupported",
            "schemaVersion 缺失或非法（应为整数）；"
            f"旧版本文件请经前端编辑器导入入口，由 migrateDoc() 升级后再提交（当前支持 {current}）",
            422,
        )
    if v > current:
        raise AppError(
            "version_unsupported",
            f"schemaVersion {v} 高于服务端当前支持的 {current}，请升级服务端版本后重试（禁止静默降级）",
            422,
        )
    floor = current - max(settings.SCHEMA_COMPAT_WINDOW, 0)  # 防御负窗口把下限抬到 CURRENT 之上
    if v < floor:
        raise AppError(
            "version_unsupported",
            f"schemaVersion {v} 低于兼容窗口下限 {floor}（当前支持 {current}）；"
            "请经前端编辑器导入入口，由 migrateDoc() 升级后再提交",
            422,
        )


def check_size(doc_raw: dict) -> None:
    if serialized_size(doc_raw) > settings.DOC_MAX_BYTES:
        raise AppError(
            "doc_too_large",
            f"doc 体积超过 {settings.DOC_MAX_BYTES // (1024 * 1024)}MB 上限（G21）",
            422,
        )


def validate_structure(doc_raw: dict) -> ProjectDoc:
    """Pydantic v2 全量结构校验，失败转 G20 错误体。"""
    try:
        return ProjectDoc.model_validate(doc_raw)
    except ValidationError as exc:
        errors = [{"path": _loc_to_path(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise AppError("doc_invalid", "工程 doc 结构校验失败", 422, errors=errors) from exc


def validate_references(model: ProjectDoc) -> None:
    """跨对象引用完整性（02 §2.13 规则 1~5），单次递归遍历组件树。失败 422 + errors 字段路径。"""
    errors: list[dict] = []

    def uniq(label: str, pairs: list[tuple[str, str]]) -> None:
        """pairs: (值, 完整字段路径)；重复时报后出现的位置。"""
        seen: dict[str, str] = {}
        for value, path in pairs:
            if value in seen:
                errors.append({
                    "path": path,
                    "message": f"{label}重复：{value}（首次出现于 {seen[value]}）",
                })
            else:
                seen[value] = path

    var_ids = {v.id for v in model.variables}
    var_type_by_id = {v.id: v.type for v in model.variables}
    ds_ids = {d.id for d in model.datasources}

    # ---- 规则 1：唯一性 ----
    uniq("variables[].id", [(v.id, f"variables[{i}].id") for i, v in enumerate(model.variables)])
    uniq("variables[].key", [(v.key, f"variables[{i}].key") for i, v in enumerate(model.variables)])
    uniq("pages[].id", [(p.id, f"pages[{i}].id") for i, p in enumerate(model.pages)])
    uniq("datasources[].id", [(d.id, f"datasources[{i}].id") for i, d in enumerate(model.datasources)])
    uniq("alarmRules[].id", [(r.id, f"alarmRules[{i}].id") for i, r in enumerate(model.alarmRules)])

    # 组件 id 全工程唯一（含组内递归）；绑定引用/同 prop 唯一在同一遍历中完成
    comp_pairs: list[tuple[str, str]] = []
    binding_pairs: list[tuple[str, str]] = []

    # M7：事件动作引用校验需要全量组件/页面 id，先行收集
    comp_ids: set[str] = set()

    def _collect_ids(nodes: list[ComponentNode]) -> None:
        for n in nodes:
            comp_ids.add(n.id)
            if n.children:
                _collect_ids(n.children)

    page_ids = {p.id for p in model.pages}
    for page in model.pages:
        _collect_ids(page.components)

    def walk(nodes: list[ComponentNode], prefix: str) -> None:
        for ci, node in enumerate(nodes):
            p = f"{prefix}[{ci}]"
            comp_pairs.append((node.id, f"{p}.id"))
            seen_props: dict[str, int] = {}
            for bi, b in enumerate(node.bindings):
                bp = f"{p}.bindings[{bi}]"
                binding_pairs.append((b.id, f"{bp}.id"))
                # 规则 2：绑定引用存在性
                if b.variableId not in var_ids:
                    errors.append({"path": f"{bp}.variableId", "message": f"变量 {b.variableId} 不存在"})
                # 规则 3：同一组件同一 prop 仅一条绑定
                if b.prop in seen_props:
                    errors.append({
                        "path": f"{bp}.prop",
                        "message": f"同一组件同一 prop 仅允许一条绑定（与 bindings[{seen_props[b.prop]}] 重复：{b.prop}）",
                    })
                else:
                    seen_props[b.prop] = bi
            # M7：事件动作引用存在性（writeVar 变量 / 弹框与切页目标）
            for ei, ev in enumerate(node.events or []):
                ep = f"{p}.events[{ei}]"
                for ai, act in enumerate(ev.actions):
                    ap = f"{ep}.actions[{ai}]"
                    if act.type == "writeVar":
                        if not act.variableId or act.variableId not in var_ids:
                            errors.append({"path": f"{ap}.variableId", "message": f"writeVar 变量 {act.variableId} 不存在"})
                        else:
                            target = next(v for v in model.variables if v.id == act.variableId)
                            if not target.writable:
                                errors.append({"path": f"{ap}.variableId", "message": f"writeVar 目标变量 {target.key} 未开启 writable"})
                    elif act.type in ("showPopup", "hidePopup", "toggleVisible"):
                        if not act.targetId or act.targetId not in comp_ids:
                            errors.append({"path": f"{ap}.targetId", "message": f"目标组件 {act.targetId} 不存在"})
                    elif act.type == "switchPage":
                        if not act.pageId or act.pageId not in page_ids:
                            errors.append({"path": f"{ap}.pageId", "message": f"目标页面 {act.pageId} 不存在"})
                    elif act.type == "openUrl":
                        if not act.url:
                            errors.append({"path": f"{ap}.url", "message": "openUrl 缺少 url"})
            if node.children:
                walk(node.children, f"{p}.children")

    for pi, page in enumerate(model.pages):
        walk(page.components, f"pages[{pi}].components")
    uniq("组件 id", comp_pairs)
    uniq("绑定 id", binding_pairs)

    # ---- 规则 2：变量 → 数据源引用存在性（M7：虚拟变量哨兵豁免） ----
    for i, v in enumerate(model.variables):
        if v.expr is not None and v.datasourceId == "virtual":
            continue
        if v.datasourceId not in ds_ids:
            errors.append({"path": f"variables[{i}].datasourceId", "message": f"数据源 {v.datasourceId} 不存在"})

    # ---- 规则 2/5：报警规则引用与变量类型约束（02 §2.11）----
    for i, rule in enumerate(model.alarmRules):
        if rule.variableId not in var_ids:
            errors.append({"path": f"alarmRules[{i}].variableId", "message": f"变量 {rule.variableId} 不存在"})
            continue
        vtype = var_type_by_id[rule.variableId]
        if vtype == "string":
            errors.append({"path": f"alarmRules[{i}].variableId", "message": "string 类型变量不允许配置报警规则"})
        elif vtype == "boolean" and rule.op not in ("==", "!="):
            errors.append({
                "path": f"alarmRules[{i}].op",
                "message": "boolean 变量仅允许 == / !=（threshold 用 1/0 表示 true/false）",
            })

    # ---- 规则 4：project.id 必须为 UUID 格式（与库内一致性在 project_service 检查）----
    if not UUID_RE.match(model.project.id or ""):
        errors.append({"path": "project.id", "message": "project.id 必须为 UUID 格式"})

    if errors:
        raise AppError("reference_error", "工程 doc 引用完整性校验失败", 422, errors=errors)


def validate_full(doc_raw: dict) -> ProjectDoc:
    """完整流水线（不含凭证处理；凭证合并/置空/加密在 project_service 按场景执行）。"""
    check_schema_version(doc_raw)
    check_size(doc_raw)
    model = validate_structure(doc_raw)
    validate_references(model)
    return model


def collect_warnings(model: ProjectDoc) -> list[str]:
    """非阻断告警（02 §2.13 规则 7）：单页组件 > 200（软上限，仅提示）。"""

    def count(nodes: list) -> int:
        return sum(1 + count(n.children or []) for n in nodes)

    warns: list[str] = []
    for i, page in enumerate(model.pages):
        c = count(page.components)
        if c > 200:
            warns.append(f"pages[{i}]（{page.name}）组件数 {c} 超过建议上限 200，可能影响运行态性能")
    return warns


def blank_doc(project_id: str, name: str, author: str | None = None) -> dict:
    """新建工程默认模板：蓝色主题 + 1 个 1920x1080 页面（03-接口清单 §2.3 POST 行为）。
    页面预置一套克制的欢迎画面（标题栏带工程名 + 引导文案 + 信号色装饰线），
    让新工程打开即有画面可看；组件均可选中删除，不构成使用负担。"""
    now = _now_iso()
    welcome_components = [
        {
            "id": "node_welcome_title",
            "name": "标题栏",
            "type": "title-bar",
            "x": 560.0, "y": 24.0, "w": 800.0, "h": 64.0,
            "z": 0,
            "props": {"text": name, "align": "center"},
        },
        {
            "id": "node_welcome_lead",
            "name": "欢迎语",
            "type": "text",
            "x": 460.0, "y": 424.0, "w": 1000.0, "h": 64.0,
            "z": 1,
            "props": {"text": "开始搭建监控画面", "ellipsis": True},
            "style": {"fontSize": 40, "fontWeight": 600, "color": "#e8eef6", "textAlign": "center"},
        },
        {
            "id": "node_welcome_guide0",
            "name": "副标题",
            "type": "text",
            "x": 460.0, "y": 500.0, "w": 1000.0, "h": 32.0,
            "z": 2,
            "props": {"text": "从左侧拖入组件，或点「模板」一键生成整页画面", "ellipsis": True},
            "style": {"fontSize": 17, "color": "#9fb2c6", "textAlign": "center"},
        },
        {
            "id": "node_welcome_rule",
            "name": "装饰线",
            "type": "rect",
            "x": 900.0, "y": 556.0, "w": 120.0, "h": 2.0,
            "z": 3,
            "props": {},
            "style": {"fill": "#1ba7b8"},
        },
        {
            "id": "node_welcome_guide1",
            "name": "引导一",
            "type": "text",
            "x": 460.0, "y": 596.0, "w": 1000.0, "h": 28.0,
            "z": 4,
            "props": {"text": "01   拖入组件 · 右侧属性面板绑定变量与样式", "ellipsis": True},
            "style": {"fontSize": 15, "color": "#7f93a8", "textAlign": "center"},
        },
        {
            "id": "node_welcome_guide2",
            "name": "引导二",
            "type": "text",
            "x": 460.0, "y": 636.0, "w": 1000.0, "h": 28.0,
            "z": 5,
            "props": {"text": "02   顶部「数据」接入 MQTT / REST / Modbus 数据源", "ellipsis": True},
            "style": {"fontSize": 15, "color": "#7f93a8", "textAlign": "center"},
        },
        {
            "id": "node_welcome_guide3",
            "name": "引导三",
            "type": "text",
            "x": 460.0, "y": 676.0, "w": 1000.0, "h": 28.0,
            "z": 6,
            "props": {"text": "03   顶部「预览」查看运行效果 · 修改自动保存", "ellipsis": True},
            "style": {"fontSize": 15, "color": "#7f93a8", "textAlign": "center"},
        },
    ]
    return {
        "schemaVersion": settings.CURRENT_SCHEMA_VERSION,
        "project": {
            "id": project_id,
            "name": name,
            "description": None,
            "author": author,
            "createdAt": now,
            "updatedAt": now,
        },
        "settings": {
            "designSize": {"width": 1920, "height": 1080},
            "adaptive": "fit-contain",
            "theme": "blue-dark",
            "primaryColor": "#2563eb",
            "alarm": {
                "levelColors": {"info": "#3b82f6", "warn": "#f59e0b", "critical": "#ef4444"},
                "soundEnabled": True,
                "soundThrottleSec": 60,
            },
        },
        "datasources": [],
        "variables": [],
        "pages": [
            {
                "id": "page_1",
                "name": "主页面",
                "order": 0,
                "background": {"color": "#0b1220"},
                "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
                "components": welcome_components,
            }
        ],
        "alarmRules": [],
    }
