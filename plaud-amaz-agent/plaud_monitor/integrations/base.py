from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class ApiConfigError(RuntimeError):
    """Raised when an API integration is enabled but not fully configured."""


class ApiRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, response_body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True)
class EnvRequirement:
    config_key: str
    label: str
    required: bool = True


def env_name(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ApiConfigError(f"Missing environment variable mapping: {key}")
    return value


def env_value(config: dict[str, Any], key: str) -> str:
    name = env_name(config, key)
    return os.environ.get(name, "").strip()


def require_env(config: dict[str, Any], key: str) -> str:
    name = env_name(config, key)
    value = os.environ.get(name, "").strip()
    if not value:
        raise ApiConfigError(f"Missing required environment variable: {name}")
    return value


def missing_envs(config: dict[str, Any], requirements: list[EnvRequirement]) -> list[str]:
    missing: list[str] = []
    for requirement in requirements:
        name = str(config.get(requirement.config_key) or "").strip()
        if requirement.required and (not name or not os.environ.get(name, "").strip()):
            missing.append(name or requirement.config_key)
    return missing


def redact(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def build_url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    base = base_url.rstrip("/")
    api_path = path if path.startswith("/") else f"/{path}"
    url = f"{base}{api_path}"
    if query:
        filtered = {key: value for key, value in query.items() if value is not None}
        if filtered:
            url = f"{url}?{urllib.parse.urlencode(filtered, doseq=True)}"
    return url


def http_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: Any | None = None,
    timeout: int = 30,
) -> Any:
    final_headers = dict(headers or {})
    data: bytes | None = None
    if body is not None:
        if isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json;charset=UTF-8")
    request = urllib.request.Request(url, data=data, headers=final_headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise ApiRequestError(f"HTTP {exc.code} from {url}", exc.code, body_text) from exc
    except urllib.error.URLError as exc:
        raise ApiRequestError(f"Network error calling {url}: {exc.reason}") from exc
    if not raw:
        return {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiRequestError(f"Non-JSON response from {url}", response_body=text) from exc


def form_json(
    url: str,
    payload: dict[str, str],
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    final_headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        **(headers or {}),
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    return http_json("POST", url, final_headers, data, timeout)
