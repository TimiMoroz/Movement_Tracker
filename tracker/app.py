from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os, requests, math, uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yandexlyceum_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tracker.db'
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

YANDEX_KEY = "f3a0fe3a-b07e-4840-a1da-06f18b2ddf13"
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = 'login'


# ========== МОДЕЛИ ==========
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='default.png')
    routes = db.relationship('Route', backref='author', lazy=True, cascade='all, delete-orphan')
    places = db.relationship('Place', backref='author', lazy=True, cascade='all, delete-orphan')


class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    date = db.Column(db.DateTime, default=datetime.now)
    dist = db.Column(db.Float, default=0.0)
    pts = db.Column(db.Text, nullable=False)
    clat = db.Column(db.Float, default=55.751244)
    clon = db.Column(db.Float, default=37.618423)
    uid = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Place(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    addr = db.Column(db.String(500))
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    cat = db.Column(db.String(100))
    saved = db.Column(db.DateTime, default=datetime.now)
    uid = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@login.user_loader
def load_user(uid): return User.query.get(int(uid))

with app.app_context(): db.create_all()


# ========== КУКИ ==========
def cookie(k, d=None): return request.cookies.get(k, d)
def set_c(r, k, v, d=365): r.set_cookie(k, str(v), max_age=60*60*24*d)
def del_c(r, k): r.set_cookie(k, '', max_age=0)

def map_pos():
    return dict(lat=float(cookie('mlat', 55.751244)), lon=float(cookie('mlon', 37.618423)), zoom=int(cookie('mzoom', 12)))


# ========== ГЛАВНАЯ ==========
@app.route('/')
def index():
    p = map_pos()
    r = make_response(render_template('base.html', page='index', map=p, yandex_key=YANDEX_KEY,
        visits=int(cookie('v', 0)), new=cookie('fv')!='true', dark=cookie('theme','dark')=='dark'))
    set_c(r, 'v', int(cookie('v', 0))+1)
    if cookie('fv')!='true': set_c(r, 'fv', 'true')
    return r


# ========== АВАТАРЫ ==========
@app.route('/ava/<fn>')
def ava(fn): return send_from_directory(app.config['UPLOAD_FOLDER'], fn)


@app.route('/profile')
@login_required
def profile():
    rc = Route.query.filter_by(uid=current_user.id).count()
    pc = Place.query.filter_by(uid=current_user.id).count()
    td = db.session.query(db.func.sum(Route.dist)).filter_by(uid=current_user.id).scalar() or 0
    return render_template('base.html', page='profile', rc=rc, pc=pc, td=round(td,2), dark=cookie('theme','dark')=='dark')


@app.route('/upava', methods=['POST'])
@login_required
def upava():
    f = request.files.get('avatar')
    if not f or f.filename=='': return redirect(url_for('profile'))
    ext = f.filename.rsplit('.',1)[-1].lower()
    if ext not in ('png','jpg','jpeg','gif','webp'): return redirect(url_for('profile'))
    fn = f"{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    if current_user.avatar != 'default.png':
        op = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar)
        if os.path.exists(op): os.remove(op)
    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    current_user.avatar = fn; db.session.commit()
    flash('Аватар обновлён','success')
    return redirect(url_for('profile'))


@app.route('/delava')
@login_required
def delava():
    if current_user.avatar != 'default.png':
        op = os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar)
        if os.path.exists(op): os.remove(op)
    current_user.avatar = 'default.png'; db.session.commit()
    return redirect(url_for('profile'))


# ========== МАРШРУТЫ ==========
@app.route('/api/save', methods=['POST'])
@login_required
def save():
    d = request.get_json()
    if not d or len(d.get('pts',[]))<2: return jsonify({'e':'min 2 pts'}),400
    pts = d['pts']
    route = Route(name=d.get('name','Без названия'), pts=str(pts), dist=d.get('dist',0),
                  clat=sum(p[0] for p in pts)/len(pts), clon=sum(p[1] for p in pts)/len(pts), uid=current_user.id)
    db.session.add(route); db.session.commit()
    return jsonify({'id':route.id,'name':route.name}),201


