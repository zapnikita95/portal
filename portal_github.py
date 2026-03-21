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

    Сначала запрос **без** Authorization: публичный репозиторий так всегда работает.
    Если в .env лежит битый/просроченный PAT, запрос *с* Bearer даёт 401 — из‑за этого
    «Скачать APK» ломался при том, что релиз на GitHub есть.
    При 404 повторяем **с** токеном (приватный репозиторий).
    """
    o, r = _split_owner_repo(owner_repo)
    api = f"https://api.github.com/repos/{o}/{r}/releases/tags/{APK_RELEASE_TAG}"
    tok = (token or "").strip()

    def _release_json(with_auth: bool) -> dict:
        req = urllib.request.Request(api, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "PortalDesktop/1.0")
        if with_auth and tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    data: Optional[dict] = None
    try:
        data = _release_json(False)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(e)
        if e.code == 404 and tok:
            try:
                data = _release_json(True)
            except urllib.error.HTTPError as e2:
                try:
                    d2 = e2.read().decode("utf-8", errors="replace")[:400]
                except Exception:
                    d2 = str(e2)
                if e2.code == 404:
                    return None, (
                        "Релиза с APK нет или нет доступа (тег portal-android-latest). "
                        "Для приватного репо нужен валидный PORTAL_GITHUB_TOKEN (repo)."
                    )
                return None, f"GitHub API {e2.code}: {d2}"
        else:
            if e.code == 404:
                return None, (
                    "Релиза с APK пока нет (тег portal-android-latest). "
                    "Нажми «Собрать на GitHub», дождись CI и скачай снова."
                )
            return None, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return None, str(e)

    if not isinstance(data, dict):
        return None, "Некорректный ответ GitHub API"

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
    tok = (token or "").strip()

    def _open_asset(with_auth: bool):
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/octet-stream")
        req.add_header("User-Agent", "PortalDesktop/1.0")
        if with_auth and tok:
            req.add_header("Authorization", f"Bearer {tok}")
        return urllib.request.urlopen(req, timeout=900)

    tmp = dest_file.with_suffix(dest_file.suffix + ".part")
    try:
        try:
            tmp.unlink()
        except OSError:
            pass
        try:
            resp = _open_asset(False)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and tok:
                resp = _open_asset(True)
            else:
                raise
        try:
            with resp:
                with open(tmp, "wb") as out:
                    shutil.copyfileobj(resp, out, length=256 * 1024)
        except urllib.error.HTTPError:
            raise
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
