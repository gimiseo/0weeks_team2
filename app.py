from flask import Flask, render_template, request, redirect, url_for, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
import jwt
import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = "supersecretkey"  # ⚠️ change in production

# --- MongoDB setup ---
# MongoDB 연결 URI를 macOS 환경에 맞게 확인
client = MongoClient('localhost', 27017) # localhost 대신 127.0.0.1 사용
db = client["flask_jwt_auth"]
users_collection = db["users"]

# --- 파일 경로 설정 ---
PROFILE_FOLDER = os.path.join(os.getcwd(), "static", "profile_imgs")  # 절대 경로로 변경
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config["PROFILE_FOLDER"] = PROFILE_FOLDER

UPLOAD_FOLDER = os.path.join(os.getcwd(), "static", "uploads")  # 업로드 폴더 경로
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

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
    # 기본 페이지를 teampage로 리다이렉트
    return redirect(url_for("teampage"))

@app.route("/signup", methods=["GET", "POST"])
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

@app.route("/login", methods=["GET", "POST"])
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

@app.route("/dashboard")
def dashboard():
    username = get_current_user(request)
    user = users_collection.find_one({"username": username})
    if not user:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=user)

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.set_cookie("token", "", expires=0)
    return resp

@app.route("/teamsignup", methods=["GET", "POST"]) # 팀 생성 API
def teamsignup():
    user = get_current_user(request)
    if not user:
        return redirect(url_for("login"))

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
        return redirect(url_for("login"))

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

# 작성된 글을 저장할 리스트
posts = []

@app.route('/teampagewrite', methods=['GET', 'POST'])
def teampagewrite():
    if request.method == 'POST':
        # 폼 데이터 가져오기
        title = request.form.get('title')
        content = request.form.get('content')
        author = request.form.get('author')
        image_url = None

        # 파일 업로드 처리
        if 'image' in request.files:
            image = request.files['image']
            if image.filename != '':
                image_path = os.path.join(app.config["UPLOAD_FOLDER"], image.filename)
                image.save(image_path)
                image_url = f"/static/uploads/{image.filename}"

        # 데이터 저장
        posts.append({'title': title, 'content': content, 'author': author, 'image_url': image_url})
        # teampage로 리다이렉트
        return redirect(url_for('teampage'))
    return render_template('teampagewrite.html')

@app.route('/teampage')
def teampage():
    # 저장된 글을 teampage.html에 전달
    return render_template('teampage.html', posts=posts)

@app.route('/delete_post', methods=['POST'])
def delete_post():
    post_title = request.form.get('post_title')
    global posts
    # 제목을 기준으로 해당 글 삭제
    posts = [post for post in posts if post['title'] != post_title]
    return redirect(url_for('teampage'))

@app.route('/edit_post', methods=['GET'])
def edit_post():
    title = request.args.get('title')
    post = next((post for post in posts if post['title'] == title), None)
    if not post:
        return "Post not found!", 404  # 글을 찾지 못한 경우 404 에러 반환
    return render_template('edit_post.html', post=post)

@app.route('/update_post', methods=['POST'])
def update_post():
    old_title = request.form.get('old_title')
    new_title = request.form.get('title')
    new_content = request.form.get('content')
    global posts
    for post in posts:
        if post['title'] == old_title:
            post['title'] = new_title
            post['content'] = new_content
            break
    return redirect(url_for('teampage'))

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return {"error": "No image uploaded"}, 400

    image = request.files['image']
    if image.filename == '':
        return {"error": "No selected file"}, 400

    # 이미지 저장
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], image.filename)
    image.save(image_path)

    # 저장된 이미지의 URL 반환
    image_url = f"/static/uploads/{image.filename}"
    return {"url": image_url}, 200

@app.route('/delete_team', methods=['POST'])
def delete_team():
    user = get_current_user(request)
    if not user:
        return redirect(url_for("login"))

    # 현재 사용자가 팀의 생성자인지 확인
    team = db["teams"].find_one({"created_by": user})
    if not team:
        return "삭제 권한이 없습니다. 팀 생성자만 팀을 삭제할 수 있습니다!", 403

    try:
        # 팀과 관련된 모든 데이터 삭제
        team_id = team["_id"]
        
        # 1. 팀의 모든 게시글 삭제 (현재는 메모리에 저장되어 있으므로 전역 posts 리스트 초기화)
        global posts
        posts.clear()  # 모든 게시글 삭제
        
        # 2. 팀 정보 삭제
        db["teams"].delete_one({"_id": team_id})
        
        # 3. 팀과 관련된 추가 데이터가 있다면 여기서 삭제
        # 예: 팀 멤버십 정보, 팀 설정 등
        
        # 대시보드로 리다이렉트
        return redirect(url_for("dashboard"))
        
    except Exception as e:
        return f"팀 삭제 중 오류가 발생했습니다: {str(e)}", 500

if __name__ == "__main__":
    # macOS에서 실행 시 호스트를 명시적으로 설정
    app.run('0.0.0.0', port=5001, debug=True)
