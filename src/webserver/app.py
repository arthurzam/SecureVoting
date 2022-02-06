from flask import Flask
import flask
app = Flask(__name__)

TALLIERS = ['ws://127.0.0.1:8080', 'ws://127.0.0.1:8081', 'ws://127.0.0.1:8082']

@app.route('/')
def hello_world():
    return 'Hello, Docker!'

@app.route('/register')
def register():
    # resp = flask.send_from_directory('static', 'register.html')
    resp = flask.render_template('register.html', talliers=TALLIERS)
    # resp.headers.set('Content-Security-Policy', "connect-src 'self' www.example.com;")
    return resp

@app.route('/login')
def login():
    # resp = flask.send_from_directory('static', 'register.html')
    resp = flask.render_template('login.html', talliers=TALLIERS)
    return resp
