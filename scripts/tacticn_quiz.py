#!/usr/bin/env python3
"""
Tacticn – Quiz-Reels: ein Zeichen pro Video aus dem Tacticn-Baukasten (tacticn.de), Raten mit Countdown, Auflösung.

  python scripts/tacticn_quiz.py --probe              # Baukasten untersuchen (Auswahllisten, Namen) – nur Log
"""
import argparse
import json

BASE = "https://tacticn.de/baukasten/10-1211"


def probe(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 432, "height": 768}, locale="de-DE")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        info = page.evaluate("""() => ({
            title: document.title,
            selects: [...document.querySelectorAll('select')].map(s => ({label: s.getAttribute('aria-label'),
                name: s.name, value: s.value, options: [...s.options].map(o => [o.value, o.text])})),
            inputs: [...document.querySelectorAll('input,[role=combobox],button')].slice(0, 60).map(e =>
                [e.tagName, e.getAttribute('aria-label'), e.getAttribute('placeholder'), (e.innerText || '').slice(0, 40)]),
            headings: [...document.querySelectorAll('h1,h2,h3')].map(h => h.innerText),
            links: [...new Set([...document.querySelectorAll('a')].map(a => a.href))].slice(0, 200),
            text: document.body.innerText.slice(0, 4000),
        })""")
        print(json.dumps(info, ensure_ascii=False, indent=1))
        for path in ("/baukasten", "/sitemap.xml"):
            try:
                r = page.goto("https://tacticn.de" + path, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                print("=====", path, r.status if r else None)
                links = page.evaluate("() => [...new Set([...document.querySelectorAll('a')].map(a => a.href))]")
                print(json.dumps([l for l in links if "baukasten" in l][:400], ensure_ascii=False))
                print(page.content()[:3000] if path.endswith(".xml") else page.inner_text("body")[:3000])
            except Exception as e:  # noqa: BLE001
                print(path, "Fehler:", e)
        b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--url", default=BASE)
    a = ap.parse_args()
    if a.probe:
        probe(a.url)


if __name__ == "__main__":
    main()
