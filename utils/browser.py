"""
Playwright Browser Manager with persistent session support, anti-detection measures,
and human-like behavior simulation.
"""

from pathlib import Path
import random
import time
from typing import Optional
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright
from utils.logger import logger


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""


class BrowserManager:
    def __init__(self, platform: str, headless: bool = False, profile_dir: Optional[str] = None):
        self.platform = platform
        self.headless = headless
        
        base_dir = Path(__file__).parent.parent.resolve()
        if profile_dir:
            self.profile_path = Path(profile_dir)
        else:
            self.profile_path = base_dir / "data" / "browser_profiles" / platform
        self.profile_path.mkdir(exist_ok=True, parents=True)

        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def start(self) -> Page:
        """Launches persistent browser context with anti-detection flags."""
        logger.info(
            f"Launching {'[Headless/Background]' if self.headless else '[Visible Window]'} browser for {self.platform.capitalize()}..."
        )
        self.playwright = sync_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--start-maximized",
            "--disable-features=IsolateOrigins,site-per-process",
            "--lang=en-US,en",
        ]

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_path),
            headless=self.headless,
            viewport={"width": 1440, "height": 900},
            user_agent=DEFAULT_USER_AGENT,
            locale="en-US",
            timezone_id="Asia/Kolkata",
            args=args,
            ignore_default_args=["--enable-automation"],
        )

        # Inject stealth scripts into all new pages
        self.context.add_init_script(STEALTH_JS)

        pages = self.context.pages
        if pages:
            self.page = pages[0]
        else:
            self.page = self.context.new_page()

        return self.page

    def close(self):
        """Safely closes context and playwright engine."""
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    @staticmethod
    def human_delay(min_seconds: float = 2.5, max_seconds: float = 5.5):
        """Pauses execution for a random human-like interval."""
        delay = round(random.uniform(min_seconds, max_seconds), 2)
        time.sleep(delay)

    @staticmethod
    def smooth_scroll(page: Page, scrolls: int = 3, distance: int = 400):
        """Scrolls page gradually mimicking a human reading the screen."""
        for _ in range(scrolls):
            page.evaluate(f"window.scrollBy({{top: {distance}, behavior: 'smooth'}})")
            time.sleep(random.uniform(0.8, 1.6))
