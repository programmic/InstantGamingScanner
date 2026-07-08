import re
from typing import Dict, Any
from thefuzz import fuzz
import unicodedata
from enum import Enum

class MatchDebug(Enum):
    None_ = 0
    Listed = 1
    All = 2

def normalize(text: str) -> str:
    if text is None:
        return ''

    text = str(text)

    # Unicode cleanup (fix ™, ®, accented chars, etc.)
    text = unicodedata.normalize('NFKD', text)

    # Remove trademark / registered marks explicitly
    text = re.sub(r'[\u2122\u00AE\u00A9]', '', text)  # ™ ® ©

    # Fix camel-case-ish concatenations (PlantsVersusZombies → Plants Versus Zombies)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

    # Replace weird punctuation (^tm, ^r, etc.)
    text = re.sub(r'\^(tm|r|c)\b', '', text, flags=re.IGNORECASE)

    # Lowercase
    text = text.lower()

    # Normalize separators
    text = re.sub(r'[:\-_/]', ' ', text)

    # Remove noise words BUT KEEP "edition" if you care about DLC separation
    text = re.sub(r'\b(europe|eu|global|steam)\b', '', text)

    # Clean non-alphanumerics
    text = re.sub(r'[^a-z0-9 ]', ' ', text)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def find_best_match(item_norm: str, p_all_games: Dict[str, Any], match_debug: MatchDebug = MatchDebug.None_) -> Dict[str, Any]:
    """Find the best matching game in p_all_games for a normalized wishlist item.

    Returns a dict with keys: accept (bool), best_info (dict|None), best_db_name (str|None),
    best_score (float), score_set, score_partial, score_sort, candidates (list).
    """
    # Build a normalized index for exact-fast-path
    database_normalized = {}
    for key, info in p_all_games.items():
        display = info.get('display_name') if isinstance(info, dict) else key
        n = normalize(display)
        database_normalized.setdefault(n, []).append((key, info))

    best_score = -1
    best_info = None
    best_db_name = None
    best_scores = (0, 0, 0)
    best_db_norm = ''

    candidates = []
    for db_key, db_info in p_all_games.items():
        db_display = db_info.get('display_name') if isinstance(db_info, dict) else db_key
        db_norm = normalize(db_display)
        try:
            score_set = fuzz.token_set_ratio(item_norm, db_norm)
            score_partial = fuzz.partial_ratio(item_norm, db_norm)
            score_sort = fuzz.token_sort_ratio(item_norm, db_norm)
            score = (score_set * 0.5) + (score_sort * 0.3) + (score_partial * 0.2)
        except Exception:
            score_set = score_partial = score_sort = score = 0

        candidates.append((score, score_set, score_partial, score_sort, db_display, db_info, db_norm))

        if score > best_score:
            best_score = score
            best_info = db_info
            best_db_name = db_display
            best_scores = (score_set, score_partial, score_sort)
            best_db_norm = db_norm

    # Acceptance thresholds (shared heuristics)
    MIN_TOKEN_SET = 80
    MIN_PARTIAL = 75
    MIN_SORT = 75
    MIN_OVERALL = 90
    MIN_ACCEPT_SCORE = 80

    accept = False

    # Exact normalized match fast path
    try:
        if item_norm and item_norm in database_normalized:
            cand_key, cand_info = database_normalized[item_norm][0]
            best_info = cand_info
            best_db_name = cand_info.get('display_name') if isinstance(cand_info, dict) else cand_key
            best_score = 100
            best_scores = (100, 100, 100)
            best_db_norm = item_norm
            accept = True
    except Exception:
        pass

    # compute meaningful tokens
    try:
        item_tokens = [t for t in re.findall(r"\w+", item_norm) if t not in {'the','a','an','of','and'}]
    except Exception:
        item_tokens = []

    score_set, score_partial, score_sort = best_scores

    if not accept:
        if score_set == 100 and score_partial >= 90:
            accept = True

    if not accept:
        if len(item_tokens) <= 2:
            if score_set >= 90 and (score_partial >= MIN_PARTIAL or score_sort >= MIN_SORT):
                accept = True
        else:
            if score_set >= MIN_TOKEN_SET and (score_partial >= MIN_PARTIAL or score_sort >= MIN_SORT) and best_score >= MIN_ACCEPT_SCORE:
                accept = True

    if not accept and best_score >= MIN_OVERALL:
        accept = False

    # Prevent single-token subset-like matches
    try:
        stopwords = {'edition', 'deluxe', 'standard', 'ultimate', 'bundle', 'dlc', 'season', 'pass'}
        item_tokens = [t for t in re.findall(r"\w+", item_norm) if t not in stopwords]
        db_tokens = [t for t in re.findall(r"\w+", best_db_norm) if t not in stopwords]
        min_tokens = min(len(item_tokens), len(db_tokens)) if db_tokens else len(item_tokens)
        if min_tokens < 2 and accept:
            try:
                db_compact = re.sub(r'\s+', '', best_db_norm)
                item_compact = re.sub(r'\s+', '', item_norm)
                if item_norm == best_db_norm or best_score >= 97:
                    accept = True
                elif len(item_tokens) <= 1 and db_compact.startswith(item_compact) and score_partial >= 90 and score_set >= 90:
                    accept = True
                else:
                    accept = False
            except Exception:
                accept = False
    except Exception:
        pass

    # sort candidates for optional debugging
    candidates.sort(reverse=True, key=lambda x: x[0])

    return {
        'accept': accept,
        'best_info': best_info,
        'best_db_name': best_db_name,
        'best_score': best_score,
        'score_set': score_set,
        'score_partial': score_partial,
        'score_sort': score_sort,
        'candidates': candidates,
    }
