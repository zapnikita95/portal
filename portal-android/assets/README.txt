Медиа для шапки (слева вверху):
  - icon.png — предпочтительно (та же картинка, что иконка лаунчера; статичный Image, без «круга из точек»).
  - portal_main.gif — если нужен анимированный талисман (AsyncImage).

Положи файлы в portal-android/assets/ перед buildozer.
Сгенерировать: из корня репозитория `python3 scripts/generate_branding_icons.py`,
затем `cp assets/branding/portal_icon.png portal-android/assets/icon.png`.

Без icon.png / gif шапка подхватит ../assets/branding/portal_icon.png при dev-запуске с ПК.
