# 第三方代码声明（Third-Party Notices）

## visual-drag-demo

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