@app.route('/api/routes')
@login_required
def routes():
    return jsonify([{'id':r.id,'name':r.name,'date':r.date.strftime('%d.%m.%Y %H:%M'),'dist':r.dist}
                    for r in Route.query.filter_by(uid=current_user.id).order_by(Route.date.desc()).limit(5)])


@app.route('/api/route/<int:rid>')
@login_required
def one_route(rid):
    r = Route.query.filter_by(id=rid,uid=current_user.id).first()
    if not r: return jsonify({'e':'not found'}),404
    return jsonify({'id':r.id,'name':r.name,'date':r.date.strftime('%d.%m.%Y %H:%M'),'pts':eval(r.pts),'dist':r.dist})


@app.route('/route/<int:rid>')
@login_required
def view_route(rid):
    r = Route.query.filter_by(id=rid,uid=current_user.id).first()
    if not r: return redirect(url_for('index'))
    return render_template('base.html', page='view_route', route=r, pts=eval(r.pts), dark=cookie('theme','dark')=='dark', yandex_key=YANDEX_KEY)


@app.route('/route/<int:rid>/del')
@login_required
def del_route(rid):
    r = Route.query.filter_by(id=rid,uid=current_user.id).first()
    if r: db.session.delete(r); db.session.commit()
    return redirect(url_for('index'))


# ========== МЕСТА ==========
@app.route('/save_place', methods=['POST'])
@login_required
def save_place():
    Place(name=request.form.get('name',''), addr=request.form.get('addr',''),
          lat=float(request.form.get('lat',0)), lon=float(request.form.get('lon',0)),
          cat=request.form.get('cat',''), uid=current_user.id).save_to_db()
    db.session.add(pl); db.session.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/places')
@login_required
def places():
    return render_template('base.html', page='places',
        places=Place.query.filter_by(uid=current_user.id).order_by(Place.saved.desc()).all(),
        dark=cookie('theme','dark')=='dark')


@app.route('/place/<int:pid>/del')
@login_required
def del_place(pid):
    p = Place.query.filter_by(id=pid,uid=current_user.id).first()
    if p: db.session.delete(p); db.session.commit()
    return redirect(url_for('places'))


# ========== ТЕМА, КУКИ, API DOCS ==========
@app.route('/theme/<th>')
def theme_route(th):
    r = make_response(redirect(request.referrer or url_for('index')))
    set_c(r, 'theme', th)
    return r


@app.route('/savepos', methods=['POST'])
def savepos():
    r = make_response(redirect(url_for('index')))
    for k, v in [('mlat','lat'),('mlon','lon'),('mzoom','zoom')]:
        set_c(r, k, request.form.get(v, '12' if k=='mzoom' else '55.751244'), 7)
    return r


@app.route('/resetc')
def resetc():
    r = make_response(redirect(url_for('index')))
    for k in ['v','fv','mlat','mlon','mzoom','theme']: del_c(r,k)
    return r


@app.route('/cookies')
def cookies():
    return render_template('base.html', page='cookies', dark=cookie('theme','dark')=='dark')


@app.route('/api/docs')
def docs():
    return render_template('base.html', page='api_docs', dark=cookie('theme','dark')=='dark')


# ========== АВТОРИЗАЦИЯ ==========
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        u, p = request.form.get('username','').strip(), request.form.get('password','')
        if not u or not p or len(p)<4:
            flash('Логин и пароль (мин. 4 символа)','error'); return redirect(url_for('register'))
        if User.query.filter_by(username=u).first():
            flash('Пользователь уже есть','error'); return redirect(url_for('register'))
        db.session.add(User(username=u, password_hash=generate_password_hash(p)))
        db.session.commit()
        login_user(User.query.filter_by(username=u).first())
        r = make_response(redirect(url_for('index')))
        set_c(r,'fv','true'); set_c(r,'v',1)
        flash(f'Добро пожаловать, {u}!','success')
        return r
    return render_template('base.html', page='register', dark=cookie('theme','dark')=='dark')


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u, p = request.form.get('username','').strip(), request.form.get('password','')
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password_hash, p):
            login_user(user)
            r = make_response(redirect(url_for('index')))
            set_c(r,'v', int(cookie('v',0))+1)
            flash(f'С возвращением, {u}!','success')
            return r
        flash('Неверные данные','error')
    return render_template('base.html', page='login', dark=cookie('theme','dark')=='dark')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)