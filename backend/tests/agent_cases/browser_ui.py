"""Verify the current product works without making any AI requests."""

import re
from pathlib import Path

from playwright.async_api import Browser, expect


async def run_agent_checks(browser: Browser, base: str, artifacts: Path) -> list[str]:
    context = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = await context.new_page()
    ai_requests: list[str] = []

    def inspect_request(request: object) -> None:
        url = str(getattr(request, "url"))
        if any(
            part in url
            for part in (
                "/assistant-status",
                "/models",
                "/model-connection",
                "/scene-draft",
                "/agent-",
                "/experiment-draft",
            )
        ):
            ai_requests.append(url)

    page.on("request", inspect_request)
    await page.goto(base)
    await expect(page.get_by_role("button", name="模型接入", exact=True)).to_have_count(0)
    await expect(page.locator('input[type="password"]')).to_have_count(0)
    await page.get_by_label("你想试试什么？", exact=True).fill("我想卖冰粉，预算500元。")
    await page.get_by_role("button", name=re.compile("开始预演")).click()
    await expect(page.get_by_text("这句话会保存为你的想法。", exact=False)).to_be_visible()
    await page.get_by_role("button", name="用演示条件先试试").click()
    await page.get_by_role("button", name="确认这些条件，开始预演 →").click()
    await page.get_by_role("button", name="确认条件，开摊 →").click()
    await page.get_by_role("button", name="下一阶段 →").click()
    await page.reload()
    await expect(page.locator(".stage-badge")).to_have_text("第 1 阶段")
    await page.get_by_role("button", name="直接看完整结算").click()
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥117.00")
    await page.get_by_role("link", name="4 现实挑战").click()
    await expect(page.get_by_label("最想确认的一个问题")).to_be_visible()
    assert ai_requests == [], ai_requests
    await page.screenshot(path=str(artifacts / "ai-deferred.png"), full_page=True)
    # The test server deliberately has legacy LLM variables. The extension stays off.
    result = await page.evaluate(
        "async () => { const r = await fetch('/api/v1/models'); "
        "return {status:r.status,body:await r.json()}; }"
    )
    assert result["status"] == 503
    assert result["body"]["error"]["code"] == "AI_FEATURE_DEFERRED"
    await context.close()
    return [
        "no model setup or Key required",
        "custom idea explicitly uses manual conditions",
        "scene opening, steps, reload and settlement issue zero AI requests",
        "legacy credentials do not activate the deferred server extension",
    ]
