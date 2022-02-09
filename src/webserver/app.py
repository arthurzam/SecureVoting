import flask

app = flask.Flask(__name__)

TALLIERS = ['127.0.0.1:8080', '127.0.0.1:8081', '127.0.0.1:8082']
TALLIERS = ['ws://' + x for x in TALLIERS]
CSP = f"connect-src 'self' {' '.join(TALLIERS)};"

@app.context_processor
def inject_user():
    return {'talliers': TALLIERS}

@app.after_request
def apply_caching(response):
    response.headers.set('Content-Security-Policy', CSP)
    return response

@app.route('/')
def hello_world():
    return 'Hello, Docker!'

@app.route('/register')
def register():
    # resp = flask.send_from_directory('static', 'register.html')
    return flask.render_template('register.html')

@app.route('/login')
def login():
    return flask.render_template('login.html')

@app.route('/election/create')
def election_create():
    return flask.render_template('election_create.html')

@app.route('/elections')
def elections():
    return flask.render_template('elections.html')
