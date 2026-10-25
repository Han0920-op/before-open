import re
from pathlib import Path

from playwright.async_api import Browser, expect


async def run_agent_checks(browser: Browser, base: str, artifacts: Path) -> list[str]:
    context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = await context.new_page()
    await page.goto(base)
    await page.get_by_role("button", name="模型接入", exact=True).click()
    await expect(page.get_by_role("heading", name="选择帮你整理想法的模型")).to_be_visible()
    await page.get_by_label("你的 API Key").fill("test-only-key-not-a-real-credential")
    await expect(page.get_by_role("button", name="连接并授权调用")).to_be_disabled()
    await page.get_by_role("checkbox").check()
    await page.get_by_role("button", name="连接并授权调用").click()
    await expect(page.get_by_text("当前已填写：deepseek-chat")).to_be_visible()
    await expect(page.get_by_label("你的 API Key")).to_have_value("")
    await page.screenshot(path=str(artifacts / "model-connection.png"), full_page=True)
    await page.get_by_role("button", name="收起", exact=True).click()
    await page.get_by_label("你想试试什么？", exact=True).fill("我想卖冰粉，预算500元，备货200份。")
    await page.get_by_role("button", name=re.compile("开始预演")).click()
    await page.get_by_role("button", name="让智能体准备场景", exact=True).click()
    await expect(page.get_by_role("heading", name="已知和已确认的条件")).to_be_visible()
    assert await page.get_by_text("待确认", exact=True).count() > 0
    await page.get_by_role("button", name="未知条件用演示假设继续").click()
    await expect(page.get_by_role("button", name="确认这些条件并运行分析")).to_be_visible()
    await page.screenshot(path=str(artifacts / "agent-confirmation.png"), full_page=True)
    await page.get_by_role("button", name="确认这些条件并运行分析").click()
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥712.00")
    await expect(
        page.get_by_text("按目前投入，预算还差320.00元。可以比较更小的备货方案。", exact=True)
    ).to_be_visible()
    await page.get_by_text(re.compile("查看真实执行记录")).click()
    await expect(
        page.locator(".trace-item").filter(has_text="calculate_retail").first
    ).to_be_visible()
    await expect(page.locator(".trace-item").filter(has_text="check_budget").first).to_be_visible()
    await page.screenshot(path=str(artifacts / "agent-tools.png"), full_page=True)
    await page.get_by_role("button", name="确认：试试备货108份的方案").click()
    await expect(page.get_by_role("button", name="看看有什么不同")).to_be_visible()
    await page.get_by_role("button", name="看看有什么不同").click()
    await expect(page.locator(".compare-grid .metric.primary strong").first).to_have_text(
        "−¥712.00"
    )
    await expect(page.locator(".compare-grid .metric.primary strong").last).to_have_text("−¥390.00")
    assert (
        await page.evaluate("JSON.stringify(localStorage)+JSON.stringify(sessionStorage)") == "{}{}"
    )
    await page.reload()
    await page.get_by_role("button", name=re.compile("模型接入")).click()
    await expect(page.get_by_text("当前已填写：deepseek-chat")).to_be_visible()
    await page.get_by_role("button", name="断开当前模型").click()
    await expect(page.get_by_text("当前已填写：deepseek-chat")).to_have_count(0)
    await context.close()
    return [
        "model connection consent and no browser key persistence",
        "scripted-model draft retains facts and pauses for explicit confirmation",
        "confirmed graph executes real calculation/budget tools and shows evidence",
        "confirmed branch comparison and session connection disconnect",
    ]
