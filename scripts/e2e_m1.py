# -*- coding: utf-8 -*-
"""M1 画布编辑器 E2E 验收（对齐 04-分阶段任务拆解.md M1 验收标准）。
前置：nginx(8088) 已运行；本脚本经 with_server.py 由 vite dev(5173) 代理访问。
覆盖：放置/拖拽移动/吸附/撤销重做/成组解组/保存持久化（刷新后坐标一致）。
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5199"
PASS = 0
FAIL = 0

# 凭证一律从环境变量读取，不写入仓库
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    sys.exit("缺少环境变量 ADMIN_PASSWORD")


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {detail}" if detail and not cond else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1


def node_rect(page, idx: int = 0):
    """读取第 idx 个顶层节点的 left/top/width（设计 px，zoom=1 时与 CSS 一致）"""
    return page.evaluate(
        """(i) => {
        const nodes = [...document.querySelectorAll('.canvas-page > .canvas-node')];
        const n = nodes[i];
        if (!n) return null;
        const s = getComputedStyle(n);
        return { left: parseFloat(s.left), top: parseFloat(s.top), w: parseFloat(s.width) };
    }""",
        idx,
    )


def drag_node(page, idx: int, dx: int, dy: int):
    """按住第 idx 个节点拖动 (dx,dy) 设计像素后松开。
    画布加载即自动适配视口（zoom ≤ 1），屏幕位移需按实际缩放比例换算。"""
    box = page.evaluate(
        """(i) => {
        const pg = document.querySelector('.canvas-page');
        const scale = pg.getBoundingClientRect().width / 1920;  // 实际渲染缩放
        const n = document.querySelectorAll('.canvas-page > .canvas-node')[i];
        const r = n.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2, scale };
    }""",
        idx,
    )
    s = box["scale"]
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x"] + dx * s, box["y"] + dy * s, steps=8)
    page.mouse.up()
    page.wait_for_timeout(120)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---- 登录 ----
    page.goto(f"{BASE}/login")
    page.wait_for_load_state("networkidle")
    page.fill("input[placeholder='用户名']", ADMIN_USER)
    page.fill("input[placeholder='密码']", ADMIN_PASSWORD)
    page.click("button.login-btn")
    page.wait_for_url("**/projects")
    check("登录并进入工程列表", "/projects" in page.url)

    # ---- 新建工程 ----
    page.click("text=新建工程")
    page.fill("input[placeholder='如：一号车间产线']", "M1自动化验证")
    page.click(".el-dialog__footer button.el-button--primary")
    page.wait_for_timeout(600)
    check("工程已创建", page.locator("td", has_text="M1自动化验证").count() > 0)

    # ---- 进入编辑器 ----
    row = page.locator("tr", has_text="M1自动化验证").first
    row.get_by_text("编辑", exact=True).click()
    page.wait_for_url("**/editor/**")
    page.wait_for_selector(".canvas-page")
    page.wait_for_timeout(400)
    check("编辑器加载（画布 1920x1080）", page.locator(".canvas-page").count() == 1)

    # ---- 放置组件（点击组件面板 → 当前可视区中心；页签条占高后不必等于设计中心，用相对断言） ----
    page.click(".palette-item >> text=文本")
    page.wait_for_timeout(200)
    r0 = node_rect(page, 0)
    check("点击放置组件（落点在画布内）", r0 is not None and 0 <= r0["left"] <= 1920 - r0["w"] and 0 <= r0["top"] <= 1000, str(r0))
    base_x, base_y = r0["left"], r0["top"]

    # ---- 拖拽移动 ----
    drag_node(page, 0, 150, 90)
    r1 = node_rect(page, 0)
    check("拖拽移动 +150/+90", abs(r1["left"] - base_x - 150) < 2 and abs(r1["top"] - base_y - 90) < 2, str(r1))

    # ---- 撤销 / 重做 ----
    page.keyboard.press("Control+z")
    page.wait_for_timeout(150)
    r2 = node_rect(page, 0)
    check("Ctrl+Z 撤销回到原位", abs(r2["left"] - base_x) < 2 and abs(r2["top"] - base_y) < 2, str(r2))
    page.keyboard.press("Control+Shift+z")
    page.wait_for_timeout(150)
    r3 = node_rect(page, 0)
    check("Ctrl+Shift+Z 重做回到移动后", abs(r3["left"] - base_x - 150) < 2 and abs(r3["top"] - base_y - 90) < 2, str(r3))

    # ---- 吸附（第二组件右缘 1080 为目标线） ----
    page.click(".palette-item >> text=文本")
    page.wait_for_timeout(150)
    drag_node(page, 1, 0, 150)  # 第二个组件移到 (840, 642)，右缘 = 840+240 = 1080
    # 从 990 拖 dx=+38 → 原始 1028，距 1080 中心线不命中；改为贴近右缘：dx = 1080-990-2 = 88 → 1078 距 1080 差 2 ≤5 → 吸附到 1080
    drag_node(page, 0, 88, 0)
    r4 = node_rect(page, 0)
    check("5px 吸附到相邻组件右缘 x=1080", abs(r4["left"] - 1080) < 0.6, str(r4))

    # ---- 成组 / 解组（顶部常驻工具栏） ----
    page.locator(".canvas-page > .canvas-node").nth(0).click()  # 选中 A
    page.locator(".canvas-page > .canvas-node").nth(1).click(modifiers=["Control"])  # 加选 B
    page.wait_for_timeout(120)
    page.get_by_role("button", name="组合", exact=True).click()
    page.wait_for_timeout(150)
    group_count = page.locator(".canvas-page > .canvas-node.group").count()
    check("两个组件成组（1 个组节点 ×2 children）", group_count == 1)
    g0 = node_rect(page, 0)
    drag_node(page, 0, 40, 40)  # 整组拖动
    g1 = node_rect(page, 0)
    check("组整体拖动（组原点 +40/+40）", abs(g1["left"] - g0["left"] - 40) < 2 and abs(g1["top"] - g0["top"] - 40) < 2, f"{g0}->{g1}")
    page.get_by_role("button", name="拆分", exact=True).click()
    page.wait_for_timeout(150)
    check("拆分还原 2 个顶层组件", page.locator(".canvas-page > .canvas-node:not(.group)").count() == 2)

    # ---- 双击行内编辑文本 ----
    target = page.locator(".canvas-page > .canvas-node").first
    target.dblclick()
    page.wait_for_timeout(300)
    editing = page.locator(".inline-edit").count()
    if editing:
        page.locator(".inline-edit").fill("改过的标题")
        page.evaluate("() => document.querySelector('.inline-edit')?.blur()")  # blur 提交
        page.wait_for_timeout(200)
    text_ok = page.evaluate(
        "() => document.querySelector('.canvas-page > .canvas-node .text-widget')?.textContent.includes('改过的标题')"
    )
    check("双击进入行内编辑并提交", editing == 1 and text_ok is True, f"editing={editing}")

    # ---- Ctrl+D 直接复制（先清选择，拆分后默认双选会复制两份——行为正确，测试需单选） ----
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)
    before_count = page.locator(".canvas-page > .canvas-node").count()
    page.locator(".canvas-page > .canvas-node").nth(0).click()
    page.wait_for_timeout(120)
    page.keyboard.press("Control+d")
    page.wait_for_timeout(200)
    after_count = page.locator(".canvas-page > .canvas-node").count()
    check("Ctrl+D 直接复制（+1）", after_count == before_count + 1, f"{before_count}->{after_count}")

    # ---- 右键菜单 ----
    page.locator(".canvas-page > .canvas-node").last.click(button="right")
    page.wait_for_timeout(200)
    menu_items = page.locator(".ws-contextmenu li").count()
    check("右键菜单弹出且含操作项", menu_items >= 6, f"items={menu_items}")
    page.keyboard.press("Escape")

    # ---- 手动保存 ----
    page.get_by_role("button", name="保存", exact=True).click()
    page.wait_for_timeout(800)
    saved = page.locator(".save-status", has_text="已保存").count() == 1
    check("保存成功（状态=已保存）", saved)
    before = node_rect(page, 0)

    # ---- 刷新重开：坐标一致 ----
    page.reload()
    page.wait_for_selector(".canvas-page")
    page.wait_for_timeout(600)
    after = node_rect(page, 0)
    check(
        "刷新后重开，坐标/尺寸完全一致",
        before and after and abs(before["left"] - after["left"]) < 0.6 and abs(before["top"] - after["top"]) < 0.6 and abs(before["w"] - after["w"]) < 0.6,
        f"{before} -> {after}",
    )

    page.screenshot(path="artifacts/m1_editor.png", full_page=False)
    check("无页面 JS 错误", len(errors) == 0, "; ".join(errors[:3]))

    browser.close()

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
