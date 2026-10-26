## 变更说明

<!-- 这个 PR 解决什么问题？不要只贴 issue 编号。 -->

## 变更类型

- [ ] 新功能（feat）
- [ ] 缺陷修复（fix）
- [ ] 重构 / 性能（refactor / perf）
- [ ] 文档（docs）
- [ ] 测试（test）
- [ ] 构建 / CI / 依赖（chore）

## 自检清单

- [ ] 已阅读并签署 [CLA.md](../CLA.md)（首次贡献者必填，已在 PR 评论中声明）
- [ ] `cd web && npm run build` 通过（含 `vue-tsc --noEmit`）
- [ ] `cd web && npm test` 通过
- [ ] `cd server && pytest` 通过
- [ ] 未使用 `structuredClone`，未硬编码颜色值，未手改 `auto-imports.d.ts` / `components.d.ts`
- [ ] 涉及 bug 修复时，已在 [docs/经验教训.md](../docs/经验教训.md) 追加记录

## 契约影响（重要）

- [ ] 本 PR **不涉及**契约变更
- [ ] 本 PR 涉及契约变更，且已双侧同步：

| 前端 | 后端 | 是否同步 |
|---|---|---|
| `web/src/types/doc.ts` | `server/app/schemas/doc.py` | |
| `web/src/utils/expr.ts` | `server/app/services/expr_eval.py` | |
| `web/src/runtime/engine.ts` `toEngineering()` | `server/app/services/convert.py` | |

- [ ] 若涉及 `schemaVersion`，已同步更新 [docs/design/02-工程JSON数据结构.md](../docs/design/02-工程JSON数据结构.md)

## 组件相关（如适用）

- [ ] 新增组件仅在 `registry.ts` 追加注册项，未修改协议形状
- [ ] 绑定 / 报警样式逻辑未绕开 `WidgetHost.vue` 另写

## 截图 / 录屏

<!-- UI 变更必须附前后对比；纯后端改动可写「不适用」 -->
