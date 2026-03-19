import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _post_json(url: str, api_key: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-Forwarded-Proto': 'https',
    }
    if api_key:
        headers['X-API-Key'] = api_key
    req = Request(
        url,
        data=data,
        headers=headers,
        method='POST',
    )
    with urlopen(req, timeout=120) as response:
        body = response.read().decode('utf-8')
        return json.loads(body)


def _get_json(url: str, api_key: Optional[str]) -> Dict[str, Any]:
    headers = {
        'X-Forwarded-Proto': 'https',
    }
    if api_key:
        headers['X-API-Key'] = api_key
    req = Request(
        url,
        headers=headers,
        method='GET',
    )
    with urlopen(req, timeout=60) as response:
        body = response.read().decode('utf-8')
        return json.loads(body)


def _print_result(title: str, result: Dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description='Test Mero Share Service endpoints')
    parser.add_argument('--base-url', default=os.getenv('BASE_URL', 'http://localhost:8000'))
    parser.add_argument('--api-key', default=os.getenv('API_KEY'))

    parser.add_argument('--dp-id')
    parser.add_argument('--username')
    parser.add_argument('--password')
    parser.add_argument('--crn')
    parser.add_argument('--pin')
    parser.add_argument('--ipo-name')
    parser.add_argument('--company-share-id')
    parser.add_argument('--units', type=int, default=10)
    parser.add_argument('--bank')

    parser.add_argument('--test-health', action='store_true')
    parser.add_argument('--test-dps', action='store_true')
    parser.add_argument('--test-login', action='store_true')
    parser.add_argument('--test-portfolio', action='store_true')
    parser.add_argument('--test-allotment', action='store_true')
    parser.add_argument('--test-apply', action='store_true')

    args = parser.parse_args()

    api_key = args.api_key or os.getenv('API_KEY')
    base_url = args.base_url.rstrip('/')

    try:
        if args.test_health:
            result = _get_json(f"{base_url}/health", api_key)
            _print_result('Health', result)

        if args.test_dps:
            result = _get_json(f"{base_url}/dps", api_key)
            _print_result('DPs', result)

        if args.test_login:
            if not all([args.dp_id, args.username, args.password]):
                print('Missing required args for test-login: --dp-id --username --password')
                sys.exit(1)
            payload = {
                'credentials': {
                    'dpId': args.dp_id,
                    'username': args.username,
                    'password': args.password,
                }
            }
            result = _post_json(f"{base_url}/test-login", api_key, payload)
            _print_result('Test Login', result)

        if args.test_portfolio:
            if not all([args.dp_id, args.username, args.password]):
                print('Missing required args for portfolio: --dp-id --username --password')
                sys.exit(1)
            payload = {
                'credentials': {
                    'dpId': args.dp_id,
                    'username': args.username,
                    'password': args.password,
                }
            }
            result = _post_json(f"{base_url}/portfolio", api_key, payload)
            _print_result('Portfolio', result)

        if args.test_allotment:
            if not all([args.dp_id, args.username, args.password, args.ipo_name]):
                print('Missing required args for check-allotment: --dp-id --username --password --ipo-name')
                sys.exit(1)
            payload = {
                'credentials': {
                    'dpId': args.dp_id,
                    'username': args.username,
                    'password': args.password,
                },
                'ipoName': args.ipo_name,
            }
            result = _post_json(f"{base_url}/check-allotment", api_key, payload)
            _print_result('Check Allotment', result)

        if args.test_apply:
            if not all([args.dp_id, args.username, args.password, args.crn, args.pin, (args.company_share_id or args.ipo_name), args.bank]):
                print('Missing required args for apply-ipo: --dp-id --username --password --crn --pin --bank and --company-share-id (or --ipo-name)')
                sys.exit(1)
            payload = {
                'dp_id': args.dp_id,
                'username': args.username,
                'password': args.password,
                'crn': args.crn,
                'pin': args.pin,
                'ipo_details': {
                    'company_share_id': args.company_share_id or (args.ipo_name or ''),
                    'units': args.units,
                    'bank': args.bank or '',
                },
            }
            result = _post_json(f"{base_url}/apply-ipo", api_key, payload)
            _print_result('Apply IPO', result)

        if not any(
            [
                args.test_health,
                args.test_dps,
                args.test_login,
                args.test_portfolio,
                args.test_allotment,
                args.test_apply,
            ]
        ):
            parser.print_help()

    except HTTPError as exc:
        body = exc.read().decode('utf-8') if exc.fp else ''
        print(f"HTTPError: {exc.code} {exc.reason}\n{body}")
        sys.exit(1)
    except URLError as exc:
        print(f"URLError: {exc.reason}")
        sys.exit(1)


if __name__ == '__main__':
    main()
