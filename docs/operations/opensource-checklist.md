# 开源前治理清单

> 目标形态：整仓 AGPL-3.0 公开（web + server），企业版专有能力留在私有仓叠加。
> 本文件记录开源前必须完成的整改项与**未执行的破坏性操作**，执行前须逐项确认。

## 一、已完成（2026-10-26）

| 项 | 文件 | 说明 |
|---|---|---|
| 贡献者许可协议 | `CLA.md`、`CLA-SIGNATURES.md` | 许可授予含「再许可权」，支撑 AGPL + 商业闭源双授权 |
| 商标政策 | `TRADEMARK.md` | 代码开源 ≠ 商标授权；白标/OEM 需书面许可 |
| 贡献指南 | `CONTRIBUTING.md` | 契约双侧同步、组件协议只增不改、硬性编码约定 |
| PR 模板 | `.github/PULL_REQUEST_TEMPLATE.md` | 含契约同步自检表 |
| Issue 模板 | `.github/ISSUE_TEMPLATE/*.yml` | GitHub form 格式 |
| Issue 模板（Gitee） | `.gitee/ISSUE_TEMPLATE.zh-CN.md` | Gitee 不支持 GitHub form 格式 |
| README | `README.md` | 补「参与贡献」小节、真实 Issues 地址、商标声明 |

## 二、阻断级：不处理不得公开

### 2.1 `.recon/` 泄漏第三方系统登录态（最高风险）

已入库 67 个文件，含：

- `token.txt` —— **第三方系统的真实 JWT**（非测试数据）
- `userinfo.json`、`captcha.png`、`routers.json` —— 对方后台的用户信息与路由结构
- `recon_step*.py`、`shots/` —— 针对特定站点的自动化侦察脚本与截图

公开后果：泄露他人系统凭证 + 暴露无授权访问痕迹，可能引发法律纠纷。
**仅删除当前文件无效**，历史仍可检出，必须重写历史。

#### 推荐方案：`git filter-repo` 就地剥离（保留其余历史）

先在**副本**上验证，确认无误再操作正式仓库：

```bash
# 0. 工具
pip install git-filter-repo

# 1. 在副本上操作（不要直接动工作仓库）
git clone --mirror https://gitee.com/miao_zeyun/web-scada.git /tmp/webscada-clean.git
cd /tmp/webscada-clean.git

# 2. 剥离 .recon 全历史
git filter-repo --path .recon --invert-paths --force

# 3. 验证（两条都应为空输出）
git log --all --oneline -- .recon
git rev-list --objects --all | grep -i recon

# 4. 回推（此步不可逆，执行前确认已备份 + 无人依赖旧历史）
git remote add origin https://gitee.com/miao_zeyun/web-scada.git
git push --force origin 'refs/heads/*' 'refs/tags/*'
```

> 副作用：**全部 commit hash 改变**。协作者需重新 clone；Gitee 的 PR、issue
> 中的 commit 引用会失效。当前为单人开发 + internal-pilot，代价可接受。

#### 备选方案：新建仓库只推当前树

放弃全部历史，`git init` 新仓后推当前工作树。更彻底、零遗漏，但开源项目失去
开发历史会降低可信度，不建议。

#### 执行后必做

- [ ] 在 Gitee 后台检查「仓库动态/附件」是否残留旧内容
- [ ] 确认 `.recon` 已加入 `.gitignore`（2026-10-26 已加；但仅加 gitignore 不会
      停止跟踪，还需 `git rm -r --cached .recon`，在重写历史时一并处理）
- [ ] 通知任何已有 clone 的机器重新克隆

### 2.2 测试脚本硬编码口令 ✅ 已完成（2026-10-26）

`scripts/acceptance_m0.py`、`scripts/e2e_m1.py` 原含明文口令，现统一改为环境变量：

| 变量 | 用途 |
|---|---|
| `ADMIN_USER` / `ADMIN_PASSWORD` | 登录（缺省 `ADMIN_PASSWORD` 直接退出并提示） |
| `MQTT_USER` / `MQTT_PASSWORD` | 验收脚本内嵌数据源凭证 |

`e2e/playwright.config.ts` 注释、`docs/design/02` §数据源示例中的明文密码一并脱敏。

> 保留项：`server/tests/` 中的固定口令属于测试夹具（SQLite 内存库，不连真实服务），
> 公开无实质风险；反向用例（「错误密码 401」）保留任意字符串。

### 2.3 商业评估文档不公开 ✅ 已完成（2026-10-26）

`docs/assessment/` 5 份文件已移至 `docs/private/assessment/`（`.gitignore` 已加
`docs/private/`）。README、NOTICE、CHANGELOG 中的引用已改为「内部文档，不随开源发布」。

**历史剥离须一并处理该路径**（见 §2.1，filter-repo 命令已含 `docs/assessment`）。

### 2.3b 竞品名清理 ✅ 已完成（2026-10-26）

源码注释与文档中共 15 处使用了竞品简称「BY」，违反 `CLAUDE.md`「对外文案竞品一律称
『业界主流组态』」的约定，已批量替换为「业界主流组态」。`ORDER BY` 等 SQL 关键字
未受影响。

### 2.4 `docs/经验教训.md` 人工过筛

该文件记录了踩坑细节，可能包含客户名称、内部环境地址、竞品对比结论。
需逐条确认后再公开（保留技术结论，删除涉及第三方的具体信息）。

## 三、建议级

- [ ] **商标注册**：提交「webScada」文字商标（第 9 类软件 / 第 42 类技术服务）。
      TRADEMARK.md 的效力依赖注册，未注册时仅有反不正当竞争法的弱保护。
- [ ] **双平台托管**：Gitee 为主仓，GitHub 镜像（国际曝光）。镜像同步可用
      `git push --mirror` 或 Gitee 的仓库镜像功能。
- [ ] **CI 增加契约一致性检查**：自动比对 `web/src/types/doc.ts` 与
      `server/app/schemas/doc.py`、`web/src/utils/expr.ts` 与
      `server/app/services/expr_eval.py`（当前依赖人工纪律，是最易漂移处）。
- [ ] **企业版私有仓就位**：开源发布前先建好私有仓，避免「企业版功能无处安放」
      导致回流到公开仓。

## 四、公开后维护节奏

- 新功能先进企业版，稳定后下沉开源版；**不要**为了转化故意阉割基础能力。
- 每个 bug 修复同步追加 `docs/经验教训.md`（见 CONTRIBUTING.md §6）。
- 收到竞品抄用的线索时，优先用商标 + 商业谈判处理，不要指望 AGPL 诉讼止损。
