import requests  # Importerar request library för http requests
from flask import Flask, jsonify, request, Response, send_file  # importerar flask moduler
from flask_sqlalchemy import SQLAlchemy  # Importerar SQLAlchemy för databas hantering
from prometheus_client import Counter, Histogram, Gauge, generate_latest, start_http_server  # import prometheus metric
import time  # Import time

app = Flask(__name__)  # Flask instans
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.db'  # databas URI för SQLAlchemy
db = SQLAlchemy(app)  # Databas instans

OMDB_API_KEY = 'ac4df6cd'  # OMDB API-nyckel
OMDB_API_URL = 'https://www.omdbapi.com/'  # OMDB API URI

# Init Prometheus metric
REQUEST_LATENCY = Histogram('http_request_latency_seconds', 'HTTP request latency', ['endpoint'])
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests')
UPTIME_GAUGE = Gauge('app_uptime_seconds', 'Uptime of the application in seconds')

START_TIME = time.time()  # recording and storing run time

# Prometheus server på port 80
start_http_server(8000)


@app.route('/metrics')  # Endpoint för metrics
def custom_metrics():
    uptime_seconds = int(time.time() - START_TIME)
    UPTIME_GAUGE.set(uptime_seconds)

    return Response(generate_latest(), mimetype='text/plain')


class User(db.Model):  # SQLAlchemy db models
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    movies = db.relationship('Movie', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id='{self.user_id}', name='{self.name}', email='{self.email}')>"


class Movie(db.Model):  # SQLAlchemy db models
    id = db.Column(db.Integer, primary_key=True)
    imdb_id = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@app.route('/api/users', methods=['POST'])  # Endpoint för att lägga till user
def add_user():
    data = request.get_json()  # extraherar JSON data från request
    user_id = data.get('user_id')  # Hämtar user ID från JSON datan
    name = data.get('name')  # Hämtar namn från JSON datan
    email = data.get('email')  # Hämtar email från JSON datan
    movies = data.get('movies')  # Hämtar movies från JSON datan

    if not user_id or not name or not email:  # validerar
        return jsonify({'message': 'User ID, name, and email are required'}), 400

    new_user = User(user_id=user_id, name=name, email=email)  # Skapar user objekt för att commita till db
    db.session.add(new_user)
    db.session.commit()

    if movies:  # lägger till associerade movies
        for imdb_id in movies:
            new_movie = Movie(imdb_id=imdb_id, user_id=new_user.id)
            db.session.add(new_movie)

    db.session.commit()  # commitar till db

    REQUEST_COUNT.inc()  # Inkrementar request count

    return jsonify({'message': 'User added successfully'}), 201  # returnerar om lyckat


@app.route('/api/users/<string:user_id>', methods=['GET'])  # Endpoint för hämta vid specifik user ID
def get_user_and_movies(user_id):
    user = User.query.filter_by(user_id=user_id).first()  # Söker efter user i db
    if not user:  # om user not found
        return jsonify({'message': 'User not found'}), 404

    user_data = {'user_id': user.user_id, 'name': user.name, 'email': user.email, 'movies': []}  # Skapar user_data dict
    for movie in user.movies:  # loopar genom users filmer
        movie_details = fetch_movie_details(movie.imdb_id)  # fetchar film detaljer från OMDB
        if movie_details:  # Om film detaljer finns
            user_data['movies'].append(movie_details)  # Appendar film detaljer

    REQUEST_COUNT.inc()  # Incrementar request count

    return jsonify(user_data)  # returnerar user data


