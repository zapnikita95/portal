Медиа для шапки приложения (Kivy AsyncImage):
  - portal_main.gif  (предпочтительно) или
  - icon.png

Положи файлы сюда, в portal-android/assets/, перед buildozer.
Иконки можно сгенерировать из репозитория: python3 scripts/generate_branding_icons.py
(затем скопируй нужное в эту папку).

Без этих файлов в APK в шапке будет пустой/белый квадрат — это не баг шрифта.
