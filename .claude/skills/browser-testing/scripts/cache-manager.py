#!/usr/bin/env python3
"""
Cache manager for browser testing - stores SELECTORS and COORDINATES, not ref_ids.

ref_ids are ephemeral (invalidated on any DOM change), so we store:
- playwright_selector: Accessibility-based selector (preferred)
- css_selector: CSS selector for the element
- text_selector: Natural language description for find()
- coordinates: Last known click position {x, y}
- viewport_size: Viewport when coordinates were captured (e.g., "1536x643")

Output format (simplified for token efficiency):
- HIT:playwright:button "Quick Recovery"  (Playwright selector, preferred)
- HIT:150,300,1536x643  (coordinates + viewport)
- HIT:selector:Quick Recovery button  (no coords, use find())
- MISS
"""

import json
import sys
from pathlib import Path
from datetime import datetime

CACHE_FILE = Path(__file__).parent.parent / "element-cache.json"

def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {"version": "3.0", "pages": {}, "stats": {"hits": 0, "misses": 0}}

def save_cache(cache):
    cache["last_updated"] = datetime.now().isoformat()
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def get_page_key(url):
    """Extract page key from URL (e.g., localhost:3002)"""
    return url.replace("http://", "").replace("https://", "").split("/")[0]

def get_element(page_url, cache_key, prefer="playwright"):
    """
    Get cached element.
    Output:
    - HIT:playwright:button "Text"  (Playwright selector, preferred)
    - HIT:x,y,viewport  (coordinates)
    - HIT:selector:text  (text selector for claude-in-chrome)
    - MISS

    Args:
        prefer: "playwright" or "coordinates" or "any"
    """
    cache = load_cache()
    page_key = get_page_key(page_url)

    if page_key in cache["pages"]:
        elem = cache["pages"][page_key].get("elements", {}).get(cache_key)
        if elem:
            cache["stats"]["hits"] = cache["stats"].get("hits", 0) + 1
            elem["hit_count"] = elem.get("hit_count", 0) + 1
            save_cache(cache)

            # Prefer Playwright selector (accessibility-based)
            if prefer in ["playwright", "any"]:
                pw_selector = elem.get("playwright_selector")
                if pw_selector:
                    print(f"HIT:playwright:{pw_selector}")
                    return

            # Fallback to coordinates if available
            if prefer in ["coordinates", "any"]:
                coords = elem.get("coordinates")
                viewport = elem.get("viewport_size")
                if coords and viewport:
                    print(f"HIT:{coords['x']},{coords['y']},{viewport}")
                    return

            # Fallback to text/CSS selector for claude-in-chrome
            selector = elem.get("text_selector") or elem.get("css_selector")
            if selector:
                print(f"HIT:selector:{selector}")
                return

    cache["stats"]["misses"] = cache["stats"].get("misses", 0) + 1
    save_cache(cache)
    print("MISS")

def store_element(page_url, cache_key, playwright_selector=None, css_selector=None,
                  text_selector=None, coords=None, viewport=None):
    """Store element with selectors and coordinates (NOT ref_ids)."""
    cache = load_cache()
    page_key = get_page_key(page_url)

    if page_key not in cache["pages"]:
        cache["pages"][page_key] = {"elements": {}}

    elements = cache["pages"][page_key]["elements"]
    if cache_key not in elements:
        elements[cache_key] = {"hit_count": 0, "alternatives": []}

    elem = elements[cache_key]

    if playwright_selector:
        elem["playwright_selector"] = playwright_selector
    if css_selector:
        elem["css_selector"] = css_selector
    if text_selector:
        elem["text_selector"] = text_selector
    if coords:
        # Parse coords string "x,y" to dict
        if isinstance(coords, str):
            x, y = coords.split(",")
            elem["coordinates"] = {"x": int(x), "y": int(y)}
        else:
            elem["coordinates"] = coords
    if viewport:
        elem["viewport_size"] = viewport

    elem["last_updated"] = datetime.now().isoformat()
    save_cache(cache)
    print(f"STORED:{cache_key}")

def add_alternative(page_url, cache_key, alternative, alt_type="text"):
    """Add alternative selector to an element.

    Args:
        alt_type: "playwright", "css", or "text"
    """
    cache = load_cache()
    page_key = get_page_key(page_url)

    if page_key in cache["pages"]:
        elem = cache["pages"][page_key].get("elements", {}).get(cache_key)
        if elem:
            alt_entry = {"type": alt_type, "selector": alternative}
            alternatives = elem.setdefault("alternatives", [])
            # Check if already exists
            if not any(a.get("selector") == alternative for a in alternatives):
                alternatives.append(alt_entry)
                save_cache(cache)
                print(f"ADDED:{alt_type}:{alternative}")
                return
            else:
                print(f"EXISTS:{alternative}")
                return
    print("NOTFOUND")

