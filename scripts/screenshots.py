"""Take the README screenshots and the ask-flow GIF of the Streamlit app with a headless browser.

Usage::

    uv run --with playwright playwright install chromium
    uv run --with playwright python scripts/screenshots.py

Starts the app on a free local port with a throw-away cache folder, drives it with Playwright and
writes PNG files and one GIF into ``docs/screenshots/``. Only the synthetic examples are shown, and
the app runs on rules alone: no provider, no key, no network.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1600, "height": 1000}
SCALE = 1.5  # device pixels per CSS pixel: sharp enough to read the sheet in the README
GIF_WIDTH = 1000


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_up(url: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/_stcore/health", timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"the app did not start at {url}")


def settle(page: Page) -> None:
    """Wait until Streamlit has finished running the script and the page has stopped moving."""
    page.wait_for_timeout(500)
    page.wait_for_selector("[data-testid='stStatusWidget']", state="detached", timeout=300_000)
    page.wait_for_selector("[data-testid='stSpinner']", state="detached", timeout=300_000)
    page.wait_for_timeout(1200)


def load_example(page: Page, name: str) -> None:
    """Pick an example set in the sidebar and press "Load the example"."""
    page.get_by_test_id("stSidebar").get_by_test_id("stSelectbox").click()
    page.get_by_role("option", name=name).click()
    settle(page)
    page.get_by_role("button", name="Load the example").click()
    settle(page)


def ask(page: Page, question: str, frames: list[Image.Image] | None = None) -> None:
    """Type a question into the chat box and send it; optionally record frames while typing."""
    box = page.get_by_test_id("stChatInputTextArea")
    box.click()
    if frames is None:
        box.fill(question)
    else:
        for end in range(0, len(question) + 1, 6):
            box.fill(question[:end])
            to_top(page)
            frames.append(grab(page))
        box.fill(question)
        frames.append(grab(page))
    box.press("Enter")
    settle(page)
    box.blur()
    to_top(page)


def collapse_sidebar(page: Page) -> None:
    page.get_by_test_id("stSidebar").hover()
    page.get_by_test_id("stSidebarCollapseButton").click()
    settle(page)


def expand_sidebar(page: Page) -> None:
    page.get_by_test_id("stExpandSidebarButton").click()
    settle(page)


TO_TOP = """() => {
    for (const el of document.querySelectorAll('*')) { if (el.scrollTop > 0) el.scrollTop = 0; }
}"""


def to_top(page: Page) -> None:
    """Scroll every scrolled container back to the top (sending a question scrolls the page down)."""
    page.evaluate(TO_TOP)
    page.wait_for_timeout(300)


def grab(page: Page) -> Image.Image:
    return Image.open(io.BytesIO(page.screenshot())).convert("RGB")


def save_gif(frames: list[Image.Image], durations: list[int], path: Path) -> None:
    """Write the frames as a looping GIF, scaled down to GIF_WIDTH, on one shared palette."""
    height = round(frames[0].height * GIF_WIDTH / frames[0].width)
    small = [f.resize((GIF_WIDTH, height), Image.LANCZOS) for f in frames]
    palette = small[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    quantised = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in small]
    quantised[0].save(
        path, save_all=True, append_images=quantised[1:], duration=durations, loop=0, optimize=True, disposal=1
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="drawing-reader-shots-") as cache:
        env = os.environ | {
            "DRAWING_READER_CACHE": cache,
            "DRAWING_READER_PROVIDER": "none",
            "DRAWING_READER_ENV_FILE": str(Path(cache) / "no.env"),  # a local .env must not change the pictures
        }
        command = [
            sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "streamlit_app.py"),
            "--server.headless=true", f"--server.port={port}", "--server.address=127.0.0.1",
            "--browser.gatherUsageStats=false", "--theme.base=light", "--client.toolbarMode=minimal",
        ]  # fmt: skip
        server = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_until_up(url)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
                page.goto(url)
                page.wait_for_selector("text=Load a drawing set to begin", timeout=120_000)
                settle(page)
                page.screenshot(path=OUTPUT / "start.png")

                load_example(page, "access platform set")
                page.screenshot(path=OUTPUT / "first-look.png")

                page.get_by_text("First look").click()  # fold the summary so the GIF frames need no scrolling
                collapse_sidebar(page)
                frames: list[Image.Image] = [grab(page)]
                ask(page, "What is the brace size?", frames)
                typed = len(frames)
                frames.append(grab(page))
                page.get_by_role("button", name="Show on S-301").first.click()
                settle(page)
                to_top(page)
                frames.append(grab(page))
                page.screenshot(path=OUTPUT / "ask-evidence-detail.png")
                page.get_by_role("button", name="Show on S-201").first.click()
                settle(page)
                to_top(page)
                frames.append(grab(page))
                page.screenshot(path=OUTPUT / "ask-evidence.png")
                durations = [900] + [120] * (typed - 2) + [700, 2600, 2600, 2600]
                save_gif(frames, durations, OUTPUT / "ask-flow.gif")

                expand_sidebar(page)
                load_example(page, "access platform scan")
                page.wait_for_selector("text=This PDF is a scan", timeout=300_000)
                settle(page)
                collapse_sidebar(page)
                ask(page, "What sizes are the beams?")
                page.screenshot(path=OUTPUT / "scan.png")
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=30)
    for path in sorted(OUTPUT.glob("*.*")):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
