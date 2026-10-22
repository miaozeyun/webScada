"""doc 凭证脱敏 / 空值保留合并 / 导入置空（G6）。

与前端 web/src/utils/sanitize.ts 是同一契约的两端（G6）：
- 脱敏范围：mqtt/opcua 的 config.password；rest/websocket 的 config.headers 中
  键名匹配 authorization|token|password|secret|key（不区分大小写）的键值；
  settings.notify.channels[] 中钉钉渠道的 secret（工厂可用阶段二 Task 4）。
- mqtt/opcua 的 config.username 不脱敏。
- 所有出口（GET 工程详情 / 导出 / 分享快照）一律脱敏为空字符串。
"""
import copy
import re

SENSITIVE_HEADER_RE = re.compile(r"(authorization|token|password|secret|key)", re.IGNORECASE)


def iter_datasource_configs(doc: dict):
    """遍历 doc.datasources，yield (datasource_dict, config_dict)。"""
    for ds in doc.get("datasources") or []:
        if isinstance(ds, dict) and isinstance(ds.get("config"), dict):
            yield ds, ds["config"]


def iter_notify_channels(doc: dict):
    """遍历 doc.settings.notify.channels，yield 渠道 dict（钉钉渠道含敏感 secret）。"""
    notify_cfg = (doc.get("settings") or {}).get("notify")
    if not isinstance(notify_cfg, dict):
        return
    for ch in notify_cfg.get("channels") or []:
        if isinstance(ch, dict):
            yield ch


def _iter_sensitive_fields(ds: dict, config: dict):
    """yield 每个敏感字段的 (容器 dict, 键名)。
    mqtt/opcua → config.password；rest/websocket → config.headers 敏感键。
    """
    if ds.get("type") in ("mqtt", "opcua") and "password" in config:
        yield config, "password"
    if ds.get("type") in ("rest", "websocket"):
        headers = config.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if SENSITIVE_HEADER_RE.search(key):
                    yield headers, key


def sanitize_doc_for_output(doc: dict) -> dict:
    """深拷贝并把全部敏感字段置空字符串——GET 详情 / 导出 / 分享快照统一出口。

    台账缩略图（project.thumbnail，编辑器保存前截图写入的 base64 展示缓存）一并剔除：
    导出/分享文件不携带大图；编辑器每次保存前会重新截图写回，GET 详情无此字段不影响闭环。
    """
    out = copy.deepcopy(doc)
    for ds, config in iter_datasource_configs(out):
        for container, key in _iter_sensitive_fields(ds, config):
            container[key] = ""
    for ch in iter_notify_channels(out):
        if ch.get("kind") == "dingtalk" and "secret" in ch:
            ch["secret"] = ""
    project = out.get("project")
    if isinstance(project, dict) and project.get("thumbnail") is not None:
        project.pop("thumbnail")
    return out


def merge_sensitive_fields(submitted: dict, stored: dict) -> None:
    """PUT 空值保留合并（02 §4.3 规则⑤，就地修改 submitted）。

    防"编辑器载入脱敏 doc（密码框为空）→ 用户做无关修改 → PUT 全量覆盖 →
    空串抹掉库内凭证 → 采集器重建后 MQTT 鉴权失败"的断数缺陷。

    匹配规则：按 datasource.id 关联库内旧 doc。对每个敏感字段：
    - 提交值缺失或空串 → 保留库内值（库内为 FER1: 密文，原样透传）
    - 提交值为 null    → 从 submitted 删除该键（= 显式清除；username 与
                        password 同时清除 = 无凭据，对应 allow_anonymous 场景）
    - 提交值为非空串   → 覆盖为新值（保存前由 encrypt_doc_credentials 加密）
    """
    stored_by_id: dict[str, dict] = {}
    for ds, _config in iter_datasource_configs(stored):
        stored_by_id[ds.get("id", "")] = ds

    for ds, config in iter_datasource_configs(submitted):
        old_ds = stored_by_id.get(ds.get("id", ""))
        if old_ds is None:
            continue  # 新增数据源：无旧值可保留，按提交值走加密
        old_config = old_ds.get("config", {})
        old_headers = old_config.get("headers") or {}

        # mqtt / opcua password（opcua 沿 mqtt 同口径，阶段二 Task 8）
        if ds.get("type") in ("mqtt", "opcua"):
            _merge_one(config, old_config, "password")

        # rest / websocket headers 敏感键
        if ds.get("type") in ("rest", "websocket"):
            headers = config.get("headers")
            if isinstance(headers, dict):
                for key in list(headers.keys()):
                    if SENSITIVE_HEADER_RE.search(key):
                        _merge_one(headers, old_headers, key)
            elif old_headers:
                # headers 键整体缺省/非对象 = 保留库内旧值（与 mqtt password 缺省语义一致，
                # 规则⑤；否则省略 headers 的 PUT 会静默清掉库内凭证——复查 minor 修复）
                config["headers"] = copy.deepcopy(old_headers)

    # settings.notify.channels[].secret（钉钉）：渠道无 id，按 (kind, url) 关联库内旧渠道
    # （与数据源凭证注回的 URL 一致性口径一致；同 URL 换渠道视为同一机器人）
    stored_dingtalk: dict[str, dict] = {}
    for ch in iter_notify_channels(stored):
        if ch.get("kind") == "dingtalk" and ch.get("url"):
            stored_dingtalk.setdefault(str(ch["url"]), ch)
    for ch in iter_notify_channels(submitted):
        if ch.get("kind") != "dingtalk":
            continue
        old_ch = stored_dingtalk.get(str(ch.get("url") or ""))
        if old_ch is not None:
            _merge_one(ch, old_ch, "secret")


def _merge_one(container: dict, old_container: dict, key: str) -> None:
    """单字段合并：null → 删除键；缺失/空串 → 保留旧值；非空 → 保留新值。"""
    if key not in container or container[key] == "":
        if key in old_container and old_container[key] not in (None, ""):
            container[key] = old_container[key]  # 密文（或旧明文）透传，加密步骤统一处理
        elif key not in container:
            pass  # 双方都缺 → 保持缺失
    elif container[key] is None:
        del container[key]  # 显式清除


def clear_credentials_for_import(doc: dict) -> None:
    """导入凭证一律视为空（02 §4.3 规则③）：安全默认，导入后需在各数据源面板重填。

    同时强制 mqtt cleanSession=true（02 契约：导入工程不继承导出方的持久会话配置）。
    """
    for ds, config in iter_datasource_configs(doc):
        if ds.get("type") == "mqtt":
            config["cleanSession"] = True
        if ds.get("type") in ("mqtt", "opcua") and "password" in config:
            config["password"] = ""
        if ds.get("type") in ("rest", "websocket"):
            headers = config.get("headers")
            if isinstance(headers, dict):
                for key in list(headers.keys()):
                    if SENSITIVE_HEADER_RE.search(key):
                        headers[key] = ""
    for ch in iter_notify_channels(doc):
        if ch.get("kind") == "dingtalk" and "secret" in ch:
            ch["secret"] = ""
