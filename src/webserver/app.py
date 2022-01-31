from flask import Flask
import flask
app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello, Docker!'

@app.route('/register')
def register():
    resp = flask.send_from_directory('static', 'register.html')
    # resp.headers.set('Content-Security-Policy', "connect-src 'self' www.example.com;")
    return resp
