from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict
from urllib.request import Request, urlopen


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_dps() -> List[Dict[str, str]]:
    url = 'https://meroshare.cdsc.com.np/api/casba/bank/'
    try:
        request = Request(url, headers={'User-Agent': 'mero-share-service/1.0'})
        with urlopen(request, timeout=10) as response:
            if response.status == 200:
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
                if formatted:
                    return formatted
    except Exception:
        pass

    url_alt = 'https://meroshare.cdsc.com.np/api/casba/bank'
    try:
        request = Request(url_alt, headers={'User-Agent': 'mero-share-service/1.0'})
        with urlopen(request, timeout=10) as response:
            if response.status == 200:
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
                if formatted:
                    return formatted
    except Exception:
        pass

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