def show_stats():
    """Display cache statistics."""
    cache = load_cache()
    stats = cache.get("stats", {})
    hits = stats.get("hits", 0)
    misses = stats.get("misses", 0)
    total = hits + misses
    hit_rate = (hits / total * 100) if total > 0 else 0

    print(f"Cache Stats: {hits} hits, {misses} misses ({hit_rate:.0f}% hit rate)")
    print(f"Version: {cache.get('version', '1.0')}")
    print(f"Updated: {cache.get('last_updated', 'Never')}")

    for page, data in cache.get("pages", {}).items():
        elements = data.get("elements", {})
        with_pw = sum(1 for e in elements.values() if e.get("playwright_selector"))
        with_coords = sum(1 for e in elements.values() if e.get("coordinates"))
        print(f"  {page}: {len(elements)} elements ({with_pw} Playwright, {with_coords} coords)")

def list_elements():
    """List all cached elements briefly."""
    cache = load_cache()
    for page, data in cache.get("pages", {}).items():
        print(f"{page}:")
        for key, elem in data.get("elements", {}).items():
            # Priority: playwright > coords > text selector
            pw = elem.get("playwright_selector")
            coords = elem.get("coordinates")

            if pw:
                display = f"PW: {pw[:40]}"
            elif coords:
                display = f"coords: {coords['x']},{coords['y']}"
            else:
                selector = elem.get("text_selector", elem.get("css_selector", "?"))
                display = f"sel: {selector[:30]}"

            print(f"  {key}: {display}")

def clear_cache(cache_key=None):
    """Clear all cache or specific key."""
    cache = load_cache()
    if cache_key:
        for page in cache.get("pages", {}).values():
            if cache_key in page.get("elements", {}):
                del page["elements"][cache_key]
        print(f"CLEARED:{cache_key}")
    else:
        cache["pages"] = {}
        cache["stats"] = {"hits": 0, "misses": 0}
        print("CLEARED:all")
    save_cache(cache)

def migrate_cache():
    """Migrate cache from v2.0 to v3.0 format."""
    cache = load_cache()
    if cache.get("version") == "3.0":
        print("ALREADY:v3.0")
        return

    # Add version field
    cache["version"] = "3.0"

    # Convert alternatives to new format
    for page in cache.get("pages", {}).values():
        for elem in page.get("elements", {}).values():
            alternatives = elem.get("alternatives", [])
            new_alts = []
            for alt in alternatives:
                if isinstance(alt, str):
                    new_alts.append({"type": "text", "selector": alt})
                elif isinstance(alt, dict):
                    new_alts.append(alt)
            elem["alternatives"] = new_alts

    save_cache(cache)
    print("MIGRATED:v3.0")

def print_usage():
    print("Usage: cache-manager.py <command> [args]")
    print("")
    print("Commands:")
    print("  get <url> <key> [--prefer playwright|coordinates|any]")
    print("                             - Get element (default: prefer Playwright)")
    print("  store <url> <key> [options]  - Store element")
    print("    --playwright 'selector'  - Playwright selector (accessibility-based)")
    print("    --selector 'text'        - Text selector for find()")
    print("    --css 'selector'         - CSS selector")
    print("    --coords 'x,y'           - Click coordinates")
    print("    --viewport 'WxH'         - Viewport size (e.g., 1536x643)")
    print("  alt <url> <key> <selector> [--type playwright|css|text]")
    print("                             - Add alternative selector")
    print("  show                       - Display statistics")
    print("  list                       - List all cached elements")
    print("  clear [key]                - Clear cache")
    print("  migrate                    - Migrate cache to v3.0 format")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "show":
        show_stats()
    elif cmd == "list":
        list_elements()
    elif cmd == "clear":
        clear_cache(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "migrate":
        migrate_cache()
    elif cmd == "get" and len(sys.argv) >= 4:
        prefer = "playwright"  # Default to Playwright
        if "--prefer" in sys.argv:
            idx = sys.argv.index("--prefer")
            if idx + 1 < len(sys.argv):
                prefer = sys.argv[idx + 1]
        get_element(sys.argv[2], sys.argv[3], prefer=prefer)
    elif cmd == "store" and len(sys.argv) >= 4:
        # Parse optional arguments
        url, key = sys.argv[2], sys.argv[3]
        kwargs = {}
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == "--playwright" and i + 1 < len(sys.argv):
                kwargs["playwright_selector"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--selector" and i + 1 < len(sys.argv):
                kwargs["text_selector"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--css" and i + 1 < len(sys.argv):
                kwargs["css_selector"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--coords" and i + 1 < len(sys.argv):
                kwargs["coords"] = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--viewport" and i + 1 < len(sys.argv):
                kwargs["viewport"] = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        store_element(url, key, **kwargs)
    elif cmd == "alt" and len(sys.argv) >= 5:
        alt_type = "text"
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                alt_type = sys.argv[idx + 1]
        add_alternative(sys.argv[2], sys.argv[3], sys.argv[4], alt_type=alt_type)
    else:
        print_usage()
        sys.exit(1)
