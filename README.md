# Art Auction

Онлайн-аукцион для продажи произведений искусства. Пользователи могут создавать лоты, делать ставки и просматривать историю аукционов.

## Функциональность
- Регистрация и авторизация пользователей.
- Создание лотов с изображениями и отложенным стартом.
- Ставки в реальном времени с форматированием цен.
- Отображение статуса аукциона (активен, ещё не начался, завершён).
- Профиль пользователя с историей лотов и ставок.

## Технологии
- **Backend**: Flask, SQLAlchemy, PostgreSQL (по умолчанию через `DATABASE_URL`), SQLite (fallback)
- **Frontend**: Bootstrap, Jinja2, JavaScript
- **Развёртывание**: Render

## Установка
1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/TwelveHeavens/art-auction.git
   cd art-auction

2. Создайте виртуально окружение:
    python -m venv venv
    source venv/bin/activate  # Linux/Mac
    venv\Scripts\activate     # Windows

3. Установите зависимости:
    pip install -r requirements.txt

4. Настройте базу данных:
   - Создайте файл `.env` в корне проекта (рядом с `app.py`) и добавьте строку:
     ```
     DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/auction
     ```
     Замените `user`/`password` и хост/порт на ваши параметры PostgreSQL.  
     Если PostgreSQL запущен в Docker, используйте адрес `localhost`, `127.0.0.1` или `host.docker.internal` (для Windows/Mac) и проброшенный порт контейнера. Создайте БД командой `psql -c "CREATE DATABASE auction;"` (например, через `docker exec -it <postgres_container> psql -U postgres`).
     Файл `.env` автоматически подхватывается приложением и Alembic.
   - **SQLite (fallback)**: если `DATABASE_URL` отсутствует, приложение использует локальный файл `instance/auction.db`.

5. Примените миграции (если используете PostgreSQL):
    alembic upgrade head

6. Запустите приложение:
    python app.py

## Развёртывание
Проект развёрнут на Render 
