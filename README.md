# InstantGamingScanner

Quick scraper to extract trending Steam game data from Instant-Gaming.

## What it does
- Renders pages (Playwright / undetected_chromedriver / Selenium fallback) and extracts `window.searchResults` JSON.
- Saves debug HTML pages (`page_*.html`) and prints a compact table of game name, EUR price and discount.

## Prerequisites
- Windows with Python 3.8+ (venv recommended)
- Chrome/Chromium binary (optional if using Playwright)
- Chromedriver (optional if using Selenium)

## Python dependencies
Install required packages in your virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install playwright selenium undetected-chromedriver requests
playwright install
```

Notes:
- If `undetected_chromedriver` is not available, the script will try Playwright.
- Playwright is the most reliable option for this project; run `playwright install` after installing the package.

## Usage
Run the main script from the project root:

```powershell
python main.py
```

The script auto-detects available backends. It will:
- Render each page and search for `window.searchResults`.
- Save debug pages as `page_<n>.html` when requests fallback is used.
- Print results to the console.

## Files of interest
- [main.py](main.py) — main scraper and renderer logic
- `page_*.html` — saved HTML snapshots for debugging

## Extending / Troubleshooting
- To save extracted data to CSV/JSON, modify `print_games_from_search_results()` or add a saver after parsing.
- If extraction fails, check `page_1.html` to inspect where the data is embedded (some pages include `window.searchResults` in a script tag).
- If Playwright is failing, ensure the Chromium browsers are installed via `playwright install`.

## License
MIT License
