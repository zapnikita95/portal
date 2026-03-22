# GitHub API / токен (для разработчиков)

Нужно, если из настольного Portal жмёшь **«Собрать на GitHub»** или хочешь дергать Actions API из скрипта.

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Включи **`repo`** (для приватного репо обязательно) и **`workflow`** (иначе GitHub отклонит push в `.github/workflows/`).
3. Передай окружению перед запуском: `export PORTAL_GITHUB_TOKEN="ghp_…"` (не коммить в репозиторий).

Пуш по HTTPS с тем же PAT: без scope **`workflow`** будет ошибка вида *refusing to allow a Personal Access Token… without workflow scope*. Альтернатива — **SSH** (`git@github.com:…`).

Обход без PAT в git: один раз создать workflow-файл через веб-редактор на GitHub.

Шаблон workflow для legacy Kivy: [`portal-android/github-workflow-portal-android-apk.yml`](../portal-android/github-workflow-portal-android-apk.yml).
