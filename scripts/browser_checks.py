"""Real browser + PostgreSQL checks, isolated from development projects and observations.

Run with backend/.venv/bin/python scripts/browser_checks.py. Requires system Chromium.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from alembic.config import Config
from playwright.async_api import Browser, Page, Route, async_playwright, expect
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.database import make_engine  # noqa: E402

ARTIFACTS = ROOT / ".local" / "browser-checks"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_ready(url: str) -> None:
    with httpx.Client(trust_env=False) as client:
        for _ in range(60):
            try:
                if client.get(url, timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise RuntimeError("Test service did not become ready")


async def create_example(page: Page, base: str, name: str) -> str:
    await page.goto(base)
    await page.get_by_role("button", name=re.compile(name)).click()
    await page.get_by_role("button", name=re.compile("开始预演")).click()
    await expect(page.get_by_role("heading", name="准备你的专属场景")).to_be_visible()
    await expect(page.get_by_text("演示假设", exact=True).first).to_be_visible()
    await page.get_by_role("button", name="确认这些条件，开始预演 →").click()
    await expect(page.get_by_role("heading", name="如果按这些条件试一次")).to_be_visible()
    return page.url.split("/projects/")[1].split("/")[0]


async def no_overflow(page: Page) -> None:
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "horizontal overflow"
    )


async def run_checks(browser: Browser, base: str) -> list[str]:
    results: list[str] = []
    desktop = await browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
    page = await desktop.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(type(error).__name__))
    await page.goto(base)
    await expect(page.get_by_role("heading", level=1)).to_contain_text("真的开张了呢")
    await no_overflow(page)
    await page.screenshot(path=str(ARTIFACTS / "home-desktop.png"), full_page=True)
    await page.keyboard.press("Tab")
    await expect(page.get_by_role("link", name="跳到主要内容")).to_be_focused()
    await page.keyboard.press("Enter")
    results.append("desktop home, accessible inputs and no overflow")

    project = await create_example(page, base, "卖冰粉")
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥117.00")
    # Invalid data clears results; it must never leave stale successful numbers on screen.
    await page.get_by_label("今天准备多少份", exact=True).fill("-1")
    await expect(page.get_by_text("请先修正标红的输入。")).to_be_visible()
    await expect(page.locator(".metric.primary")).to_have_count(0)
    await page.get_by_label("今天准备多少份", exact=True).fill("10")
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥65.00")
    await page.screenshot(path=str(ARTIFACTS / "sandbox-desktop.png"), full_page=True)
    # Previewing changes must not persist any extra versions.
    versions = await page.evaluate(
        "async (id) => (await (await fetch('/api/v1/projects/'+id)).json()).data.versions.length",
        project,
    )
    assert versions == 1
    await page.get_by_role("button", name="保存为新方案").click()
    await expect(page.get_by_text("方案 2", exact=True)).to_be_visible()
    await page.reload()
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥65.00")
    results.append(
        "retail_perishable: invalid input, authoritative preview, explicit branch and reload"
    )

    await page.get_by_role("link", name="3 比比方案").click()
    await page.get_by_role("button", name="看看有什么不同").click()
    await expect(page.get_by_text("两边采用相同的需求假设。", exact=False)).to_be_visible()
    await expect(page.locator(".compare-grid .metric.primary strong").first).to_have_text(
        "−¥117.00"
    )
    await expect(page.locator(".compare-grid .metric.primary strong").last).to_have_text("−¥65.00")
    await page.screenshot(path=str(ARTIFACTS / "comparison-desktop.png"), full_page=True)
    results.append("parallel comparison preserves the original scheme")

    await page.get_by_role("link", name="4 现实挑战").click()
    await page.get_by_label("最想确认的一个问题").fill("价格接受度（自动化测试，不是真实调查）")
    await page.get_by_label("打算怎么了解").fill("仅测试保存流程；真实调查须另行征得参与者同意。")
    await page.get_by_role("button", name="保存这项挑战").click()
    await expect(page.get_by_label("你记录的数值")).to_be_visible()
    await page.get_by_label("你记录的数值").fill("9.00")
    await page.get_by_label("这次样本有多少个").fill("3")
    await page.get_by_label("实际观察到了什么").fill("自动化测试数据，未做实际用户调查。")
    await page.get_by_label("这次观察有什么局限").fill(
        "这是隔离数据库中的测试记录，不代表真实反馈。"
    )
    await page.get_by_role("button", name="保存这次观察").click()
    await expect(page.locator(".observation")).to_have_count(1)
    await page.reload()
    await expect(page.locator(".observation")).to_contain_text("不代表真实反馈")
    results.append(
        "manual task and observation save/reload with explicit provenance and limitations"
    )

    await page.route("**/api/v1/projects?*", lambda route: route.abort())
    await page.get_by_role("link", name="我的想法", exact=True).click()
    await expect(page.get_by_role("alert")).to_be_visible()
    await page.unroute("**/api/v1/projects?*")
    await page.get_by_role("button", name="再试一次").click()
    await expect(page.get_by_role("link", name="继续看看 →").first).to_be_visible()
    results.append("network failure offers recovery without a blank page")

    mobile = await browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, locale="zh-CN"
    )
    phone = await mobile.new_page()
    await create_example(phone, base, "做手工饰品")
    await expect(phone.locator(".metric.primary strong")).to_have_text("−¥50.00")
    await expect(phone.get_by_text("¥22.00", exact=True)).to_be_visible()
    await no_overflow(phone)
    await phone.screenshot(path=str(ARTIFACTS / "durable-mobile.png"), full_page=True)
    await create_example(phone, base, "接宠物摄影订单")
    await expect(phone.locator(".metric.primary strong")).to_have_text("¥320.00")
    await phone.get_by_label("完成一单要多少分钟", exact=True).fill("180")
    await expect(phone.locator(".metric.primary strong")).to_have_text("¥120.00")
    await expect(phone.get_by_label("今天准备多少份", exact=True)).to_have_count(0)
    await no_overflow(phone)
    await phone.screenshot(path=str(ARTIFACTS / "service-mobile.png"), full_page=True)
    results.append("mobile durable and service fields, amounts, live edits and no overflow")

    # Check a delayed response cannot replace a newer draft's result.
    await page.goto(f"{base}/projects/{project}/play")
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥65.00")

    async def delay_old(route: Route) -> None:
        data = route.request.post_data_json
        if data["scene"]["fields"]["stock_qty"]["value"] == 15:
            response = await route.fetch()
            await asyncio.sleep(0.8)
            try:
                await route.fulfill(response=response)
            except Exception:
                pass  # Aborting this obsolete preview is the expected application behavior.
        else:
            await route.continue_()

    await page.route("**/preview", delay_old)
    await page.get_by_label("今天准备多少份", exact=True).fill("15")
    await page.wait_for_timeout(400)
    await page.get_by_label("今天准备多少份", exact=True).fill("9")
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥70.50")
    await page.wait_for_timeout(1000)
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥70.50")
    await page.unroute("**/preview", delay_old)
    await page.route("**/preview", lambda route: route.abort())
    await page.get_by_label("今天准备多少份", exact=True).fill("8")
    await expect(page.get_by_role("alert")).to_be_visible()
    await expect(page.locator(".metric.primary")).to_have_count(0)
    await page.unroute("**/preview")
    await page.get_by_role("button", name="再试一次").click()
    await expect(page.locator(".metric.primary strong")).to_have_text("−¥76.00")
    results.append("preview network failure clears stale numbers and can be retried")

    async def lose_branch_response(route: Route) -> None:
        await route.fetch()
        await route.abort()

    await page.route("**/branches", lose_branch_response)
    await page.get_by_role("button", name="保存为新方案").click()
    await expect(page.get_by_role("alert")).to_be_visible()
    await page.unroute("**/branches")
    await page.get_by_role("button", name="保存为新方案").click()
    await expect(page.get_by_text("方案 3", exact=True)).to_be_visible()
    versions = await page.evaluate(
        "async (id) => (await (await fetch('/api/v1/projects/'+id)).json()).data.versions.length",
        project,
    )
    assert versions == 3
    results.append("lost write response reuses the original intent key; no duplicate branch")
    assert not errors, errors
    results.append("obsolete preview responses cannot overwrite the current result; no page errors")
    await desktop.close()
    await mobile.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--production", action="store_true", help="test built assets using Vite preview"
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="isolated scripted-model Agent UI test, no real provider",
    )
    args = parser.parse_args()
    url = Settings.load().database_url
    if not url or not url.startswith("postgresql"):
        raise RuntimeError("Start the documented PostgreSQL development service first")
    chromium = shutil.which("chromium")
    if not chromium:
        raise RuntimeError("Install system Chromium; browser checks cannot be claimed without it")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS / ("agent-report.json" if args.agent else "report.json")
    execution_id = uuid4().hex
    report_path.write_text(json.dumps({"status": "running", "execution_id": execution_id}))
    admin = make_engine(url)
    schema = "test_browser_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    test_url = (
        make_url(url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    engine = make_engine(test_url)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        config = Config(str(ROOT / "backend" / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        api_port, ui_port = free_port(), free_port()
        backend_env = {**os.environ, "DATABASE_URL": test_url, "COOKIE_SECURE": "false"}
        if args.agent:
            backend_env["BEFORE_OPEN_AGENT_TEST"] = "1"
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "tests.agent_cases.browser_app:app" if args.agent else "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                cwd=ROOT / "backend",
                env=backend_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )
        processes.append(
            subprocess.Popen(
                [
                    "npm",
                    "run",
                    "preview" if args.production else "dev",
                    "--",
                    "--port",
                    str(ui_port),
                ],
                cwd=ROOT / "frontend",
                env={**os.environ, "BEFORE_OPEN_API_TARGET": f"http://127.0.0.1:{api_port}"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )
        wait_ready(f"http://127.0.0.1:{api_port}/api/v1/ready")
        wait_ready(f"http://127.0.0.1:{ui_port}")

        async def check() -> list[str]:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    executable_path=chromium,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                try:
                    if args.agent:
                        from tests.agent_cases.browser_ui import run_agent_checks

                        return await run_agent_checks(
                            browser, f"http://127.0.0.1:{ui_port}", ARTIFACTS
                        )
                    return await run_checks(browser, f"http://127.0.0.1:{ui_port}")
                finally:
                    await browser.close()

        results = asyncio.run(check())
        report = {
            "execution_id": execution_id,
            "completed_at": datetime.now(UTC).isoformat(),
            "status": "passed",
            "scenarios": results,
            "count": len(results),
            "database": "isolated PostgreSQL schema",
            "build": "production" if args.production else "development",
            "model_transport": "scripted_test_not_real_provider" if args.agent else "not_used",
            "screenshots": str(ARTIFACTS),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


if __name__ == "__main__":
    main()
