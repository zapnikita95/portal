"""
Ссылки и API GitHub для сборки Android APK (workflow_dispatch).
Токен только из окружения PORTAL_GITHUB_TOKEN (scope: repo + workflow).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Tuple

DEFAULT_WORKFLOW_FILE = "portal-android-apk.yml"


def actions_workflow_page_url(owner_repo: str, workflow_file: str = DEFAULT_WORKFLOW_FILE) -> str:
    o, _, r = owner_repo.strip().partition("/")
    if not o or not r:
        raise ValueError("github_repo должен быть вида owner/repo")
    return f"https://github.com/{o}/{r}/actions/workflows/{workflow_file}"


def actions_runs_page_url(owner_repo: str) -> str:
    o, _, r = owner_repo.strip().partition("/")
    if not o or not r:
        raise ValueError("github_repo должен быть вида owner/repo")
    return f"https://github.com/{o}/{r}/actions"


def dispatch_android_apk_workflow(
    owner_repo: str,
    token: str,
    *,
    ref: str = "main",
    workflow_file: str = DEFAULT_WORKFLOW_FILE,
) -> Tuple[bool, str]:
    """
    POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches
    workflow_file: имя файла в .github/workflows (например portal-android-apk.yml).
    """
    token = (token or "").strip()
    if not token:
        return False, "Нет токена (PORTAL_GITHUB_TOKEN)"
    o, _, r = owner_repo.strip().partition("/")
    if not o or not r:
        return False, "Некорректный github_repo (нужно owner/repo)"

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
                return True, "Сборка запущена. Через ~10–40 мин открой Actions → последний run → Artifacts."
            return True, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            detail = str(e)
        return False, f"GitHub API {e.code}: {detail}"
    except Exception as e:
        return False, str(e)
