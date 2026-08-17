from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def get_google_access_token() -> tuple[str, float]:
    token = _google_access_token_from_google_auth()
    if token:
        return token
    token = _google_access_token_from_gcloud()
    if token:
        return token
    raise RuntimeError(
        "Google-Cloud-Authentifizierung fehlt. Installiere `google-auth` mit ADC-Unterstuetzung "
        "oder fuehre `gcloud auth application-default login` aus."
    )


def get_google_quota_project() -> str | None:
    explicit = os.environ.get("GOOGLE_CLOUD_QUOTA_PROJECT")
    if explicit:
        return explicit

    adc_quota_project = get_google_quota_project_from_adc()
    if adc_quota_project:
        return adc_quota_project

    gcloud_quota_project = _get_gcloud_config_value("billing/quota_project")
    if gcloud_quota_project:
        return gcloud_quota_project

    return _get_gcloud_config_value("project")


def get_google_project_id() -> str | None:
    for env_name in ("GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GOOGLE_PROJECT_ID"):
        value = os.environ.get(env_name)
        if value:
            return value

    project_id = _google_project_id_from_google_auth()
    if project_id:
        return project_id

    gcloud_project = _get_gcloud_config_value("project")
    if gcloud_project:
        return gcloud_project

    return get_google_quota_project_from_adc()


def get_google_quota_project_from_adc() -> str | None:
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if not adc_path.exists():
        return None
    try:
        payload = json.loads(adc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    quota_project = payload.get("quota_project_id")
    return quota_project if isinstance(quota_project, str) and quota_project else None


def _google_access_token_from_google_auth() -> tuple[str, float] | None:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError:
        return None

    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    credentials.refresh(Request())
    if not credentials.token:
        return None
    expires_in_sec = 3300.0
    if getattr(credentials, "expiry", None) is not None:
        try:
            expires_in_sec = max(60.0, (credentials.expiry - _utcnow()).total_seconds())
        except (TypeError, ValueError):
            expires_in_sec = 3300.0
    return credentials.token, expires_in_sec


def _google_project_id_from_google_auth() -> str | None:
    try:
        import google.auth
    except ImportError:
        return None

    _credentials, project_id = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    if not project_id:
        return None
    return str(project_id)


def _google_access_token_from_gcloud() -> tuple[str, float] | None:
    gcloud_binary = shutil.which("gcloud")
    if not gcloud_binary:
        return None
    try:
        result = subprocess.run(
            [gcloud_binary, "auth", "application-default", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    token = result.stdout.strip()
    if not token:
        return None
    return token, 3300.0


def _get_gcloud_config_value(key: str) -> str | None:
    gcloud_binary = shutil.which("gcloud")
    if not gcloud_binary:
        return None
    try:
        result = subprocess.run(
            [gcloud_binary, "config", "get-value", key],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    value = result.stdout.strip()
    if not value or value == "(unset)":
        return None
    return value


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
