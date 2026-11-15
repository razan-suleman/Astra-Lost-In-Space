"""HTTP access to the real-observation backend."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import streamlit as st


class APIError(Exception):
    pass


@st.cache_data(ttl=60, show_spinner=False)
def _get(base_url: str, path: str, params: dict | None) -> bytes:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{base_url}{path}{query}"
    return _request(base_url, Request(url))


@st.cache_data(ttl=60, show_spinner=False)
def _post(base_url: str, path: str, payload: str) -> bytes:
    return _request(base_url, Request(
        f"{base_url}{path}", data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    ))


def _request(base_url: str, request: Request) -> bytes:
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise APIError(f"Backend returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise APIError(f"Cannot reach the backend at {base_url}: {exc}") from exc


def get(path: str, params: dict | None = None) -> bytes:
    base_url = os.environ.get("ASTRA_API_URL", "http://127.0.0.1:8000").rstrip("/")
    return _get(base_url, path, params)


def get_json(path: str, params: dict | None = None) -> dict:
    return _decode_json(get(path, params), path)


def post_json(path: str, payload: dict) -> dict:
    base_url = os.environ.get("ASTRA_API_URL", "http://127.0.0.1:8000").rstrip("/")
    return _decode_json(_post(base_url, path, json.dumps(payload, sort_keys=True)), path)


def _decode_json(data: bytes, path: str) -> dict:
    try:
        result = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise APIError(f"Backend returned invalid JSON for {path}") from exc
    if not isinstance(result, dict):
        raise APIError(f"Backend returned an unexpected response for {path}")
    return result
