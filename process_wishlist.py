from bs4 import BeautifulSoup
import json
import re

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


with open("my_wishlist.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

def is_real_game(name):
    """Filter out non-games"""
    name = name.strip()
    
    # Skip languages
    languages = {
        'español', 'português', 'english', 'deutsch', 'français', 'italiano',
        '日本語', '한국어', '中文', 'русский', 'polski', 'български',
        'tiếng việt', 'bahasa indonesia', 'українська'
    }
    
    # Skip legal/boilerplate
    skip_phrases = {
        'property of their respective', 'trademarks are property', 
        'subscriber agreement', 'refunds', 'get support', 'my account',
        'deck compatibility', 'no items match', 'all with', 'included in all prices'
    }
    
    name_lower = name.lower()
    name_upper = name.upper()
    
    # Must have 2+ words OR be recognizable game pattern
    words = name.split()
    if len(words) < 2:
        return False
    
    # Skip if contains language/legal text
    if any(lang in name_lower for lang in languages):
        return False
    if any(phrase in name_lower for phrase in skip_phrases):
        return False
    
    # Skip Steam UI elements
    if any(skip in name_upper for skip in {'STEAM', 'VALVE', 'WISHLIST', 'CART', 'STORE', 'VIEW', 'REMOVE'}):
        return False
    
    # Must be >10 chars (excludes short UI text)
    return len(name) > 10

# 🎯 EXTRACT ALL GAME NAMES FROM ATTRIBUTES (Steam's secret)
games = set()

# 1. Title attributes (MOST GAMES HERE)
for elem in soup.find_all(attrs={"title": True}):
    title = elem['title'].strip()
    if is_real_game(title):
        games.add(title)

# 2. Data-tooltip-html (Steam stores full names here)
for elem in soup.find_all(attrs={"data-tooltip-html": True}):
    tooltip = elem['data-tooltip-html']
    # Extract game name from tooltip HTML
    tooltip_soup = BeautifulSoup(tooltip, 'html.parser')
    name_elem = tooltip_soup.find(['h4', 'span', 'div'], string=True)
    if name_elem:
        name = name_elem.get_text(strip=True)
        if is_real_game(name):
            games.add(name)

# 3. App/sub links with text
for link in soup.find_all("a", href=re.compile(r"/app/\d+|/sub/\d+")):
    name = (link.get('title') or link.get_text(strip=True)).strip()
    if is_real_game(name):
        games.add(name)

# 4. Explicit game name elements
for elem in soup.find_all(["h2", "h3", "h4", ".game_name", "[data-name]"]):
    name = elem.get_text(strip=True)
    if is_real_game(name):
        games.add(name)

# Convert to list & sort by length (longest first)
wishlist_games = sorted([g for g in games if is_real_game(g)], 
                       key=len, reverse=True)

print(f"🎮 EXTRACTED {len(wishlist_games)} GAMES!")
print("\n" + "="*100)
print("TOP 30 GAMES:")
for i, game in enumerate(wishlist_games[:30], 1):
    print(f"{i:2d}. {game}")

print(f"\n... and {len(wishlist_games)-30} more")
print(f"\n✅ Saved to wishlist_games.txt")

# Save ALL games
with open("wishlist_games.txt", "w", encoding="utf-8") as f:
    for game in wishlist_games:
        f.write(game + "\n")

# MATCH WITH games.json
print("\n" + "="*100)
print("🔥 CHECKING DEALS...")

try:
    with open("games.json", "r") as f:
        games_db = json.load(f)
    
    matches = []
    for db_name, info in games_db.items():
        for wishlist_game in wishlist_games:
            # Better matching
            db_words = set(db_name.lower().split())
            wish_words = set(wishlist_game.lower().split())
            
            # 60% word overlap OR exact substring
            overlap = len(db_words & wish_words) / len(db_words | wish_words)
            if overlap > 0.6 or db_name.lower() in wishlist_game.lower():
                matches.append({
                    'wishlist': wishlist_game,
                    'database': db_name,
                    'discount': info.get('discount', 0),
                    'price': info.get('price', 'N/A'),
                    'orig_price': info.get('original_price', 'N/A')
                })
                break
    
    print(f"\n🎉 {len(matches)} DEALS FOUND!")
    for match in sorted(matches, key=lambda x: x['discount'] or 0, reverse=True)[:15]:
        discount_color = get_discount_class(match['discount'])
        price_color = get_price_class(match['price'])
        print(f"  {discount_color}{match['discount']}%{get_discount_class(None)}  {match['wishlist'][:40]:<40} "
              f"→ {price_color}{match['price']}€{get_price_class(None)} (was {match['orig_price']}€)")
    
    with open("deals.json", "w") as f:
        json.dump(matches, f, indent=2)
        
except Exception as e:
    print(f"Games.json error: {e}")

print("\n✅ deals.json saved!")