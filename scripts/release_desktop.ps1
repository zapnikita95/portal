<#
.SYNOPSIS
  Подготовка релиза десктопного Portal для GitHub (Windows ZIP + macOS через CI).

.DESCRIPTION
  1) (Опционально) Поднимает PORTAL_DESKTOP_VERSION в portal_config.py и CFBundleShortVersionString в pyinstaller_portal.spec.
  2) Коммит и push текущей ветки.
  3) Создаёт аннотированный тег vX.Y.Z и пушит его на origin.

  После push тега workflow собирает PortalSetup.exe (Inno), Portal-Windows.zip и macOS — публикует GitHub Release;
  в приложении кнопка обновления откроет загрузку PortalSetup.exe (Windows).

.PARAMETER BuildInstaller
  Вместе с -LocalBuild: после PyInstaller вызвать ISCC.exe (Inno Setup 6) → dist\PortalSetup.exe.

  Локальная сборка PyInstaller здесь НЕ загружает ZIP на GitHub; загрузку делает только Actions.

.PARAMETER Version
  Версия без префикса v, например 1.2.0. Тег будет v1.2.0.

.PARAMETER BumpConfig
  Записать эту версию в portal_config.py и pyinstaller_portal.spec (macOS plist в spec).

.PARAMETER LocalBuild
  После bump (если был) запустить: pip, generate_branding_icons, pyinstaller — проверка перед push.

.PARAMETER SkipCommit
  Не делать git commit (только тег, если версия уже закоммичена).

.PARAMETER SkipPush
  Ничего не пушить (только показать команды).

.PARAMETER DryRun
  Печать шагов без изменения файлов и без git write.

.EXAMPLE
  .\scripts\release_desktop.ps1 -Version 1.2.0 -BumpConfig
  # затем дождаться зелёного workflow: Actions → Portal Desktop Build
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [switch]$BumpConfig,
    [switch]$LocalBuild,
    [switch]$BuildInstaller,
    [switch]$SkipCommit,
    [switch]$SkipPush,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

$ver = $Version.Trim().TrimStart("v", "V")
if ($ver -notmatch '^\d+\.\d+\.\d+') {
    Write-Error "Version должен быть semver вида 1.2.0 (букв v не нужно). Сейчас: $Version"
}
$tag = "v$ver"

Write-Step "Релиз десктопа: версия $ver, тег $tag"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git не найден в PATH"
}

$dirty = git status --porcelain
if ($dirty -and -not $BumpConfig) {
    Write-Warning "Рабочее дерево не чистое. Закоммитьте или используйте -BumpConfig после stash."
}

if ($BumpConfig) {
    Write-Step "Обновление версии в portal_config.py и pyinstaller_portal.spec"
    $cfg = Join-Path $Root "portal_config.py"
    $spec = Join-Path $Root "pyinstaller_portal.spec"
    if (-not (Test-Path $cfg)) { Write-Error "Нет $cfg" }
    if (-not (Test-Path $spec)) { Write-Error "Нет $spec" }

    $enc = New-Object System.Text.UTF8Encoding $false
    $c = [System.IO.File]::ReadAllText($cfg, $enc)
    $c2 = $c -replace 'PORTAL_DESKTOP_VERSION = "[^"]*"', "PORTAL_DESKTOP_VERSION = `"$ver`""
    if ($c -eq $c2) { Write-Error "Не удалось заменить PORTAL_DESKTOP_VERSION в portal_config.py" }

    $s = [System.IO.File]::ReadAllText($spec, $enc)
    $s2 = $s -replace '"CFBundleShortVersionString":\s*"[^"]*"', "`"CFBundleShortVersionString`": `"$ver`""
    if ($s -eq $s2) { Write-Warning "CFBundleShortVersionString в spec не заменён (проверьте формат файла)." }

    if (-not $DryRun) {
        [System.IO.File]::WriteAllText($cfg, $c2, $enc)
        if ($s -ne $s2) { [System.IO.File]::WriteAllText($spec, $s2, $enc) }
    }
}

if ($LocalBuild) {
    Write-Step "Локальная сборка (проверка)"
    if ($DryRun) {
        Write-Host "  [DryRun] python -m pip install ... ; pyinstaller ..."
    }
    else {
        python -m pip install --upgrade pip
        pip install -r requirements.txt pyinstaller pillow pywin32
        python scripts/generate_branding_icons.py
        pyinstaller -y pyinstaller_portal.spec
        Write-Host "Готово: dist\Portal\Portal.exe" -ForegroundColor Green
    }
}

if ($BuildInstaller) {
    if (-not $LocalBuild) {
        Write-Error "Укажите -LocalBuild вместе с -BuildInstaller (нужна папка dist\Portal)."
    }
    Write-Step "Inno Setup → dist\PortalSetup.exe"
    if ($DryRun) {
        Write-Host "  [DryRun] ISCC installer\PortalSetup.iss /DMyAppVersion=$ver"
    }
    else {
        $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (-not (Test-Path $iscc)) { $iscc = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe" }
        if (-not (Test-Path $iscc)) {
            Write-Error "Не найден ISCC.exe. Установите Inno Setup 6: https://jrsoftware.org/isdl.php"
        }
        & $iscc "installer\PortalSetup.iss" "/DMyAppVersion=$ver"
        if (-not (Test-Path "dist\PortalSetup.exe")) { Write-Error "Не создан dist\PortalSetup.exe" }
        Write-Host "Готово: dist\PortalSetup.exe" -ForegroundColor Green
    }
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -eq "HEAD") {
    Write-Error "Detached HEAD — переключитесь на ветку (main/master)."
}

if ($BumpConfig -and $SkipCommit) {
    Write-Error "Нельзя -BumpConfig вместе с -SkipCommit: сначала закоммитьте версию, иначе в теге будет старый код."
}

if (-not $SkipCommit -and $BumpConfig -and -not $DryRun) {
    Write-Step "git add + commit"
    git add portal_config.py
    if (Test-Path (Join-Path $Root "pyinstaller_portal.spec")) {
        git add pyinstaller_portal.spec
    }
    git commit -m "release: desktop $ver"
}
elseif (-not $SkipCommit -and $BumpConfig) {
    Write-Host "[DryRun] git add portal_config.py pyinstaller_portal.spec && git commit -m release: desktop $ver"
}

if (-not $DryRun) {
    $exists = git tag -l $tag
    if ($exists) {
        Write-Error "Тег $tag уже существует. Удалите его локально/на remote или выберите другую версию."
    }
}

if (-not $SkipPush -and -not $DryRun) {
    Write-Step "Push ветки $branch"
    git push origin $branch
    Write-Step "Создание тега $tag и push (запуск CI релиза)"
    git tag -a $tag -m "Portal Desktop $tag"
    git push origin $tag
    Write-Host "`nОк. Actions → Portal Desktop Build → release: PortalSetup.exe, ZIP, macOS." -ForegroundColor Green
    $url = (git remote get-url origin).Trim()
    if ($url -match "github\.com[:/]([^/]+)/([^/.]+)") {
        Write-Host "  https://github.com/$($matches[1])/$($matches[2])/actions/workflows/portal-desktop-release.yml" -ForegroundColor Green
    }
}
elseif ($SkipPush -or $DryRun) {
    Write-Step "Пуш пропущен. Выполните вручную:"
    Write-Host "  git push origin $branch"
    Write-Host "  git tag -a $tag -m `"Portal Desktop $tag`""
    Write-Host "  git push origin $tag"
}

Write-Host "`nПроверка обновлений в приложении: latest GitHub Release с тегом новее PORTAL_DESKTOP_VERSION." -ForegroundColor DarkGray
