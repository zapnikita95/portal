#!/bin/bash
# Двойной клик в Finder → делегируем полному скрипту (фон + хромакей по умолчанию)
cd "$(dirname "$0")" || exit 1
exec bash "./start_portal.command" "$@"
