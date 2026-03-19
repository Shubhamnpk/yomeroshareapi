import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from playwright.sync_api import sync_playwright


def _pick_select(candidates: List[Dict]) -> Dict:
    # Prefer select elements whose id/name hints at DP, otherwise choose max options
    def score(item: Dict) -> Tuple[int, int]:
        hint = 1 if any(k in (item.get('id', '') + item.get('name', '')).lower() for k in ['dp', 'depository', 'participant']) else 0
        return (hint, item.get('count', 0))

    if not candidates:
        return {}
    candidates.sort(key=score, reverse=True)
    return candidates[0]


def _parse_option(value: str, text: str) -> Dict[str, str]:
    raw = (text or '').strip()
    val = (value or '').strip()
    if not raw:
        return {}

    # Skip placeholders
    if re.search(r'choose|select', raw, re.IGNORECASE):
        return {}

    dp_id = ''
    if val and val.isdigit():
        dp_id = val
    else:
        m = re.search(r'(\d{4,})', raw)
        if m:
            dp_id = m.group(1)

    name = raw
    # Try to split formats like "CODE - NAME" or "NAME (CODE)"
    code = ''
    if ' - ' in raw:
        left, right = [p.strip() for p in raw.split(' - ', 1)]
        if left and len(left) <= 10 and re.match(r'^[A-Za-z0-9]+$', left):
            code = left.upper()
            name = right or raw
    else:
        m = re.search(r'\(([^)]+)\)\s*$', raw)
        if m:
            code = m.group(1).strip().upper()
            name = raw[: m.start()].strip() or raw

    if not code:
        # Best-effort: derive code from first token
        token = re.split(r'\s+', name)[0]
        if token and len(token) <= 10 and re.match(r'^[A-Za-z0-9]+$', token):
            code = token.upper()

    if not dp_id:
        return {}

    return {'id': dp_id, 'name': name, 'code': code}


def scrape_dps() -> List[Dict[str, str]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        page.goto('https://meroshare.cdsc.com.np/#/login', wait_until='domcontentloaded')

        page.wait_for_selector('.select2-selection', timeout=20000)

        candidates = page.evaluate(
            """
            () => {
                const selects = Array.from(document.querySelectorAll('select'));
                return selects.map(s => ({
                    id: s.id || '',
                    name: s.name || '',
                    count: s.options ? s.options.length : 0,
                    options: Array.from(s.options || []).map(o => ({ value: o.value, text: o.textContent || '' }))
                }));
            }
            """
        )

        target = _pick_select(candidates)
        options = target.get('options') if target else []

        # Fallback: open dropdown and read visible results if select is empty
        if not options:
            page.click('.select2-selection')
            page.wait_for_selector('.select2-results__option', timeout=10000)
            options = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('.select2-results__option'))
                    .map(el => ({ value: el.getAttribute('value') || '', text: el.textContent || '' }));
                """
            )

        browser.close()

    parsed = []
    seen = set()
    for opt in options or []:
        item = _parse_option(str(opt.get('value', '')), str(opt.get('text', '')))
        if not item:
            continue
        if item['id'] in seen:
            continue
        seen.add(item['id'])
        parsed.append(item)

    return parsed


def main() -> None:
    items = scrape_dps()
    if not items:
        print('No DPS items found. The dropdown might be loading data dynamically.')
        return

    out_path = Path(__file__).resolve().parent / 'dps.json'
    out_path.write_text(json.dumps(items, indent=2), encoding='utf-8')
    print(f'Wrote {len(items)} items to {out_path}')


if __name__ == '__main__':
    main()
