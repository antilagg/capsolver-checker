from typing import Optional, List
from dataclasses import dataclass
from patchright.async_api import async_playwright
from quart import Quart, request, jsonify
from logmagix import Logger, Loader
import asyncio
import os
from collections import deque
import time


@dataclass
class TurnstileAPIResult:
    result: Optional[str]
    elapsed_time_seconds: Optional[float] = None
    status: str = "success"
    error: Optional[str] = None


class PagePool:
    def __init__(self, context, debug: bool = False, log=None):
        self.context = context
        self.min_size = 1
        self.max_size = 10
        self.available_pages: deque = deque()
        self.in_use_pages: set = set()
        self._lock = asyncio.Lock()
        self.debug = debug
        self.log = log

    async def initialize(self):
        for _ in range(self.min_size):
            page = await self.context.new_page()
            self.available_pages.append(page)

    async def get_page(self):
        async with self._lock:
            if (not self.available_pages and
                    len(self.in_use_pages) < self.max_size):
                page = await self.context.new_page()
                if self.debug:
                    self.log.debug(f"Created new page. Total pages: {len(self.in_use_pages) + 1}")
            else:
                while not self.available_pages:
                    await asyncio.sleep(0.1)
                page = self.available_pages.popleft()

            self.in_use_pages.add(page)
            return page

    async def return_page(self, page):
        async with self._lock:
            self.in_use_pages.remove(page)
            total_pages = len(self.available_pages) + len(self.in_use_pages) + 1
            if total_pages > self.min_size and len(self.available_pages) >= 2:
                await page.close()
                if self.debug:
                    self.log.debug(f"Closed excess page. Total pages: {total_pages - 1}")
            else:
                self.available_pages.append(page)


class TurnstileAPIServer:
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Turnstile Solver</title>
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onloadTurnstileCallback" 
                async="" defer=""></script>
    </head>
    <body>
        <!-- cf turnstile -->
    </body>
    </html>
    """

    def __init__(self, debug: bool = False):
        self.app = Quart(__name__)
        self.log = Logger()
        self.debug = False
        self.page_pool = None
        self.browser = None
        self.context = None
        self.browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--window-position=2000,2000",
        ]
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.before_serving(self._startup)
        self.app.route('/turnstile', methods=['GET'])(self.process_turnstile)
        self.app.route('/')(self.index)

    async def _startup(self) -> None:
        os.system("cls")
        self.log.debug("Starting browser initialization...")
        try:
            await self._initialize_browser()
            self.log.success("Browser and page pool initialized successfully")
        except Exception as e:
            self.log.failure(f"Failed to initialize browser: {str(e)}")
            raise

    async def _initialize_browser(self) -> None:
        if self.debug:
            self.log.debug("Initializing browser with automation-resistant arguments...")

        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=False,
            args=self.browser_args
        )
        self.context = await self.browser.new_context()
        self.page_pool = PagePool(
            self.context,
            debug=self.debug,
            log=self.log
        )
        await self.page_pool.initialize()

        if self.debug:
            self.log.debug(
                f"Browser and page pool initialized (min: {self.page_pool.min_size}, max: {self.page_pool.max_size})")

    async def _solve_turnstile(self, url: str, sitekey: str) -> TurnstileAPIResult:
        start_time = time.time()
        page = await self.page_pool.get_page()
        try:
            url_with_slash = url + "/" if not url.endswith("/") else url
            turnstile_div = f'<div class="cf-turnstile" data-sitekey="{sitekey}"></div>'
            page_data = self.HTML_TEMPLATE.replace("<!-- cf turnstile -->", turnstile_div)

            await page.route(url_with_slash,
                             lambda route: route.fulfill(body=page_data, status=200))
            await page.goto(url_with_slash)

            await page.eval_on_selector(
                "//div[@class='cf-turnstile']",
                "el => el.style.width = '70px'"
            )

            max_attempts = 10
            attempts = 0
            while attempts < max_attempts:
                turnstile_check = await page.input_value("[name=cf-turnstile-response]")
                if turnstile_check == "":
                    await page.click("//div[@class='cf-turnstile']")
                    await asyncio.sleep(0.5)
                    attempts += 1
                else:
                    element = await page.query_selector("[name=cf-turnstile-response]")
                    if element:
                        value = await element.get_attribute("value")
                        elapsed_time = round(time.time() - start_time, 3)

                        print(f"SOLVED: {value[:45]}... ({elapsed_time}s)")

                        return TurnstileAPIResult(
                            result=value,
                            elapsed_time_seconds=elapsed_time
                        )
                    break

            return TurnstileAPIResult(
                result=None,
                status="failure",
                error="Max attempts reached without solution"
            )

        except Exception as e:
            return TurnstileAPIResult(
                result=None,
                status="error",
                error=str(e)
            )
        finally:
            await page.goto("about:blank")
            await self.page_pool.return_page(page)

    async def process_turnstile(self):
        url = request.args.get('url')
        sitekey = request.args.get('sitekey')

        if not url or not sitekey:
            return jsonify({
                "status": "error",
                "error": "Both 'url' and 'sitekey' are required"
            }), 400

        try:
            result = await self._solve_turnstile(url=url, sitekey=sitekey)
            return jsonify(result.__dict__), 200 if result.status == "success" else 500
        except Exception as e:
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500

    async def index(self):
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Turnstile Solver API</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-gray-100 min-h-screen flex items-center justify-center">
            <div class="bg-white p-8 rounded-lg shadow-md max-w-2xl w-full">
                <h1 class="text-3xl font-bold mb-6 text-center text-blue-600">Welcome to Turnstile Solver API</h1>

                <p class="mb-4 text-gray-700">To use the turnstile service, send a GET request to 
                   <code class="bg-gray-200 px-2 py-1 rounded">/turnstile</code> with the following query parameters:</p>

                <ul class="list-disc pl-6 mb-6 text-gray-700">
                    <li><strong>url</strong>: The URL where Turnstile is to be validated</li>
                    <li><strong>sitekey</strong>: The site key for Turnstile</li>
                </ul>

                <div class="bg-gray-200 p-4 rounded-lg mb-6">
                    <p class="font-semibold mb-2">Example usage:</p>
                    <code class="text-sm break-all">/turnstile?url=https://example.com&sitekey=sitekey</code>
                </div>

                <div class="bg-blue-100 border-l-4 border-blue-500 p-4 mb-6">
                    <p class="text-blue-700">This project is inspired by 
                       <a href="https://github.com/Body-Alhoha/turnaround" class="text-blue-600 hover:underline">Turnaround</a> 
                       and is currently maintained by 
                       <a href="https://github.com/Theyka" class="text-blue-600 hover:underline">Theyka</a> 
                       and <a href="https://github.com/sexfrance" class="text-blue-600 hover:underline">Sexfrance</a>.</p>
                </div>
            </div>
        </body>
        </html>
        """


def create_app():
    server = TurnstileAPIServer()
    return server.app


if __name__ == '__main__':
    app = create_app()
    app.run()

