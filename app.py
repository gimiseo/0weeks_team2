from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import jwt
import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = "supersecretkey"  # ⚠️ change in production

# --- MongoDB setup ---
client = MongoClient("mongodb://localhost:27017/")  # or your MongoDB Atlas URI
db = client["flask_jwt_auth"]
users_collection = db["users"]

PROFILE_FOLDER = "static/profile_imgs"
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config["PROFILE_FOLDER"] = PROFILE_FOLDER

# --- JWT helper functions ---
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

# --- Routes ---
@app.route("/") # 홈 API
def home():
    user = get_current_user(request)
    if user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])  # 회원가입 API
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        nickname = request.form["nickname"]

        existing_user = users_collection.find_one({"username": username})
        if existing_user:
            return "User already exists!"

        profile_img = request.files.get("profile_img")
        profile_filename = None
        if profile_img:
            ext = os.path.splitext(profile_img.filename)[1]
            profile_filename = f"{username}_profile{ext}"
            save_path = os.path.join(app.config["PROFILE_FOLDER"], profile_filename)
            profile_img.save(save_path)
        
        password_hash = generate_password_hash(password)
        users_collection.insert_one({
            "username": username,
            "password": password_hash,
            "nickname": nickname,
            "profile_img": profile_filename
        })
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])  # 로그인 API
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = users_collection.find_one({"username": username})
        if user and check_password_hash(user["password"], password):
            token = generate_jwt(username)
            resp = make_response(redirect(url_for("dashboard")))
            resp.set_cookie("token", token, httponly=True)
            return resp

        return "Invalid credentials!"

    return render_template("login.html")

@app.route("/dashboard")    # 대시보드 API
def dashboard():
    username = get_current_user(request)
    user = users_collection.find_one({"username": username})
    if not user:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=user)

@app.route("/logout") # 로그아웃 API
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.set_cookie("token", "", expires=0)
    return resp

@app.route("/teamsignup", methods=["GET", "POST"]) # 팀 생성 API
def teamsignup():
    user = get_current_user(request)
    if not user:
        return "로그인 먼저 하십시오!"   #redirect(url_for("login")) <- 원래 코드

    if request.method == "POST":
        team_name = request.form["username"]  # 팀 이름
        week = request.form["week"]
        team_password = request.form["team_password"]

        existing_team = db["teams"].find_one({"team_name": team_name})
        if existing_team:
            return "팀 이름이 이미 존재합니다!"

        team_password_hash = generate_password_hash(team_password)

        db["teams"].insert_one({
            "team_name": team_name,
            "week": week,
            "password": team_password_hash,
            "created_by": user,
            "created_at": datetime.datetime.utcnow()
        })

        return redirect(url_for("dashboard"))

    return render_template("teamsignup.html")

@app.route("/teamjoin", methods=["GET", "POST"])  # 팀 합류 API
def teamjoin():
    user = get_current_user(request)
    if not user:
        
        return "로그인 먼저 하십시오!"     #redirect(url_for("login")) <- 원래 코드

    if request.method == "POST":
        week = int(request.form["week"])
        team_password = request.form["team_password"]

        # 이미 생성된 팀 정보 가져오기 (week 기준)
        team = db["teams"].find_one({"week": week})
        if not team:
            return "해당 주차에 생성된 팀이 없습니다!"

        # 비밀번호 확인
        if not check_password_hash(team["password"], team_password):
            return "팀 비밀번호가 올바르지 않습니다!"

        # 팀 가입 처리 (예: members 배열에 추가)
        db["teams"].update_one(
            {"_id": team["_id"]},
            {"$addToSet": {"members": user}}
        )

        return redirect(url_for("dashboard"))

    return render_template("teamjoin.html")

@app.route("/mypage", methods=["GET", "POST"])
def mypage():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    # DB에서 최신 유저 정보 가져오기
    user = users_collection.find_one({"username": username})

    if request.method == "POST":
        # 이름 수정
        new_name = request.form.get("nickname")
        if new_name:
            users_collection.update_one(
                {"username": username},
                {"$set": {"nickname": new_name}}
            )
            user["nickname"] = new_name

        # 프로필 사진 업로드
        profile_img = request.files.get("profile_img")
        if profile_img:
            ext = os.path.splitext(profile_img.filename)[1]
            profile_filename = f"{username}_profile{ext}"
            save_path = os.path.join(app.config["PROFILE_FOLDER"], profile_filename)
            profile_img.save(save_path)

            users_collection.update_one(
                {"username": username},
                {"$set": {"profile_img": profile_filename}}
            )
            user["profile_img"] = profile_filename

        # POST 후 리다이렉트 → 최신 DB 정보 반영
        return redirect(url_for("mypage"))

    # 팀 리스트 가져오기 (0~20 week)
    teams = []
    for week in range(0, 21):
        team = db["teams"].find_one({"week": week})
        if team:
            teams.append({"week": week, "team_name": team["team_name"]})
        else:
            teams.append({"week": week, "team_name": f"Team {100 + week}"})

    return render_template("mypage.html", user=user, teams=teams)


@app.route("/delete_profile") # 프로필 사진 삭제 API
def delete_profile():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    user = users_collection.find_one({"username": username})
    if user and user.get("profile_img"):
        # 파일 삭제
        try:
            os.remove(os.path.join(app.config["PROFILE_FOLDER"], user["profile_img"]))
        except FileNotFoundError:
            pass

        # DB 정보 삭제
        users_collection.update_one(
            {"username": username},
            {"$set": {"profile_img": None}}
        )

    return redirect(url_for("mypage"))


@app.route("/update_profile_img", methods=["POST"])  # 프로필 사진 업데이트 API
def update_profile_img():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    user = users_collection.find_one({"username": username})
    profile_img = request.files.get("profile_img")
    if profile_img:
        ext = os.path.splitext(profile_img.filename)[1]
        profile_filename = f"{username}_profile{ext}"
        save_path = os.path.join(app.config["PROFILE_FOLDER"], profile_filename)
        profile_img.save(save_path)

        users_collection.update_one(
            {"username": username},
            {"$set": {"profile_img": profile_filename}}
        )

    return redirect(url_for("mypage"))



if __name__ == "__main__":
    app.run(debug=True)
