import os, math, uuid, requests
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.urandom(24).hex(),
    SQLALCHEMY_DATABASE_URI='sqlite:///tracker.db',
    UPLOAD_FOLDER='static/avatars',
    MAX_CONTENT_LENGTH=2 * 1024 * 1024
)
YANDEX_KEY = 'f3a0fe3a-b07e-4840-a1da-06f18b2ddf13'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = 'login'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    routes = db.relationship('Route', backref='author', lazy=True, cascade='all, delete-orphan')
    markers = db.relationship('Marker', backref='author', lazy=True, cascade='all, delete-orphan')
    favorites = db.relationship('Favorite', backref='user', lazy=True, cascade='all, delete-orphan')


class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.now)
    dist = db.Column(db.Float, default=0.0)
    points = db.Column(db.Text, nullable=False)
    place_names = db.Column(db.Text, default='')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Marker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    desc = db.Column(db.Text, default='')
    photo = db.Column(db.String(500), default='')
    cat = db.Column(db.String(50), default='other')
    vis = db.Column(db.String(20), default='all')
    created = db.Column(db.DateTime, default=datetime.now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    favorites = db.relationship('Favorite', backref='marker', lazy=True, cascade='all, delete-orphan')


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    marker_id = db.Column(db.Integer, db.ForeignKey('marker.id'), nullable=False)
    created = db.Column(db.DateTime, default=datetime.now)


@login.user_loader
def load_user(uid):
    return User.query.get(int(uid))


with app.app_context():
    db.create_all()


def cookie(k, d=None):
    return request.cookies.get(k, d)


def set_c(r, k, v, d=365):
    r.set_cookie(k, str(v), max_age=60 * 60 * 24 * d)


def map_pos():
    return dict(
        lat=float(cookie('lat', 55.751244)),
        lon=float(cookie('lon', 37.618423)),
        zoom=int(cookie('zoom', 12))
    )


CATS = {
    'park': {'name': 'Парк', 'color': '#22c55e', 'icon': '🌳'},
    'shop': {'name': 'Магазин', 'color': '#f59e0b', 'icon': '🛒'},
    'cafe': {'name': 'Кафе', 'color': '#ef4444', 'icon': '☕'},
    'culture': {'name': 'Культура', 'color': '#8b5cfc', 'icon': '🏛'},
    'other': {'name': 'Другое', 'color': '#6b7280', 'icon': '📍'}
}


@app.route('/')
def index():
    p = map_pos()
    visits = int(cookie('visits', 0)) + 1
    is_new = cookie('first_visit') != 'yes'

    if current_user.is_authenticated:
        markers = Marker.query.filter(
            (Marker.vis == 'all') | (Marker.user_id == current_user.id)
        ).order_by(Marker.created.desc()).all()
    else:
        markers = Marker.query.filter_by(vis='all').order_by(Marker.created.desc()).all()

    r = make_response(render_template('base.html', page='index', map=p, yandex_key=YANDEX_KEY,
                                      visits=visits, new=is_new, dark=cookie('theme', 'dark') == 'dark',
                                      markers=markers, cats=CATS))
    set_c(r, 'visits', visits)
    if is_new:
        set_c(r, 'first_visit', 'yes')
    return r


@app.route('/api/markers')
def api_markers():
    if current_user.is_authenticated:
        markers = Marker.query.filter(
            (Marker.vis == 'all') | (Marker.user_id == current_user.id)
        ).order_by(Marker.created.desc()).all()
    else:
        markers = Marker.query.filter_by(vis='all').order_by(Marker.created.desc()).all()

    return jsonify([{
        'id': m.id,
        'name': m.name,
        'lat': m.lat,
        'lon': m.lon,
        'desc': m.desc,
        'cat': m.cat,
        'color': CATS.get(m.cat, CATS['other'])['color'],
        'vis': m.vis,
        'author': m.author.username,
        'mine': current_user.is_authenticated and m.user_id == current_user.id
    } for m in markers])


@app.route('/api/add_marker', methods=['POST'])
@login_required
def add_marker():
    d = request.get_json()
    m = Marker(
        name=d.get('name', ''),
        lat=d['lat'],
        lon=d['lon'],
        desc=d.get('desc', ''),
        cat=d.get('cat', 'other'),
        vis=d.get('vis', 'all'),
        user_id=current_user.id
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id}), 201


