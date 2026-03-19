from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict
from urllib.request import Request, urlopen


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_dps() -> List[Dict[str, str]]:
    logger = logging.getLogger('mero-share-service')

    def _try_fetch(url: str) -> List[Dict[str, str]]:
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                return []
            data = json.load(response)
            formatted = []
            for item in data:
                if 'id' in item and 'name' in item and 'code' in item:
                    formatted.append(
                        {
                            'id': str(item['id']),
                            'name': item['name'],
                            'code': item['code'],
                        }
                    )
            return formatted

    urls = []
    env_url = os.getenv('DPS_URL')
    if env_url:
        urls.extend([u.strip() for u in env_url.split(',') if u.strip()])
    urls.extend(
        [
            'https://meroshare.cdsc.com.np/api/casba/bank/',
            'https://meroshare.cdsc.com.np/api/casba/bank',
        ]
    )

    for url in urls:
        try:
            items = _try_fetch(url)
            if items:
                return items
        except Exception as exc:
            logger.info('DPS fetch failed for %s: %s', url, str(exc))
            continue

    file_path = Path(__file__).resolve().parent.parent / 'dps.json'
    if file_path.exists():
        try:
            with file_path.open('r', encoding='utf-8') as handle:
                return json.load(handle)
        except Exception:
            pass

    return [
        {'id': '13100', 'name': 'NIC ASIA Bank Limited', 'code': 'NIC'},
        {'id': '10200', 'name': 'Nabil Bank Limited', 'code': 'NABIL'},
        {'id': '11600', 'name': 'Global IME Bank Limited', 'code': 'GBIME'},
        {'id': '11000', 'name': 'Rastriya Banijya Bank Limited', 'code': 'RBB'},
    ]
