# Art Auction

Онлайн-аукцион для продажи произведений искусства. Пользователи могут создавать лоты, делать ставки и просматривать историю аукционов.

## Функциональность
- Регистрация и авторизация пользователей.
- Создание лотов с изображениями и отложенным стартом.
- Ставки в реальном времени с форматированием цен.
- Отображение статуса аукциона (активен, ещё не начался, завершён).
- Профиль пользователя с историей лотов и ставок.

## Технологии
- **Backend**: Flask, SQLAlchemy, SQLite
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

4. Запустите приложение:
    python app.py

## Развёртывание
Проект развёрнут на Render 
