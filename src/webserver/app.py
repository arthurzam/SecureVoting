import flask
import os


app = flask.Flask(__name__)

print('Hello', os.environ)
TALLIERS = os.getenv('TALLIERS_EXTERNAL').split('|')
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
    return flask.redirect('login')

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

@app.route('/election/vote')
def election_vote():
    return flask.render_template('election_vote.html')

@app.route('/elections')
def elections():
    return flask.render_template('elections.html')
