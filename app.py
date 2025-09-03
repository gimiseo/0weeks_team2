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
@app.route("/")
def home():
    user = get_current_user(request)
    if user:
        return redirect(url_for("main_page"))
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        nickname = request.form["nickname"]

        existing_user = users_collection.find_one({"username": username})
        if existing_user:
            return "User already exists!"
        
        existing_nickname = users_collection.find_one({"nickname": nickname})
        if existing_nickname:
            return "Nickname already exists!"

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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = users_collection.find_one({"username": username})
        if user and check_password_hash(user["password"], password):
            token = generate_jwt(username)
            resp = make_response(redirect(url_for("main_page")))
            resp.set_cookie("token", token, httponly=True)
            return resp

        return "Invalid credentials!"

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    username = get_current_user(request)
    user = users_collection.find_one({"username": username})
    if not user:
        return redirect(url_for("login"))
    return render_template("testing.html", user=user)

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.set_cookie("token", "", expires=0)
    return resp

@app.route("/team_signup", methods=["GET", "POST"])
def team_signup():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    if request.method == "POST":
        team_name = request.form["team_name"]  # 팀 이름
        week = int(request.form["week"])      # 주차를 int로 변환
        team_password = request.form["team_password"]

        # 같은 주차에 같은 이름의 팀이 있는지 확인
        existing_team = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        if existing_team:
            return f"{week}주차에 '{team_name}' 팀 이름이 이미 존재합니다!"

        # 비밀번호 해시화
        room_password_hash = generate_password_hash(team_password)
        
        # 현재 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return redirect(url_for("login"))

        # 새로운 팀 생성 (MongoDB 구조에 맞게)
        new_team = {
            "teamName": team_name,
            "description": f"{week}주차 스터디 팀",  # 기본 설명
            "week": week,
            "roomPasswordHash": room_password_hash,
            "masterId": current_user["_id"],
            "createdAt": datetime.datetime.utcnow(),
            "upvote": 0,  # 초기 추천수 0
            "members": [
                {
                    "userId": current_user["_id"],
                    "role": "master",
                    "joinedAt": datetime.datetime.utcnow()
                }
            ],
            "posts": []  # 빈 게시물 배열로 시작
        }

        # 팀을 데이터베이스에 삽입
        db["teams"].insert_one(new_team)

        return redirect(url_for("dashboard"))

    return render_template("team_signup.html")

@app.route("/main_page")
@app.route("/main_page/<int:week>")
def main_page(week=None):
    # 주차 계산 및 색상 결정 로직
    start_date = datetime.date(2025, 8, 1) # 배포시 2025, 8, 29 확인
    current_date = datetime.date.today()
    days_diff = (current_date - start_date).days
    current_week = days_diff // 7
    
    # week 파라미터가 있으면 해당 주차, 없으면 현재 주차
    selected_week = week if week is not None else current_week
    
    # 템플릿에 전달할 데이터 생성
    weeks_data = [{
        'week': week_num,
        'color': 'green' if week_num < current_week else 
                'blue' if week_num == current_week else 'gray'
    } for week_num in range(21)]
    
    # 선택된 주차의 팀들을 가져오기 (upvote 기준 내림차순 정렬)
    selected_week_teams = list(db["teams"].find(
        {"week": selected_week}
    ).sort("upvote", -1))
    
    # 팀 멤버들의 상세 정보를 가져오기
    teams_with_members = []
    for team in selected_week_teams:
        # 각 멤버의 상세 정보 조회
        team_members = []
        for member in team.get("members", []):
            user_info = users_collection.find_one({"_id": member["userId"]})
            if user_info:
                team_members.append({
                    "username": user_info["username"],
                    "nickname": user_info["nickname"],
                    "profile_img": user_info.get("profile_img"),
                    "role": member["role"]
                })
        
        teams_with_members.append({
            "teamName": team["teamName"],
            "description": team.get("description", ""),
            "week": team["week"],
            "upvote": team.get("upvote", 0),
            "members": team_members,
            "member_count": len(team_members)
        })
    
    return render_template("main_page.html", 
                         current_week=current_week,
                         selected_week=selected_week,
                         weeks_data=weeks_data,
                         selected_teams=teams_with_members)

@app.route("/teams_partial/<int:week>")
def teams_partial(week):
    """특정 주차의 팀 목록 HTML 부분만 반환"""
    teams = list(db["teams"].find({"week": week}).sort("upvote", -1))
    
    teams_with_members = []
    for team in teams:
        team_members = []
        for member in team.get("members", []):
            user_info = users_collection.find_one({"_id": member["userId"]})
            if user_info:
                team_members.append({
                    "username": user_info["username"],
                    "nickname": user_info["nickname"],
                    "profile_img": user_info.get("profile_img"),
                    "role": member["role"]
                })
        
        teams_with_members.append({
            "teamName": team["teamName"],
            "description": team.get("description", ""),
            "week": team["week"],
            "upvote": team.get("upvote", 0),
            "members": team_members,
            "member_count": len(team_members)
        })
    
    return render_template("teams_partial.html", 
                         selected_week=week,
                         selected_teams=teams_with_members)

@app.route("/team_join", methods=["GET", "POST"])
def team_join():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    if request.method == "POST":
        week = int(request.form["week"])
        team_password = request.form["team_password"]
        
        # 현재 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return redirect(url_for("login"))
        
        # 해당 주차의 모든 팀 조회
        teams_in_week = list(db["teams"].find({"week": week}))
        
        if not teams_in_week:
            return f"{week}주차에 생성된 팀이 없습니다!"
        
        # 비밀번호가 맞는 팀 찾기
        target_team = None
        for team in teams_in_week:
            if check_password_hash(team["roomPasswordHash"], team_password):
                target_team = team
                break
        
        if not target_team:
            return f"{week}주차에 해당 비밀번호를 가진 팀이 없습니다!"
        
        # 이미 해당 팀의 멤버인지 확인
        is_already_member = any(
            member["userId"] == current_user["_id"] 
            for member in target_team["members"]
        )
        
        if is_already_member:
            return f"이미 '{target_team['teamName']}' 팀의 멤버입니다!"
        
        # 새 멤버를 팀에 추가
        new_member = {
            "userId": current_user["_id"],
            "role": "member",
            "joinedAt": datetime.datetime.utcnow()
        }
        
        db["teams"].update_one(
            {"_id": target_team["_id"]},
            {"$push": {"members": new_member}}
        )
        
        success_message = f"'{target_team['teamName']}' 팀에 성공적으로 가입되었습니다!"
        return f'<script>alert("{success_message}"); window.location.href="{url_for("dashboard")}";</script>'

    return render_template("team_join.html")

@app.route("/team_page", methods=["GET", "POST"])
def team_page():
    return render_template("team_page.html")

if __name__ == "__main__":
    app.run(debug=True)