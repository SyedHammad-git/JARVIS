from __future__ import annotations

import requests
from flask import Blueprint, g, jsonify, request

from app.key_store import (
    PROVIDER_ENV,
    KeyStorageUnavailable,
    delete_user_key,
    list_user_keys,
    save_user_key,
    update_key_test_status,
)

keys_bp = Blueprint("keys", __name__)
_PROVIDER_CHECKS = {
    "groq": ("https://api.groq.com/openai/v1/models", "bearer"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "query"),
    "openrouter": ("https://openrouter.ai/api/v1/auth/key", "bearer"),
    "weather": ("https://api.openweathermap.org/data/2.5/weather", "query"),
}


class ProviderUnavailable(RuntimeError):
    pass


def _valid_provider(provider: str) -> bool:
    return provider in PROVIDER_ENV


def _probe(provider: str, key: str) -> bool:
    url, auth_mode = _PROVIDER_CHECKS[provider]
    headers = {"Authorization": f"Bearer {key}"} if auth_mode == "bearer" else {}
    params = {"key": key} if provider == "gemini" else {}
    if provider == "weather":
        params = {"appid": key, "q": "London"}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=8)
    except requests.RequestException:
        raise ProviderUnavailable("provider_probe_failed") from None
    return response.status_code == 200


@keys_bp.get("/api/keys")
def keys_list():
    try:
        return jsonify({"ok": True, "providers": list_user_keys(g.current_user["username"])})
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503


@keys_bp.post("/api/keys/<provider>")
def keys_save(provider):
    if not _valid_provider(provider):
        return jsonify({"ok": False, "error": "unsupported_provider"}), 404
    body = request.get_json(silent=True) or {}
    key = body.get("key")
    if not isinstance(key, str) or not key.strip() or len(key) > 512:
        return jsonify({"ok": False, "error": "invalid_key"}), 400
    try:
        save_user_key(g.current_user["username"], provider, key.strip())
        return jsonify({"ok": True})
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    except RuntimeError:
        return jsonify({"ok": False, "error": "api_key_storage_failed"}), 503


@keys_bp.post("/api/keys/<provider>/test")
def keys_test(provider):
    if not _valid_provider(provider):
        return jsonify({"ok": False, "error": "unsupported_provider"}), 404
    body = request.get_json(silent=True) or {}
    key = body.get("key")
    if not isinstance(key, str) or not key.strip() or len(key) > 512:
        return jsonify({"ok": False, "error": "invalid_key"}), 400
    try:
        supplied_key = key.strip()
        valid = _probe(provider, supplied_key)
        update_key_test_status(g.current_user["username"], provider, supplied_key, valid)
    except ProviderUnavailable:
        return jsonify({"ok": False, "error": "provider_unavailable"}), 502
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    except RuntimeError:
        return jsonify({"ok": False, "error": "api_key_storage_failed"}), 503
    return jsonify({"ok": True, "valid": valid})


@keys_bp.delete("/api/keys/<provider>")
def keys_delete(provider):
    if not _valid_provider(provider):
        return jsonify({"ok": False, "error": "unsupported_provider"}), 404
    try:
        delete_user_key(g.current_user["username"], provider)
        return jsonify({"ok": True})
    except KeyStorageUnavailable:
        return jsonify({"ok": False, "error": "api_key_storage_unavailable"}), 503
    except RuntimeError:
        return jsonify({"ok": False, "error": "api_key_storage_failed"}), 503
