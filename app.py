from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid
import json
from sqlalchemy import desc, func
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-super-secreta-mano-confie-em-mim'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///upaeflix.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 5000 * 1024 * 1024  # 5GB máximo, METE BRONCA!
app.config['ALLOWED_VIDEO'] = {'mp4', 'mkv', 'avi', 'mov', 'webm'}
app.config['ALLOWED_IMAGE'] = {'jpg', 'jpeg', 'png', 'webp'}

# Criar diretórios de upload se não existirem
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'videos'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'posters'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails'), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# MODELOS DO BANCO DE DADOS
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    profile_pic = db.Column(db.String(256), default='default_profile.jpg')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    watchlist = db.relationship('WatchList', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    views = db.relationship('View', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Tabelas associativas pros relacionamentos many-to-many
movie_categories = db.Table('movie_categories',
                            db.Column('movie_id', db.Integer, db.ForeignKey('movie.id'), primary_key=True),
                            db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
                            )

series_categories = db.Table('series_categories',
                             db.Column('series_id', db.Integer, db.ForeignKey('series.id'), primary_key=True),
                             db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
                             )


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False)

    def __repr__(self):
        return f'<Category {self.name}>'


class Movie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    original_title = db.Column(db.String(128))
    description = db.Column(db.Text)
    release_year = db.Column(db.Integer)
    duration = db.Column(db.Integer)  # em minutos
    poster_url = db.Column(db.String(256))
    video_path = db.Column(db.String(256), nullable=False)
    views_count = db.Column(db.Integer, default=0)
    featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    categories = db.relationship('Category', secondary=movie_categories, backref=db.backref('movies', lazy='dynamic'))
    watchlists = db.relationship('WatchList', backref='movie', lazy='dynamic', cascade='all, delete-orphan')
    views = db.relationship('View', backref='movie', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'original_title': self.original_title,
            'description': self.description,
            'release_year': self.release_year,
            'duration': self.duration,
            'poster_url': self.poster_url,
            'views_count': self.views_count,
            'categories': [c.name for c in self.categories],
            'featured': self.featured
        }


class Series(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    original_title = db.Column(db.String(128))
    description = db.Column(db.Text)
    release_year = db.Column(db.Integer)
    end_year = db.Column(db.Integer)
    poster_url = db.Column(db.String(256))
    views_count = db.Column(db.Integer, default=0)
    featured = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    episodes = db.relationship('Episode', backref='series', lazy='dynamic', cascade='all, delete-orphan')
    categories = db.relationship('Category', secondary=series_categories, backref=db.backref('series', lazy='dynamic'))
    watchlists = db.relationship('WatchList', backref='series', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'original_title': self.original_title,
            'description': self.description,
            'release_year': self.release_year,
            'end_year': self.end_year,
            'poster_url': self.poster_url,
            'views_count': self.views_count,
            'categories': [c.name for c in self.categories],
            'seasons': self.get_seasons(),
            'featured': self.featured
        }

    def get_seasons(self):
        # Retorna uma lista com as temporadas disponíveis
        seasons = db.session.query(Episode.season.distinct()).filter_by(series_id=self.id).order_by(
            Episode.season).all()
        return [season[0] for season in seasons]


class Episode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    season = db.Column(db.Integer, nullable=False)
    episode_number = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer)  # em minutos
    thumbnail_url = db.Column(db.String(256))
    video_path = db.Column(db.String(256), nullable=False)
    views_count = db.Column(db.Integer, default=0)
    series_id = db.Column(db.Integer, db.ForeignKey('series.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    views = db.relationship('View', backref='episode', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'season': self.season,
            'episode_number': self.episode_number,
            'duration': self.duration,
            'thumbnail_url': self.thumbnail_url,
            'views_count': self.views_count,
            'series_id': self.series_id,
            'series_title': self.series.title
        }


class WatchList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=True)
    series_id = db.Column(db.Integer, db.ForeignKey('series.id'), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)


class View(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=True)
    episode_id = db.Column(db.Integer, db.ForeignKey('episode.id'), nullable=True)
    timestamp = db.Column(db.Float, default=0)  # Em segundos, pra continuar de onde parou
    completed = db.Column(db.Boolean, default=False)
    date_viewed = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# FUNÇÃO PARA DECORAR ROTAS QUE SÓ ADMIN PODE ACESSAR
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Acesso negado! Você não é admin, mano!', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)

    return decorated_function


# FUNÇÕES AUXILIARES
def allowed_file(filename, filetype):
    if filetype == 'video':
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_VIDEO']
    elif filetype == 'image':
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE']
    return False


def save_file(file, filetype):
    # Gera um nome único para o arquivo para evitar sobrescritas
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{filename}"

    if filetype == 'video':
        path = os.path.join(app.config['UPLOAD_FOLDER'], 'videos', unique_filename)
        file.save(path)
        return f"uploads/videos/{unique_filename}"

    elif filetype == 'poster':
        path = os.path.join(app.config['UPLOAD_FOLDER'], 'posters', unique_filename)
        file.save(path)
        return f"uploads/posters/{unique_filename}"

    elif filetype == 'thumbnail':
        path = os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails', unique_filename)
        file.save(path)
        return f"uploads/thumbnails/{unique_filename}"

    return None


# ROTAS DE AUTENTICAÇÃO
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Usuário ou senha incorretos. Dá uma conferida aí, mano!', 'danger')
            return redirect(url_for('login'))

        login_user(user, remember=True)
        next_page = request.args.get('next')

        if not next_page or next_page.startswith('/'):
            next_page = url_for('index')

        return redirect(next_page)

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        # Verificar se usuário/email já existem
        if User.query.filter_by(username=username).first():
            flash('Nome de usuário já existe, tenta outro!', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email já cadastrado. Já não lembra a senha?', 'danger')
            return redirect(url_for('register'))

        # Criar usuário novo
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Cadastro realizado com sucesso! Agora é só fazer login e assistir!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# PÁGINAS PRINCIPAIS
@app.route('/')
def index():
    # Destaque (featured)
    featured_movies = Movie.query.filter_by(featured=True).limit(5).all()
    featured_series = Series.query.filter_by(featured=True).limit(5).all()

    # Buscar filmes e séries pra exibir
    recent_movies = Movie.query.order_by(Movie.created_at.desc()).limit(10).all()
    popular_movies = Movie.query.order_by(Movie.views_count.desc()).limit(10).all()

    # Filmes por categoria
    action_movies = Movie.query.join(movie_categories).join(Category).filter(Category.name == 'Ação').limit(10).all()
    comedy_movies = Movie.query.join(movie_categories).join(Category).filter(Category.name == 'Comédia').limit(10).all()

    # Séries
    recent_series = Series.query.order_by(Series.created_at.desc()).limit(10).all()

    # Se o usuário estiver logado, mostrar "continue assistindo"
    continue_watching = []
    if current_user.is_authenticated:
        # Filmes não terminados
        movie_views = View.query.filter_by(user_id=current_user.id, completed=False).filter(
            View.movie_id.isnot(None)).order_by(View.date_viewed.desc()).limit(6).all()

        for view in movie_views:
            movie = Movie.query.get(view.movie_id)
            if movie:
                continue_watching.append({
                    'id': movie.id,
                    'title': movie.title,
                    'poster_url': movie.poster_url,
                    'progress': (view.timestamp / (movie.duration * 60)) * 100 if movie.duration else 0,
                    'timestamp': view.timestamp,
                    'type': 'movie'
                })

        # Episódios não terminados
        episode_views = View.query.filter_by(user_id=current_user.id, completed=False).filter(
            View.episode_id.isnot(None)).order_by(View.date_viewed.desc()).limit(6).all()

        for view in episode_views:
            episode = Episode.query.get(view.episode_id)
            if episode:
                series = Series.query.get(episode.series_id)
                continue_watching.append({
                    'id': episode.id,
                    'title': f"{series.title}: T{episode.season}E{episode.episode_number}",
                    'poster_url': episode.thumbnail_url or series.poster_url,
                    'progress': (view.timestamp / (episode.duration * 60)) * 100 if episode.duration else 0,
                    'timestamp': view.timestamp,
                    'type': 'episode',
                    'series_id': series.id
                })

    # Lista de observação do usuário
    watchlist_items = []
    if current_user.is_authenticated:
        watchlist = WatchList.query.filter_by(user_id=current_user.id).order_by(WatchList.date_added.desc()).all()

        for item in watchlist:
            if item.movie_id:
                movie = Movie.query.get(item.movie_id)
                watchlist_items.append({
                    'id': movie.id,
                    'title': movie.title,
                    'poster_url': movie.poster_url,
                    'type': 'movie'
                })
            elif item.series_id:
                series = Series.query.get(item.series_id)
                watchlist_items.append({
                    'id': series.id,
                    'title': series.title,
                    'poster_url': series.poster_url,
                    'type': 'series'
                })

    # Obtém categorias para o menu
    categories = Category.query.all()

    return render_template('index.html',
                           featured_movies=featured_movies,
                           featured_series=featured_series,
                           recent_movies=recent_movies,
                           popular_movies=popular_movies,
                           action_movies=action_movies,
                           comedy_movies=comedy_movies,
                           recent_series=recent_series,
                           continue_watching=continue_watching,
                           watchlist=watchlist_items,
                           categories=categories)


@app.route('/movie/<int:movie_id>')
def movie_details(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    # Filmes similares baseados nas categorias
    similar_movies = []
    if movie.categories:
        category_ids = [c.id for c in movie.categories]
        similar_movies = Movie.query.join(movie_categories).filter(
            movie_categories.c.category_id.in_(category_ids),
            Movie.id != movie.id
        ).distinct().limit(6).all()

    # Verificar se está na lista de observação do usuário
    in_watchlist = False
    progress = 0
    if current_user.is_authenticated:
        watchlist_item = WatchList.query.filter_by(user_id=current_user.id, movie_id=movie.id).first()
        in_watchlist = watchlist_item is not None

        # Verificar progresso de visualização
        view = View.query.filter_by(user_id=current_user.id, movie_id=movie.id).order_by(
            View.date_viewed.desc()).first()
        if view:
            progress = (view.timestamp / (movie.duration * 60)) * 100 if movie.duration else 0

    return render_template('movie_details.html',
                           movie=movie,
                           similar_movies=similar_movies,
                           in_watchlist=in_watchlist,
                           progress=progress)


@app.route('/series/<int:series_id>')
def series_details(series_id):
    series = Series.query.get_or_404(series_id)

    # Pegar todas as temporadas e episódios
    seasons = {}
    for season in series.get_seasons():
        episodes = Episode.query.filter_by(series_id=series.id, season=season).order_by(Episode.episode_number).all()
        seasons[season] = episodes

    # Séries similares baseadas nas categorias
    similar_series = []
    if series.categories:
        category_ids = [c.id for c in series.categories]
        similar_series = Series.query.join(series_categories).filter(
            series_categories.c.category_id.in_(category_ids),
            Series.id != series.id
        ).distinct().limit(6).all()

    # Verificar se está na lista de observação do usuário
    in_watchlist = False
    if current_user.is_authenticated:
        watchlist_item = WatchList.query.filter_by(user_id=current_user.id, series_id=series.id).first()
        in_watchlist = watchlist_item is not None

    # Progresso de cada episódio
    episode_progress = {}
    if current_user.is_authenticated:
        for season, episodes in seasons.items():
            for episode in episodes:
                view = View.query.filter_by(user_id=current_user.id, episode_id=episode.id).order_by(
                    View.date_viewed.desc()).first()
                if view:
                    progress = (view.timestamp / (episode.duration * 60)) * 100 if episode.duration else 0
                    episode_progress[episode.id] = progress

    return render_template('series_details.html',
                           series=series,
                           seasons=seasons,
                           similar_series=similar_series,
                           in_watchlist=in_watchlist,
                           episode_progress=episode_progress)


@app.route('/watch/movie/<int:movie_id>')
@login_required
def watch_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)

    # Recuperar posição anterior, se existir
    timestamp = 0
    view = View.query.filter_by(user_id=current_user.id, movie_id=movie.id).order_by(View.date_viewed.desc()).first()

    if view:
        timestamp = view.timestamp
    else:
        # Criar uma nova visualização
        view = View(user_id=current_user.id, movie_id=movie.id)
        db.session.add(view)

        # Incrementar contador de visualizações
        movie.views_count += 1

        db.session.commit()

    return render_template('player.html',
                           media=movie,
                           media_type='movie',
                           timestamp=timestamp,
                           next_media=None)


@app.route('/watch/episode/<int:episode_id>')
@login_required
def watch_episode(episode_id):
    episode = Episode.query.get_or_404(episode_id)
    series = Series.query.get(episode.series_id)

    # Recuperar posição anterior, se existir
    timestamp = 0
    view = View.query.filter_by(user_id=current_user.id, episode_id=episode.id).order_by(
        View.date_viewed.desc()).first()

    if view:
        timestamp = view.timestamp
    else:
        # Criar uma nova visualização
        view = View(user_id=current_user.id, episode_id=episode.id)
        db.session.add(view)

        # Incrementar contador de visualizações
        episode.views_count += 1
        series.views_count += 1

        db.session.commit()

    # Determinar o próximo episódio
    next_episode = Episode.query.filter(
        Episode.series_id == episode.series_id,
        ((Episode.season == episode.season) & (Episode.episode_number > episode.episode_number)) |
        (Episode.season > episode.season)
    ).order_by(Episode.season, Episode.episode_number).first()

    return render_template('player.html',
                           media=episode,
                           media_type='episode',
                           timestamp=timestamp,
                           next_media=next_episode,
                           series=series)


@app.route('/category/<string:category_slug>')
def category(category_slug):
    category = Category.query.filter_by(slug=category_slug).first_or_404()

    # Filmes desta categoria
    movies = Movie.query.join(movie_categories).join(Category).filter(Category.id == category.id).all()

    # Séries desta categoria
    series = Series.query.join(series_categories).join(Category).filter(Category.id == category.id).all()

    return render_template('category.html',
                           category=category,
                           movies=movies,
                           series=series)


@app.route('/search')
def search():
    query = request.args.get('q', '')

    if not query:
        return redirect(url_for('index'))

    # Buscar filmes e séries que correspondem à consulta
    movies = Movie.query.filter(Movie.title.ilike(f'%{query}%')).all()
    series = Series.query.filter(Series.title.ilike(f'%{query}%')).all()

    return render_template('search_results.html',
                           query=query,
                           movies=movies,
                           series=series)


@app.route('/watchlist')
@login_required
def watchlist():
    watchlist_movies = Movie.query.join(WatchList).filter(WatchList.user_id == current_user.id).all()
    watchlist_series = Series.query.join(WatchList).filter(WatchList.user_id == current_user.id).all()

    return render_template('watchlist.html',
                           movies=watchlist_movies,
                           series=watchlist_series)


# ROTAS ADMIN - ÁREA DE UPLOAD E GERENCIAMENTO
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # Estatísticas
    total_movies = Movie.query.count()
    total_series = Series.query.count()
    total_episodes = Episode.query.count()
    total_users = User.query.count()

    # Conteúdos mais populares
    popular_movies = Movie.query.order_by(Movie.views_count.desc()).limit(5).all()
    popular_series = Series.query.order_by(Series.views_count.desc()).limit(5).all()

    return render_template('admin/dashboard.html',
                           total_movies=total_movies,
                           total_series=total_series,
                           total_episodes=total_episodes,
                           total_users=total_users,
                           popular_movies=popular_movies,
                           popular_series=popular_series)


@app.route('/admin/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_upload():
    categories = Category.query.all()

    if request.method == 'POST':
        content_type = request.form.get('content_type')

        if content_type == 'movie':
            # Processar upload de filme
            title = request.form.get('title')
            original_title = request.form.get('original_title', '')
            description = request.form.get('description', '')
            release_year = request.form.get('release_year', 0)
            duration = request.form.get('duration', 0)
            category_ids = request.form.getlist('categories')

            # Validação básica
            if not title or not release_year or not duration or not category_ids:
                flash('Preencha todos os campos obrigatórios!', 'danger')
                return redirect(url_for('admin_upload'))

            # Processar poster
            poster_url = None
            if 'poster' in request.files and request.files['poster'].filename:
                poster_file = request.files['poster']
                if allowed_file(poster_file.filename, 'image'):
                    poster_url = save_file(poster_file, 'poster')
                else:
                    flash('Formato de imagem não permitido!', 'danger')
                    return redirect(url_for('admin_upload'))

            # Processar vídeo
            if 'video' not in request.files or not request.files['video'].filename:
                flash('Você precisa enviar um arquivo de vídeo!', 'danger')
                return redirect(url_for('admin_upload'))

            video_file = request.files['video']
            if not allowed_file(video_file.filename, 'video'):
                flash('Formato de vídeo não permitido!', 'danger')
                return redirect(url_for('admin_upload'))

            video_path = save_file(video_file, 'video')

            # Criar novo filme
            movie = Movie(
                title=title,
                original_title=original_title,
                description=description,
                release_year=int(release_year),
                duration=int(duration),
                poster_url=poster_url,
                video_path=video_path,
                featured=bool(request.form.get('featured', False))
            )

            # Adicionar categorias
            for category_id in category_ids:
                category = Category.query.get(int(category_id))
                if category:
                    movie.categories.append(category)

            db.session.add(movie)
            db.session.commit()

            flash('Filme adicionado com sucesso!', 'success')
            return redirect(url_for('admin_upload'))

        elif content_type == 'series':
            # Processar upload de série
            title = request.form.get('title')
            original_title = request.form.get('original_title', '')
            description = request.form.get('description', '')
            release_year = request.form.get('release_year', 0)
            end_year = request.form.get('end_year', 0)
            category_ids = request.form.getlist('categories')

            # Validação básica
            if not title or not release_year or not category_ids:
                flash('Preencha todos os campos obrigatórios!', 'danger')
                return redirect(url_for('admin_upload'))

            # Processar poster
            poster_url = None
            if 'poster' in request.files and request.files['poster'].filename:
                poster_file = request.files['poster']
                if allowed_file(poster_file.filename, 'image'):
                    poster_url = save_file(poster_file, 'poster')
                else:
                    flash('Formato de imagem não permitido!', 'danger')
                    return redirect(url_for('admin_upload'))

            # Criar nova série
            series = Series(
                title=title,
                original_title=original_title,
                description=description,
                release_year=int(release_year),
                end_year=int(end_year) if end_year else None,
                poster_url=poster_url,
                featured=bool(request.form.get('featured', False))
            )

            # Adicionar categorias
            for category_id in category_ids:
                category = Category.query.get(int(category_id))
                if category:
                    series.categories.append(category)

            db.session.add(series)
            db.session.commit()

            flash('Série adicionada com sucesso! Agora adicione os episódios.', 'success')
            return redirect(url_for('admin_add_episode', series_id=series.id))

        elif content_type == 'category':
            # Processar adição de categoria
            name = request.form.get('name')
            if not name:
                flash('Digite um nome para a categoria!', 'danger')
                return redirect(url_for('admin_upload'))

            # Gerar slug
            slug = name.lower().replace(' ', '-')

            # Verificar se já existe
            if Category.query.filter_by(slug=slug).first():
                flash('Esta categoria já existe!', 'danger')
                return redirect(url_for('admin_upload'))

            category = Category(name=name, slug=slug)
            db.session.add(category)
            db.session.commit()

            flash('Categoria adicionada com sucesso!', 'success')
            return redirect(url_for('admin_upload'))

    # GET request - mostrar formulário
    return render_template('admin/upload.html', categories=categories)


@app.route('/admin/add-episode/<int:series_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_episode(series_id):
    series = Series.query.get_or_404(series_id)

    if request.method == 'POST':
        # Processar upload de episódio
        title = request.form.get('title')
        description = request.form.get('description', '')
        season = request.form.get('season', 1)
        episode_number = request.form.get('episode_number', 1)
        duration = request.form.get('duration', 0)

        # Validação básica
        if not title or not season or not episode_number or not duration:
            flash('Preencha todos os campos obrigatórios!', 'danger')
            return redirect(url_for('admin_add_episode', series_id=series_id))

        # Processar thumbnail
        thumbnail_url = None
        if 'thumbnail' in request.files and request.files['thumbnail'].filename:
            thumbnail_file = request.files['thumbnail']
            if allowed_file(thumbnail_file.filename, 'image'):
                thumbnail_url = save_file(thumbnail_file, 'thumbnail')
            else:
                flash('Formato de imagem não permitido!', 'danger')
                return redirect(url_for('admin_add_episode', series_id=series_id))

        # Processar vídeo
        if 'video' not in request.files or not request.files['video'].filename:
            flash('Você precisa enviar um arquivo de vídeo!', 'danger')
            return redirect(url_for('admin_add_episode', series_id=series_id))

        video_file = request.files['video']
        if not allowed_file(video_file.filename, 'video'):
            flash('Formato de vídeo não permitido!', 'danger')
            return redirect(url_for('admin_add_episode', series_id=series_id))

        video_path = save_file(video_file, 'video')

        # Criar novo episódio
        episode = Episode(
            title=title,
            description=description,
            season=int(season),
            episode_number=int(episode_number),
            duration=int(duration),
            thumbnail_url=thumbnail_url,
            video_path=video_path,
            series_id=series_id
        )

        db.session.add(episode)
        db.session.commit()

        flash('Episódio adicionado com sucesso!', 'success')

        # Verificar se o usuário quer adicionar mais episódios
        if 'add_another' in request.form:
            return redirect(url_for('admin_add_episode', series_id=series_id))
        else:
            return redirect(url_for('admin_manage_content'))

    # GET request - mostrar formulário
    # Determinar próxima temporada/episódio
    last_episode = Episode.query.filter_by(series_id=series_id).order_by(Episode.season.desc(),
                                                                         Episode.episode_number.desc()).first()

    next_season = 1
    next_episode = 1

    if last_episode:
        if last_episode.episode_number < 20:  # Assumindo máximo de 20 episódios por temporada
            next_season = last_episode.season
            next_episode = last_episode.episode_number + 1
        else:
            next_season = last_episode.season + 1
            next_episode = 1

    return render_template('admin/add_episode.html',
                           series=series,
                           next_season=next_season,
                           next_episode=next_episode)


@app.route('/admin/manage')
@login_required
@admin_required
def admin_manage_content():
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    series = Series.query.order_by(Series.created_at.desc()).all()
    categories = Category.query.all()

    return render_template('admin/manage.html',
                           movies=movies,
                           series=series,
                           categories=categories)


@app.route('/admin/edit/movie/<int:movie_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    categories = Category.query.all()

    if request.method == 'POST':
        # Atualizar filme
        movie.title = request.form.get('title')
        movie.original_title = request.form.get('original_title', '')
        movie.description = request.form.get('description', '')
        movie.release_year = int(request.form.get('release_year', 0))
        movie.duration = int(request.form.get('duration', 0))
        movie.featured = bool(request.form.get('featured', False))

        # Processar poster se houver um novo
        if 'poster' in request.files and request.files['poster'].filename:
            poster_file = request.files['poster']
            if allowed_file(poster_file.filename, 'image'):
                movie.poster_url = save_file(poster_file, 'poster')
            else:
                flash('Formato de imagem não permitido!', 'danger')
                return redirect(url_for('admin_edit_movie', movie_id=movie_id))

        # Processar vídeo se houver um novo
        if 'video' in request.files and request.files['video'].filename:
            video_file = request.files['video']
            if allowed_file(video_file.filename, 'video'):
                movie.video_path = save_file(video_file, 'video')
            else:
                flash('Formato de vídeo não permitido!', 'danger')
                return redirect(url_for('admin_edit_movie', movie_id=movie_id))

        # Atualizar categorias
        movie.categories = []
        category_ids = request.form.getlist('categories')
        for category_id in category_ids:
            category = Category.query.get(int(category_id))
            if category:
                movie.categories.append(category)

        db.session.commit()
        flash('Filme atualizado com sucesso!', 'success')
        return redirect(url_for('admin_manage_content'))

    # GET request - mostrar formulário
    return render_template('admin/edit_movie.html', movie=movie, categories=categories)


@app.route('/admin/edit/series/<int:series_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_series(series_id):
    series = Series.query.get_or_404(series_id)
    categories = Category.query.all()

    if request.method == 'POST':
        # Atualizar série
        series.title = request.form.get('title')
        series.original_title = request.form.get('original_title', '')
        series.description = request.form.get('description', '')
        series.release_year = int(request.form.get('release_year', 0))
        series.end_year = int(request.form.get('end_year', 0)) if request.form.get('end_year') else None
        series.featured = bool(request.form.get('featured', False))

        # Processar poster se houver um novo
        if 'poster' in request.files and request.files['poster'].filename:
            poster_file = request.files['poster']
            if allowed_file(poster_file.filename, 'image'):
                series.poster_url = save_file(poster_file, 'poster')
            else:
                flash('Formato de imagem não permitido!', 'danger')
                return redirect(url_for('admin_edit_series', series_id=series_id))

        # Atualizar categorias
        series.categories = []
        category_ids = request.form.getlist('categories')
        for category_id in category_ids:
            category = Category.query.get(int(category_id))
            if category:
                series.categories.append(category)

        db.session.commit()
        flash('Série atualizada com sucesso!', 'success')
        return redirect(url_for('admin_manage_content'))

    # GET request - mostrar formulário
    return render_template('admin/edit_series.html', series=series, categories=categories)


@app.route('/admin/episodes/<int:series_id>')
@login_required
@admin_required
def admin_manage_episodes(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id).order_by(Episode.season, Episode.episode_number).all()

    return render_template('admin/manage_episodes.html', series=series, episodes=episodes)


@app.route('/admin/edit/episode/<int:episode_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_episode(episode_id):
    episode = Episode.query.get_or_404(episode_id)

    if request.method == 'POST':
        # Atualizar episódio
        episode.title = request.form.get('title')
        episode.description = request.form.get('description', '')
        episode.season = int(request.form.get('season', 1))
        episode.episode_number = int(request.form.get('episode_number', 1))
        episode.duration = int(request.form.get('duration', 0))

        # Processar thumbnail se houver um novo
        if 'thumbnail' in request.files and request.files['thumbnail'].filename:
            thumbnail_file = request.files['thumbnail']
            if allowed_file(thumbnail_file.filename, 'image'):
                episode.thumbnail_url = save_file(thumbnail_file, 'thumbnail')
            else:
                flash('Formato de imagem não permitido!', 'danger')
                return redirect(url_for('admin_edit_episode', episode_id=episode_id))

        # Processar vídeo se houver um novo
        if 'video' in request.files and request.files['video'].filename:
            video_file = request.files['video']
            if allowed_file(video_file.filename, 'video'):
                episode.video_path = save_file(video_file, 'video')
            else:
                flash('Formato de vídeo não permitido!', 'danger')
                return redirect(url_for('admin_edit_episode', episode_id=episode_id))

        db.session.commit()
        flash('Episódio atualizado com sucesso!', 'success')
        return redirect(url_for('admin_manage_episodes', series_id=episode.series_id))

    # GET request - mostrar formulário
    return render_template('admin/edit_episode.html', episode=episode)


# ROTAS DA API
@app.route('/api/movies')
def api_movies():
    movies = Movie.query.all()
    return jsonify([movie.to_dict() for movie in movies])


@app.route('/api/series')
def api_series():
    series = Series.query.all()
    return jsonify([s.to_dict() for s in series])


@app.route('/api/categories')
def api_categories():
    categories = Category.query.all()
    return jsonify([{'id': c.id, 'name': c.name, 'slug': c.slug} for c in categories])


@app.route('/api/movie/<int:movie_id>')
def api_movie_details(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    return jsonify(movie.to_dict())


@app.route('/api/series/<int:series_id>')
def api_series_details(series_id):
    series = Series.query.get_or_404(series_id)
    return jsonify(series.to_dict())


@app.route('/api/series/<int:series_id>/episodes')
def api_series_episodes(series_id):
    series = Series.query.get_or_404(series_id)
    episodes = Episode.query.filter_by(series_id=series_id).order_by(Episode.season, Episode.episode_number).all()
    return jsonify([episode.to_dict() for episode in episodes])


@app.route('/api/watchlist/add', methods=['POST'])
@login_required
def api_add_to_watchlist():
    data = request.json

    if 'movie_id' in data:
        movie_id = data['movie_id']

        # Verificar se já está na watchlist
        existing = WatchList.query.filter_by(user_id=current_user.id, movie_id=movie_id).first()
        if existing:
            return jsonify({'success': False, 'message': 'Filme já está na sua lista!'})

        # Adicionar à watchlist
        watchlist_item = WatchList(user_id=current_user.id, movie_id=movie_id)
        db.session.add(watchlist_item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Filme adicionado à sua lista!'})

    elif 'series_id' in data:
        series_id = data['series_id']

        # Verificar se já está na watchlist
        existing = WatchList.query.filter_by(user_id=current_user.id, series_id=series_id).first()
        if existing:
            return jsonify({'success': False, 'message': 'Série já está na sua lista!'})

        # Adicionar à watchlist
        watchlist_item = WatchList(user_id=current_user.id, series_id=series_id)
        db.session.add(watchlist_item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Série adicionada à sua lista!'})

    return jsonify({'success': False, 'message': 'Parâmetros inválidos!'})


@app.route('/api/watchlist/remove', methods=['POST'])
@login_required
def api_remove_from_watchlist():
    data = request.json

    if 'movie_id' in data:
        movie_id = data['movie_id']
        WatchList.query.filter_by(user_id=current_user.id, movie_id=movie_id).delete()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Filme removido da sua lista!'})

    elif 'series_id' in data:
        series_id = data['series_id']
        WatchList.query.filter_by(user_id=current_user.id, series_id=series_id).delete()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Série removida da sua lista!'})

    return jsonify({'success': False, 'message': 'Parâmetros inválidos!'})


@app.route('/api/playback/update', methods=['POST'])
@login_required
def api_update_playback():
    data = request.json

    if 'movie_id' in data and 'timestamp' in data:
        movie_id = data['movie_id']
        timestamp = float(data['timestamp'])
        completed = bool(data.get('completed', False))

        # Buscar visualização existente ou criar nova
        view = View.query.filter_by(user_id=current_user.id, movie_id=movie_id).order_by(
            View.date_viewed.desc()).first()

        if not view:
            view = View(user_id=current_user.id, movie_id=movie_id)
            db.session.add(view)

        view.timestamp = timestamp
        view.completed = completed
        view.date_viewed = datetime.utcnow()

        db.session.commit()

        return jsonify({'success': True})

    elif 'episode_id' in data and 'timestamp' in data:
        episode_id = data['episode_id']
        timestamp = float(data['timestamp'])
        completed = bool(data.get('completed', False))

        # Buscar visualização existente ou criar nova
        view = View.query.filter_by(user_id=current_user.id, episode_id=episode_id).order_by(
            View.date_viewed.desc()).first()

        if not view:
            view = View(user_id=current_user.id, episode_id=episode_id)
            db.session.add(view)

        view.timestamp = timestamp
        view.completed = completed
        view.date_viewed = datetime.utcnow()

        db.session.commit()

        return jsonify({'success': True})

    return jsonify({'success': False, 'message': 'Parâmetros inválidos!'})


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')

    if not query or len(query) < 2:
        return jsonify([])

    # Buscar filmes
    movies = Movie.query.filter(Movie.title.ilike(f'%{query}%')).limit(5).all()

    # Buscar séries
    series = Series.query.filter(Series.title.ilike(f'%{query}%')).limit(5).all()

    results = []

    for movie in movies:
        results.append({
            'id': movie.id,
            'title': movie.title,
            'poster_url': movie.poster_url,
            'year': movie.release_year,
            'type': 'movie'
        })

    for s in series:
        results.append({
            'id': s.id,
            'title': s.title,
            'poster_url': s.poster_url,
            'year': s.release_year,
            'type': 'series'
        })

    return jsonify(results)


# Rota para servir os vídeos com controle de acesso
@app.route('/stream/<path:filename>')
@login_required
def stream_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# CRIAR BANCO DE DADOS E INSERIR DADOS INICIAIS
def create_sample_data():
    # Criar categorias
    categories = [
        {'name': 'Ação', 'slug': 'acao'},
        {'name': 'Comédia', 'slug': 'comedia'},
        {'name': 'Drama', 'slug': 'drama'},
        {'name': 'Ficção Científica', 'slug': 'ficcao-cientifica'},
        {'name': 'Terror', 'slug': 'terror'},
        {'name': 'Romance', 'slug': 'romance'},

    ]

    for cat_data in categories:
        if not Category.query.filter_by(slug=cat_data['slug']).first():
            category = Category(name=cat_data['name'], slug=cat_data['slug'])
            db.session.add(category)

    # Criar usuário admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@upaeflix.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)

    db.session.commit()
    print("Dados de exemplo criados com sucesso!")


@app.cli.command("create-tables")
def create_tables():
    db.create_all()
    print("Tabelas criadas com sucesso!")


# ROTAS ADMIN API
@app.route('/api/admin/delete', methods=['POST'])
@login_required
@admin_required
def api_admin_delete():
    data = request.json

    if not data or 'id' not in data or 'type' not in data:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos'})

    try:
        id = int(data['id'])
        item_type = data['type']

        if item_type == 'movie':
            movie = Movie.query.get(id)
            if not movie:
                return jsonify({'success': False, 'message': 'Filme não encontrado'})

            db.session.delete(movie)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Filme excluído com sucesso!'})

        elif item_type == 'series':
            series = Series.query.get(id)
            if not series:
                return jsonify({'success': False, 'message': 'Série não encontrada'})

            db.session.delete(series)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Série excluída com sucesso!'})

        elif item_type == 'episode':
            episode = Episode.query.get(id)
            if not episode:
                return jsonify({'success': False, 'message': 'Episódio não encontrado'})

            db.session.delete(episode)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Episódio excluído com sucesso!'})

        elif item_type == 'category':
            category = Category.query.get(id)
            if not category:
                return jsonify({'success': False, 'message': 'Categoria não encontrada'})

            # Verificar se existem filmes ou séries usando esta categoria
            if category.movies.count() > 0 or category.series.count() > 0:
                return jsonify({
                    'success': False,
                    'message': 'Esta categoria possui filmes ou séries associados. Remova as associações primeiro.'
                })

            db.session.delete(category)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Categoria excluída com sucesso!'})

        else:
            return jsonify({'success': False, 'message': 'Tipo de item inválido'})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao excluir: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro ao excluir: {str(e)}'})


@app.route('/api/admin/update-category', methods=['POST'])
@login_required
@admin_required
def api_admin_update_category():
    data = request.json

    if not data or 'id' not in data or 'name' not in data:
        return jsonify({'success': False, 'message': 'Parâmetros inválidos'})

    try:
        id = int(data['id'])
        name = data['name'].strip()

        if not name:
            return jsonify({'success': False, 'message': 'Nome da categoria é obrigatório'})

        category = Category.query.get(id)
        if not category:
            return jsonify({'success': False, 'message': 'Categoria não encontrada'})

        # Gerar novo slug se o nome mudou
        if category.name != name:
            slug = name.lower().replace(' ', '-')

            # Verificar se o slug já existe
            existing = Category.query.filter(Category.slug == slug, Category.id != id).first()
            if existing:
                return jsonify({'success': False, 'message': 'Já existe uma categoria com este nome'})

            category.name = name
            category.slug = slug

        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Categoria atualizada com sucesso!',
            'category': {
                'id': category.id,
                'name': category.name,
                'slug': category.slug
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Erro ao atualizar: {str(e)}'})


@app.cli.command("create-admin")
def create_admin():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@upaeflix.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Usuário admin criado com sucesso!")
    else:
        print("Usuário admin já existe!")


@app.cli.command("sample-data")
def sample_data():
    create_sample_data()


@app.route('/admin/users')
@login_required
@admin_required
def admin_manage_users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')

    # Filtrar usuários por busca se necessário
    if search:
        users = User.query.filter(
            db.or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        ).order_by(User.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
    else:
        users = User.query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=20, error_out=False
        )

    # Estatísticas dos usuários
    total_users = User.query.count()
    admin_users = User.query.filter_by(is_admin=True).count()
    regular_users = total_users - admin_users

    return render_template('admin/manage_users.html',
                           users=users,
                           search=search,
                           total_users=total_users,
                           admin_users=admin_users,
                           regular_users=regular_users)


@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        try:
            # Atualizar dados básicos
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            is_admin = bool(request.form.get('is_admin', False))

            # Validações
            if not username or not email:
                flash('Nome de usuário e email são obrigatórios!', 'danger')
                return redirect(url_for('admin_edit_user', user_id=user_id))

            # Verificar se username já existe (exceto para o próprio usuário)
            existing_user = User.query.filter(User.username == username, User.id != user_id).first()
            if existing_user:
                flash('Nome de usuário já existe!', 'danger')
                return redirect(url_for('admin_edit_user', user_id=user_id))

            # Verificar se email já existe (exceto para o próprio usuário)
            existing_email = User.query.filter(User.email == email, User.id != user_id).first()
            if existing_email:
                flash('Email já está em uso!', 'danger')
                return redirect(url_for('admin_edit_user', user_id=user_id))

            # Atualizar dados
            user.username = username
            user.email = email
            user.is_admin = is_admin

            # Atualizar senha se fornecida
            new_password = request.form.get('new_password', '').strip()
            if new_password:
                if len(new_password) < 6:
                    flash('Nova senha deve ter pelo menos 6 caracteres!', 'danger')
                    return redirect(url_for('admin_edit_user', user_id=user_id))
                user.set_password(new_password)

            db.session.commit()
            flash('Usuário atualizado com sucesso!', 'success')
            return redirect(url_for('admin_manage_users'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar usuário: {str(e)}', 'danger')
            print(f"Erro ao editar usuário: {str(e)}")

    return render_template('admin/edit_user.html', user=user)


@app.route('/api/admin/user/delete', methods=['POST'])
@login_required
@admin_required
def api_admin_delete_user():
    data = request.json

    if not data or 'user_id' not in data:
        return jsonify({'success': False, 'message': 'ID do usuário é obrigatório'})

    try:
        user_id = int(data['user_id'])

        # Não permitir deletar próprio usuário
        if user_id == current_user.id:
            return jsonify({'success': False, 'message': 'Você não pode deletar sua própria conta!'})

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Usuário não encontrado'})

        # Verificar se é o último admin
        if user.is_admin:
            admin_count = User.query.filter_by(is_admin=True).count()
            if admin_count <= 1:
                return jsonify({'success': False, 'message': 'Não é possível deletar o último administrador!'})

        # Deletar usuário (as relações serão deletadas em cascata)
        db.session.delete(user)
        db.session.commit()

        return jsonify({'success': True, 'message': f'Usuário "{user.username}" deletado com sucesso!'})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao deletar usuário: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro ao deletar usuário: {str(e)}'})


@app.route('/api/admin/user/toggle-admin', methods=['POST'])
@login_required
@admin_required
def api_admin_toggle_user_admin():
    data = request.json

    if not data or 'user_id' not in data:
        return jsonify({'success': False, 'message': 'ID do usuário é obrigatório'})

    try:
        user_id = int(data['user_id'])

        # Não permitir alterar próprio status
        if user_id == current_user.id:
            return jsonify({'success': False, 'message': 'Você não pode alterar seu próprio status de admin!'})

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Usuário não encontrado'})

        # Se está removendo admin, verificar se não é o último
        if user.is_admin:
            admin_count = User.query.filter_by(is_admin=True).count()
            if admin_count <= 1:
                return jsonify({'success': False, 'message': 'Não é possível remover o último administrador!'})

        # Alternar status de admin
        user.is_admin = not user.is_admin
        db.session.commit()

        status = "administrador" if user.is_admin else "usuário comum"
        return jsonify(
            {'success': True, 'message': f'Usuário "{user.username}" agora é {status}!', 'is_admin': user.is_admin})

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao alterar status admin: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro ao alterar status: {str(e)}'})


@app.route('/api/admin/users/stats')
@login_required
@admin_required
def api_admin_users_stats():
    try:
        # Estatísticas gerais
        total_users = User.query.count()
        admin_users = User.query.filter_by(is_admin=True).count()

        # Usuários mais ativos (por views)
        most_active = db.session.query(
            User.username,
            User.id,
            func.count(View.id).label('total_views')
        ).join(View).group_by(User.id).order_by(func.count(View.id).desc()).limit(10).all()

        # Usuários registrados por mês (últimos 6 meses)
        from datetime import datetime, timedelta
        six_months_ago = datetime.utcnow() - timedelta(days=180)

        monthly_registrations = db.session.query(
            func.strftime('%Y-%m', User.created_at).label('month'),
            func.count(User.id).label('count')
        ).filter(User.created_at >= six_months_ago).group_by(
            func.strftime('%Y-%m', User.created_at)
        ).all()

        return jsonify({
            'success': True,
            'total_users': total_users,
            'admin_users': admin_users,
            'regular_users': total_users - admin_users,
            'most_active': [{'username': u[0], 'id': u[1], 'views': u[2]} for u in most_active],
            'monthly_registrations': [{'month': m[0], 'count': m[1]} for m in monthly_registrations]
        })

    except Exception as e:
        print(f"Erro ao buscar estatísticas: {str(e)}")
        return jsonify({'success': False, 'message': f'Erro ao buscar estatísticas: {str(e)}'})


# INICIALIZAR APLICAÇÃO
if __name__ == '__main__':
    # Criar pastas de upload se não existirem
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'videos'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'posters'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails'), exist_ok=True)

    # Criar tabelas se não existirem
    with app.app_context():
        db.create_all()

        # Criar dados de exemplo se o banco estiver vazio
        if not Category.query.first():
            create_sample_data()

    app.run(debug=True, host='0.0.0.0', port=5000)
