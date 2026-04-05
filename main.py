from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import shutil
import os
import re
import requests
import json
import time
import subprocess
from selenium.webdriver.support.ui import WebDriverWait
from enum import Enum

print("\033c",end="")

# enum list of status indicators for messages
class Stat(Enum):
    INFO = 1
    SUCCESS = 2
    WARNING = 3
    ERROR = 4

def p(status: Stat, message: str) -> None:
    if status == Stat.INFO:
        print(f"\033[34m[?]\033[0m {message}")
    elif status == Stat.SUCCESS:
        print(f"\033[32m[*]\033[0m {message}")
    elif status == Stat.WARNING:
        print(f"\033[33m[!]\033[0m {message}")
    elif status == Stat.ERROR:
        print(f"\033[31m[#]\033[0m {message}")


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
            profile_dir = os.path.join(os.getcwd(), 'uc_profile')
            uc_options.add_argument(f"--user-data-dir={profile_dir}")
            driver = uc.Chrome(options=uc_options)
            p(Stat.SUCCESS, "undetected_chromedriver (uc) started successfully")
            try:
                driver.get(url)
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
                        ct = r.headers.get('content-type', '')
                        if r.request.resource_type == 'xhr' or 'application/json' in ct or '/search' in r.url or '/api/' in r.url:
                            responses.append(r)
                    except Exception:
                        pass
                page.on('response', _on_response)
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                try:
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


def init_fetcher() -> dict:
    """Detect available backends and binary paths once at startup.
    Returns an env dict used by get_search_results_with_selenium to avoid repeated checks.
    """
    env = {}
    try:
        import undetected_chromedriver as uc
        env['uc'] = uc
        p(Stat.INFO, "undetected_chromedriver available")
    except Exception:
        env['uc'] = None
        p(Stat.WARNING, "undetected_chromedriver not available")
    try:
        from playwright.sync_api import sync_playwright
        env['sync_playwright'] = sync_playwright
        p(Stat.INFO, "playwright available")
    except Exception:
        env['sync_playwright'] = None
        p(Stat.WARNING, "playwright not available")

    chrome_base = r'C:\Users\Simon\Documents\Python\InstantGamingScanner\chrome-win64'
    chrome_path1 = os.path.join(chrome_base, 'chrome.exe')
    chrome_path2 = os.path.join(chrome_base, 'chrome-win64', 'chrome.exe')
    env['chrome_path1'] = chrome_path1 if os.path.exists(chrome_path1) else None
    env['chrome_path2'] = chrome_path2 if os.path.exists(chrome_path2) else None
    if env['chrome_path1']:
        p(Stat.SUCCESS, f"Found chrome.exe at: {env['chrome_path1']}")
    elif env['chrome_path2']:
        p(Stat.SUCCESS, f"Found chrome.exe at: {env['chrome_path2']}")
    else:
        p(Stat.WARNING, f"chrome.exe not found in expected locations")

    chromedriver_path = r'C:\Users\Simon\Documents\Python\InstantGamingScanner\chromedriver\chromedriver.exe'
    env['chromedriver_path'] = chromedriver_path if os.path.exists(chromedriver_path) else None
    if env['chromedriver_path']:
        p(Stat.SUCCESS, f"Found chromedriver.exe at: {env['chromedriver_path']}")
    else:
        p(Stat.WARNING, f"chromedriver.exe not found at {chromedriver_path}")

    return env

# scrape instant-gaming.com for game prices and discounts


def print_games_from_search_results(data):
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
                return "\033[36m"  
            elif p < 5:
                return "\033[32m"
            elif p < 10:
                return "\033[33m"
            else:
                return "\033[90m"
        except Exception:
            return "\033[0m"
    
    GTL: int = 45 # Game title length

    print(f"% | €  {'Game Name':<{GTL}} {'Original Price':<11}  {'Price':<8} {'Discount (%)'}")
    print("-" * 95)

    games = {}

    for game in data.get("hits", []):
        name = game.get("name", "Unknown")
        original_price = game.get("default_retail", "N/A")
        price = game.get("price_eur", "N/A")
        discount = game.get("discount", "N/A")
        discount_color = get_discount_class(discount)
        price_color = get_price_class(price)
        discount_price = f"{price.split('.')[0][:3]:>3},{price.split('.')[1][:2]:>2}" if price != "N/A" else "N/A"
        original_price = f"{original_price.split('.')[0][:3]:>3},{original_price.split('.')[1][:2]:>2}" if original_price != "N/A" else "N/A"
        if len(name[:GTL]) % 2 == 0:
            name_str = f"{name[:GTL-2]:<{GTL}}".replace("  ", " .") + "  " # replace double spaces with dot for better visibility of spacing
        else:
            name_str = f"{name[:GTL-2]:<{GTL}}".replace("  ", ". ") + "  " # replace double spaces with dot for better visibility of spacing

        games[name] = {
            "original_price": original_price,
            "price": discount_price,
            "discount": discount
        }

        print(f"{discount_color}%\033[0m | {price_color}€\033[0m  {name_str} {original_price}{' '*6}{discount_price}   {discount:>4}%")

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

BASE_URL: str = "https://www.instant-gaming.com/en/pc/steam/trending/?page="
BASE_DIRECTORY: str = os.getcwd() + "/tmp_html"  # current working directory for saving HTML files

if __name__ == "__main__":
    # detect available backends once
    env = init_fetcher()
    # choose processing method once, in order of preference
    if env.get('uc') is not None:
        chosen = ProcessType.SELENIUM
        p(Stat.INFO, "Using undetected_chromedriver (Selenium) for all pages")
    elif env.get('sync_playwright') is not None:
        chosen = ProcessType.PLAYWRIGHT
        p(Stat.INFO, "Using Playwright for all pages")
    else:
        chosen = ProcessType.REQUESTS
        p(Stat.INFO, "Falling back to requests for all pages")

    games: dict = {}
    for i in range(1, 11):
        # Force requests for pagination to avoid renderer returning cached/identical JS state
        cache_bust = int(time.time() * 1000)
        url = BASE_URL + str(i) + f"&_cb={cache_bust}"
        data = process_site(url, chosen, env=env, base_directory=BASE_DIRECTORY)


        if data:
            print(f"\nPage {i} results:")
            games.update(print_games_from_search_results(data))
        else:
            p(Stat.ERROR, f"Failed to process page {i}")