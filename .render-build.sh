#!/usr/bin/env bash
# .render-build.sh

# Устанавливаем зависимости
pip install -r requirements.txt

# Применяем миграции
alembic upgrade head