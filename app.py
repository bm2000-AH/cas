from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, send
from datetime import datetime
import random
import os

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = 'your_secret_key_here'
socketio = SocketIO(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['UPLOAD_FOLDER'] = 'static/avatars'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    balance = db.Column(db.Integer, default=500)
    avatar = db.Column(db.String(300), nullable=True)
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)

class GameLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    game_type = db.Column(db.String(50))
    bet_amount = db.Column(db.Integer)
    bet_number = db.Column(db.String(10))
    result_number = db.Column(db.String(10))
    win = db.Column(db.Boolean)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='game_logs')

symbol_payout = {"🍒": 2, "🍋": 3, "🔔": 5, "⭐": 8, "7️⃣": 10}

def create_tables():
    db.create_all()

@app.route('/')
def index():
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            avatar_url = url_for('static', filename=f"avatars/{user.avatar}") if user.avatar else None
            return render_template('index.html', username=user.username, balance=user.balance, avatar=avatar_url)
        session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        avatar_file = request.files.get('avatar')

        if User.query.filter_by(username=username).first():
            return render_template('register.html', error="Пользователь уже существует")

        hashed_pw = generate_password_hash(password)
        avatar_filename = None

        if avatar_file and avatar_file.filename:
            filename = secure_filename(avatar_file.filename)
            avatar_filename = f"{username}_{filename}"
            avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename))

        user = User(username=username, password=hashed_pw, avatar=avatar_filename)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        return render_template('login.html', error='Неверные учетные данные')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = db.session.get(User, session['user_id'])

    if request.method == 'POST':
        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename:
            filename = secure_filename(avatar_file.filename)
            avatar_filename = f"{user.username}_{filename}"
            avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename)
            avatar_file.save(avatar_path)
            user.avatar = avatar_filename
            db.session.commit()
            flash("Аватар обновлён!")

    avatar_url = url_for('static', filename=f"avatars/{user.avatar}") if user.avatar else None
    return render_template('profile.html', username=user.username, balance=user.balance,
                           games_played=user.games_played, games_won=user.games_won, avatar=avatar_url)

@app.route('/update_password', methods=['POST'])
def update_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    current = request.form.get('current_password')
    new = request.form.get('new_password')
    if not check_password_hash(user.password, current):
        flash("Неверный текущий пароль.")
    else:
        user.password = generate_password_hash(new)
        db.session.commit()
        flash("Пароль обновлён.")
    return redirect(url_for('profile'))

@app.route('/update_username', methods=['POST'])
def update_username():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    new_name = request.form.get('new_username')
    user = db.session.get(User, session['user_id'])
    if User.query.filter_by(username=new_name).first():
        flash("Этот логин уже занят.")
        return redirect(url_for('profile'))
    if user.avatar and user.avatar.startswith(user.username + "_"):
        new_avatar = new_name + "_" + user.avatar.split("_", 1)[1]
        os.rename(os.path.join(app.config['UPLOAD_FOLDER'], user.avatar),
                  os.path.join(app.config['UPLOAD_FOLDER'], new_avatar))
        user.avatar = new_avatar
    user.username = new_name
    db.session.commit()
    flash("Имя пользователя обновлено.")
    return redirect(url_for('profile'))

@app.route('/slots')
def slots():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('slots.html', balance=db.session.get(User, session['user_id']).balance)

