from flask import Flask, render_template, request, redirect, url_for, make_response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson import ObjectId
import jwt
import datetime
import os
import uuid
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = "supersecretkey"  # ⚠️ change in production

# --- MongoDB setup ---
client = MongoClient("mongodb://localhost:27017/")  # or your MongoDB Atlas URI
db = client["flask_jwt_auth"]
users_collection = db["users"]

PROFILE_FOLDER = "static/profile_imgs"
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config["PROFILE_FOLDER"] = PROFILE_FOLDER

# 업로드된 이미지 폴더 설정
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB 제한

# 허용되는 파일 확장자
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

# 이미지 삭제 관련 헬퍼 함수들
def extract_image_urls_from_content(content):
    """HTML 콘텐츠에서 이미지 URL들을 추출"""
    if not content:
        return []
    
    # img 태그의 src 속성에서 /static/uploads/ 경로를 찾음
    pattern = r'src="([^"]*static/uploads/[^"]*)"'
    urls = re.findall(pattern, content)
    return urls

def delete_image_files(image_urls):
    """이미지 URL들에 해당하는 실제 파일들을 삭제"""
    deleted_files = []
    for url in image_urls:
        try:
            # URL에서 파일 경로 추출 (/static/uploads/filename.jpg -> static/uploads/filename.jpg)
            if url.startswith('/static/uploads/'):
                file_path = url[1:]  # 앞의 '/' 제거
                full_path = os.path.join(os.getcwd(), file_path)
                
                if os.path.exists(full_path):
                    os.remove(full_path)
                    deleted_files.append(full_path)
                    print(f"삭제된 이미지: {full_path}")
        except Exception as e:
            print(f"이미지 삭제 실패: {url}, 오류: {e}")
    
    return deleted_files

def delete_post_images(post_content):
    """포스트 콘텐츠에서 이미지들을 찾아서 삭제"""
    image_urls = extract_image_urls_from_content(post_content)
    return delete_image_files(image_urls)

def delete_team_images(team_data):
    """팀의 모든 포스트에서 이미지들을 찾아서 삭제"""
    deleted_files = []
    
    # 팀의 모든 포스트 확인
    posts = team_data.get("posts", [])
    for post in posts:
        content = post.get("content", "")
        post_deleted_files = delete_post_images(content)
        deleted_files.extend(post_deleted_files)
    
    return deleted_files

def find_unused_images_in_edit(old_content, new_content):
    """글 수정 시 더 이상 사용되지 않는 이미지들을 찾아서 반환"""
    old_images = extract_image_urls_from_content(old_content)
    new_images = extract_image_urls_from_content(new_content)
    
    # 기존에 있었지만 새 콘텐츠에서는 없는 이미지들
    unused_images = [img for img in old_images if img not in new_images]
    return unused_images

def delete_unused_images_on_edit(old_content, new_content):
    """글 수정 시 사용하지 않는 이미지들을 삭제"""
    unused_images = find_unused_images_in_edit(old_content, new_content)
    if unused_images:
        deleted_files = delete_image_files(unused_images)
        return deleted_files
    return []

def find_recent_uploaded_images():
    """최근 업로드된 이미지들 중 어떤 글에서도 사용되지 않는 이미지들을 찾음"""
    try:
        # 최근 1시간 내에 업로드된 이미지들 찾기
        upload_folder = os.path.join(os.getcwd(), 'static/uploads')
        if not os.path.exists(upload_folder):
            return []
        
        recent_images = []
        current_time = datetime.datetime.now()
        
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path):
                # 파일 생성 시간 확인 (1시간 이내)
                file_time = datetime.datetime.fromtimestamp(os.path.getctime(file_path))
                if (current_time - file_time).total_seconds() < 3600:  # 1시간
                    recent_images.append(f"/static/uploads/{filename}")
        
        # 모든 팀의 모든 포스트에서 사용 중인 이미지들 수집
        used_images = set()
        teams = list(db["teams"].find({}))
        
        for team in teams:
            posts = team.get("posts", [])
            for post in posts:
                content = post.get("content", "")
                post_images = extract_image_urls_from_content(content)
                used_images.update(post_images)
        
        # 사용되지 않는 최근 이미지들 반환
        unused_recent_images = [img for img in recent_images if img not in used_images]
        return unused_recent_images
        
    except Exception as e:
        print(f"최근 업로드 이미지 정리 중 오류: {e}")
        return []