@app.route('/api/users/<string:user_id>', methods=['PUT'])  # endpoint för att uppdatera user details
def update_user(user_id):
    data = request.get_json()  # Extraherar JSON data från request
    name = data.get('name')  # Hämtar name från JSON data
    email = data.get('email')  # Hämtar email från JSON data
    imdb_id = data.get('imdb_id')  # Hämtar IMDB ID från JSON data
    action = data.get('action')  # Hämtar IMDB ID från JSON data

    user = User.query.filter_by(user_id=user_id).first()  # Söker databas efter user id
    if not user:  # om user not found
        return jsonify({'message': 'User not found'}), 404

    if name:  # om namn finns ändras det
        user.name = name
    if email:  # om email finns ändras det
        user.email = email

    if action == 'add' and imdb_id:  # Hanterar action om det är add och lägger in ny film i db
        new_movie = Movie(imdb_id=imdb_id, user_id=user.id)
        db.session.add(new_movie)
    elif action == 'remove' and imdb_id:  # Hanterar action om det är remove
        movie = Movie.query.filter_by(user_id=user.id, imdb_id=imdb_id).first()  # sök i databas efter user id och film
        if movie:
            db.session.delete(movie)  # Tar bort film från databas
        else:
            return jsonify({'message': 'Movie not found for this user'}), 404  # returnerar om film inte fanns

    db.session.commit()  # commitar ändringar

    REQUEST_COUNT.inc()  # Incrementar request count

    return jsonify({'message': 'User updated successfully'})  # returnerar om lyckat


@app.route('/api/users/<string:user_id>', methods=['DELETE'])  # endpoint för att ta bort user
def delete_user(user_id):
    user = User.query.filter_by(user_id=user_id).first()  # söker databas efter user id
    if not user:  # om inte user found
        return jsonify({'message': 'User not found'}), 404

    db.session.delete(user)  # tar bort user från db
    db.session.commit()  # commitar ändringar

    REQUEST_COUNT.inc()  # Incrementar request count

    return jsonify({'message': 'User deleted successfully'}), 204  # returnerar om lyckat


@app.route('/api/users', methods=['GET'])  # endpoint för hämta alla users
def get_all_users():
    users = User.query.all()  # söker efter alla users i db
    if not users:  # om db tom
        return jsonify({'message': 'No users found'}), 404

    users_data = []  # empty list för att spara user data
    for user in users:  # loopar genom alla users
        user_data = {'user_id': user.user_id, 'name': user.name, 'email': user.email}  # skapar userdata dict
        users_data.append(user_data)  # appendar user data till empty list

    REQUEST_COUNT.inc()  # Incrementar request count

    return jsonify(users_data)  # returnerar om lyckat


@app.route('/api/users/movies', methods=['GET'])  # Endpoint för att få alla users och filmer
def get_users_and_movies():
    users = User.query.all()  # söker efter alla users i db
    if not users:  # om db tom
        return jsonify({'message': 'No users found'}), 404

    users_data = []  # skapar empty list för user data
    for user in users:  # loopar genom alla users
        user_data = {'user_id': user.user_id, 'name': user.name, 'email': user.email, 'movies': []}  # skapar dict för user data
        for movie in user.movies:  # loopar genom user filmer
            movie_details = fetch_movie_details(movie.imdb_id)  # fetchar film detaljer genom OMDB API
            if movie_details:  # om film detaljer finns
                user_data['movies'].append(movie_details)  # appendar film detaljer
        users_data.append(user_data)  # appendar user data till empty list

    REQUEST_COUNT.inc()  # Increment request count

    return jsonify(users_data)  # returnerar user data JSON


@app.route('/api/docs')  # endpoint for att visa API dokumentation
def api_docs():
    spec_file_path = 'openapi.yaml'  # path till dokumentation
    return send_file(spec_file_path, mimetype='text/yaml')  # servar dokumentationen


def fetch_movie_details(imdb_id):  # funktion för fetcha film detaljer från OMDB API
    params = {'i': imdb_id, 'apikey': OMDB_API_KEY}  # Ställer in request parametrar
    response = requests.get(OMDB_API_URL, params=params)  # skapar GET request till OMDB API
    if response.status_code == 200:  # Om request lyckat
        movie_data = response.json()  # Parsar JSON response
        return {'imdb_id': imdb_id, 'title': movie_data.get('Title'), 'year': movie_data.get('Year')}  # returnerar film detaljer
    elif response.status_code == 404:  # om film inte hittad
        return {'imdb_id': imdb_id, 'title': 'Movie Not Found', 'year': 'N/A'}
    else:
        return None  # om error returnera None


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Skapar database tables
    app.run(debug=False)  # run flask app
