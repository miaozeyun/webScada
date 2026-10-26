# NOTICE — webScada 版权与授权边界声明

Copyright (c) 2026 webScada 作者与贡献者（Git 作者：miao_zeyun）

本软件的开源核心部分依据 **GNU Affero General Public License v3.0（AGPL-3.0）** 授权，
完整许可文本见仓库根目录 [LICENSE](LICENSE)。除 LICENSE 中允许的情形外，
任何复制、修改、再分发均须遵守 AGPL-3.0 的全部条款。

## 一、双授权模式：开源核心 / 企业版

webScada 采用「开源核心 + 企业版」双授权模式，二者边界如下：

| 能力 | 开源核心（本仓库，AGPL-3.0） | 企业版（商业授权） |
|---|---|---|
| 组态编辑器、39+ 组件、数据绑定与状态动画 | ✅ | ✅ |
| 工程 CRUD / 导入导出 / 发布分享快照 | ✅ | ✅ |
| MQTT / REST / WebSocket / Mock / Modbus TCP / OPC UA 数据接入 | ✅ | ✅ |
| 企业版专有功能（规划中）：RTSP 转码视频接入 | ❌ | ✅ |
| 企业版专有功能（规划中）：主备冗余 / 高可用 | ❌ | ✅ |
| 企业版专有功能（规划中）：白标 OEM、License 授权机制 | ❌ | ✅ |
| 企业版专有功能（规划中）：SLA 级支持与工单体系 | ❌ | ✅ |

> 诚实声明：企业版能力截至本文件撰写时**尚未交付**，上述企业版条目为规划边界，
> 用于提前划定开源核心的商业边界；落地节奏见 README「路线图」与
> `docs/assessment/commercial-readiness-2026-10-20.md`。

商业授权（含不符合 AGPL-3.0 闭源使用场景的替代许可）请联系：

- 邮箱：`18835132457@163.com`
- 微信：`miaozeyun2020`

（开源核心的 AGPL 义务不因购买企业版而豁免已分发部分。）

## 二、AGPL-3.0 关键义务提示（非法律建议，全文以 LICENSE 为准）

1. **网络交互即须提供源码**：AGPL-3.0 第 13 条规定，若您修改本软件并向网络用户提供
   交互服务（如云上托管组态 SaaS），您必须向这些用户提供修改后对应版本的完整源码。
   此条款即本项目选择 AGPL 的原因——防止云厂商闭源白嫖，同时保护企业版商业边界。
2. 修改后的版本必须显著标注变更、保留版权与许可声明，且不得降低用户的许可权利。
3. 将本软件（或其修改版）作为库链接进更大的作品时，整个组合作品仍受 AGPL-3.0 约束。
4. 分发时应随附 LICENSE 全文与本 NOTICE。

## 三、第三方组件

- 本仓库画布编辑器交互实现移植/参考自 visual-drag-demo（MIT License），
  详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 主要运行时依赖的许可：EMQX（Apache-2.0）、Nginx（BSD-2-Clause）、PostgreSQL
  （PostgreSQL License）、FastAPI / Uvicorn / Pydantic / SQLAlchemy（MIT / BSD）、
  Vue 3 / Element Plus / Pinia / Axios（MIT）、ECharts（Apache-2.0）、
  mqtt.js（MIT）、Vite / TypeScript（MIT / Apache-2.0）。
  各依赖的完整声明以其上游仓库为准；本仓库分发物中未内嵌修改这些依赖的源码。
