"""HTTP client for the Port Dashboard FastAPI backend."""

import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None


DEFAULT_BASE_URL = os.environ.get("PORT_DASHBOARD_URL", "http://localhost:9229")


def get_base_url() -> str:
    return os.environ.get("PORT_DASHBOARD_URL", DEFAULT_BASE_URL)


def _ensure_requests():
    if requests is None:
        print("Error: 'requests' package is required. Install with: pip install requests", file=sys.stderr)
        sys.exit(1)


def api_get(path: str, params: Optional[Dict] = None) -> Any:
    _ensure_requests()
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        print(f"Error: Cannot connect to Port Dashboard at {get_base_url()}", file=sys.stderr)
        print("Make sure the dashboard is running: start.bat", file=sys.stderr)
        sys.exit(1)


def api_post(path: str, data: Optional[Dict] = None) -> Any:
    _ensure_requests()
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            print(f"Error ({resp.status_code}): {detail}", file=sys.stderr)
            sys.exit(1)
        return resp.json()
    except requests.ConnectionError:
        print(f"Error: Cannot connect to Port Dashboard at {get_base_url()}", file=sys.stderr)
        sys.exit(1)


def api_put(path: str, data: Optional[Dict] = None) -> Any:
    _ensure_requests()
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.put(url, json=data, timeout=10)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            print(f"Error ({resp.status_code}): {detail}", file=sys.stderr)
            sys.exit(1)
        return resp.json()
    except requests.ConnectionError:
        print(f"Error: Cannot connect to Port Dashboard at {get_base_url()}", file=sys.stderr)
        sys.exit(1)


def api_delete(path: str) -> Any:
    _ensure_requests()
    url = f"{get_base_url()}{path}"
    try:
        resp = requests.delete(url, timeout=10)
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            print(f"Error ({resp.status_code}): {detail}", file=sys.stderr)
            sys.exit(1)
        return resp.json()
    except requests.ConnectionError:
        print(f"Error: Cannot connect to Port Dashboard at {get_base_url()}", file=sys.stderr)
        sys.exit(1)


def format_output(data: Any, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return str(data)
