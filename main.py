import sys

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
import os
import re
import requests
import json
import time
from enum import Enum
from InquirerPy import inquirer as ip
import re
from thefuzz import fuzz
import matcher
from matcher import MatchDebug
from logging import getLogger, FileHandler, Formatter, INFO, ERROR

from env_get import *

global BASE_URL, BASE_URL_NON_STEAM, BASE_DIRECTORY
BASE_DIRECTORY: str = os.getcwd() + "/tmp_html"  # current working directory for saving HTML files
BASE_URL = "https://www.instant-gaming.com/en/pc/steam/trending/"
BASE_URL_NON_STEAM = "https://www.instant-gaming.com/en/pc/trending/"
# debug flag to print detailed fuzzy-match candidate scores for wishlist items
MATCH_DEBUG = False


def visible_length(s: str) -> int:
    ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')
    return len(ANSI_ESCAPE.sub('', s))

def get_discount_class(discount):
    try:
        d = int(discount)
        if d >= 90:
            return "\033[35m"  
        elif d >= 75:
            return "\033[32m"
        elif d >= 60:
            return "\033[33m"
        elif d > 45:
            return "\033[31m"
        else:
            return "\033[90m"
    except Exception:
        return "\033[0m"
    
def get_price_class(price):
    try:
        p = float(price)
        if p == 0:
            return "\033[95m"  
        elif p <= 1:
            return "\033[35m"
        elif p <= 5:
            return "\033[32m"
        elif p <= 10:
            return "\033[33m"
        else:
            return "\033[90m"
    except Exception:
        return "\033[0m"

def get_search_results_with_selenium(url, env=None):
    p(Stat.INFO, f"Starting renderer to fetch data from: {url}")
    if env is None:
        env = init_fetcher()

    uc = env.get('uc')
    sync_playwright = env.get('sync_playwright')
    chrome_path1 = env.get('chrome_path1')
    chrome_path2 = env.get('chrome_path2')
    chromedriver_path = env.get('chromedriver_path')

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    try:
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
    except Exception:
        pass

    # select chrome binary
    if chrome_path1 and os.path.exists(chrome_path1):
        chrome_path = chrome_path1
        p(Stat.INFO, f"Using Chrome binary: {chrome_path}")
    elif chrome_path2 and os.path.exists(chrome_path2):
        chrome_path = chrome_path2
        p(Stat.INFO, f"Using Chrome binary: {chrome_path}")
    else:
        p(Stat.ERROR, f"ERROR: Could not find chrome.exe at {chrome_path1} or {chrome_path2}")
        raise FileNotFoundError("chrome.exe not found for Selenium")

    options.binary_location = chrome_path
    if not chromedriver_path or not os.path.exists(chromedriver_path):
        raise FileNotFoundError(f"chromedriver not found at {chromedriver_path}")

    driver = None
    html = None

    # Try undetected_chromedriver first
    if uc is not None:
        try:
            p(Stat.INFO, "Attempting undetected_chromedriver (uc) for stealth browsing...")
            uc_options = uc.ChromeOptions()
            uc_options.add_argument("--window-size=1920,1080")
            uc_options.add_argument("--no-sandbox")
            uc_options.add_argument("--disable-dev-shm-usage")
            uc_options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            driver = uc.Chrome(options=uc_options)
            p(Stat.SUCCESS, "undetected_chromedriver (uc) started successfully")
            try:
                driver.get(url)
                time.sleep(2)  # wait for JS to execute and populate searchResults
            except Exception as e:
                p(Stat.ERROR, f"uc driver.get() exception: {e}")
            html = driver.page_source
            try:
                driver.save_screenshot('uc_debug.png')
            except Exception:
                pass
            current = driver.current_url
            p(Stat.INFO, f"uc current URL: {current}")
        except Exception as e:
            p(Stat.ERROR, f"uc failed: {e}")
            driver = None

    # Try Playwright next (if available)
    if (driver is None) and sync_playwright is not None:
        try:
            p(Stat.INFO, "Attempting Playwright (chromium) for stealth browsing...")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                page = context.new_page()
                responses = []
                def _on_response(r):
                    try:
                        url = r.url
                        if any(x in url for x in ["api", "search", "hits", "products", "listing"]):
                            printl("🔥 API CANDIDATE:", url)
                    except:
                        pass
                page.on('response', _on_response)
                # navigate and wait for network to quiet down, then wait for the page JS to populate searchResults
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                try:
                    try:
                        page.wait_for_function("() => window.searchResults || window.__SEARCH_RESULTS__ || window.__INITIAL_STATE__", timeout=8000)
                    except Exception:
                        pass
                    js_val = page.evaluate('() => (window.searchResults || window.__SEARCH_RESULTS__ || window.__INITIAL_STATE__ || null)')
                    if js_val:
                        p(Stat.SUCCESS, "Found searchResults via page.evaluate in Playwright")
                        context.close()
                        browser.close()
                        return js_val
                except Exception:
                    pass

                for r in responses:
                    try:
                        ct = r.headers.get('content-type', '')
                        if 'application/json' in ct or r.request.resource_type == 'xhr':
                            j = None
                            try:
                                j = r.json()
                            except Exception:
                                try:
                                    j = json.loads(r.text())
                                except Exception:
                                    j = None
                            if isinstance(j, dict) and ('hits' in j or 'results' in j or 'searchResults' in j):
                                p(Stat.SUCCESS, f"Found JSON XHR response from Playwright: {r.url}")
                                context.close()
                                browser.close()
                                return j
                    except Exception:
                        continue

                html = page.content()
                page.screenshot(path='playwright_debug.png')
                current = page.url
                p(Stat.INFO, f"playwright current URL: {current}")
                context.close()
                browser.close()
        except Exception as e:
            p(Stat.ERROR, f"Playwright failed: {e}")
            html = None

    # Fallback: start selenium chromedriver
    if driver is None:
        try:
            service = Service(executable_path=chromedriver_path, log_path='chromedriver.log')
            driver = webdriver.Chrome(service=service, options=options)
        except Exception as e:
            p(Stat.ERROR, f"Error starting ChromeDriver / Chrome: {e}")
            try:
                with open('chromedriver.log', 'r', encoding='utf-8') as lf:
                    p(Stat.INFO, '\n--- chromedriver.log ---')
                    p(Stat.INFO, lf.read())
                    p(Stat.INFO, '--- end chromedriver.log ---\n')
            except Exception:
                pass
            raise

    # attempt to hide webdriver and other automation indicators via CDP before navigation
    try:
        stealth_js = (
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "window.navigator.chrome = { runtime: {} };"
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});"
            "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});"
        )
        try:
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': stealth_js})
        except Exception:
            try:
                driver.execute_script(stealth_js)
            except Exception:
                pass
    except Exception as e:
        p(Stat.ERROR, f"Could not set CDP stealth script: {e}")

    # navigate if we don't already have HTML
    try:
        if html is None:
            p(Stat.INFO, f"Navigating with Selenium to: {url}")
            driver.get(url)
            try:
                WebDriverWait(driver, 30).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            except Exception as e:
                p(Stat.WARNING, f"Timed out waiting for document.readyState complete: {e}")
            html = driver.page_source
    except Exception as e:
        p(Stat.ERROR, f"driver.get() raised an exception: {e}")

    try:
        current = driver.current_url
        p(Stat.INFO, f"Current URL after navigation: {current}")
    except Exception as e:
        p(Stat.ERROR, f"Could not retrieve current_url: {e}")

    try:
        driver.save_screenshot('selenium_debug.png')
    except Exception as e:
        p(Stat.WARNING, f"Could not save screenshot: {e}")
    try:
        with open('selenium_page.html', 'w', encoding='utf-8') as f:
            f.write(html or driver.page_source)
        p(Stat.INFO, 'Saved selenium_page.html for inspection.')
    except Exception as e:
        p(Stat.WARNING, f"Could not save page HTML: {e}")

    match = re.search(r'window\\.searchResults\\s*=\\s*({.*?})\\s*;?', (html or ''), re.DOTALL)
    if not match:
        p(Stat.INFO, "window.searchResults not found in rendered page!")
        try:
            driver.quit()
        except Exception:
            pass
        return None
    json_str = match.group(1)
    try:
        data = json.loads(json_str)
    except Exception as e:
        p(Stat.ERROR, f"Error parsing JSON from rendered HTML: {e}")
        try:
            driver.quit()
        except Exception:
            pass
        return None
    try:
        driver.quit()
    except Exception:
        pass
    return data
