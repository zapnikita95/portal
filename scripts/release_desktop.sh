#!/usr/bin/env bash
# Релиз десктопа на GitHub: bump версии → commit → push ветки → тег v* → push тега.
# CI: .github/workflows/portal-desktop-release.yml публикует Portal-Windows.zip и macOS.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION=""
BUMP=0
LOCAL_BUILD=0
SKIP_COMMIT=0
SKIP_PUSH=0
DRY_RUN=0

usage() {
  echo "Usage: $0 --version 1.2.0 [--bump] [--local-build] [--skip-commit] [--skip-push] [--dry-run]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --bump) BUMP=1; shift ;;
    --local-build) LOCAL_BUILD=1; shift ;;
    --skip-commit) SKIP_COMMIT=1; shift ;;
    --skip-push) SKIP_PUSH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) usage ;;
  esac
done

[[ -n "$VERSION" ]] || usage
VER="${VERSION#v}"
VER="${VER#V}"
if ! [[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  echo "Version must be semver like 1.2.0" >&2
  exit 1
fi
TAG="v$VER"

if [[ "$BUMP" -eq 1 && "$SKIP_COMMIT" -eq 1 ]]; then
  echo "Cannot use --bump with --skip-commit" >&2
  exit 1
fi

echo "==> Release $VER (tag $TAG)"

if [[ "$BUMP" -eq 1 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] would patch portal_config.py and pyinstaller_portal.spec"
  else
    perl -i -pe "s/PORTAL_DESKTOP_VERSION = \"[^\"]*\"/PORTAL_DESKTOP_VERSION = \"$VER\"/" portal_config.py
    perl -i -pe 's/"CFBundleShortVersionString":\s*"[^"]*"/"CFBundleShortVersionString": "'"$VER"'"/' pyinstaller_portal.spec
  fi
fi

if [[ "$LOCAL_BUILD" -eq 1 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] pyinstaller ..."
  else
    python3 -m pip install --upgrade pip
    pip3 install -r requirements.txt pyinstaller pillow
    python3 scripts/generate_branding_icons.py
    pyinstaller -y pyinstaller_portal.spec
  fi
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" != "HEAD" ]] || { echo "Detached HEAD" >&2; exit 1; }

if [[ "$BUMP" -eq 1 && "$SKIP_COMMIT" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
  git add portal_config.py pyinstaller_portal.spec
  git commit -m "release: desktop $VER"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  if git tag -l "$TAG" | grep -q .; then
    echo "Tag $TAG already exists" >&2
    exit 1
  fi
fi

if [[ "$SKIP_PUSH" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
  git push origin "$BRANCH"
  git tag -a "$TAG" -m "Portal Desktop $TAG"
  git push origin "$TAG"
  echo "Done. Watch: Actions → Portal Desktop Build → release job"
else
  echo "Run manually:"
  echo "  git push origin $BRANCH"
  echo "  git tag -a $TAG -m \"Portal Desktop $TAG\""
  echo "  git push origin $TAG"
fi
