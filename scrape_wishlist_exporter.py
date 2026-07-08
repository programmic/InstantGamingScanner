# scrape_wishlist_exporter.py

import sys
import re
from env_get import *


def find_all_regrex(data: str, regex: str) -> list[str]:
    hits: list[str] = []

    for match in re.finditer(regex, data):
        hits.append(match.group(0))

    return hits
    

def get_wishlist_items_playwright(username: str, get_appid: bool = False, quiet: bool = False) -> list[str]:
    p(Stat.INFO, f"Fetching wishlist items for user{username}")
    env = init_fetcher()
    
    sync_playwright = env.get('sync_playwright')
    
    if sync_playwright is None:
        p(Stat.ERROR, "Playwright not availible in env")
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=
            [
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
        
        page = context.new_page()
        
        url = f"https://www.steamwishlistcalculator.com/wishlist/{username}"
        
        # try load page
        
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        page.wait_for_timeout(3000)
        
        data_found = False
        
        try:
            html = page.content()
        except Exception as e:
            raise ("Error:", e)
        
        game_ids = find_all_regrex(html, r'title="[^"]*" target="_blank">[^"]*</a>')
        del game_ids[-5:]
        
        
        items = []

        for game in game_ids:
            game = game.split(' target="_blank">')[0]
            game = game[7:-1]
            items.append(game)

        p(Stat.SUCCESS, f"Successfully fetched{len(items)}item names")
        return items
            
       