# (moved imports to top)

# scrape instant-gaming.com for game prices and discounts

def print_games_from_search_results(data, nosleep=False):
    
    
    GTL: int = 45 # Game title length

    printl(f"% | €  {'Game Name':<{GTL}} {'Original Price':<11}  {'Price':<8} {'Discount'} {'type':<20}")
    printl("-" * 95)

    games = {}


    print_data = {}
    for game in data.get("hits", []):
        try:
            name = game.get("name", "Unknown")
            original_price = game.get("default_retail", "N/A")
            price = game.get("price_eur", "N/A")
            discount = game.get("discount", "N/A")
            discount_color = get_discount_class(discount)
            if price is not None and price != "N/A":
                price_color = get_price_class(price)
                if isinstance(price, (int, float, str)) and str(price) != "N/A":
                    discount_price = f"{price.split('.')[0][:3]:>3},{price.split('.')[1][:2]:>2}" if price != "N/A" else "N/A"
                else:
                    discount_price = "N/A"
                
                if isinstance(original_price, str) and original_price != "N/A":
                    original_price = f"{original_price.split('.')[0][:3]:>3},{original_price.split('.')[1][:2]:>2}" if original_price != "N/A" else "N/A"
                else: discount_price = "N/A"
            else:
                price_color = "\033[0m"
                discount_price = "N/A"
            try:
                type = game.get("type", "N/A")
            except Exception as e:
                p(Stat.ERROR, f"Error parsing type for {name}: {e}")
                type = "N/A"
            if len(name[:GTL]) % 2 == 0:
                name_str = f"{name[:GTL-2]:<{GTL}}".replace("  ", " .") + "  " # replace double spaces with dot for better visibility of spacing
            else:
                name_str = f"{name[:GTL-2]:<{GTL}}".replace("  ", ". ") + "  " # replace double spaces with dot for better visibility of spacing

            # use a composite key so multiple entries with the same display name but different
            # platforms/ids are preserved instead of overwritten
            key = make_game_key_from_obj(game)
            games[key] = {
                "display_name": name,
                "original_price": original_price,
                "price": discount_price,
                "discount": discount,
                "type": type
            }
            print_data[key] = {
                "discount_color":discount_color,
                "price_color": price_color,
                "name_str": name_str,
                "original_price": original_price,
                "discount_price": discount_price,
                "discount": discount,
                "type": type
                }
        except Exception as e:
            if e != "'NoneType' object has no attribute 'split'":
                p(Stat.ERROR, f"Error occurred while processing game {name}: {e}")
    for g in print_data.keys():
        game = print_data[g]
        printl(f"{str(game['discount_color'])}%\033[0m | {str(game['price_color'])}€\033[0m  {str(game['name_str'])} {str(game['original_price'])}{' '*6}{str(game['discount_price'])}   {str(game['discount']):>4}% {str(game['type']) if str(game['type']) else 'N/A'}")
        if not nosleep: time.sleep(0.04)  # slight delay for better readability

    return games

class ProcessType(Enum):
    SELENIUM = 1
    REQUESTS = 2
    PLAYWRIGHT = 3

