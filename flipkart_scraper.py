#!/usr/bin/env python3
"""
Standalone Flipkart search-results scraper (Selenium + BeautifulSoup).

Usage:
    python flipkart_scraper.py "smartphone"
    python flipkart_scraper.py "running shoes" --pages 3 --sort price_asc -o shoes.json
    python flipkart_scraper.py "laptop" --pages 2 --show        # watch the browser

As a library:
    from flipkart_scraper import scrape
    products = scrape("smartphone", pages=2)

Flipkart obfuscates its CSS class names and rotates them regularly, so this
parser deliberately avoids them. It relies on things that stay stable:
product cards carry a `data-id` attribute, product links contain `/p/`,
prices start with `₹`, discounts read "NN% off", and so on.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://www.flipkart.com"
SORT_OPTIONS = ("relevance", "popularity", "price_asc", "price_desc", "recency_desc")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

log = logging.getLogger("flipkart")

RATING_RE = re.compile(r"^[1-5](\.\d)?$")
RATINGS_COUNT_RE = re.compile(r"([\d,]+)\s+Ratings?", re.I)
REVIEWS_COUNT_RE = re.compile(r"([\d,]+)\s+Reviews?", re.I)
RATINGS_PAREN_RE = re.compile(r"^\(([\d,]+)\)$")  # grid layout shows "(1,234)"
DISCOUNT_RE = re.compile(r"(\d+)%\s*off", re.I)
TOTAL_PAGES_RE = re.compile(r"Page\s+\d+\s+of\s+([\d,]+)")


@dataclass
class Product:
    product_id: str
    title: str
    brand: str
    price: int | None
    mrp: int | None
    discount_pct: int | None
    rating: float | None
    ratings_count: int | None
    reviews_count: int | None
    specs: str
    url: str
    image_url: str
    page: int
    position: int


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _clean_url(href: str) -> str:
    """Drop Flipkart's tracking params, keep the product page + pid."""
    full = urljoin(BASE_URL, href)
    parsed = urlparse(full)
    pid = parse_qs(parsed.query).get("pid", [None])[0]
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return f"{clean}?pid={pid}" if pid else clean


def parse_card(card, page: int, position: int) -> Product | None:
    link = card.find("a", href=re.compile(r"/p/"))
    if not link:
        return None

    strings = [s for s in card.stripped_strings if s not in ("&", "Add to Compare")]

    # Title: grid cards put the full title on an <a title=...>; list cards on img alt.
    titled = card.find("a", title=True)
    img = card.find("img", alt=True, src=re.compile(r"flixcart\.com/image"))
    if titled:
        title = titled["title"].strip()
    elif img and img.get("alt", "").strip():
        title = img["alt"].strip()
    else:
        title = strings[0] if strings else ""

    # Brand: grid cards show it as the first line above the title.
    brand = ""
    if titled and strings and strings[0] != title and not strings[0].startswith("₹"):
        brand = strings[0]
    elif title:
        brand = title.split()[0]

    # Prices: first ₹ value is the selling price; the ₹ value right before
    # "NN% off" is the MRP. Ignore "Upto ₹X Off on Exchange" offer text.
    price = mrp = discount = None
    for i, s in enumerate(strings):
        if s == "Upto":
            break
        if s.startswith("₹"):
            if price is None:
                price = _to_int(s)
            elif mrp is None:
                mrp = _to_int(s)
        m = DISCOUNT_RE.search(s)
        if m and discount is None:
            discount = int(m.group(1))
    if discount is None:
        mrp = None  # a second ₹ without a discount label isn't an MRP

    rating = ratings_count = reviews_count = None
    for s in strings:
        if rating is None and RATING_RE.match(s):
            rating = float(s)
        elif ratings_count is None and (m := RATINGS_COUNT_RE.search(s)):
            ratings_count = _to_int(m.group(1))
        elif reviews_count is None and (m := REVIEWS_COUNT_RE.search(s)):
            reviews_count = _to_int(m.group(1))
        elif ratings_count is None and (m := RATINGS_PAREN_RE.match(s)):
            ratings_count = _to_int(m.group(1))

    specs = " | ".join(li.get_text(" ", strip=True) for li in card.find_all("li"))
    image = card.find("img", src=re.compile(r"flixcart\.com/image"))

    return Product(
        product_id=card.get("data-id", ""),
        title=title,
        brand=brand,
        price=price,
        mrp=mrp,
        discount_pct=discount,
        rating=rating,
        ratings_count=ratings_count,
        reviews_count=reviews_count,
        specs=specs,
        url=_clean_url(link["href"]),
        image_url=image["src"] if image else "",
        page=page,
        position=position,
    )


