# 参与贡献

感谢你愿意参与 webScada。本文件说明**必须遵守的流程**，以及与项目结构强相关的
硬性约定——这些约定不是风格偏好，违反会导致 CI 失败或线上故障。

## 0. 开始之前

- **首次贡献必须先签署 [CLA.md](CLA.md)**，否则 PR 不会被合并。
- 提交 Bug 或功能建议请使用 Issue 模板；安全问题**不要开公开 Issue**，
  见 [SECURITY 说明](#7-安全漏洞)。
- 本项目为「开源核心 + 企业版」双授权（[NOTICE.md](NOTICE.md)）。
  请勿提交你无权授权的代码，包括从其他项目复制的片段。

## 1. 本地开发

```bash
# 后端（Windows venv 路径；Linux/macOS 用 .venv/bin/）
cd server
.venv/Scripts/pytest            # 默认 SQLite 内存库，无需 PostgreSQL

# 前端
cd web
npm ci
npm run dev                     # 端口 5199（strictPort）
npm run build                   # vue-tsc --noEmit + vite build，类型检查是门禁
npm test                        # vitest run
```

完整部署见 [README.md](README.md)；四容器 compose 需本地 `.env` 中设置
`HTTP_PORT=8088`。

## 2. 提交前必须通过

| 检查 | 命令 | 说明 |
|---|---|---|
| 前端类型 | `cd web && npx vue-tsc --noEmit` | 任何 TS 报错都会阻断合并 |
| 前端构建 | `cd web && npm run build` | 含类型检查 |
| 前端单测 | `cd web && npm test` | vitest |
| 后端单测 | `cd server && pytest` | 默认 SQLite，无需 PG |

CI 同时会在 PostgreSQL 16 上跑 `alembic upgrade head` 冒烟与全量 pytest。

## 3. 改动契约时必须双侧同步（最容易出错的一条）

本项目的设计契约以 [docs/design/](docs/design/00-总览.md) 为准（`02-工程JSON数据结构`
是契约中心）。以下三对文件是**同构实现**，改任一侧必须同时改另一侧，并在 PR 中说明：

| 前端 | 后端 |
|---|---|
| `web/src/types/doc.ts` | `server/app/schemas/doc.py` |
| `web/src/utils/expr.ts`（表达式文法） | `server/app/services/expr_eval.py` |
| `web/src/runtime/engine.ts` 的 `toEngineering()` | `server/app/services/convert.py` |

> 迁移的唯一实现点在 `web/src/utils/migrateDoc.ts`；服务端只做 `schemaVersion`
> 等值校验（不匹配返回 422 `version_unsupported`），**不要在服务端新增迁移逻辑**。

## 4. 新增组件（widget）的唯一正确姿势

组件协议已冻结，**只增不改**：

1. 在 `web/src/widgets/registry.ts` 注册新 `type`（元信息、默认 props、属性面板 schema）；
2. 新建对应的 `.vue` 渲染器；
3. 不要改动 registry 的协议形状，也不要绕开 `WidgetHost.vue` 另写一套绑定/报警逻辑。

样式优先级（静态 props < 绑定映射 < 报警态；`visible` 绑定优先于报警）
**唯一实现点**在 `web/src/widgets/WidgetHost.vue`。

## 5. 硬性编码约定

- 浏览器基线 Chrome/Edge ≥ 90，构建目标 `es2020`：**不要使用 `structuredClone`**，
  用仓库内的深拷贝工具。
- 颜色一律走 `web/src/styles/theme.css` 的 CSS 令牌，**不要在组件里硬编码色值**。
- 接口前缀 `/api/v1`；校验失败统一返回 `422 {"code","message","errors":[...]}`。
- doc 内对象 id 由 `web/src/utils/nanoid.ts` 生成，前缀 `page_ / cmp_ / var_ / ds_ /
  bnd_ / alm_`。
- `auto-imports.d.ts` / `components.d.ts` 是 unplugin 生成物，**不要手改**。
- 后端使用异步 SQLAlchemy 2.0（PostgreSQL），不使用同步驱动或 Tortoise-ORM。
- 组件卸载时清理 ECharts 实例、WS 连接、定时器（engine / sources 提供 stop 句柄）。

## 6. 分支与提交

- 从 `main` 切出 `feat/<简述>` 或 `fix/<简述>`，通过 PR 合并到 `main`。
- 提交信息建议使用 `feat: / fix: / docs: / refactor: / test: / chore:` 前缀。
- 一个 PR 只做一件事；重构与功能改动分开。
- 修复 bug 时，请同步在 [docs/经验教训.md](docs/经验教训.md) 对应分类下追加一条
  「现象 / 根因 / 解决 / 预防」。

## 7. 安全漏洞

请**不要**通过公开 Issue 报告安全漏洞。发送邮件至 `18835132457@163.com`，
说明影响范围与复现步骤，我们会尽快回复。

## 8. 企业版与商业授权

企业版专有能力（RTSP 视频、主备冗余、白标 OEM、License 机制等）不在本仓库实现，
见 [NOTICE.md](NOTICE.md)。商业授权咨询：`18835132457@163.com`。
