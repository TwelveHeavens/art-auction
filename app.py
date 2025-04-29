from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # Замените на свой секретный ключ
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'auction.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Максимум 16MB для изображений

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
    image = db.Column(db.String(100), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    start_time = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(pytz.UTC))
    end_time = db.Column(db.DateTime, nullable=False)

    def is_active(self):
        start_time_aware = self.start_time.replace(tzinfo=pytz.UTC)
        end_time_aware = self.end_time.replace(tzinfo=pytz.UTC)
        now = datetime.now(pytz.UTC)
        return start_time_aware <= now < end_time_aware

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

# Создание базы данных
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('welcome'))
    lots = Lot.query.order_by(Lot.created_at.desc()).all()
    now_moscow = datetime.now(MOSCOW_TZ)
    return render_template('index.html', lots=lots, moscow_tz=MOSCOW_TZ, now_moscow=now_moscow)

@app.route('/welcome')
def welcome():
    featured_lots = Lot.query.filter(Lot.end_time > datetime.now(pytz.UTC)).order_by(Lot.created_at.desc()).limit(3).all()
    return render_template('welcome.html', featured_lots=featured_lots, moscow_tz=MOSCOW_TZ)

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
        title = request.form['title']
        description = request.form['description']
        start_price = float(request.form['start_price'].replace(' ', ''))
        duration_type = request.form['duration_type']
        duration_value = int(request.form['duration_value'])
        start_delay = int(request.form.get('start_delay', 0))

        if duration_value < 1:
            flash('Длительность аукциона должна быть не менее 1!')
            return redirect(url_for('add_lot'))

        if duration_type == 'minutes':
            delta = timedelta(minutes=duration_value)
        elif duration_type == 'hours':
            delta = timedelta(hours=duration_value)
        else:
            delta = timedelta(days=duration_value)

        start_time = datetime.now(MOSCOW_TZ) + timedelta(hours=start_delay)
        start_time_utc = start_time.astimezone(pytz.UTC)
        end_time = start_time + delta
        end_time_utc = end_time.astimezone(pytz.UTC)

        file = request.files['image']
        filename = None
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        lot = Lot(
            title=title,
            description=description,
            start_price=start_price,
            current_price=start_price,
            image=filename,
            user_id=current_user.id,
            start_time=start_time_utc,
            end_time=end_time_utc
        )
        db.session.add(lot)
        db.session.commit()
        flash('Лот добавлен!')
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

if __name__ == '__main__':
    app.run(debug=True)