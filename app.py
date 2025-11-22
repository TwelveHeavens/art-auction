import os
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import imghdr
import magic

def allowed_image(filename):
    """Проверяет, разрешён ли формат изображения."""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_valid_image(filepath):
    mime = magic.from_file(filepath, mime=True)
    return mime in ['image/png', 'image/jpeg', 'image/gif']

def format_time_until(end_time_moscow, now_moscow):
    """Возвращает строку: 'До окончания: ~2 ч' или 'Завершится сейчас!'"""
    if end_time_moscow <= now_moscow:
        return "Аукцион завершён"
    
    delta = end_time_moscow - now_moscow
    total_seconds = int(delta.total_seconds())
    
    if total_seconds <= 0:
        return "Завершится сейчас!"
    elif total_seconds > 3600:
        hours = total_seconds // 3600
        return f"До окончания: ~{hours} ч"
    elif total_seconds > 60:
        minutes = total_seconds // 60
        return f"До окончания: ~{minutes} мин"
    else:
        return "Завершится сейчас!"


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, '.env')
if os.path.exists(DOTENV_PATH):
    load_dotenv(DOTENV_PATH)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key-for-local')
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)  # Создаём папку instance/

# Базовая SQLite БД (fallback)
sqlite_path = f"sqlite:///{os.path.join(INSTANCE_DIR, 'auction.db')}"

# Основная БД берётся из переменной окружения DATABASE_URL (PostgreSQL),
# при её отсутствии используется SQLite. Дополнительно удаляем неразрывные
# пробелы, которые могут появиться при копировании строки из редактора/браузера.
def _sanitize_database_url(url: str | None) -> str | None:
    if not url:
        return None
    # Удаляем все не-ASCII символы (неразрывные пробелы и т.п.) и пробелы по краям
    ascii_only = ''.join(ch for ch in url if ord(ch) < 128)
    return ascii_only.strip() or None


raw_database_url = os.getenv('DATABASE_URL')
cleaned_database_url = _sanitize_database_url(raw_database_url)

def _ensure_psycopg_driver(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith('postgresql://'):
        return 'postgresql+psycopg://' + url[len('postgresql://'):]
    return url

cleaned_database_url = _ensure_psycopg_driver(cleaned_database_url)

app.config['SQLALCHEMY_DATABASE_URI'] = cleaned_database_url or sqlite_path
db_uri = app.config['SQLALCHEMY_DATABASE_URI']
non_ascii_positions = [(idx, hex(ord(ch))) for idx, ch in enumerate(db_uri) if ord(ch) >= 128]
print(f"Используемая БД: {db_uri!r}")
print(f"Длина строки подключения: {len(db_uri)}")
print(f"Непечатные символы (позиция, код): {non_ascii_positions}")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Московский часовой пояс
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Модель пользователя
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Модель профиля пользователя
class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(100), nullable=True)

# Модель лота
class Lot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    start_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float, nullable=False)
    images = db.relationship('LotImage', backref='lot', lazy=True, cascade='all, delete-orphan')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    start_time = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC))
    end_time = db.Column(db.DateTime, nullable=False)

    def is_active(self):
        start_time_aware = self.start_time.replace(tzinfo=pytz.UTC)
        end_time_aware = self.end_time.replace(tzinfo=pytz.UTC)
        now = datetime.now(pytz.UTC)
        return start_time_aware <= now < end_time_aware
    
    def can_edit(self):
        now = datetime.now(pytz.UTC)
        start_time_aware = self.start_time.replace(tzinfo=pytz.UTC)
        return start_time_aware > now

    def get_winner(self):
        if not self.is_active() and self.end_time.replace(tzinfo=pytz.UTC) <= datetime.now(pytz.UTC):
            highest_bid = Bid.query.filter_by(lot_id=self.id).order_by(Bid.amount.desc()).first()
            if highest_bid:
                return User.query.get(highest_bid.user_id)
        return None

    def created_at_moscow(self):
        return self.created_at.replace(tzinfo=pytz.UTC).astimezone(MOSCOW_TZ)

    def start_time_moscow(self):
        return self.start_time.replace(tzinfo=pytz.UTC).astimezone(MOSCOW_TZ)

    def end_time_moscow(self):
        return self.end_time.replace(tzinfo=pytz.UTC).astimezone(MOSCOW_TZ)
    