def cleanup_unused_recent_images():
    """사용되지 않는 최근 업로드 이미지들을 삭제"""
    unused_images = find_recent_uploaded_images()
    if unused_images:
        deleted_files = delete_image_files(unused_images)
        return deleted_files
    return []

def cleanup_all_unused_images():
    """전체 업로드 폴더에서 사용되지 않는 모든 이미지들을 정리"""
    try:
        upload_folder = os.path.join(os.getcwd(), 'static/uploads')
        if not os.path.exists(upload_folder):
            return []
        
        # 업로드 폴더의 모든 이미지 파일들
        all_images = []
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            if os.path.isfile(file_path) and any(filename.lower().endswith(ext) for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']):
                all_images.append(f"/static/uploads/{filename}")
        
        # 모든 팀의 모든 포스트에서 사용 중인 이미지들 수집
        used_images = set()
        teams = list(db["teams"].find({}))
        
        for team in teams:
            posts = team.get("posts", [])
            for post in posts:
                content = post.get("content", "")
                post_images = extract_image_urls_from_content(content)
                used_images.update(post_images)
        
        # 사용되지 않는 이미지들 찾기
        unused_images = [img for img in all_images if img not in used_images]
        
        # 사용되지 않는 이미지들 삭제
        if unused_images:
            deleted_files = delete_image_files(unused_images)
            print(f"전체 정리: {len(deleted_files)}개의 미사용 이미지를 삭제했습니다.")
            return deleted_files
        
        return []
        
    except Exception as e:
        print(f"전체 이미지 정리 중 오류: {e}")
        return []

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
        team_name = request.form["team_name"]  
        week = int(request.form["week"])      
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

        # 새로운 팀 생성
        new_team = {
            "teamName": team_name,
            "description": f"{week}주차 스터디 팀",  
            "week": week,
            "roomPasswordHash": room_password_hash,
            "masterId": current_user["_id"],
            "createdAt": datetime.datetime.utcnow(),
            "upvote": 0,  
            "members": [
                {
                    "userId": current_user["_id"],
                    "role": "master",
                    "joinedAt": datetime.datetime.utcnow()
                }
            ],
            "posts": []  
        }

        # 팀을 데이터베이스에 삽입
        db["teams"].insert_one(new_team)

        return redirect(url_for("dashboard"))

    return render_template("team_signup.html")

@app.route("/main_page")
@app.route("/main_page/<int:week>")
def main_page(week=None):
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 로그인한 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    
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
        
        # 역할별로 정렬 (팀장 -> 관리자 -> 멤버 순)
        role_order = {"master": 0, "admin": 1, "member": 2}
        team_members.sort(key=lambda x: role_order.get(x["role"], 999))
        
        teams_with_members.append({
            "id": str(team["_id"]),  
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
                         selected_teams=teams_with_members,
                         current_user=current_user)

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
                
        # 역할별로 정렬 (팀장 -> 관리자 -> 멤버 순)
        role_order = {"master": 0, "admin": 1, "member": 2}
        team_members.sort(key=lambda x: role_order.get(x["role"], 999))
        
        teams_with_members.append({
            "id": str(team["_id"]),  
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

@app.route("/team_join/<int:default_week>", methods=["GET", "POST"])
def team_join(default_week=None):
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

    return render_template("team_join.html", default_week=default_week)

@app.route("/team_join/<team_id>", methods=["GET", "POST"])
def team_join_specific(team_id):
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # team_id 유효성 검사
    if not team_id or team_id.strip() == "":
        return redirect(url_for("main_page"))
    
    try:
        team_object_id = ObjectId(team_id)
    except:
        return redirect(url_for("main_page"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        return redirect(url_for("main_page"))
    
    if request.method == "POST":
        team_password = request.form["team_password"]
        
        # 현재 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return redirect(url_for("login"))
        
        # 비밀번호 확인
        if not check_password_hash(team["roomPasswordHash"], team_password):
            return render_template("team_join_specific.html", 
                                 team=team, 
                                 error="비밀번호가 올바르지 않습니다.")
        
        # 이미 해당 팀의 멤버인지 확인
        is_already_member = any(
            member["userId"] == current_user["_id"] 
            for member in team["members"]
        )
        
        if is_already_member:
            return render_template("team_join_specific.html", 
                                 team=team, 
                                 error="이미 이 팀의 멤버입니다.")
        
        # 새 멤버를 팀에 추가
        new_member = {
            "userId": current_user["_id"],
            "role": "member",
            "joinedAt": datetime.datetime.utcnow()
        }
        
        db["teams"].update_one(
            {"_id": team["_id"]},
            {"$push": {"members": new_member}}
        )
        
        # 성공 시 팀 페이지로 리다이렉트
        return redirect(url_for("team_page", team_id=team_id))
    
    return render_template("team_join_specific.html", team=team)

@app.route("/team_page")
def team_page_redirect():
    return redirect(url_for("main_page"))

@app.route("/team_page/<team_id>")
def team_page(team_id):
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 로그인한 사용자 정보 조회
    current_user_data = users_collection.find_one({"username": username})
    
    # team_id가 비어있거나 None인 경우 main_page로 리다이렉트
    if not team_id or team_id.strip() == "":
        return redirect(url_for("main_page"))
    
    try:
        team_object_id = ObjectId(team_id)
    except:
        # 잘못된 팀 ID인 경우 main_page로 리다이렉트
        return redirect(url_for("main_page"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        # 팀을 찾을 수 없는 경우 main_page로 리다이렉트
        return redirect(url_for("main_page"))
    
    # 팀 멤버들의 상세 정보 조회
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
    
    # 현재 사용자가 팀 멤버인지 확인
    current_user = users_collection.find_one({"username": username})
    is_member = any(member["userId"] == current_user["_id"] for member in team.get("members", []))
    
    # Check if current user is team master
    is_team_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master"
        for member in team.get("members", [])
    )
    
    # Process posts to include post IDs
    posts_with_ids = []
    for post in team.get("posts", []):
        is_post_author = post.get("authorId") == current_user["_id"]
        
        post_data = {
            "id": str(post.get("_id", "")),  # Convert ObjectId to string, empty if no _id
            "title": post.get("title", ""),
            "content": post.get("content", ""),
            "author": post.get("author", ""),
            "authorId": post.get("authorId"),
            "createdAt": post.get("createdAt"),
            "updatedAt": post.get("updatedAt"),
            "likes": post.get("likes", 0),
            
            "can_edit": is_post_author,
            "can_delete": is_post_author or is_team_master
        }
        posts_with_ids.append(post_data)

    # 팀 데이터 구성
    team_data = {
        "id": str(team["_id"]),
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "upvote": team.get("upvote", 0),
        "members": team_members,
        "member_count": len(team_members),
        "posts": posts_with_ids
    }
    
    return render_template("team_page.html",
                           team=team_data,
                           is_member=is_member,
                           current_user=current_user_data)

@app.route("/team_post_write/<team_id>", methods=["GET", "POST"])
def team_post_write(team_id):
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # team_id 유효성 검사
    if not team_id or team_id.strip() == "":
        return redirect(url_for("main_page"))
    
    try:
        team_object_id = ObjectId(team_id)
    except:
        return redirect(url_for("main_page"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        return redirect(url_for("main_page"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 현재 사용자가 해당 팀의 멤버인지 확인
    is_member = any(
        member["userId"] == current_user["_id"] 
        for member in team.get("members", [])
    )
    
    if not is_member:
        return redirect(url_for("team_page", team_id=team_id))
    
    if request.method == "POST":
        # 폼에서 데이터 가져오기
        author = request.form.get("author", "").strip()
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        
        # 기본 유효성 검사
        if not title or len(title) < 2:
            return '<script>alert("제목은 최소 2글자 이상이어야 합니다."); history.back();</script>'
        
        if len(title) > 100:
            return '<script>alert("제목은 100글자를 초과할 수 없습니다."); history.back();</script>'
        
        if not author:
            return '<script>alert("작성자명을 입력해주세요."); history.back();</script>'
        
        # 새 포스트 생성 (고유한 post_id 추가)
        new_post = {
            "_id": ObjectId(),  # 각 포스트에 고유한 ID 생성
            "title": title,
            "content": content,
            "author": author,
            "authorId": current_user["_id"],
            "createdAt": datetime.datetime.utcnow(),
            "likes": 0
        }
        
        try:
            # 팀에 포스트 추가
            result = db["teams"].update_one(
                {"_id": team["_id"]},
                {"$push": {"posts": new_post}}
            )
            
            if result.modified_count > 0:
                # 글 작성 완료 후 사용되지 않는 최근 업로드 이미지들 정리
                recent_deleted = cleanup_unused_recent_images()
                if recent_deleted:
                    print(f"글 작성 완료 후 미사용 이미지 {len(recent_deleted)}개를 정리했습니다.")
                
                success_message = "글이 성공적으로 작성되었습니다!"
                return f'<script>alert("{success_message}"); window.location.href="/team_page/{team_id}";</script>'
            else:
                return '<script>alert("글 작성에 실패했습니다. 다시 시도해주세요."); history.back();</script>'
                
        except Exception as e:
            print(f"글 작성 중 오류 발생: {e}")
            return '<script>alert("글 작성 중 오류가 발생했습니다. 다시 시도해주세요."); history.back();</script>'
    
    # GET 요청 처리 - 글 작성 폼 표시
    # 팀 멤버들의 상세 정보 조회
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
    
    # 역할별로 정렬 (팀장 -> 관리자 -> 멤버 순)
    role_order = {"master": 0, "admin": 1, "member": 2}
    team_members.sort(key=lambda x: role_order.get(x["role"], 999))
    
    # 템플릿에 전달할 팀 데이터 구성
    team_data = {
        "id": str(team["_id"]),
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "upvote": team.get("upvote", 0),
        "members": team_members,
        "member_count": len(team_members)
    }
    
    return render_template("team_post_write.html", team=team_data, current_user=current_user)

# 이미지 업로드를 위한 라우트 추가
@app.route("/upload_image", methods=["POST"])
def upload_image():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    if 'image' not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "파일이 선택되지 않았습니다."}), 400
    
    if file and allowed_file(file.filename):
        # 안전한 파일명 생성
        filename = secure_filename(file.filename)
        # 중복 방지를 위해 타임스탬프 추가
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_")
        filename = timestamp + filename
        
        # 파일 저장
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # 웹에서 접근 가능한 URL 반환
        image_url = f"/static/uploads/{filename}"
        return jsonify({"url": image_url})
    
    return jsonify({"error": "허용되지 않는 파일 형식입니다."}), 400

@app.route("/edit_post", methods=["GET", "POST"])
def edit_post():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    post_id = request.args.get("post_id") or request.form.get("post_id")
    team_id = request.args.get("team_id") or request.form.get("team_id")
    
    if not post_id or not team_id:
        return redirect(url_for("main_page"))
    
    try:
        team_object_id = ObjectId(team_id)
        post_object_id = ObjectId(post_id)
    except:
        return redirect(url_for("main_page"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        return redirect(url_for("main_page"))
    
    # 해당 포스트 찾기
    post_to_edit = None
    for post in team.get("posts", []):
        if post.get("_id") == post_object_id:
            post_to_edit = post
            break
        # 기존 posts (post_id가 없는 경우)에 대한 fallback
        elif not post.get("_id") and post.get("title") == request.args.get("title"):
            post_to_edit = post
            break
    
    if not post_to_edit:
        return redirect(url_for("team_page", team_id=team_id))
    
    # 작성자만 수정 가능
    if post_to_edit.get("authorId") != current_user["_id"]:
        return f'<script>alert("본인이 작성한 게시글만 수정할 수 있습니다."); window.location.href="/team_page/{team_id}";</script>'
    
    if request.method == "POST":
        # 수정된 데이터 받기
        new_title = request.form.get("title", "").strip()
        new_content = request.form.get("content", "").strip()
        
        if not new_title or len(new_title) < 2:
            return '<script>alert("제목은 최소 2글자 이상이어야 합니다."); history.back();</script>'
        
        if len(new_title) > 100:
            return '<script>alert("제목은 100글자를 초과할 수 없습니다."); history.back();</script>'
        
        # 수정 전 내용 저장 (이미지 정리용)
        old_content = post_to_edit.get("content", "")
        
        try:
            # 게시글 업데이트 (post_id 기준)
            result = db["teams"].update_one(
                {"_id": team_object_id, "posts._id": post_object_id},
                {
                    "$set": {
                        "posts.$.title": new_title,
                        "posts.$.content": new_content,
                        "posts.$.updatedAt": datetime.datetime.utcnow()
                    }
                }
            )
            
            # post_id가 없는 기존 포스트의 경우 title과 authorId로 업데이트 시도 (fallback)
            if result.modified_count == 0:
                result = db["teams"].update_one(
                    {
                        "_id": team_object_id,
                        "posts.title": request.form.get("original_title") or post_to_edit.get("title"),
                        "posts.authorId": current_user["_id"]
                    },
                    {
                        "$set": {
                            "posts.$.title": new_title,
                            "posts.$.content": new_content,
                            "posts.$.updatedAt": datetime.datetime.utcnow()
                        }
                    }
                )
            
            if result.modified_count > 0:
                # 수정으로 인해 사용되지 않는 이미지들 삭제
                if old_content:
                    deleted_images = delete_unused_images_on_edit(old_content, new_content)
                    if deleted_images:
                        print(f"포스트 수정으로 {len(deleted_images)}개의 이미지를 삭제했습니다.")
                    
                    # 추가로 최근 업로드된 사용되지 않는 이미지들도 정리
                    recent_deleted = cleanup_unused_recent_images()
                    if recent_deleted:
                        print(f"최근 업로드된 미사용 이미지 {len(recent_deleted)}개를 추가로 삭제했습니다.")
                
                return f'<script>alert("게시글이 수정되었습니다."); window.location.href="/team_page/{team_id}";</script>'
            else:
                return '<script>alert("게시글 수정에 실패했습니다."); history.back();</script>'
                
        except Exception as e:
            print(f"게시글 수정 중 오류: {e}")
            return '<script>alert("게시글 수정 중 오류가 발생했습니다."); history.back();</script>'
    
    # GET 요청 - 수정 폼 표시
    # 팀 멤버들 정보 조회
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
    
    team_data = {
        "id": str(team["_id"]),
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "members": team_members
    }
    
    # 포스트 데이터에 post_id 추가
    post_data = {
        "id": str(post_to_edit.get("_id", "")),  # post_id
        "title": post_to_edit.get("title", ""),
        "content": post_to_edit.get("content", ""),
        "author": post_to_edit.get("author", ""),
        "authorId": post_to_edit.get("authorId")
    }
    
    return render_template("team_post_edit.html", 
                         team=team_data, 
                         post=post_data, 
                         current_user=current_user)

@app.route("/delete_post", methods=["POST"])
def delete_post():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    post_id = request.form.get("post_id")
    team_id = request.form.get("team_id")
    
    if not post_id or not team_id:
        return redirect(url_for("main_page"))
    
    # team_id와 post_id 유효성 검사
    try:
        team_object_id = ObjectId(team_id)
        post_object_id = ObjectId(post_id)
    except:
        return redirect(url_for("main_page"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        return f'<script>alert("팀을 찾을 수 없습니다."); window.location.href="/main_page";</script>'
    
    # 삭제할 포스트 찾기 및 권한 확인
    post_to_delete = None
    for post in team.get("posts", []):
        # post_id가 있는 경우와 없는 경우 모두 처리 (하위 호환성)
        if post.get("_id") == post_object_id:
            post_to_delete = post
            break
        # 기존 posts (post_id가 없는 경우)에 대한 fallback - title로 찾기
        elif not post.get("_id") and post.get("title") == request.form.get("post_title"):
            post_to_delete = post
            break
    
    if not post_to_delete:
        return f'<script>alert("삭제할 게시글을 찾을 수 없습니다."); window.location.href="/team_page/{team_id}";</script>'
    
    # 작성자 또는 팀장만 삭제 가능
    is_author = post_to_delete.get("authorId") == current_user["_id"]
    is_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master" 
        for member in team.get("members", [])
    )
    
    if not (is_author or is_master):
        return f'<script>alert("게시글 삭제 권한이 없습니다."); window.location.href="/team_page/{team_id}";</script>'
    
    # 포스트에서 사용된 이미지들 삭제
    try:
        post_content = post_to_delete.get("content", "")
        if post_content:
            deleted_images = delete_post_images(post_content)
            if deleted_images:
                print(f"포스트 ID '{post_id}'에서 {len(deleted_images)}개의 이미지를 삭제했습니다.")
    except Exception as e:
        print(f"포스트 이미지 삭제 중 오류: {e}")
    
    # 게시글 삭제
    try:
        # post_id로 삭제
        result = db["teams"].update_one(
            {"_id": team_object_id},
            {"$pull": {"posts": {"_id": post_object_id}}}
        )
        
        # post_id가 없는 기존 포스트의 경우 title로 삭제 시도 (fallback)
        if result.modified_count == 0 and request.form.get("post_title"):
            result = db["teams"].update_one(
                {"_id": team_object_id},
                {"$pull": {"posts": {
                    "title": request.form.get("post_title"),
                    "authorId": current_user["_id"]
                }}}
            )
        
        if result.modified_count > 0:
            return f'<script>alert("게시글이 삭제되었습니다."); window.location.href="/team_page/{team_id}";</script>'
        else:
            return f'<script>alert("게시글 삭제에 실패했습니다."); window.location.href="/team_page/{team_id}";</script>'
            
    except Exception as e:
        print(f"게시글 삭제 중 오류: {e}")
        return f'<script>alert("게시글 삭제 중 오류가 발생했습니다."); window.location.href="/team_page/{team_id}";</script>'

@app.route("/delete_team", methods=["POST"])
def delete_team():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    team_name = request.form.get("team_name")
    week = request.form.get("week", type=int)
    
    if not team_name or week is None:
        return '<script>alert("팀 정보가 올바르지 않습니다."); history.back();</script>'
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return '<script>alert("해당 팀을 찾을 수 없습니다."); history.back();</script>'
    
    # 현재 사용자가 팀장인지 확인
    is_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master"
        for member in team.get("members", [])
    )
    
    if not is_master:
        return '<script>alert("팀장만 팀을 삭제할 수 있습니다."); history.back();</script>'
    
    # 팀의 모든 이미지 삭제
    deleted_images = delete_team_images(team)
    if deleted_images:
        print(f"팀 '{team_name}'에서 {len(deleted_images)}개의 이미지를 삭제했습니다.")
    
    # 팀 삭제
    result = db["teams"].delete_one({
        "teamName": team_name,
        "week": week
    })
    
    if result.deleted_count > 0:
        return redirect(url_for("main_page"))
    else:
        return '<script>alert("팀 삭제에 실패했습니다."); history.back();</script>'
    
@app.route("/my_page")
def my_page():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재는 메인페이지로 리다이렉트, 추후 my_page.html 구현시 수정
    return redirect(url_for("main_page"))

if __name__ == "__main__":
    app.run(debug=True)