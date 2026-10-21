# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in the `web/` directory.

webScada 前端：Vue3 + TypeScript + Vite + Pinia + Element Plus（按需自动引入）+ ECharts。权威契约见 [docs/design/02-工程JSON数据结构.md](../docs/design/02-工程JSON数据结构.md)，类型同构文件是 `src/types/doc.ts`（改契约须与 `server/app/schemas/doc.py` 双侧同步）。

## 命令

```bash
npm run dev            # vite dev server，端口 5199（strictPort：5173 被占，防静默换端口误导 E2E）
npm run build          # vue-tsc --noEmit + vite build——类型检查是门禁，改完必须过
npm test               # vitest run
npx vitest run src/utils/__tests__/migrateDoc.spec.ts   # 单个测试文件
npx vitest run -t "名称"                                # 按用例名过滤
```

- dev 代理：`/api → http://localhost:8088`（compose 的 nginx 入口，server 容器 8000 不暴露宿主机）；**必须 `ws: true`**，否则运行态 WebSocket `/api/v1/ws/runtime` 永挂「连接中」。
- vitest 环境 `node`（被测对象为纯函数，无 DOM）；`@` 别名在 vite.config.ts / vitest.config.ts 两处各配一份，改别名要同步。
- 测试内嵌在 `src/**/__tests__/*.spec.ts`，不在独立 tests/ 目录。

## 架构

### 双模式共享渲染器

编辑画布与运行大屏共用 `src/widgets/`（唯一组件实现）；编辑态只是外包选中/操作层。

- `widgets/registry.ts`：协议核心（type → 元信息/默认 props/属性面板 schema/渲染器），协议已冻结——**新增组件只增注册项，不改协议形状**。
- `widgets/WidgetHost.vue`：绑定求值装配 + 报警态叠加；**样式优先级（静态 props < 绑定映射 < 报警态；visible 绑定优先于报警）唯一实现点在此**，勿在单个组件里另写一套。
- 图表组件基于 `EchartsBase.vue` 适配器（按需注册、实例复用、刷新节流）。
- 行业图元：`src/assets/symbols/`（75 个自绘 SVG，9 大类），经 SymbolWidget 挂载；`MySymbolThumb` 供组件库缩略卡。

### 编辑态

`stores/editor.ts` 是核心：全量 doc + 选中集 + 页面级快照历史栈（上限 50）。**变更协议：交互开始 `beginChange()` → 改 doc → `_markDirty()`**；保存 3s 防抖 PUT（带 `baseRevision` 乐观锁，409 冲突由 http 层统一提示）。历史为页面级快照，切换页面即清空。

- `editor/canvas/`：CanvasStage（缩放平移/坐标换算）、SelectionLayer、AlignGuides（吸附）、MarqueeSelect、group.ts（成组/解组、组内相对坐标）。
- `editor/panels/`：组件库/图层/属性/页面等面板；DataDrawer 承载数据源/变量/报警规则三表 CRUD——**doc 级数据变更不入页面级 undo 栈**（历史快照语义不含它）。
- `editor/history.ts`、`keyboard.ts`：撤销重做与快捷键。

### 运行态

`runtime/engine.ts` 运行态引擎（编辑器预览 PreviewOverlay 与分享页 ShareView 共用）：数据源 → 变量池 → 绑定求值 → 报警判定。

- 双通道：`server: true` 时值流/报警/写通道由服务端 WS 驱动（sources.ts `startServerChannel`）；否则浏览器直连（编辑器连接测试路径）。
- `toEngineering()`（engine.ts）是与后端 convert.py 同构的换算链（bitIndex/scale/offset/precision），**仅服务注入预览路径**——运行态值已由服务端换算，不再调用。
- `actions.ts` 反控写中心：写权限收敛到 `writable` 选项（编辑器预览 true / 分享页恒 false）。
- `utils/expr.ts`：白名单表达式引擎，**文法与 `server/app/services/expr_eval.py` 逐一对应（契约 §11.2 最易漂移点）——改任一侧必须双侧同步且用例同构**。

### API 层

`api/http.ts`：axios 实例，响应拦截器**已解包 `res.data`**——各 api 模块的泛型返回值就是业务数据本身，不要再 `.data`。401 → 清 token 跳登录；`REVISION_CONFLICT` → 统一提示。token 存 localStorage `webscada_token`。

`api/uploads.ts`：图片直传（multipart → `/api/v1/uploads`，返回相对 URL）；属性面板 `ImagePicker.vue` 负责单图/多图（轮播）上传，组件 props 只存 URL。

### 路由与权限

`router/index.ts`：`/login`、`/projects`、`/editor/:id`、`/s/:token`（免登录分享页）、`/admin/users|audit`（requiresAdmin）。角色经 `/auth/me` 惰性拉取并模块级缓存（`fetchMyRole`），进 `/login` 即作废；守卫里动态 import api 模块——**http.ts 顶层 import 了 router，静态引入会循环依赖**。

## 硬性约定

- 浏览器基线 Chrome/Edge ≥ 90：build target es2020，**不用 `structuredClone`**（用自写深拷贝 util）。
- 全站色彩走 `src/styles/theme.css` CSS 令牌（浅色工业仪表主题），勿在组件里硬编码色值。
- doc 内对象 id 用 `utils/nanoid.ts` 生成，前缀约定 `page_ / cmp_ / var_ / ds_ / bnd_ / alm_`。
- `auto-imports.d.ts` / `components.d.ts` 是 unplugin 生成物，不手改。
- schemaVersion 迁移唯一实现点在 `utils/migrateDoc.ts`（服务端只校验版本）；doc 载入经 `utils/docNormalize.ts` 归一化（容忍模板/导入缺字段）。
- 组件卸载注意清理 ECharts 实例、WS 连接、定时器（engine/sources 提供 stop 句柄）。