def process_site(url: str, process_type: ProcessType, env: dict=None, base_directory: str=None) -> dict:
    # For PLAYWRIGHT and SELENIUM processing we use the same renderer function
    text = None
    if process_type in (ProcessType.SELENIUM, ProcessType.PLAYWRIGHT):
        try:
            data = get_search_results_with_selenium(url, env=env)
            if data:
                return data
            else:
                p(Stat.INFO, "Falling back to requests (renderer did not find data)...")
        except Exception as e:
            p(Stat.ERROR, f"Renderer error: {e}\nFalling back to requests...")

    # If we're explicitly using requests, or renderer failed, fetch via requests as a fallback
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        response = requests.get(url, headers=headers)
        p(Stat.INFO, f"Requests GET {url} -> {response.status_code} {response.url}")
        text = response.text
    except Exception as e:
        p(Stat.ERROR, f"Requests GET failed for {url}: {e}")
        return None

    # Save the first page HTML for manual inspection
    # save each page HTML to page_<n>.html for debugging
    m = re.search(r'page=(\d+)', url)
    page_num = m.group(1) if m else '0'
    try:
        with open(f'{base_directory}/page_{page_num}.html', 'w', encoding='utf-8') as f:
            f.write(text)
        p(Stat.INFO, f'Saved page_{page_num}.html for inspection.')
    except Exception:
        pass

    # Look for common bot-blocking markers on page 1
    if url.endswith('page=1'):
        bot_markers = [
            'Access Denied', 'are you a robot', 'Cloudflare', 'captcha', 'verify you are human',
            'unusual traffic', 'blocked', 'protection', 'challenge', 'bot detection', 'DDOS-GUARD',
            'Attention Required', 'Please enable cookies', 'security check', 'Incapsula', 'PerimeterX'
        ]
        found_markers = [marker for marker in bot_markers if marker.lower() in (text or '').lower()]
        if found_markers:
            p(Stat.WARNING, f"Warning: Possible bot-blocking detected on page 1: {', '.join(found_markers)}")

    # Use regex to extract window.searchResults JSON from <script> tag
    match = re.search(r'window\\.searchResults\\s*=\\s*({.*?})\\s*;</script>', text, re.DOTALL)
    if not match:
        p(Stat.ERROR, f"Could not find 'window.searchResults' in page: {url}")
        p(Stat.INFO, f"Extracted data (start): {text[:200]}")
        return None
    game_data_str = match.group(1)
    try:
        data = json.loads(game_data_str)
    except Exception as e:
        p(Stat.ERROR, f"Error parsing JSON from {url}: {e}")
        p(Stat.INFO, f"Extracted data (start): {game_data_str[:200]}")
        return None
    return data

