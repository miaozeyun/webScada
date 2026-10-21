# 第三方代码声明（Third-Party Notices）

本文件声明本仓库**直接复用/移植**的第三方代码，以及**直接依赖**的许可类型。
完整许可文本以各包随附的 LICENSE 为准（npm 包位于 `node_modules/<pkg>/`，
pip 包位于虚拟环境 `site-packages/<pkg>/`）。所有依赖均为宽松许可
（MIT / BSD / Apache-2.0 / PostgreSQL License），与本项目 AGPL-3.0 兼容，
且本仓库未对任何依赖源码做修改。

## 一、移植代码

### visual-drag-demo（MIT License）

本仓库的画布编辑器交互实现（8 向缩放"对称点锚定"算法、旋转感知光标映射、右键菜单与
工具栏的交互模式、双击行内编辑模式）移植/参考自 [visual-drag-demo](https://github.com/woai3c/visual-drag-demo)。

其源码以 MIT License 授权：

```
MIT License

Copyright (c) 2021 谭光志

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

移植位置：`web/src/utils/resize.ts`（算法主体）、`web/src/editor/`（交互模式与右键菜单结构）。

## 二、前端直接依赖（运行时，随构建产物分发）

| 包 | 许可（SPDX） |
|---|---|
| vue | MIT |
| vue-router | MIT |
| pinia | MIT |
| element-plus | MIT |
| @element-plus/icons-vue | MIT |
| axios | MIT |
| echarts | Apache-2.0 |
| mqtt（MQTT.js） | MIT |
| html2canvas | MIT |
| nanoid | MIT |

> **ECharts 特别说明**：依 Apache-2.0 第 4 条，分发时须保留其版权、许可与 NOTICE
> 声明（见 `node_modules/echarts/` 内随附文件）。

## 三、前端构建/开发依赖（仅开发期使用，不随运行时分发）

@vitejs/plugin-vue（MIT）、vite（MIT）、vitest（MIT）、vue-tsc（MIT）、
typescript（Apache-2.0）、unplugin-auto-import（MIT）、unplugin-vue-components（MIT）

## 四、后端直接依赖（运行时）

| 包 | 许可（SPDX） |
|---|---|
| fastapi | MIT |
| uvicorn[standard] | BSD-3-Clause |
| sqlalchemy | MIT |
| asyncpg | Apache-2.0 |
| aiosqlite | MIT |
| alembic | MIT |
| pydantic / pydantic-settings | MIT |
| PyJWT | MIT |
| bcrypt | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause（双许可，任一满足） |
| httpx | BSD-3-Clause |
| aiomqtt | MIT |
| websockets | BSD-3-Clause |
| pymodbus | BSD-3-Clause |
| loguru | MIT |
| python-multipart | Apache-2.0 |

开发期：pytest（MIT）、pytest-asyncio（Apache-2.0）。

## 五、部署镜像（docker-compose 拉起，不内嵌于本仓库）

EMQX（Apache-2.0）、Nginx（BSD-2-Clause）、PostgreSQL（PostgreSQL License）——
商业边界与总体授权说明见 [NOTICE.md](NOTICE.md)。