# Модель ставки
class Bid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey('lot.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))

    def created_at_moscow(self):
        return self.created_at.replace(tzinfo=pytz.UTC).astimezone(MOSCOW_TZ)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('welcome'))
    # Получаем параметры из URL
    status = request.args.get('status', 'all')  # all, active, pending, ended
    sort = request.args.get('sort', 'newest')   # newest, oldest, price_low, price_high

    query = Lot.query

    now_utc = datetime.now(pytz.UTC)

    # Фильтрация по статусу
    if status == 'active':
        query = query.filter(Lot.start_time <= now_utc, Lot.end_time > now_utc)
    elif status == 'pending':
        query = query.filter(Lot.start_time > now_utc)
    elif status == 'ended':
        query = query.filter(Lot.end_time <= now_utc)
    else: 'all' # — не фильтруем

    # Сортировка
    if sort == 'oldest':
        query = query.order_by(Lot.created_at.asc())
    elif sort == 'price_low':
        query = query.order_by(Lot.current_price.asc())
    elif sort == 'price_high':
        query = query.order_by(Lot.current_price.desc())
    else:  # newest
        query = query.order_by(Lot.created_at.desc())

    lots = query.all()
    lot_count = len(lots)
    now_moscow = datetime.now(MOSCOW_TZ)

    return render_template(
        'index.html',
        lots=lots,
        moscow_tz=MOSCOW_TZ,
        now_moscow=now_moscow,
        current_status=status,
        current_sort=sort,
        lot_count=lot_count
    )

class LotImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey('lot.id'), nullable=False)

    def url(self):
        return url_for('static', filename='uploads/' + self.filename)

@app.route('/welcome')
def welcome():
    now_moscow = datetime.now(MOSCOW_TZ)
    featured_lots = Lot.query.filter(Lot.end_time > datetime.now(pytz.UTC)).order_by(Lot.created_at.desc()).limit(3).all()
    
    # Добавим вычисления для каждого лота
    for lot in featured_lots:
        lot.time_until_str = format_time_until(lot.end_time_moscow(), now_moscow)
    
    return render_template('welcome.html', featured_lots=featured_lots, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Пользователь уже существует!')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        profile = Profile(user_id=user.id)
        db.session.add(profile)
        db.session.commit()
        flash('Регистрация успешна! Войдите в систему.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль!')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('welcome'))

@app.route('/add_lot', methods=['GET', 'POST'])
@login_required
def add_lot():
    if request.method == 'POST':
        # Получаем данные из формы
        title = request.form['title']
        description = request.form['description']
        start_price = float(request.form['start_price'].replace(' ', ''))

        # === 1. Время старта (новая логика) ===
        start_time_str = request.form['start_time']  # формат: "2025-11-21T15:30"
        start_time_naive = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
        start_time_moscow = MOSCOW_TZ.localize(start_time_naive)
        start_time_utc = start_time_moscow.astimezone(pytz.UTC)

        # === 2. Длительность ===
        duration_type = request.form['duration_type']
        duration_value = int(request.form['duration_value'])

        if duration_value < 1:
            flash('Длительность аукциона должна быть не менее 1!', 'danger')
            return redirect(url_for('add_lot'))

        if duration_type == 'minutes':
            delta = timedelta(minutes=duration_value)
        elif duration_type == 'hours':
            delta = timedelta(hours=duration_value)
        else:  # days
            delta = timedelta(days=duration_value)

        end_time_utc = start_time_utc + delta

        # === 3. Загрузка изображений ===
        files = request.files.getlist('images')
        saved_filenames = []

        for file in files:
            if file and file.filename:
                if not allowed_image(file.filename):
                    flash('Разрешены только изображения: PNG, JPG, JPEG.', 'danger')
                    return redirect(url_for('add_lot'))

                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)

                if not is_valid_image(filepath):
                    os.remove(filepath)
                    flash('Один из файлов не является изображением.', 'danger')
                    return redirect(url_for('add_lot'))

                if os.path.getsize(filepath) > 10 * 1024 * 1024:
                    os.remove(filepath)
                    flash('Один из файлов слишком большой. Максимум 10 МБ.', 'danger')
                    return redirect(url_for('add_lot'))

                saved_filenames.append(filename)

        # === 4. Создание лота ===
        lot = Lot(
            title=title,
            description=description,
            start_price=start_price,
            current_price=start_price,
            user_id=current_user.id,
            start_time=start_time_utc,
            end_time=end_time_utc
        )
        db.session.add(lot)
        db.session.flush()  # Получаем lot.id

        for filename in saved_filenames:
            lot_image = LotImage(filename=filename, lot_id=lot.id)
            db.session.add(lot_image)

        db.session.commit()
        flash('Лот добавлен!', 'success')
        return redirect(url_for('index'))

    return render_template('add_lot.html')

