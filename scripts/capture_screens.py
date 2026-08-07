"""Headless screenshots of the running UI (localhost:8000) -> docs/screenshots/.
    python scripts/capture_screens.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"


def wait_results(page):
    page.wait_for_function("document.getElementById('results') && !document.getElementById('results').classList.contains('hidden')", timeout=30000)
    page.wait_for_timeout(1200)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 1500}, device_scale_factor=2)
        page.goto(URL, wait_until="networkidle")

        # 1. form with a preset loaded (anti-aging + texture)
        page.click("button.preset[data-i='0']")
        wait_results(page)
        page.screenshot(path=str(OUT / "01_form_preset.png"), full_page=True)

        # 2. routine with conflicts avoided (oily + acne -> AM/PM split)
        page.click("button.preset[data-i='1']")
        wait_results(page)
        page.screenshot(path=str(OUT / "02_conflicts_avoided.png"), full_page=True)

        # 3. safety toggle OFF -> red conflicts
        page.click("#toggle")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "03_safety_off.png"), full_page=True)

        # 4. debug panel expanded (toggle back on first)
        page.click("#toggle")
        page.wait_for_timeout(2500)
        page.eval_on_selector("details:last-of-type", "el => el.open = true")
        page.wait_for_timeout(400)
        # also expand a 'why this for you' for flavour
        page.eval_on_selector_all("details", "els => els.forEach(e => e.open = true)")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "04_debug_panel.png"), full_page=True)

        # 5. owned product pinned + §5.5 resolution ladder
        page.click("button.preset[data-i='4']")
        wait_results(page)
        page.screenshot(path=str(OUT / "05_owned_pinned.png"), full_page=True)

        # 6. swap that re-binds a SECOND slot: reject the retinoid -> the acid re-schedules AM<->PM
        page.click("button.preset[data-i='1']")   # oily + acne: retinoid PM + BHA AM
        wait_results(page)
        page.evaluate("""() => {
          for (const c of document.querySelectorAll('#results .rounded-lg')) {
            if (/retinol/i.test(c.textContent)) {
              const b = [...c.querySelectorAll('button')].find(x => /swap/i.test(x.textContent));
              if (b) { b.click(); return true; }
            }
          } return false;
        }""")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "06_swap_reschedule.png"), full_page=True)

        b.close()
    print("saved:", *[f.name for f in sorted(OUT.glob('*.png'))])


if __name__ == "__main__":
    sys.exit(main())