@app.route('/api/del_marker/<int:mid>', methods=['DELETE'])
@login_required
def del_marker(mid):
    m = Marker.query.filter_by(id=mid, user_id=current_user.id).first()
    if m:
        db.session.delete(m)
        db.session.commit()
        return jsonify({'ok': True})
    return jsonify({'error': 'Нельзя удалить чужую метку'}), 403


@app.route('/api/favorite/<int:mid>', methods=['POST'])
@login_required
def toggle_fav(mid):
    fav = Favorite.query.filter_by(user_id=current_user.id, marker_id=mid).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'status': 'removed'})
    db.session.add(Favorite(user_id=current_user.id, marker_id=mid))
    db.session.commit()
    return jsonify({'status': 'added'})


@app.route('/api/search_place', methods=['POST'])
def search_place():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Нет данных'}), 400

        q = data.get('query', '').strip()
        if not q:
            return jsonify({'error': 'Введите название'}), 400

        url = 'https://geocode-maps.yandex.ru/1.x/'
        params = {
            'apikey': YANDEX_KEY,
            'geocode': q,
            'format': 'json',
            'lang': 'ru_RU',
            'results': 5
        }

        print(f"Запрос к Яндексу: {url}?apikey=...&geocode={q}")

        resp = requests.get(url, params=params, timeout=10)

        print(f"Статус ответа: {resp.status_code}")
        print(f"Тело ответа: {resp.text[:500]}")

        if resp.status_code != 200:
            return jsonify({'error': f'Ошибка API: {resp.status_code}. {resp.text[:200]}'}), 500

        data_resp = resp.json()
        items = data_resp.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])

        if not items:
            # Пробуем поиск организаций
            center = map_pos()
            url2 = 'https://search-maps.yandex.ru/v1/'
            params2 = {
                'apikey': YANDEX_KEY,
                'text': q,
                'lang': 'ru_RU',
                'll': f"{center['lon']},{center['lat']}",
                'spn': '0.05,0.05',
                'type': 'biz',
                'results': 5
            }

            resp2 = requests.get(url2, params=params2, timeout=10)
            if resp2.status_code == 200:
                data2 = resp2.json()
                items2 = data2.get('features', [])
                if items2:
                    results = []
                    for item in items2[:5]:
                        props = item.get('properties', {})
                        coords = item.get('geometry', {}).get('coordinates', [0, 0])
                        results.append({
                            'name': props.get('name', q),
                            'lat': coords[1],
                            'lon': coords[0],
                            'addr': props.get('description', ''),
                            'cat': 'other',
                            'photo': '',
                            'why': props.get('description', ''),
                            'color': '#6b7280'
                        })
                    return jsonify(results)

            return jsonify({'error': f'Ничего не найдено: {q}'}), 404

        results = []
        for item in items[:5]:
            geo = item['GeoObject']
            pos = geo['Point']['pos'].split()
            lat, lon = float(pos[1]), float(pos[0])
            name = geo.get('name', q)
            addr = geo.get('description', '') or geo.get('name', '')

            cat = 'other'
            ql = q.lower()
            if any(w in ql for w in ['парк', 'сквер', 'сад']):
                cat = 'park'
            elif any(w in ql for w in ['магазин', 'тц', 'супермаркет']):
                cat = 'shop'
            elif any(w in ql for w in ['кафе', 'ресторан', 'кофейня']):
                cat = 'cafe'
            elif any(w in ql for w in ['музей', 'театр', 'собор', 'храм']):
                cat = 'culture'

            results.append({
                'name': name,
                'lat': lat,
                'lon': lon,
                'addr': addr,
                'cat': cat,
                'photo': '',
                'why': f'Адрес: {addr}',
                'color': CATS[cat]['color']
            })

        return jsonify(results)

    except Exception as e:
        import traceback
        print("ОШИБКА В ПОИСКЕ:")
        print(traceback.format_exc())
        return jsonify({'error': f'Ошибка сервера: {str(e)}'}), 500