@app.route('/spin', methods=['POST'])
def spin_slot():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'})
    user = db.session.get(User, session['user_id'])
    bet = int(request.json.get("bet", 10))
    if user.balance < bet:
        return jsonify({'error': 'Недостаточно средств'})
    symbols = ["🍒", "🍋", "🔔", "⭐", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    user.balance -= bet
    user.games_played += 1
    win = len(set(result)) == 1
    winnings = bet * 10 if win else 0
    if win:
        user.balance += winnings
        user.games_won += 1
    db.session.add(GameLog(user_id=user.id, game_type='slots', bet_amount=bet, result_number=''.join(result), win=win))
    db.session.commit()
    return jsonify({'result': result, 'win': win, 'winnings': winnings, 'balance': user.balance})

@app.route('/roulette')
def roulette():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('roulette.html', balance=db.session.get(User, session['user_id']).balance)

@app.route('/spin_roulette', methods=['POST'])
def spin_roulette():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'})
    user = db.session.get(User, session['user_id'])
    try:
        bet = int(request.json.get("amount", 10))
        number = int(request.json.get("bet"))
    except (ValueError, TypeError):
        return jsonify({'error': 'Некорректный ввод'})
    if not 1 <= number <= 6:
        return jsonify({'error': 'Число должно быть от 1 до 6'})
    if user.balance < bet:
        return jsonify({'error': 'Недостаточно средств'})
    user.balance -= bet
    rolled = random.randint(1, 6)
    win = (rolled == number)
    if win:
        user.balance += bet * 6
        user.games_won += 1
    user.games_played += 1
    db.session.add(GameLog(user_id=user.id, game_type='roulette', bet_amount=bet,
                           bet_number=str(number), result_number=str(rolled), win=win))
    db.session.commit()
    return jsonify({'number': rolled, 'win': win, 'balance': user.balance})

@app.route('/blackjack')
def blackjack():
    return render_template('blackjack.html', balance=db.session.get(User, session['user_id']).balance)

@app.route('/blackjack_action', methods=['POST'])
def blackjack_action():
    action = request.json.get('action')
    bet = int(request.json.get('bet', 10))

    if 'user_id' not in session:
        return jsonify({'error': 'Вы не авторизованы'})

    user = db.session.get(User, session['user_id'])
    if user.balance < bet:
        return jsonify({'error': 'Недостаточно средств'})

    def create_deck():
        deck = [r + s for r in '23456789TJQKA' for s in '♠♥♦♣']
        random.shuffle(deck)
        return deck

    def value(hand):
        total = sum(11 if c[0] == 'A' else 10 if c[0] in 'JQKT' else int(c[0]) for c in hand)
        aces = sum(1 for c in hand if c[0] == 'A')
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    if action == 'start':
        deck = create_deck()
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        session.update({'deck': deck, 'player': player, 'dealer': dealer, 'bet': bet})
        return jsonify({'player': player, 'dealer': [dealer[0], '?'], 'done': False})

    deck = session.get('deck', [])
    player = session.get('player', [])
    dealer = session.get('dealer', [])

    if action == 'hit':
        if not deck:
            return jsonify({'error': 'Колода пуста, начните новую игру'})
        player.append(deck.pop())
        session['deck'] = deck
        return jsonify({'player': player, 'dealer': [dealer[0], '?'], 'done': value(player) > 21})

    elif action == 'stand':
        while value(dealer) < 17:
            if not deck:
                return jsonify({'error': 'Колода пуста, начните новую игру'})
            dealer.append(deck.pop())
        p_val, d_val = value(player), value(dealer)
        win = p_val <= 21 and (p_val > d_val or d_val > 21)
        result = 'Победа!' if win else 'Проигрыш' if p_val > d_val or p_val > 21 else 'Ничья'
        user.balance -= session['bet']
        if win:
            user.balance += session['bet'] * 2
        db.session.commit()
        for k in ['deck', 'player', 'dealer', 'bet']:
            session.pop(k, None)
        return jsonify({'player': player, 'dealer': dealer, 'result': result, 'balance': user.balance, 'done': True})

    return jsonify({'error': 'Неверное действие'})

@app.route('/donate')
def donate():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    user.balance += 1000
    db.session.commit()
    flash("Бонус получен!")
    return redirect(url_for('profile'))

@app.route('/admin')
def admin():
    return render_template('admin.html', users=User.query.all())

@app.route('/edit_balance', methods=['POST'])
def edit_balance():
    user = db.session.get(User, request.form.get('user_id'))
    if user:
        user.balance = int(request.form.get('new_balance'))
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/block_user', methods=['POST'])
def block_user():
    user = db.session.get(User, request.form.get('user_id'))
    if user:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin'))


@app.route('/mines_result', methods=['POST'])
def mines_result():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'})

    user = db.session.get(User, session['user_id'])
    data = request.get_json()
    bet = int(data.get("bet", 0))
    win = bool(data.get("win", False))
    reward = int(data.get("reward", 0))

    if user.balance < bet:
        return jsonify({'error': 'Недостаточно средств'})

    user.balance -= bet
    if win:
        user.balance += reward
        user.games_won += 1

    user.games_played += 1
    db.session.add(GameLog(
        user_id=user.id,
        game_type='mines',
        bet_amount=bet,
        result_number=str(reward),
        win=win
    ))
    db.session.commit()
    return jsonify({'balance': user.balance})

@app.route('/mines')
def mines():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    return render_template('mines.html', balance=user.balance)


@app.route('/mines_action', methods=['POST'])
def mines_action():
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'})

    user = db.session.get(User, session['user_id'])
    data = request.get_json()
    action = data.get("action")

    if action == "start":
        bet = int(data.get("bet", 0))
        if user.balance < bet:
            return jsonify({'error': 'Недостаточно средств'})

        # Генерация мин (например, 5 случайных ячеек на 5x5 поле)
        mine_count = 5
        grid_size = 25
        mines = random.sample(range(grid_size), mine_count)
        session['mines_game'] = {
            'bet': bet,
            'mines': mines,
            'opened': [],
            'grid': list(range(grid_size))
        }

        user.balance -= bet
        db.session.commit()
        return jsonify({'success': True, 'balance': user.balance})

    elif action == "click":
        index = int(data.get("index"))
        game = session.get("mines_game")
        if not game:
            return jsonify({'error': 'Нет активной игры'})

        if index in game['opened']:
            return jsonify({'error': 'Уже открыта'})

        if index in game['mines']:
            session.pop('mines_game', None)
            return jsonify({'hit_mine': True, 'index': index})

        game['opened'].append(index)
        session['mines_game'] = game
        return jsonify({'safe': True, 'opened': game['opened']})

    elif action == "cashout":
        game = session.get("mines_game")
        if not game:
            return jsonify({'error': 'Нет активной игры'})

        opened = game.get("opened", [])
        bet = game["bet"]

        if not opened:
            return jsonify({'error': 'Нельзя забрать до открытия хоть одной клетки'})

        # Примерная формула: +20% за каждую клетку
        multiplier = 1 + len(opened) * 0.2
        win = round(bet * multiplier)

        user.balance += win
        db.session.commit()

        session.pop("mines_game", None)
        return jsonify({'win': win, 'balance': user.balance})

    return jsonify({'error': 'Неверное действие'})


@app.route('/stats')
def stats():
    return render_template('stats.html',
                           total_games=db.session.query(db.func.sum(User.games_played)).scalar(),
                           total_wins=db.session.query(db.func.sum(User.games_won)).scalar(),
                           total_balance=db.session.query(db.func.sum(User.balance)).scalar())

@app.route('/history')
def game_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    logs = GameLog.query.filter_by(user_id=session['user_id']).order_by(GameLog.timestamp.desc()).limit(50).all()
    return render_template('history.html', logs=logs)

@app.route("/chat")
def chat():
    if 'user_id' not in session:
        return redirect(url_for("login"))
    return render_template("chat.html", username=db.session.get(User, session["user_id"]).username)

@socketio.on('message')
def handle_message(msg):
    print(f"Message: {msg}")
    send(msg, broadcast=True)

if __name__ == '__main__':
    with app.app_context():
        create_tables()
    socketio.run(app, debug=True)
