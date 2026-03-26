"""
GitHub: сборка Android APK (workflow_dispatch) и скачивание готового APK из Release.

Токен PORTAL_GITHUB_TOKEN (scope: repo + workflow) — только для запуска workflow и приватных репо.
Публичный репозиторий: API релиза и скачивание работают без токена (лимит 60 запросов/час с одного IP).
"""

from __future__ import annotations

import json
import shutil
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_WORKFLOW_FILE = "portal-android-apk.yml"


def _github_ssl_context() -> ssl.SSLContext:
    """
    На macOS «голый» python.org часто без цепочки в Keychain → CERTIFICATE_VERIFY_FAILED.
    certifi даёт актуальный bundle CA.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return ctx


def _urlopen(
    req: urllib.request.Request,
    *,
    timeout: float,
):
    return urllib.request.urlopen(req, timeout=timeout, context=_github_ssl_context())


# Должны совпадать с шагом «Publish to GitHub Release» в .github/workflows/portal-android-apk.yml
APK_RELEASE_TAG = "portal-android-latest"
# Flutter: .github/workflows/portal-flutter.yml → Portal-Flutter.apk
FLUTTER_RELEASE_TAG = "portal-flutter-latest"


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


def flutter_release_page_url(owner_repo: str) -> str:
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/releases/tag/{FLUTTER_RELEASE_TAG}"


def all_releases_page_url(owner_repo: str) -> str:
    """Страница всех релизов (десктоп DMG/ZIP, Flutter APK и т.д.)."""
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/releases"


FLUTTER_WORKFLOW_FILE = "portal-flutter.yml"


def portal_flutter_workflow_url(owner_repo: str) -> str:
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/actions/workflows/{FLUTTER_WORKFLOW_FILE}"


def ios_install_guide_url(owner_repo: str) -> str:
    """Ссылка на инструкцию установки iOS в репозитории (Markdown на GitHub)."""
    o, r = _split_owner_repo(owner_repo)
    return f"https://github.com/{o}/{r}/blob/main/portal_flutter/IOS_INSTALL.md"


def get_release_apk_asset_download_url(
    owner_repo: str,
    release_tag: str,
    preferred_apk_name: str,
    *,
    token: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    browser_download_url для .apk из релиза с заданным тегом.
    Сначала запрос без Authorization; при 404 с токеном — для приватного репо.
    """
    o, r = _split_owner_repo(owner_repo)
    api = f"https://api.github.com/repos/{o}/{r}/releases/tags/{release_tag}"
    tok = (token or "").strip()

    def _release_json(with_auth: bool) -> dict:
        req = urllib.request.Request(api, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "PortalDesktop/1.0")
        if with_auth and tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with _urlopen(req, timeout=60) as resp:
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
                        f"Релиза с APK нет или нет доступа (тег {release_tag}). "
                        "Для приватного репо нужен валидный PORTAL_GITHUB_TOKEN (repo)."
                    )
                return None, f"GitHub API {e2.code}: {d2}"
        else:
            if e.code == 404:
                return None, (
                    f"Релиза с APK пока нет (тег {release_tag}). "
                    "Запусти CI (Actions), дождись сборки и скачай снова."
                )
            return None, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return None, str(e)

    if not isinstance(data, dict):
        return None, "Некорректный ответ GitHub API"

    assets = data.get("assets") or []
    preferred = preferred_apk_name
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


def get_apk_asset_download_url(
    owner_repo: str,
    *,
    token: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    return get_release_apk_asset_download_url(
        owner_repo,
        APK_RELEASE_TAG,
        "Portal-Android.apk",
        token=token,
    )


def get_flutter_apk_asset_download_url(
    owner_repo: str,
    *,
    token: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    return get_release_apk_asset_download_url(
        owner_repo,
        FLUTTER_RELEASE_TAG,
        "Portal-Flutter.apk",
        token=token,
    )


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
        return _urlopen(req, timeout=900)

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


def download_flutter_apk_to_file(
    owner_repo: str,
    dest_file: Path,
    *,
    token: Optional[str] = None,
) -> Tuple[bool, str]:
    url, err = get_flutter_apk_asset_download_url(owner_repo, token=token)
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
        return _urlopen(req, timeout=900)

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
        with _urlopen(req, timeout=90) as resp:
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


def fetch_latest_release_json(owner_repo: str) -> Tuple[Optional[dict], str]:
    """GET /releases/latest — публичный репо без токена (лимит 60/час)."""
    o, r = _split_owner_repo(owner_repo)
    api = f"https://api.github.com/repos/{o}/{r}/releases/latest"
    req = urllib.request.Request(api, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "PortalDesktop/UpdateCheck")
    try:
        with _urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        return (data if isinstance(data, dict) else None), ""
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "Релизов пока нет (404)."
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(e)
        return None, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return None, str(e)


def _parse_semver_tuple(s: str) -> Tuple[int, ...]:
    t = (s or "").strip().lstrip("vV")
    parts: List[int] = []
    for chunk in t.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def version_a_newer_than_b(tag_or_version_a: str, plain_b: str) -> bool:
    """Сравнение v1.2.3 с 1.2.0."""
    ta = _parse_semver_tuple(tag_or_version_a)
    tb = _parse_semver_tuple(plain_b)
    return ta > tb


def pick_desktop_download_url(release: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Предпочтение: Portal.dmg, Portal-macOS.dmg (CI), Portal-macOS.zip; на Windows — Portal-Windows.zip.
    Возвращает (url, имя_файла).
    """
    import sys

    assets = release.get("assets") or []
    names_urls = [(str(a.get("name") or ""), str(a.get("browser_download_url") or "")) for a in assets]
    names_urls = [(n, u) for n, u in names_urls if n and u]

    def pick(*candidates: str) -> Tuple[Optional[str], Optional[str]]:
        for want in candidates:
            for n, u in names_urls:
                if n == want:
                    return u, n
        return None, None

    if sys.platform == "darwin":
        u, n = pick("Portal.dmg", "Portal-macOS.dmg", "Portal-macOS.zip")
        if u:
            return u, n
    elif sys.platform == "win32":
        u, n = pick("PortalSetup.exe", "Portal-Windows.zip")
        if u:
            return u, n
    # fallback: любой zip/dmg из релиза
    for n, u in names_urls:
        if n.endswith(".dmg") or n.endswith(".zip"):
            return u, n
    html = release.get("html_url")
    if isinstance(html, str) and html.startswith("http"):
        return html, "releases"
    return None, None
