"""
GitHub: сборка Android APK (workflow_dispatch) и скачивание готового APK из Release.

Токен PORTAL_GITHUB_TOKEN (scope: repo + workflow) — только для запуска workflow и приватных репо.
Публичный репозиторий: API релиза и скачивание работают без токена (лимит 60 запросов/час с одного IP).
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_WORKFLOW_FILE = "portal-android-apk.yml"
# Должны совпадать с шагом «Publish to GitHub Release» в .github/workflows/portal-android-apk.yml
APK_RELEASE_TAG = "portal-android-latest"


def _split_owner_repo(owner_repo: str) -> Tuple[str, str]:
    o, _, r = owner_repo.strip().partition("/")
    if not o or not r or "/" in r:
        raise ValueError("github_repo должен быть вида owner/repo")
    return o, r


def actions_workflow_page_url(owner_repo: str, workflow_file: str = DEFAULT_WORKFLOW_FILE) -> str:
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/actions/workflows/{workflow_file}"


def actions_runs_page_url(owner_repo: str) -> str:
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/actions"


def apk_release_page_url(owner_repo: str) -> str:
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/releases/tag/{APK_RELEASE_TAG}"


def get_apk_asset_download_url(
    owner_repo: str,
    *,
    token: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Возвращает browser_download_url для APK из релиза с тегом APK_RELEASE_TAG.
    """
    o, r = _split_owner_repo(owner_repo)
    api = f"https://api.github.com/repos/{o}/{r}/releases/tags/{APK_RELEASE_TAG}"
    req = urllib.request.Request(api, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "PortalDesktop/1.0")
    tok = (token or "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(e)
        if e.code == 404:
            return None, (
                "Релиза с APK пока нет (тег portal-android-latest). "
                "Нажми «Собрать на GitHub», дождись окончания CI (~10–40 мин) и скачай снова."
            )
        return None, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return None, str(e)

    assets = data.get("assets") or []
    preferred = "Portal-Android.apk"
    for a in assets:
        if (a.get("name") or "") == preferred:
            u = a.get("browser_download_url")
            if u:
                return str(u), ""
    for a in assets:
        n = a.get("name") or ""
        if n.endswith(".apk"):
            u = a.get("browser_download_url")
            if u:
                return str(u), ""
    return None, "В релизе нет .apk — подожди, пока сборка выложит файл."


def download_apk_to_file(
    owner_repo: str,
    dest_file: Path,
    *,
    token: Optional[str] = None,
) -> Tuple[bool, str]:
    url, err = get_apk_asset_download_url(owner_repo, token=token)
    if not url:
        return False, err
    dest_file = dest_file.expanduser()
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/octet-stream")
    req.add_header("User-Agent", "PortalDesktop/1.0")
    tok = (token or "").strip()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    tmp = dest_file.with_suffix(dest_file.suffix + ".part")
    try:
        try:
            tmp.unlink()
        except OSError:
            pass
        with urllib.request.urlopen(req, timeout=900) as resp:
            with open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out, length=256 * 1024)
        tmp.replace(dest_file)
        return True, str(dest_file)
    except Exception as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False, str(e)


def dispatch_android_apk_workflow(
    owner_repo: str,
    token: str,
    *,
    ref: str = "main",
    workflow_file: str = DEFAULT_WORKFLOW_FILE,
) -> Tuple[bool, str]:
    """
    POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches
    """
    token = (token or "").strip()
    if not token:
        return False, "Нет токена (PORTAL_GITHUB_TOKEN)"
    o, r = _split_owner_repo(owner_repo)

    url = f"https://api.github.com/repos/{o}/{r}/actions/workflows/{workflow_file}/dispatches"
    body = json.dumps({"ref": ref}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code in (200, 201, 204):
                return (
                    True,
                    "Сборка запущена. Через ~10–40 мин нажми «Скачать APK» или открой релиз на GitHub.",
                )
            return True, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            detail = str(e)
        return False, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return False, str(e)
