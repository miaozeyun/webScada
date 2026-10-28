"""临时排查脚本：打开编辑器 → 数据抽屉 → 点「配置模拟数据」，抓控制台错误与 DOM 状态。"""
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5199"
logs: list[str] = []


def dump(page, label: str) -> None:
    print(f"\n===== {label} =====")
    btns = page.locator("button:has-text('配置模拟数据')")
    print("button count:", btns.count())
    for i in range(btns.count()):
        b = btns.nth(i)
        print("  disabled:", b.is_disabled(), "visible:", b.is_visible(), "text:", repr(b.inner_text()))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 950})
    page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
    page.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))

    page.goto(f"{BASE}/login")
    page.wait_for_timeout(800)
    page.fill("input[type=text]", "admin")
    page.fill("input[type=password]", "123456")
    page.click("button:has-text('登 录'), button:has-text('登录')")
    page.wait_for_url(f"{BASE}/projects", timeout=15000)
    page.wait_for_timeout(1200)
    print("projects page url:", page.url)
    # 打开第一个工程
    first = page.locator(".project-card, .card, .el-card").first
    print("cards:", page.locator(".el-card").count())
    page.locator(".el-card").first.click()
    page.wait_for_timeout(2500)
    print("editor url:", page.url)

    page.click("button:has-text('数据')")
    page.wait_for_timeout(800)
    dump(page, "drawer opened")

    # 数据源类型统计
    rows = page.locator(".el-drawer .el-table__row")
    print("datasource rows:", rows.count())
    for i in range(min(rows.count(), 8)):
        print("  row:", rows.nth(i).inner_text().replace("\n", " | ")[:120])

    btn = page.locator("button:has-text('配置模拟数据')").first
    if btn.count():
        print("clicking...")
        btn.click(force=True)
        page.wait_for_timeout(1200)
        dlg = page.locator(".el-dialog:visible")
        print("visible dialogs:", dlg.count())
        for i in range(dlg.count()):
            print("  dialog title:", dlg.nth(i).locator(".el-dialog__title").inner_text())
        page.screenshot(path="scripts/.dev_probe_click.png", full_page=False)

    page.wait_for_timeout(300)
    page.screenshot(path="scripts/.dev_probe_drawer.png", full_page=False)
    print("\n===== console =====")
    for l in logs[-60:]:
        print(l)
    browser.close()