@app.route('/api/build_route', methods=['POST'])
def build_route():
    d = request.get_json()
    pts = d.get('points', [])
    if len(pts) < 2:
        return jsonify({'error': 'Минимум 2 точки'}), 400

    ordered = [pts[0]]
    rest = pts[1:]
    while rest:
        last = ordered[-1]
        nxt = min(rest, key=lambda p: math.dist(last, p))
        ordered.append(nxt)
        rest.remove(nxt)

    waypoints = '|'.join([f"{p[1]},{p[0]}" for p in ordered])
    url = f'https://api.routing.yandex.net/v2/route?apikey={YANDEX_KEY}&waypoints={waypoints}&mode=pedestrian'

    try:
        resp = requests.get(url, timeout=10).json()
        rpts, dist = [], 0
        if 'route' in resp:
            for leg in resp['route']['legs']:
                for step in leg['steps']:
                    for pt in step['polyline']['points']:
                        rpts.append([pt['lat'], pt['lon']])
                dist += leg['distance'] / 1000
        return jsonify({'route': rpts or ordered, 'dist': round(dist, 2), 'ordered': ordered})
    except:
        dist = sum(math.dist(ordered[i - 1], ordered[i]) for i in range(1, len(ordered))) * 111
        return jsonify({'route': ordered, 'dist': round(dist, 2), 'ordered': ordered})


@app.route('/api/save_route', methods=['POST'])
@login_required
def save_route():
    d = request.get_json()
    if not d or len(d.get('points', [])) < 2:
        return jsonify({'error': 'Минимум 2 точки'}), 400
    r = Route(
        name=d.get('name', 'Мой маршрут'),
        points=str(d['points']),
        dist=d.get('dist', 0),
        place_names=d.get('place_names', ''),
        user_id=current_user.id
    )
    db.session.add(r)
    db.session.commit()
    return jsonify({'id': r.id}), 201


@app.route('/api/routes_api')
@login_required
def routes_api():
    routes = Route.query.filter_by(user_id=current_user.id).order_by(Route.date.desc()).limit(5).all()
    return jsonify(
        [{'id': r.id, 'name': r.name, 'date': r.date.strftime('%d.%m.%Y %H:%M'), 'dist': r.dist} for r in routes])


@app.route('/routes')
@login_required
def routes_list():
    routes = Route.query.filter_by(user_id=current_user.id).order_by(Route.date.desc()).all()
    return render_template('base.html', page='routes', routes=routes, dark=cookie('theme', 'dark') == 'dark',
                           yandex_key=YANDEX_KEY)


@app.route('/route/<int:rid>')
@login_required
def view_route(rid):
    r = Route.query.filter_by(id=rid, user_id=current_user.id).first()
    if not r:
        return redirect(url_for('routes_list'))
    return render_template('base.html', page='view_route', route=r, pts=eval(r.points),
                           dark=cookie('theme', 'dark') == 'dark', yandex_key=YANDEX_KEY)


@app.route('/route/<int:rid>/del')
@login_required
def del_route(rid):
    r = Route.query.filter_by(id=rid, user_id=current_user.id).first()
    if r:
        db.session.delete(r)
        db.session.commit()
    return redirect(url_for('routes_list'))


@app.route('/favorites')
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created.desc()).all()
    return render_template('base.html', page='favorites', favs=favs, cats=CATS,
                           dark=cookie('theme', 'dark') == 'dark', yandex_key=YANDEX_KEY)


@app.route('/theme/<th>')
def theme(th):
    r = make_response(redirect(request.referrer or url_for('index')))
    set_c(r, 'theme', th)
    return r


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        if not u or not p or len(p) < 4:
            flash('Заполните все поля (мин. 4 символа)', 'error')
            return redirect(url_for('register'))
        if User.query.filter_by(username=u).first():
            flash('Пользователь уже существует', 'error')
            return redirect(url_for('register'))
        db.session.add(User(username=u, password_hash=generate_password_hash(p)))
        db.session.commit()
        login_user(User.query.filter_by(username=u).first())
        r = make_response(redirect(url_for('index')))
        set_c(r, 'first_visit', 'yes')
        set_c(r, 'visits', 1)
        return r
    return render_template('base.html', page='register', dark=cookie('theme', 'dark') == 'dark')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password_hash, p):
            login_user(user)
            r = make_response(redirect(url_for('index')))
            set_c(r, 'visits', int(cookie('visits', 0)) + 1)
            return r
        flash('Неверный логин или пароль', 'error')
    return render_template('base.html', page='login', dark=cookie('theme', 'dark') == 'dark')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)