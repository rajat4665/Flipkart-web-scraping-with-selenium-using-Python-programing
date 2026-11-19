# Flipkart Scraper

A standalone command-line scraper for Flipkart search results, built with Selenium and BeautifulSoup.
Give it a search term and it saves every product from the results pages to CSV or JSON.

## Setup

You need Python 3.10+ and Google Chrome. You don't have to download chromedriver: Selenium fetches the matching version automatically.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python flipkart_scraper.py "smartphone"                          # 1 page -> output/smartphone.csv
python flipkart_scraper.py "smartphone" --pages 5                # first 5 pages
python flipkart_scraper.py "running shoes" -s price_asc -o shoes.json
python flipkart_scraper.py "laptop" --show                       # watch the browser work
```

| Option | Description |
|---|---|
| `query` | Search term (quote it if it has spaces) |
| `-p, --pages` | Number of result pages to scrape (default 1) |
| `-s, --sort` | `relevance` (default), `popularity`, `price_asc`, `price_desc`, `recency_desc` |
| `-o, --output` | Output file. The extension sets the format: `.csv` or `.json`. Default: `output/<query>.csv` |
| `--show` | Show the Chrome window instead of running headless |
| `--delay` | Seconds to wait between pages (default 2, plus random jitter) |
| `-v, --verbose` | Print debug logging |

### Use it from Python

```python
from flipkart_scraper import scrape

for p in scrape("smartphone", pages=2, sort="price_asc"):
    print(p.title, p.price, p.rating)
```

## Output fields

| Field | Example |
|---|---|
| `product_id` | `MOBHMHG6CCNS5UWR` |
| `title` | `MOTOROLA g37 power (PANTONE Impenetrable, 64 GB)` |
| `brand` | `MOTOROLA` |
| `price` / `mrp` | `14999` / `26499` (₹, integers) |
| `discount_pct` | `43` |
| `rating`, `ratings_count`, `reviews_count` | `4.2`, `17123`, `1075` |
| `specs` | `4 GB RAM \| 64 GB ROM \| ... \| 7000 mAh Battery` |
| `url`, `image_url` | Product page link (tracking params removed) and image link |
| `page`, `position` | Where the product appeared in the results |

Some fields depend on the category. Electronics results use a list layout that includes specs and ratings. Fashion results use a grid layout that shows the brand, price and discount but often no ratings or specs. Fields that aren't shown are left empty.

Products that appear on more than one page (sponsored listings, for example) are saved only once.

## How it works

Flipkart obfuscates its CSS class names (for example `_3O0U0u`) and changes them every few months, which is what broke the original 2019 version of this project. This version doesn't use class names. Instead it relies on markup that stays the same:

- each product card has a `data-id` attribute (the product ID)
- product links contain `/p/`
- prices start with `₹`, and discounts read `NN% off`
- the pagination text reads `Page X of Y`

The scraper opens `flipkart.com/search?q=...&page=N` directly, so it doesn't need to close the login pop-up or type into the search box.

## Troubleshooting

- **"No products on page N"**: the raw HTML is saved to `output/debug/page_N.html` so you can inspect it. This usually means you reached the last page, Flipkart showed a captcha or rate limit (try `--show` and a larger `--delay`), or the page layout changed.
- **Browser error**: check that Google Chrome is installed and up to date.

## Disclaimer

This project is for educational use. Respect Flipkart's Terms of Use and robots.txt, keep request rates low, and don't use scraped data commercially.
