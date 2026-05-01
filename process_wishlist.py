from bs4 import BeautifulSoup
import json
import re
import difflib
try:
    from fuzzysearch import find_near_matches
    _HAS_FUZZYSEARCH = True
except Exception:
    _HAS_FUZZYSEARCH = False

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
    import unicodedata
    # helper to detect likely DLC/expansion/add-on based on keywords
    def likely_dlc(name, info=None):
        if not name and not info:
            return False
        s = (name or '').lower()
        if isinstance(info, dict):
            s += ' ' + str(info.get('type', '')).lower()
        dlc_keywords = ['dlc', 'season pass', 'season-pass', 'expansion', 'expansion pack', 'add-on', 'addon', 'map pack', 'story pack', 'content pack', 'deluxe edition']
        for kw in dlc_keywords:
            if kw in s:
                return True
        # heuristic: title with colon (subtitle) often indicates DLC/expansion when subtitle is short
        try:
            if ':' in name:
                subtitle = name.split(':', 1)[1].strip()
                if 0 < len(subtitle.split()) <= 5:
                    return True
        except Exception:
            pass
        return False
    def normalize_tokens(name):
        # unicode normalize
        s = unicodedata.normalize('NFKD', name)
        # split camelCase / PascalCase (EldenRing -> Elden Ring)
        s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
        s = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', s)
        # replace non-alphanumeric with spaces
        s = re.sub(r'[^0-9A-Za-z]+', ' ', s)
        tokens = re.findall(r"\w+", s.lower())
        # remove common non-informative tokens
        stopwords = {
            'edition', 'deluxe', 'ultimate', 'standard', 'bundle', 'vr', 'pc',
            'europe', 'usa', 'us', 'global', 'steam', 'steam™', 'region'
        }
        tokens = [t for t in tokens if t not in stopwords]
        # normalized forms
        token_set = set(tokens)
        compact = ''.join(tokens)
        spaced = ' '.join(tokens)
        return token_set, spaced, compact

    for db_name, info in games_db.items():
        for wishlist_game in wishlist_games:
            # If games.json entries include a display_name (from main.py), prefer that for matching
            db_display = db_name
            if isinstance(info, dict) and info.get('display_name'):
                db_display = info.get('display_name')
            db_tokens, db_spaced, db_compact = normalize_tokens(db_display)
            wish_tokens, wish_spaced, wish_compact = normalize_tokens(wishlist_game)
            if not db_tokens or not wish_tokens:
                continue

            # token Jaccard overlap
            common_tokens = db_tokens & wish_tokens
            union_tokens = db_tokens | wish_tokens
            overlap = len(common_tokens) / len(union_tokens) if union_tokens else 0.0
            # sequence similarity as fallback (handles different punctuation/ordering)
            seq_ratio = difflib.SequenceMatcher(None, db_spaced, wish_spaced).ratio()

            # subset checks (one name contains all meaningful tokens of the other)
            subset = wish_tokens.issubset(db_tokens) or db_tokens.issubset(wish_tokens)
            # compact exact match (handles EldenRing vs ELDEN RING)
            compact_eq = db_compact == wish_compact

            # fuzzysearch approximate substring match when available
            fuzzy_match = False
            if _HAS_FUZZYSEARCH:
                # allow edit distance proportional to length (min 1, max 4)
                max_len = max(len(db_compact), len(wish_compact))
                max_l_dist = max(1, min(4, int(max_len * 0.18)))
                try:
                    if find_near_matches(wish_spaced, db_spaced, max_l_dist=max_l_dist):
                        fuzzy_match = True
                    elif find_near_matches(db_spaced, wish_spaced, max_l_dist=max_l_dist):
                        fuzzy_match = True
                except Exception:
                    fuzzy_match = False

            # Reject obviously tiny database entries
            if len(db_compact) < 3 or len(wish_compact) < 3:
                continue

            # Require at least two meaningful token matches for multi-word names
            min_common_tokens = 2

            score = 0.0

            # Strong exact matches accepted immediately. For subset matches require
            # at least two meaningful tokens to avoid mapping DLC/subtitles to base game
            if compact_eq or (subset and min(len(db_tokens), len(wish_tokens)) >= 2):
                score = 1.0
            elif len(common_tokens) >= min_common_tokens:
                # tighten: require higher overlap for multi-word names
                score = overlap * 0.7 + seq_ratio * 0.3
            elif len(common_tokens) == 1:
                # single-token matches are risky — accept only when token is long and sequence similarity is very high
                token = next(iter(common_tokens))
                if len(token) >= 6 and seq_ratio > 0.92 and fuzzy_match:
                    score = 0.85
                else:
                    score = 0.0
            else:
                # fallback: allow fuzzy substring+very-high-sequence
                if fuzzy_match and seq_ratio > 0.88:
                    score = 0.8

            # final acceptance threshold (stricter)
            if score >= 0.82:
                matches.append({
                    'wishlist': wishlist_game,
                    'wishlist_original': wishlist_game,
                    'database': db_name,
                    'database_original': db_display,
                    'discount': info.get('discount', 0),
                    'price': info.get('price', 'N/A'),
                    'orig_price': info.get('original_price', 'N/A'),
                    'platform': info.get('type', 'N/A') if isinstance(info, dict) else 'N/A',
                    'dlc': likely_dlc(db_display, info),
                    'score': round(score * 100)
                })
                break
    
    print(f"\n🎉 {len(matches)} DEALS FOUND!")
    for match in sorted(matches, key=lambda x: x['discount'] or 0, reverse=True)[:15]:
        display_wish = match.get('wishlist_original', match.get('wishlist'))
        display_db = match.get('database_original', match.get('database'))
        dlc_tag = '[DLC]' if match.get('dlc') else ''
        score_str = f"{match.get('score', 0)}%"
        platform = match.get('platform') or 'N/A'
        print(f"{display_wish[:48]:<50} - {str(match.get('discount','N/A')):>6}% - {match.get('price','N/A')} - {match.get('orig_price','N/A')} - {platform} - {dlc_tag} - {score_str}")
    
    with open("deals.json", "w") as f:
        json.dump(matches, f, indent=2)
        
except Exception as e:
    print(f"Games.json error: {e}")

print("\n✅ deals.json saved!")