def parse_search_page(html: str, page: int) -> tuple[list[Product], int | None]:
    """Return (products, total_pages) for one search-results page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["svg", "script", "style"]):
        tag.decompose()

    products = []
    for card in soup.find_all("div", attrs={"data-id": True}):
        if card.find_parent("div", attrs={"data-id": True}):
            continue
        product = parse_card(card, page, len(products) + 1)
        if product and product.title:
            products.append(product)

    m = TOTAL_PAGES_RE.search(soup.get_text(" "))
    total_pages = _to_int(m.group(1)) if m else None
    return products, total_pages


# --------------------------------------------------------------------------- #
# Browser
# --------------------------------------------------------------------------- #
def make_driver(headless: bool = True) -> webdriver.Chrome:
    """Chrome via Selenium Manager - the matching chromedriver is fetched automatically."""
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument(f"user-agent={USER_AGENT}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-IN")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=opts)


def search_url(query: str, page: int, sort: str) -> str:
    return f"{BASE_URL}/search?q={quote_plus(query)}&sort={sort}&page={page}"


def load_page(driver, url: str, timeout: int = 20) -> str:
    driver.get(url)
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-id]"))
        )
    except TimeoutException:
        log.warning("No product cards appeared within %ss: %s", timeout, url)
    # Scroll down in steps so lazily loaded cards/images render.
    for frac in (0.3, 0.6, 1.0):
        driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {frac});")
        time.sleep(0.4)
    return driver.page_source


def scrape(
    query: str,
    pages: int = 1,
    sort: str = "relevance",
    headless: bool = True,
    delay: float = 2.0,
    debug_dir: Path | None = None,
) -> list[Product]:
    if sort not in SORT_OPTIONS:
        raise ValueError(f"sort must be one of {SORT_OPTIONS}")

    results: list[Product] = []
    seen: set[str] = set()
    driver = make_driver(headless)
    try:
        page = 1
        while page <= pages:
            url = search_url(query, page, sort)
            log.info("Page %d -> %s", page, url)
            html = load_page(driver, url)
            products, total_pages = parse_search_page(html, page)

            if not products:
                if debug_dir:
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    dump = debug_dir / f"page_{page}.html"
                    dump.write_text(html, encoding="utf-8")
                    log.warning("Saved page HTML for inspection: %s", dump)
                log.warning(
                    "No products on page %d (end of results, a block/captcha, "
                    "or Flipkart changed its layout). Stopping.", page
                )
                break

            new = [p for p in products if p.product_id not in seen]
            seen.update(p.product_id for p in new)
            results.extend(new)
            log.info("  %d products (%d new), total %d", len(products), len(new), len(results))

            if total_pages and page >= total_pages:
                log.info("Reached last page (%d).", total_pages)
                break
            page += 1
            if page <= pages:
                time.sleep(delay + random.uniform(0, 1))  # be polite
    finally:
        driver.quit()
    return results


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def save(products: list[Product], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(p) for p in products]
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        # utf-8-sig so Excel shows ₹ and other characters correctly
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(Product)])
            writer.writeheader()
            writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scrape Flipkart search results to CSV/JSON.")
    ap.add_argument("query", help='what to search for, e.g. "smartphone"')
    ap.add_argument("-p", "--pages", type=int, default=1, help="number of result pages (default 1)")
    ap.add_argument("-s", "--sort", choices=SORT_OPTIONS, default="relevance")
    ap.add_argument("-o", "--output", type=Path,
                    help="output file, .csv or .json (default: output/<query>.csv)")
    ap.add_argument("--show", action="store_true", help="show the browser window (not headless)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between pages (default 2)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    output = args.output or Path("output") / f"{re.sub(r'[^\w-]+', '_', args.query).strip('_')}.csv"

    try:
        products = scrape(
            args.query,
            pages=max(1, args.pages),
            sort=args.sort,
            headless=not args.show,
            delay=args.delay,
            debug_dir=output.parent / "debug",
        )
    except WebDriverException as e:
        log.error("Browser error: %s", e.msg or e)
        log.error("Make sure Google Chrome is installed.")
        return 1

    if not products:
        log.error("No products scraped.")
        return 2
    save(products, output)
    log.info("Saved %d products to %s", len(products), output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