def detect_max_pages(env: dict, base_url: str) -> int:
    """Try multiple strategies to detect the maximum number of pages for a listing.

    Strategies (in order):
    - requests: parse anchors containing "page=" and look for rel="last"/aria-label="Last"
    - playwright (if available): evaluate DOM to find page links
    - fallback: return a safe cap
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    p(Stat.INFO, f"Detecting max pages for URL: {base_url} using multiple strategies...")
    try:
        # Try lightweight requests first
        r = requests.get(base_url, headers=headers, timeout=15)
        text = r.text
        # look for rel="last" href
        m = re.search(r'<a[^>]+rel=["\']last["\'][^>]*href=["\']([^"\']+)["\']', text, re.IGNORECASE)
        if m:
            href = m.group(1)
            mm = re.search(r'[?&]page=(\d+)', href)
            if mm:
                return int(mm.group(1))

        # find all page=NN in hrefs and take max (ignore page=0)
        nums = [int(n) for n in re.findall(r'[?&]page=(\d+)', text)]
        nums = [n for n in nums if n > 0]
        if nums:
            return max(nums)

        # also try path-based pagination like /trending/2/ or /trending/page/2
        nums2 = [int(n) for n in re.findall(r'/page/(\d+)', text)] + [int(n) for n in re.findall(r'/trending/(\d+)/', text)]
        nums2 = [n for n in nums2 if n > 0]
        if nums2:
            return max(nums2)

        # aria-label or visible 'Last' text
        m2 = re.search(r'<a[^>]+aria-label=["\']?Last["\']?[^>]*href=["\']([^"\']+)["\']', text, re.IGNORECASE)
        if m2:
            href = m2.group(1)
            mm = re.search(r'[?&]page=(\d+)', href)
            if mm:
                return int(mm.group(1))
    except Exception as e:
        p(Stat.ERROR, f"Error occurred while detecting max pages: {e}")

    # If Playwright is available, use it to read rendered DOM (helps with client-side pagination)
    sync_playwright = env.get('sync_playwright') if env else None
    if sync_playwright is not None:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                page.goto(base_url, wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(1000)
                # evaluate anchors and collect hrefs + visible numbers (helps path-based pagination)
                hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a=>({href:a.href, text:a.textContent.trim()}))")
                candidates = []
                for entry in hrefs or []:
                    h = entry.get('href') if isinstance(entry, dict) else entry
                    t = entry.get('text') if isinstance(entry, dict) else ''
                    mm = re.search(r'[?&]page=(\d+)', h or '')
                    if mm:
                        n = int(mm.group(1))
                        if n > 0:
                            candidates.append(n)
                    # path based
                    mm2 = re.search(r'/page/(\d+)', h or '') or re.search(r'/trending/(\d+)/', h or '')
                    if mm2:
                        n = int(mm2.group(1))
                        if n > 0:
                            candidates.append(n)
                    # also consider numeric link text (visible page numbers)
                    if t and re.fullmatch(r'\d+', t):
                        n = int(t)
                        if n > 0:
                            candidates.append(n)
                if candidates:
                    browser.close()
                    return max(candidates)

                # try to find an element labelled 'Last' and extract its href
                js_last = "() => { const a = Array.from(document.querySelectorAll('a')).find(x=>/last/i.test(x.getAttribute('aria-label')||x.textContent)); return a? a.href: null }"
                last_href = page.evaluate(js_last)
                if last_href:
                    mm = re.search(r'[?&]page=(\d+)', last_href)
                    if mm:
                        browser.close()
                        return int(mm.group(1))

                # Try to detect total results like "Showing 1-25 of 5,500 results" and compute pages
                try:
                    txt = page.content()
                    mtot = re.search(r'of\s+([\d,]+)\s+results', txt, re.IGNORECASE)
                    if mtot:
                        total = int(mtot.group(1).replace(',', ''))
                        # try to infer per-page from number of item elements
                        per = 25
                        items = page.evaluate("() => document.querySelectorAll('.product, .product-item, .search-result-item, .game-item').length")
                        try:
                            if isinstance(items, int) and items > 0:
                                per = int(items)
                        except Exception:
                            pass
                        browser.close()
                        return (total + per - 1) // per
                except Exception as e:
                    p(Stat.ERROR, f"Error detecting total results for page count estimation: {e}")

                browser.close()
        except Exception as e:
            p(Stat.ERROR, f"Error occurred while using Playwright: {e}")

    # fallback: return a reasonable cap so caller can proceed (caller may choose to iterate further)
    return 100

def normalize(text: str) -> str:
    text = text.lower()
    
    # remove region tags and editions
    text = re.sub(r'(europe|eu|global|steam|deluxe edition|goty edition|edition)', '', text)
    
    # remove non-alphanumeric
    text = re.sub(r'[^a-z0-9 ]', '', text)
    
    # collapse spaces
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def make_game_key_from_obj(game: dict) -> str:
    """Create a stable unique key for a scraped game entry.

    Prefer explicit identifiers if present (id, sku, slug). Otherwise use normalized name
    combined with type to distinguish platform/edition variants.
    """
    # prefer explicit ids if present
    for key in ('id', 'appid', 'app_id', 'product_id', 'sku', 'slug'):
        val = game.get(key)
        if val:
            try:
                return f"{key}:{str(val)}"
            except Exception:
                pass

    name = game.get('name', '') or ''
    gtype = game.get('type') or game.get('platform') or ''
    # create compact normalized composite for name
    nname = normalize(name)
    # sanitize type/platform WITHOUT stripping platform keywords like 'steam' — keep tokens
    if gtype:
        if isinstance(gtype, (list, tuple)):
            gtype_str = ' '.join(map(str, gtype))
        else:
            gtype_str = str(gtype)
        ntype = re.sub(r'[^A-Za-z0-9 ]', '', gtype_str).lower().strip()
        ntype = re.sub(r'\s+', ' ', ntype)
    else:
        ntype = ''
    if ntype:
        return f"name:{nname}::type:{ntype}"
    return f"name:{nname}"

def fetch_pages_with_playwright(env: dict, base_url: str, pages: int = 10, nosleep: bool = False) -> dict:
    """Fixed Playwright pagination with proper timeouts, deduplication, and return value"""
    sync_playwright = env.get('sync_playwright')
    if sync_playwright is None:
        p(Stat.ERROR, "Playwright not available in env")
        return {}

    p(Stat.INFO, f"Using REAL URL pagination from: {base_url}")
    
    # Initialize games dict and seen_games set
    all_games = {}
    seen_games = set()
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1920,1080'
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            }
        )
        
        for i in range(1, pages + 1):
            page = context.new_page()
            p(Stat.INFO, f"Loading page {i}/{pages}")
            
            url = f"{base_url}?page={i}"
            
            try:
                # Navigate with timeout
                page.goto(url, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(3000)  # Give JS time to execute
                
                # Try multiple strategies to detect loaded content
                data_found = False
                try:
                    # Strategy 1: Wait for searchResults with hits
                    page.wait_for_function(
                        "() => !!(window.searchResults && window.searchResults.hits && window.searchResults.hits.length > 0)", 
                        timeout=10000
                    )
                    p(Stat.SUCCESS, f"Found searchResults on page {i}")
                    data_found = True
                except:
                    pass
                
                if not data_found:
                    try:
                        # Strategy 2: Wait for product elements
                        page.wait_for_selector('.product-item, .game-item, [data-product], .search-result-item', timeout=5000)
                        p(Stat.SUCCESS, f"Found product elements on page {i}")
                        data_found = True
                    except:
                        pass
                
                if not data_found:
                    p(Stat.WARNING, f"No clear content markers on page {i}, trying extraction anyway")
                
                # Extract data with multiple fallback methods
                js_data = None
                try:
                    js_data = page.evaluate('() => window.searchResults')
                except Exception as e:
                    p(Stat.WARNING, f"Page {i} JS evaluation failed: {e}")
                
                if js_data and isinstance(js_data, dict) and js_data.get('hits'):
                    hits = js_data['hits']
                    new_count = 0
                    
                    # Process each game and deduplicate
                    for game in hits:
                        name = game.get('name', f'Unknown_{i}')

                        # create a stable unique key for this entry so that variants/platforms
                        # with the same display name are not overwritten
                        key = make_game_key_from_obj(game)

                        # Skip if we've already seen this exact entry
                        if key in seen_games:
                            continue
                        seen_games.add(key)

                        # store under composite key, keep display name for printing
                        all_games[key] = {
                            "display_name": name,
                            "original_price": game.get("default_retail", "N/A"),
                            "price": game.get("price_eur", "N/A"),
                            "discount": game.get("discount", "N/A"),
                            "type": game.get("type", "N/A"),
                            # keep raw entry for debugging if needed
                            "_raw": game
                        }
                        new_count += 1
                    
                    if new_count > 0:
                        p(Stat.SUCCESS, f"Page {i}: {len(hits)} total, {new_count} NEW games")
                        printl(f"\n{'='*95}")
                        printl(f"     PAGE {i} - TOP DEALS ({new_count} NEW GAMES)")
                        printl(f"{'='*95}")
                        print_games_from_search_results(js_data, nosleep)
                    else:
                        p(Stat.WARNING, f"Page {i}: No new games (all duplicates)")
                else:
                    p(Stat.WARNING, f"Page {i}: Empty or invalid searchResults")
                
                # Debug screenshot every 5th page
                if i % 5 == 0:
                    try:
                        page.screenshot(path=f'debug_screenshots/debug_page_{i}.png')
                        p(Stat.INFO, f"Saved debug screenshot: debug_screenshots/debug_page_{i}.png")
                    except:
                        pass
                        
            except Exception as e:
                p(Stat.ERROR, f"Page {i} navigation failed: {e}")
            
            page.close()
            
            # Rate limiting and early exit
            if i > 5 and len(seen_games) == 0:
                p(Stat.INFO, "No content found in first few pages, stopping early")
                break
            if i % 5 == 0:
                p(Stat.INFO, "⏸ Rate limiting pause...")
                time.sleep(1)
        
        browser.close()
    
    p(Stat.SUCCESS, f"Playwright complete! Total unique games: {len(all_games)}")
    return all_games

def compare_with_wishlist(p_all_games: dict, wishlist_input: str = None, sort_by: str = 'discount') -> dict:
    if wishlist_input is not None:
        try:
            wishlist_items = []
            if isinstance(wishlist_input, str):
                wishlist_items = wishlist_input.split(",")
            elif isinstance(wishlist_input, list):
                wishlist_items = wishlist_input
            else:
                p(Stat.ERROR, f"Invalid wishlist input type: {platform_type(wishlist_input)}. Expected str or list.")
        except Exception as e:
            p(Stat.ERROR, f"Error parsing wishlist input: {e}")
            wishlist_items = []
    else:
        try:
            with open('wishlist.txt', 'r', encoding='utf-8') as f:
                wishlist_items = f.read().split(",")
        except Exception as e:
            p(Stat.ERROR, f"Error reading wishlist file: {e}")
            wishlist_items = []
    printl("Wishlist Items detected:", len(wishlist_items))

    # keep both original and normalized forms
    wishlist_pairs = []
    for game_name in wishlist_items:
        orig = game_name.strip()
        norm = normalize(game_name)
        if orig:
            wishlist_pairs.append({'orig': orig, 'norm': norm})

    if wishlist_pairs:
        printl(f"\n{'='*95}")
        printl(f"     YOUR WISHLIST ITEMS")
        printl(f"{'='*95}")

        unfound_games = []
        database_normalized = {}

        final_data = {} # stores matched wishlist items with their price/discount info for potential future use (e.g. saving to file, further analysis, etc.)

        # Delegate fuzzy-evaluation and acceptance to matcher.find_best_match
        for pair in wishlist_pairs:
            item_norm = pair['norm']
            item_orig = pair['orig']

            result = matcher.find_best_match(item_norm, p_all_games, match_debug=MATCH_DEBUG)
            accept = result.get('accept', False)
            best_info = result.get('best_info')
            best_db_name = result.get('best_db_name')
            best_score = result.get('best_score', 0)
            score_set = result.get('score_set', 0)
            score_partial = result.get('score_partial', 0)
            score_sort = result.get('score_sort', 0)

            FGNL: int = 42 # Formatting Game Name Length

            # If debug mode enabled, print top candidate scores for this wishlist item
            try:
                if MATCH_DEBUG == MatchDebug.All or ( MATCH_DEBUG == MatchDebug.Listed and item_orig in debug_items):
                    p(Stat.INFO, f"Top candidates for '{item_orig}':")
                    for c in result.get('candidates', [])[:6]:
                        p(Stat.INFO, f"  {c[4][:60]:<60} -> bst={c[0]:5.1f} set={c[1]:3} prt={c[2]:3} srt={c[3]:3}")
            except Exception:
                pass

            if accept and best_info is not None:
                info = best_info
                p(Stat.SUCCESS, f"Found match: {item_orig[:FGNL]:<{FGNL}} -> {best_db_name[:FGNL]:<{FGNL}} (set={score_set:<3} prt={score_partial:<3} srt={score_sort:<3} bst={best_score:<3}   Discount: {info.get('discount', 'N/A')})")
            else:
                p(Stat.WARNING, f"No match:    {item_orig[:FGNL]:<{FGNL}}  > {(best_db_name[:FGNL] if best_db_name else 'N/A'):<{FGNL}} (best={best_score:<3} set={score_set:<3} prt={score_partial:<3} srt={score_sort:<3})")
                unfound_games.append(item_orig)
                continue

            discount = info.get('discount', 'N/A')
            price = info.get('price', 'N/A')
            original_price = info.get('original_price', 'N/A')
            orig_str = f"{original_price:>6}" if original_price is not None else "\033[90m  N/A \033[0m"
            platform_type = info.get('type', 'N/A')
            # detect likely DLC/expansion
            is_dlc = bool(info.get("is_dlc")) or None
            # store score and dlc flag
            final_data[item_orig] = {
                'discount': discount,
                'price': price,
                'original_price': original_price.strip() if isinstance(original_price, str) else original_price,
                'platform_type': platform_type,
                'dlc': is_dlc,
                'store_registry_name': best_db_name,
                'score': int(best_score)
                }
        p(Stat.INFO, f"Wishlist comparison complete! {len(wishlist_pairs) - len(unfound_games)} items found, {len(unfound_games)} items not found.")
        printl()
        # print final_data sorted by requested mode (discount or price)
        def safe_price_value(item):
            info = item[1] if isinstance(item, tuple) else item
            pval = info.get('price', None)
            try:
                if pval is None:
                    return float('inf')
                if isinstance(pval, (int, float)):
                    return float(pval)
                s = str(pval).strip()
                if s.lower() in ('n/a', ''):
                    return float('inf')
                s = s.replace(',', '.')
                # remove euro sign if present
                s = re.sub(r'[^0-9\.]', '', s)
                return float(s) if s else float('inf')
            except Exception:
                return float('inf')

        if sort_by == 'price':
            sorted_final = sorted(final_data.items(), key=safe_price_value)
        else:
            sorted_final = sorted(final_data.items(), key=lambda x: x[1]['discount'], reverse=True)
        for idx, x in enumerate(sorted_final):
            item = x[0]
            info = x[1]
            discount = info.get('discount', 'N/A')
            price = info.get('price', 'N/A')
            original_price = info.get('original_price', 'N/A')
            orig_str = f"{original_price:>5}" if original_price is not None else "\033[90m N/A \033[0m"
            platform_type = info.get('platform_type', 'N/A')
            dlc_tag = ' DLC ' if info.get('dlc') else '     '
            score_str = f"{info.get('score', 0)}%"
            
            # add seperative lines between discount levels for better readability
            if idx > 0 and isinstance(discount, (int, float)) and isinstance(sorted_final[idx-1][1]['discount'], (int, float)):
                prev_discount = sorted_final[idx-1][1]['discount']
                # Print separator when crossing into a lower tier (descending order)
                if   prev_discount >= 100 and discount < 100: printl(f"{' '*48}100 - 90\n{'='*105}")
                elif prev_discount >=  90 and discount <  90: printl(f"{' '*48 }90 - 75\n{'='*105}")
                elif prev_discount >=  75 and discount <  75: printl(f"{' '*48 }75 - 60\n{'='*105}")
                elif prev_discount >=  60 and discount <  60: printl(f"{' '*48 }60 - 45\n{'='*105}")
                elif prev_discount >=  45 and discount <  45: printl(f"{' '*48 }45 - 20\n{'='*105}")
                elif prev_discount >=  20 and discount <  20: printl(f"{' '*48 }20 - 0\n{ '='*105}")

            price_str = f"{price:>5}€" if str(price) != "1.00" else "\033[95m 1.00€\033[0m"

            display_name = info.get('store_registry_name') or "[ERROR]"
            match int(score_str[:-1]): # cut off the percennt sign for coloring
                case score if score >= 99:
                    score_color = "\033[32m"  # dark green for 99%+
                case score if score >= 90:
                    score_color = "\033[92m"  # bright green for 90%+
                case score if score >= 85:
                    score_color = "\033[33m"  # yellow for 85%+
                case score if score >= 75:
                    score_color = "\033[31m"  # red for 75%+
                case _:
                    score_color = "\033[0m"   # default color for below 60%
            platform_str = (
                ", ".join(platform_type)
                if isinstance(platform_type, list)
                else (platform_type or "N/A")
            )

            wishlist_name = str(item)[:48]
            matched_name = str(display_name)[:48]

            # print table
            line = (
                f"{wishlist_name:<50} "
                f"- {score_color}{score_str:>4}\033[0m ->  "
                f"{matched_name:<50} | "
                f"{discount:>6}% "
                f'{" "*5}'
                f"\033[90m{orig_str}\033[0m  ->  "
                f"{price_str} "
                f"{dlc_tag} "
                f"{platform_str}"
            )

            printl(line)


        if unfound_games:
            printl(f"\n{'='*105}")
            printl(f"     UNFOUND WISHLIST ITEMS")
            printl(f"{'='*105}")
            for item in unfound_games:
                printl(item)
        print_price_classes()
    else:
        p(Stat.INFO, "No wishlist items selected.")

def compare_games_lists(games1: dict, games2: dict) -> dict:
    """Compare two game dictionaries and return a dict of games that are in games1 but not in games2, along with their price/discount info from games1."""
    unique_games = {}
    # games keys may be composite (name+type or id), so compare by display_name when necessary
    games2_display_names = {v.get('display_name') if isinstance(v, dict) else None for v in games2.values()} if isinstance(games2, dict) else set()
    for key, info in games1.items():
        if isinstance(info, dict):
            display = info.get('display_name')
        else:
            display = key

        # if exact key missing and display name is present in other set, consider it duplicate
        if key not in games2 and display not in games2_display_names:
            unique_games[key] = info
    return unique_games

def scrapce_non_steam(p_page_count, env, url=BASE_URL_NON_STEAM, save_to_file=True, nosleep: bool = False) -> dict:
    non_steam_games = fetch_pages_with_playwright(env, url, pages=p_page_count, nosleep=nosleep)
    # Save non-steam games to file for inspection
    if save_to_file:
        p(Stat.INFO, f"Fetched {len(non_steam_games)} non-steam games. Saving to file...")
        try:
            with open('non_steam_games.json', 'w', encoding='utf-8') as f:
                json.dump(non_steam_games, f, indent=2)
            p(Stat.INFO, "Saved non-steam games to non_steam_games.json for inspection.")
        except Exception as e:
            p(Stat.ERROR, f"Could not save non-steam games to file: {e}")
    else:
        p(Stat.INFO, f"Fetched {len(non_steam_games)} non-steam games.")
    
    return non_steam_games

def print_price_classes():
    repres: str = f"\033[95m[ 0€ ]\033[0m  -  \033[35m[ 1€ ]\033[0m  -  \033[31m[ 5€ ]\033[0m  -  \033[33m[ 15€ ]\033[0m  -  \033[32m[ 15€+ ]\033[0m"
    title = " -= Price Classes =- "

    spacing = int(visible_length(repres) / 2 - len(title) / 2)

    printl(f"\n{' ' * spacing}{title}")
    printl(repres)

def eval_page_count(
        env,
        page_count: int | None = None,
        flags: list[ str ] = [],
        url: str = BASE_URL
        ) -> int:
    if "--all" in flags or "-a" in flags:
        p(Stat.INFO, "[Found flag in arguments]: --all (scrape all pages)")
        page_count = 0
    if page_count is None:
        try:
            page_count = ip.text("How many pages to scrape?", default="10", validate=lambda x: x.isdigit(), invalid_message="Please enter a integer").execute()
            page_count = int(page_count)
        except Exception as e:
            p(Stat.ERROR, f"Input error: {e}. Defaulting to 10 pages.")
            page_count = 10

    if page_count > 20:
        if not ip.confirm(f"You entered {page_count} pages. This may take a long time and could trigger anti-bot measures. Are you sure?", default=False).execute():
            p(Stat.INFO, "Aborting per user request.")
            exit(0)
    elif page_count < 1:
        cont = None
        if skip_confirmation:
            p(Stat.INFO, "[Found flag in arguments]: --confirm / -y (skip confirmation for scraping all pages)")
            cont = True
        elif ip.confirm(f"You entered {page_count} pages. Selection of 0 or less pages leads to all pages being scraped, which may take a very long time.\nAre you sure you want to proceed scraping ALL pages?", default=False).execute():
            cont = True
        if cont:
            p(Stat.INFO, "Proceeding to scrape all pages. This may take a very long time and could trigger anti-bot measures.")
            # detect max amount of pages automatically
            try:
                detected = detect_max_pages(env, url)
                if detected and isinstance(detected, int) and detected > 0:
                    page_count = detected
                    p(Stat.SUCCESS, f"Detected maximum pages: {page_count}")
                else:
                    p(Stat.ERROR, "Could not detect max pages, defaulting to 10 pages.")
                    page_count = 10
            except Exception as e:
                p(Stat.ERROR, f"Auto-detection failed: {e}. Defaulting to 10 pages.")
                page_count = 10
        
    return page_count

if __name__ == "__main__":

    # setup logger
    logger = getLogger('logger')

    if not logger.hasHandlers():
        os.makedirs('logs', exist_ok=True)
        handler = FileHandler('logs/log.log', encoding='utf-8')
        handler.setFormatter(Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(INFO)

    # detect console arguments for quick settings
    bool_compare_with_wishlist = None
    page_count = None
    print_games = False
    save_json = False
    load_data_from_json = False
    scrape_non_steam = None
    input_wishlist_terminal = False
    wishlist_input = None
    bool_no_sleep = False
    skip_confirmation = False
    clear_log_on_start = True
    bool_scrape_wishlist = False
    compare_sort = 'discount'
    MATCH_DEBUG = MatchDebug.None_

    if len(sys.argv) > 1:
        if "--help" in sys.argv or "-h" in sys.argv:
            printl("Usage: python main.py [options]\n")
            printl("Options:")
            printl("  --wishlist          / -w    Compare scraped games with wishlist.txt")
            printl("  --wishlist-terminal / -wt   Compare scraped games with wishlist input directly in terminal (comma-separated)")
            printl("  --scrape-wishlist   / -sw   [EXPERIMENTAL] Automatically fetch user wishlist data. Supports username argument: -sw=<username>")
            printl("  --all               / -a    Scrape all pages (default is to ask for page count)")
            printl("  --print             / -p    Print scraped games to console (default)")
            printl("  --no-print          / -np   Do not print scraped games to console")
            printl("  --save              / -s    Save scraped data to games.json")
            printl("  --load              / -l    Load scraped data from games.json instead of scraping")
            printl("  --scrape-non-steam  / -sn   Scrape non-steam games from Instant Gaming (experimental)")
            printl("  --no-non-steam      / -ns   Do not scrape non-steam games")
            printl("  --nosleep           / -nosl Disable sleep between page requests (not recommended)")
            printl("  --confirm           / -y    Skip confirmation prompts (use with caution)")
            printl("  --sort-by-price     / -sp   Sort wishlist comparison results by price instead of discount")
            printl("\n"+"-"*20+" Debug Options "+"-"*20,end="\n\n")
            printl("  --no-clear-log      / -nc   Do not clear console on start (default is to clear)")
            printl("  --debug-match       / -dm   Print top fuzzy candidates for wishlist items (for debugging matching accuracy)")
            printl("  --no-debug-match    / -ndm  Do not print fuzzy candidates for wishlist items (default)")
            printl("  --debug-match-listed / -dml Print fuzzy candidates for wishlist items that were accepted (subset of -dm)")
            printl("\n"+"-"*20+" Preset Options "+"-"*20,end="\n\n")
            printl("  --preset1           / -p1   Load data from JSON, scrape all pages, include non-steam games, no sleep between requests, skip confirmations, compare with wishlist (for quick testing)")
            printl("  --preset2           / -p2   Scrape all data, include non-steam games, no sleep between requests, skip confirmations, compare with wishlist")
            print("\n")
            exit(0)

        if "--wishlist" in sys.argv or "-w" in sys.argv:
            p(Stat.INFO, "[Found flag in arguemnts]: --wishlist / -w")
            bool_compare_with_wishlist = True
        if "--wishlist-terminal" in sys.argv or "-wt" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --wishlist-terminal / -wt")
            bool_compare_with_wishlist = True
            input_wishlist_terminal = True
            
        wishlist_username = None

        for i, arg in enumerate(sys.argv):
            if arg.startswith("--scrape-wishlist="):
                wishlist_username = arg.split("=", 1)[1]
                bool_scrape_wishlist = True

            elif arg.startswith("-sw="):
                wishlist_username = arg.split("=", 1)[1]
                bool_scrape_wishlist = True

            elif arg == "-sw" or arg == "--scrape-wishlist":
                bool_scrape_wishlist = True
                if i + 1 < len(sys.argv):
                    wishlist_username = sys.argv[i + 1]

        if "--sort-by-price" in sys.argv or "-sp" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --sort-by-price / -sp")
            compare_sort = 'price'

        elif "--no-wishlist" in sys.argv or "-nw" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --no-wishlist / -nw")
            bool_compare_with_wishlist = False
        
        if "--all" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --all (scrape all pages)")
            page_count = 0

        if "--print" in sys.argv or "-p" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --print / -p")
            print_games = True
        elif "--no-print" in sys.argv or "-np" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --no-print / -np")

            print_games = False

        if "--save" in sys.argv or "-s" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --save (will save scraped data to games.json)")
            save_json = True
        
        if "--load" in sys.argv or "-l" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --load / -l")
            load_data_from_json = True
        
        if "--scrape-non-steam" in sys.argv or "-sn" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --scrape-non-steam (will scrape non-steam games from Instant Gaming)")
            scrape_non_steam = True
        elif "--no-non-steam" in sys.argv or "-ns" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --no-non-steam (will NOT scrape non-steam games from Instant Gaming)")
            scrape_non_steam = False
        
        if "--nosleep" in sys.argv or "--no-sleep" in sys.argv or "-nosl" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --nosleep (will disable sleep between page requests)")
            bool_no_sleep = True

        if "--confirm" in sys.argv or "-y" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --confirm (will skip confirmation prompts)")
            skip_confirmation = True
        if "--debug-match" in sys.argv or "-dm" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --debug-match (will print top fuzzy candidates for wishlist items)")
            MATCH_DEBUG = MatchDebug.All
        elif "--no-debug-match" in sys.argv or "-ndm" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --no-debug-match (will NOT print fuzzy candidates for wishlist items)")
            MATCH_DEBUG = MatchDebug.None_
        elif "--debug-match-listed" in sys.argv or "-dml" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --debug-match-listed (will print fuzzy candidates for wishlist items that were accepted)")
            MATCH_DEBUG = MatchDebug.Listed

        if input_wishlist_terminal:
            try:
                wishlist_input = ip.text("Enter your wishlist items separated by commas:").execute()
                with open('wishlist.txt', 'w', encoding='utf-8') as f:
                    f.write(wishlist_input)
                p(Stat.SUCCESS, "Wishlist saved to wishlist.txt")
            except Exception as e:
                p(Stat.ERROR, f"Input error: {e}. Cannot proceed with wishlist comparison.")
                wishlist_input = ""
        elif bool_scrape_wishlist:
            p(Stat.INFO, "Fetching wishlist items via playwright now")
            try:
                from scrape_wishlist_exporter import get_wishlist_items_playwright
                if wishlist_username == None:
                    wishlist_username = ip.text("Enter username").execute()
                try:
                    wishlist_items = get_wishlist_items_playwright(wishlist_username)
                except Exception as e:
                    raise( e )
                with open('wishlist.txt', 'w', encoding='utf-8') as f:
                    f.write(",".join(wishlist_items))
            except Exception as e:
                p(Stat.ERROR, f"Error: {e}. Cannot proceed with wishlist comparison.")
                wishlist_input = ""
        
        if "--no-clear-log" in sys.argv or "-nc" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --no-clear-log / -nc (will NOT clear console on start)")
            clear_log_on_start = False
        
        if "--preset1" in sys.argv or "-p1" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --preset1 (-l -a -sn --nosleep -y -w)")
            load_data_from_json = True
            page_count = 0
            scrape_non_steam = True
            bool_no_sleep = True
            skip_confirmation = True
            bool_compare_with_wishlist = True
        
        if "--preset2" in sys.argv or "-p2" in sys.argv:
            p(Stat.INFO, "[Found flag in arguments]: --preset2 (-a -sn --nosleep -y -w)")
            load_data_from_json = False
            page_count = 0
            scrape_non_steam = True
            bool_no_sleep = True
            skip_confirmation = True
            bool_compare_with_wishlist = True

    if clear_log_on_start:
        printl("\033c", end="")
        # find and clear log file if exists
        log_file = "logs/log.log"
        if os.path.exists(log_file):
            try:
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.write("")
                p(Stat.INFO, "Cleared log file on start.")
            except Exception as e:
                p(Stat.ERROR, f"Could not clear log file: {e}")

    if MATCH_DEBUG == MatchDebug.Listed:
        # ask user for games to debug match for, comma-separated
        try:
            debug_input = ip.text("Enter wishlist items to debug matching for (comma-separated, leave blank for all):").execute()
            debug_items = [x.strip() for x in debug_input.split(",") if x.strip()]
            if debug_items:
                p(Stat.INFO, f"Debugging matches for: {', '.join(debug_items)}")
                MATCH_DEBUG = MatchDebug.Listed
            else:
                p(Stat.INFO, "No specific items entered, will debug all wishlist items.")
                MATCH_DEBUG = MatchDebug.All
        except Exception as e:
            p(Stat.ERROR, f"Input error: {e}. Will debug all wishlist items.")
            MATCH_DEBUG = MatchDebug.All

    if not load_data_from_json:
        p(Stat.INFO, "Starting Instant Gaming Scraper...")
        env = init_fetcher()

        if scrape_non_steam is None:
            if skip_confirmation:
                scrape_non_steam = False
                p(Stat.INFO, "Skipping confirmation prompts, defaulting to NOT scrape non-steam games.")
            else:
                scrape_non_steam = ip.confirm("Do you want to scrape non-steam games from Instant Gaming as well? (experimental)", default=False).execute()
        if scrape_non_steam:
            p(Stat.INFO, "Scraping non-steam games from Instant Gaming...")
            chosen_rul = BASE_URL_NON_STEAM
        else:
            chosen_rul = BASE_URL


        # get max amount of pages to scrape from user input (default 10) using inquirerPy, with validation and error handling
        page_count = eval_page_count(env, page_count, flags=sys.argv)
        
        
        if env.get('sync_playwright') is not None:
            p(Stat.INFO, f"Using Playwright with FIXED pagination - scraping {page_count} pages")
            all_games = fetch_pages_with_playwright(env, chosen_rul, pages=page_count, nosleep=bool_no_sleep)
        else:
            p(Stat.WARNING, "Playwright not available. Install with: pip install playwright && playwright install chromium")
            p(Stat.INFO, "Falling back to Selenium...")
            
            all_games = {}
            for i in range(1, page_count + 1):
                p(Stat.INFO, f"Processing page {i}/{page_count} with Selenium")
                url = f"{chosen_rul}?page={i}"
                data = get_search_results_with_selenium(url, env=env)
                
                if data and data.get('hits'):
                    p(Stat.SUCCESS, f"Page {i}: {len(data['hits'])} games")
                    printl(f"\n{'='*95}")
                    printl(f"     PAGE {i} - TOP DEALS ({len(data['hits'])} GAMES)")
                    printl(f"{'='*95}")
                    games = print_games_from_search_results(data, bool_no_sleep)
                    all_games.update(games)
                else:
                    p(Stat.WARNING, f"Page {i} failed/empty - stopping")
                    break
            
            p(Stat.SUCCESS, f"COMPLETE! Scraped {len(all_games)} unique games across {len(set([v['discount'] for v in all_games.values()]))} discount levels")

        if save_json:
            try:
                if skip_confirmation:
                    conf = True
                else:
                    conf = ip.confirm("Save results to games.json?", default=True).execute()
                if conf:
                    # check if a games.json already exists, and if so ask user if they want a comparision
                    if os.path.exists('games.json'):
                        try:
                            with open('games.json', 'r', encoding='utf-8') as f:
                                existing_games = json.load(f)

                            if skip_confirmation:
                                conf = True
                            else:
                                conf = ip.confirm("Do you want to compare the new scraped data with the existing games.json?", default=True).execute()
                            if conf:
                                comp_data = compare_games_lists(existing_games, all_games)
                                for i in comp_data:
                                    printl(f"New game found: {i} - {comp_data[i]}")
                        except Exception as e:
                            p(Stat.ERROR, f"Failed to load existing games.json for comparison: {e}")


                    with open('games.json', 'w', encoding='utf-8') as f:
                        json.dump(all_games, f, indent=4)
                    p(Stat.SUCCESS, "Saved games.json successfully!")
            except Exception as e:
                p(Stat.ERROR, f"Input prompt failed: {e}")
    else:
        try:
            with open('games.json', 'r', encoding='utf-8') as f:
                all_games = json.load(f)
            p(Stat.SUCCESS, f"Loaded {len(all_games)} games from games.json")
        except Exception as e:
            p(Stat.ERROR, f"Failed to load games.json: {e}")
            all_games = {}

    cnt = False
    if print_games:
        cnt = True
    elif print_games == False:
        cnt = False
    elif print_games is None:
        if skip_confirmation:
            conf = True
        else:
            conf = ip.confirm("Do you want to print the scraped games to console?", default=True).execute()
        cnt = conf
    else: raise ValueError("Invalid value for print_games")


    if cnt:
        def safe_discount_value(item):
            # item is a tuple (name, info_dict) or info_dict depending on caller
            info = item[1] if isinstance(item, tuple) else item
            d = info.get('discount', 0)
            try:
                if d is None:
                    return 0
                if isinstance(d, (int, float)):
                    return int(d)
                s = str(d).strip()
                if s.lower() in ('n/a', ''):
                    return 0
                if s.endswith('%'):
                    s = s[:-1]
                s = s.replace(',', '.')
                return int(float(s))
            except Exception:
                return 0

        sorted_games = sorted(all_games.items(), key=safe_discount_value, reverse=True)
        printl(f"\n{'='*95}")
        printl(f"     TOP GAMES BY DISCOUNT")
        printl(f"{'='*95}")
        for name, info in sorted_games[:500]:
            discount = info.get('discount', 'N/A')
            price = info.get('price', 'N/A')
            original_price = info.get('original_price', 'N/A')
            printl(f"{name[:48]:<50} - {discount:>6}% off -  {price:>6}€   ( {original_price:>6}€ )")
        
    cnt = False
    if bool_compare_with_wishlist:
        cnt = True
    elif bool_compare_with_wishlist is None:
        if skip_confirmation:
            conf = True
        else:
            conf = ip.confirm("Do you want to compare with your wishlist items?").execute()
        cnt = conf
    else: p(Stat.INFO, "Skipping wishlist comparison per user settings.")
        
    if cnt:
        compare_with_wishlist(all_games, wishlist_input if input_wishlist_terminal else None, sort_by=compare_sort)