@app.route('/lot/<int:lot_id>', methods=['GET', 'POST'])
def lot_detail(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    bids = Bid.query.filter_by(lot_id=lot_id).order_by(Bid.created_at.desc()).all()
    winner = lot.get_winner()
    now_moscow = datetime.now(MOSCOW_TZ)
    print(f"Lot {lot.id}: start_time={lot.start_time}, end_time={lot.end_time}, "
          f"start_time_moscow={lot.start_time_moscow()}, end_time_moscow={lot.end_time_moscow()}, "
          f"now_moscow={now_moscow}, is_active={lot.is_active()}")
    if request.method == 'POST' and current_user.is_authenticated:
        if lot.user_id == current_user.id:
            flash('Вы не можете делать ставки на свой собственный лот!')
            return redirect(url_for('lot_detail', lot_id=lot.id))
        if not lot.is_active():
            flash('Аукцион завершён или ещё не начался!')
            return redirect(url_for('lot_detail', lot_id=lot.id))
        bid_amount = float(request.form['bid_amount'].replace(' ', ''))
        if bid_amount > lot.current_price:
            lot.current_price = bid_amount
            bid = Bid(amount=bid_amount, lot_id=lot.id, user_id=current_user.id)
            db.session.add(bid)
            db.session.commit()
            flash('Ставка принята!')
        else:
            flash('Ваша ставка должна быть выше текущей!')
        return redirect(url_for('lot_detail', lot_id=lot.id))
    return render_template('lot_detail.html', lot=lot, bids=bids, winner=winner, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)


#  Функционал редактирования и удаления лота
# Редактирование лота
@app.route('/lot/<int:lot_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if lot.user_id != current_user.id:
        flash('Нельзя редактировать чужой лот.', 'danger')
        return redirect(url_for('lot_detail', lot_id=lot_id))
    if not lot.can_edit():
        flash('Нельзя редактировать лот после начала аукциона.', 'warning')
        return redirect(url_for('lot_detail', lot_id=lot_id))

    if request.method == 'POST':
        lot.title = request.form['title']
        lot.description = request.form['description']
        lot.start_price = float(request.form['start_price'].replace(' ', ''))
        lot.current_price = lot.start_price  # сбрасываем текущую цену

        # Обработка времени
        start_delay = int(request.form.get('start_delay', 0))
        duration_type = request.form['duration_type']
        duration_value = int(request.form['duration_value'])

        if duration_value < 1:
            flash('Длительность аукциона должна быть не менее 1!')
            return redirect(url_for('edit_lot', lot_id=lot_id))

        if duration_type == 'minutes':
            delta = timedelta(minutes=duration_value)
        elif duration_type == 'hours':
            delta = timedelta(hours=duration_value)
        else:
            delta = timedelta(days=duration_value)

        # Новое время старта = сейчас + отсрочка
        start_time = datetime.now(MOSCOW_TZ) + timedelta(hours=start_delay)
        start_time_utc = start_time.astimezone(pytz.UTC)
        end_time = start_time + delta
        end_time_utc = end_time.astimezone(pytz.UTC)

        lot.start_time = start_time_utc
        lot.end_time = end_time_utc

        # Обновление изображения (опционально)
        file = request.files.get('image')
        if file and file.filename:
            if not allowed_image(file.filename):
                flash('Разрешены только изображения: PNG, JPG, JPEG.', 'danger')
                return redirect(url_for('edit_lot', lot_id=lot_id))

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            if not is_valid_image(filepath):
                os.remove(filepath)
                flash('Файл не является изображением.', 'danger')
                return redirect(url_for('edit_lot', lot_id=lot_id))

            if os.path.getsize(filepath) > 10 * 1024 * 1024:
                os.remove(filepath)
                flash('Изображение слишком большое. Максимум 10 МБ.', 'danger')
                return redirect(url_for('edit_lot', lot_id=lot_id))

            lot.image = filename

        db.session.commit()
        flash('Лот успешно обновлён!', 'success')
        return redirect(url_for('lot_detail', lot_id=lot_id))

    return render_template('edit_lot.html', lot=lot)

# Удаление лота
@app.route('/lot/<int:lot_id>/delete', methods=['POST'])
@login_required
def delete_lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if lot.user_id != current_user.id:
        flash('Нельзя удалить чужой лот.', 'danger')
        return redirect(url_for('lot_detail', lot_id=lot_id))
    if not lot.can_edit():
        flash('Нельзя удалить лот после начала аукциона.', 'warning')
        return redirect(url_for('lot_detail', lot_id=lot_id))

    db.session.delete(lot)
    db.session.commit()
    flash('Лот удалён.', 'success')
    return redirect(url_for('my_auctions'))


@app.route('/my_wins')
@login_required
def my_wins():
    won_lots = []
    lots = Lot.query.filter(Lot.end_time < datetime.now(pytz.UTC)).all()
    for lot in lots:
        winner = lot.get_winner()
        if winner and winner.id == current_user.id:
            won_lots.append(lot)
    now_moscow = datetime.now(MOSCOW_TZ)
    return render_template('my_wins.html', won_lots=won_lots, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)

@app.route('/my_auctions')
@login_required
def my_auctions():
    my_lots = Lot.query.filter_by(user_id=current_user.id).all()
    now_moscow = datetime.now(MOSCOW_TZ)
    return render_template('my_auctions.html', my_lots=my_lots, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)

@app.route('/my_bids')
@login_required
def my_bids():
    active_bids = Bid.query.filter_by(user_id=current_user.id).all()
    active_lot_ids = {bid.lot_id for bid in active_bids}
    active_lots = Lot.query.filter(Lot.id.in_(active_lot_ids), Lot.start_time <= datetime.now(pytz.UTC), Lot.end_time > datetime.now(pytz.UTC)).all()
    now_moscow = datetime.now(MOSCOW_TZ)
    return render_template('my_bids.html', active_lots=active_lots, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    profile = Profile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    if request.method == 'POST':
        bio = request.form['bio']
        file = request.files.get('profile_image')
        filename = profile.profile_image
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        profile.bio = bio
        profile.profile_image = filename
        db.session.commit()
        flash('Профиль обновлён!')
        return redirect(url_for('profile'))

    lots_created = Lot.query.filter_by(user_id=current_user.id).count()
    bids_made = Bid.query.filter_by(user_id=current_user.id).count()
    lots_won = len([lot for lot in Lot.query.filter(Lot.end_time < datetime.now(pytz.UTC)).all() if lot.get_winner() and lot.get_winner().id == current_user.id])
    now_moscow = datetime.now(MOSCOW_TZ)
    return render_template('profile.html', profile=profile, lots_created=lots_created, bids_made=bids_made, lots_won=lots_won, now_moscow=now_moscow)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    profile = Profile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = Profile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    if request.method == 'POST':
        bio = request.form.get('bio', '')
        file = request.files.get('profile_image')

        if file and file.filename:
            # 1. Проверка расширения
            if not allowed_image(file.filename):
                flash('Разрешены только изображения: PNG, JPG, JPEG, GIF.', 'danger')
                return redirect(url_for('edit_profile'))

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # 2. Сохраняем временно
            file.save(filepath)

            # 3. Проверка содержимого
            if not is_valid_image(filepath):
                os.remove(filepath)  # Удаляем подозрительный файл
                flash('Файл не является изображением. Загрузите корректное изображение.', 'danger')
                return redirect(url_for('edit_profile'))

            # 4. Проверка размера (опционально, но app.config уже ограничивает)
            if os.path.getsize(filepath) > 10 * 1024 * 1024:  # 5 МБ
                os.remove(filepath)
                flash('Изображение слишком большое. Максимум 10 МБ.', 'danger')
                return redirect(url_for('edit_profile'))

            profile.profile_image = filename

        profile.bio = bio
        db.session.commit()
        flash('Профиль обновлён!', 'success')
        return redirect(url_for('profile'))

    return render_template('edit_profile.html', profile=profile)



def apply_migrations():
    """Применяет миграции Alembic при запуске (для Render)."""
    from alembic.config import Config
    from alembic import command
    import sys
    import os

    # Путь к alembic.ini
    alembic_cfg_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
    if not os.path.exists(alembic_cfg_path):
        print("⚠️ alembic.ini не найден, пропускаем миграции.")
        return

    try:
        alembic_cfg = Config(alembic_cfg_path)
        command.upgrade(alembic_cfg, "head")
        print("✅ Миграции Alembic применены.")
    except Exception as e:
        print(f"❌ Ошибка при применении миграций: {e}")
        sys.exit(1)

if __name__ == '__main__':
    if os.getenv('RENDER'):
        # Render: всегда используем PostgreSQL + миграции
        apply_migrations()
    else:
        # Локально: SQLite или PostgreSQL
        if os.getenv('DATABASE_URL') is None:
            with app.app_context():
                db.create_all()
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 10000)),
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )