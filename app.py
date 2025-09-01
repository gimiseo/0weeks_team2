from flask import Flask, render_template, request, redirect, url_for, make_response
import jwt
import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = "supersecretkey"  # change this in production!

# Fake in-memory database
users = {}  # {username: password_hash}

def generate_jwt(username):
    payload = {
        "user": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")

def decode_jwt(token):
    try:
        return jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def get_current_user(request):
    token = request.cookies.get("token")
    if token:
        data = decode_jwt(token)
        if data:
            return data["user"]
    return None

@app.route("/")
def home():
    user = get_current_user(request)
    if user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username in users:
            return "User already exists!"
        
        # ✅ store password securely
        users[username] = generate_password_hash(password)
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username in users and check_password_hash(users[username], password):
            token = generate_jwt(username)
            resp = make_response(redirect(url_for("dashboard")))
            resp.set_cookie("token", token, httponly=True)
            return resp

        return "Invalid credentials!"
    
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    user = get_current_user(request)
    if not user:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=user)

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.set_cookie("token", "", expires=0)
    return resp

if __name__ == "__main__":
    app.run(debug=True)
