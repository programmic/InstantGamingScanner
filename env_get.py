from enum import Enum
import os
from logging import getLogger, FileHandler, Formatter, INFO, ERROR

# enum list of status indicators for messages
class Stat(Enum):
    INFO = 1
    SUCCESS = 2
    WARNING = 3
    ERROR = 4


def printl(*messages: object, end='\n', sep=' ', flush=True, file=None, log=True) -> None:
    print(*messages, end=end, sep=sep, flush=flush, file=file)
    if log:
        logger = getLogger('logger')
        if not logger.hasHandlers():
            os.makedirs('logs', exist_ok=True)
            handler = FileHandler('logs/log.log', encoding='utf-8')
            handler.setFormatter(Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(handler)
            logger.setLevel(INFO)
        logger.info(sep.join(str(msg) for msg in messages))

def p(status: Stat, message: str) -> None:
    if status == Stat.INFO:
        printl(f"\033[34m[?]\033[0m {message}")
    elif status == Stat.SUCCESS:
        printl(f"\033[32m[*]\033[0m {message}")
    elif status == Stat.WARNING:
        printl(f"\033[33m[!]\033[0m {message}")
    elif status == Stat.ERROR:
        printl(f"\033[31m[#]\033[0m {message}")


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
