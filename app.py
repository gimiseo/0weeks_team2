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

        # 현재 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return redirect(url_for("login"))

        # 해당 주차에 이미 팀에 소속되어 있는지 확인
        existing_membership = db["teams"].find_one({
            "week": week,
            "members.userId": current_user["_id"]
        })
        
        if existing_membership:
            return f'{week}주차에 이미 "{existing_membership["teamName"]}" 팀에 소속되어 있습니다. 한 주차에는 하나의 팀에만 소속될 수 있습니다.'

        # 1. 같은 주차에 같은 이름의 팀이 있는지 확인
        existing_team_by_name = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        if existing_team_by_name:
            return f"{week}주차에 '{team_name}' 팀 이름이 이미 존재합니다!"

        # 2. 같은 주차에 같은 비밀번호를 가진 팀이 있는지 확인
        teams_in_week = list(db["teams"].find({"week": week}))
        for team in teams_in_week:
            if check_password_hash(team["roomPasswordHash"], team_password):
                return f"{week}주차에 동일한 비밀번호를 사용하는 팀이 이미 존재합니다!"

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
            "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9),
            "upvote": 0,  
            "members": [
                {
                    "userId": current_user["_id"],
                    "role": "master",
                    "joinedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
                }
            ],
            "posts": []  
        }

        # 팀을 데이터베이스에 삽입
        db["teams"].insert_one(new_team)

        return redirect(url_for("main_page"))

    selected_week = request.args.get('week', type=int)

    if selected_week is None:
        # week 파라미터가 없으면 current_week 계산
        start_date = datetime.date(2025, 8, 1)
        current_date = datetime.date.today()
        days_diff = (current_date - start_date).days
        selected_week = days_diff // 7
    
    return render_template("team_signup.html", selected_week=selected_week)

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
        
        # 해당 주차에 이미 팀에 소속되어 있는지 확인
        existing_membership = db["teams"].find_one({
            "week": week,
            "members.userId": current_user["_id"]
        })
        
        if existing_membership:
            return f'{week}주차에 이미 "{existing_membership["teamName"]}" 팀에 소속되어 있습니다. 한 주차에는 하나의 팀에만 소속될 수 있습니다.'
        
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
            "joinedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
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
        
        # 해당 주차에 이미 팀에 소속되어 있는지 확인
        existing_membership = db["teams"].find_one({
            "week": team["week"],
            "members.userId": current_user["_id"]
        })
        
        if existing_membership:
            return render_template("team_join_specific.html", 
                                 team=team, 
                                 error=f'{team["week"]}주차에 이미 "{existing_membership["teamName"]}" 팀에 소속되어 있습니다. 한 주차에는 하나의 팀에만 소속될 수 있습니다.')
        
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
            "joinedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        }
        
        db["teams"].update_one(
            {"_id": team["_id"]},
            {"$push": {"members": new_member}}
        )
        
        # 성공 시 팀 페이지로 리다이렉트
        return redirect(url_for("team_page", team_id=team_id))
    
    return render_template("team_join_specific.html", team=team)

def sort_comments_by_hierarchy(comments):
    """댓글을 부모-자식 관계에 따라 정렬하는 함수"""
    if not comments:
        return []
    
    try:
        # 일반 댓글과 답댓글 분리
        main_comments = []
        replies = []
        
        for comment in comments:
            if comment.get("isReply", False):
                replies.append(comment)
            else:
                main_comments.append(comment)
        
        # 일반 댓글을 생성 시간 순으로 정렬
        main_comments.sort(key=lambda x: x.get("createdAt", datetime.datetime.min))
        
        # 답댓글을 생성 시간 순으로 정렬
        replies.sort(key=lambda x: x.get("createdAt", datetime.datetime.min))
        
        # 결과 리스트
        sorted_comments = []
        
        # 각 일반 댓글 뒤에 해당하는 답댓글들 배치
        for main_comment in main_comments:
            sorted_comments.append(main_comment)
            
            # 해당 일반 댓글의 답댓글들 찾아서 추가
            main_comment_id = main_comment.get("_id")
            if main_comment_id:
                for reply in replies:
                    parent_id = reply.get("parentCommentId")
                    if parent_id and str(parent_id) == str(main_comment_id):
                        sorted_comments.append(reply)
        
        return sorted_comments
        
    except Exception as e:
        print(f"댓글 정렬 중 오류 발생: {e}")
        # 오류가 발생하면 원본 댓글 리스트를 그대로 반환
        return comments

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
    
    # 역할별로 정렬 (팀장 -> 관리자 -> 멤버 순)
    role_order = {"master": 0, "admin": 1, "member": 2}
    team_members.sort(key=lambda x: role_order.get(x["role"], 999))
    
    # 현재 사용자가 팀 멤버인지 확인
    current_user = users_collection.find_one({"username": username})
    is_member = any(member["userId"] == current_user["_id"] for member in team.get("members", []))
    
    # Check if current user is team master
    is_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master"
        for member in team.get("members", [])
    )
    
    # 현재 사용자가 이미 추천했는지 확인
    has_upvoted = current_user["_id"] in team.get("upvotedUsers", [])
    
    # 각 글에 대해 현재 사용자가 좋아요했는지 확인하고 댓글 정렬
    posts_with_ids = []
    
    for post in team.get("posts", []):
        is_post_author = post.get("authorId") == current_user["_id"]
        has_liked = current_user["_id"] in post.get("likedUsers", [])

        # 댓글을 부모-자식 관계에 따라 정렬
        sorted_comments = sort_comments_by_hierarchy(post.get("comments", []))

        post_data = {
            "id": str(post.get("_id", "")),  # Convert ObjectId to string, empty if no _id
            "title": post.get("title", ""),
            "content": post.get("content", ""),
            "author": post.get("author", ""),
            "authorId": post.get("authorId"),
            "createdAt": post.get("createdAt"),
            "updatedAt": post.get("updatedAt"),
            "likes": post.get("likes", 0),
            "has_liked": has_liked,
            "comments": sorted_comments,  # 여기에 댓글 포함

            "can_edit": is_post_author,
            "can_delete": is_post_author or is_master
        }
        posts_with_ids.append(post_data)

    # 팀 데이터 구성
    team_data = {
        "id": str(team["_id"]),
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "upvote": team.get("upvote", 0),
        "has_upvoted": has_upvoted,
        "members": team_members,
        "member_count": len(team_members),
        "posts": posts_with_ids
    }
    
    return render_template("team_page.html",
                           team=team_data,
                           is_member=is_member,
                           is_master=is_master,
                           current_user=current_user_data)

@app.route("/team_upvote", methods=["POST"])
def team_upvote():
    """팀 추천 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    team_id = request.args.get("team_id") or request.form.get("team_id")
    
    if not team_id:
        return jsonify({"error": "팀 정보가 필요합니다."}), 400
    
    # ObjectId로 변환
    try:
        team_object_id = ObjectId(team_id)
    except:
        return jsonify({"error": "잘못된 팀 ID 형식입니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 이미 추천했는지 확인
    upvoted_users = team.get("upvotedUsers", [])
    if current_user["_id"] in upvoted_users:
        return jsonify({"error": "이미 추천하신 팀입니다."}), 400
    
    # 추천수 1 증가 및 추천한 사용자 목록에 추가
    result = db["teams"].update_one(
        {"_id": team_object_id},
        {
            "$inc": {"upvote": 1},
            "$addToSet": {"upvotedUsers": current_user["_id"]}
        }
    )
    
    if result.modified_count > 0:
        # 업데이트된 추천수 조회
        updated_team = db["teams"].find_one({"_id": team_object_id})
        new_upvote_count = updated_team.get("upvote", 0)
        
        return jsonify({
            "success": True,
            "new_upvote_count": new_upvote_count
        })
    else:
        return jsonify({"error": "추천 처리에 실패했습니다."}), 500

@app.route("/post_like", methods=["POST"])
def post_like():
    """포스트 좋아요 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    team_id = request.form.get("team_id")
    post_id = request.form.get("post_id")
    
    if not team_id or not post_id:
        return jsonify({"error": "팀 정보와 포스트 정보가 필요합니다."}), 400
    
    # ObjectId로 변환
    try:
        team_object_id = ObjectId(team_id)
        post_object_id = ObjectId(post_id)
    except:
        return jsonify({"error": "잘못된 ID 형식입니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 해당 포스트 찾기
    post_found = False
    for post in team.get("posts", []):
        if post.get("_id") == post_object_id:
            post_found = True
            # 이미 좋아요했는지 확인
            liked_users = post.get("likedUsers", [])
            if current_user["_id"] in liked_users:
                return jsonify({"error": "이미 좋아요하신 포스트입니다."}), 400
            break
    
    if not post_found:
        return jsonify({"error": "포스트를 찾을 수 없습니다."}), 404
    
    # 좋아요 수 1 증가 및 좋아요한 사용자 목록에 추가
    result = db["teams"].update_one(
        {"_id": team_object_id, "posts._id": post_object_id},
        {
            "$inc": {"posts.$.likes": 1},
            "$addToSet": {"posts.$.likedUsers": current_user["_id"]}
        }
    )
    
    if result.modified_count > 0:
        # 업데이트된 좋아요 수 조회
        updated_team = db["teams"].find_one({"_id": team_object_id})
        new_like_count = 0
        for post in updated_team.get("posts", []):
            if post.get("_id") == post_object_id:
                new_like_count = post.get("likes", 0)
                break
        
        return jsonify({
            "success": True,
            "new_like_count": new_like_count
        })
    else:
        return jsonify({"error": "좋아요 처리에 실패했습니다."}), 500

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
            "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9),
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
                        "posts.$.updatedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
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
                            "posts.$.updatedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
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
    
    team_id = request.form.get("team_id")
    
    if not team_id:
        return '<script>alert("팀 정보가 올바르지 않습니다."); history.back();</script>'
    
    try:
        team_object_id = ObjectId(team_id)
    except:
        return '<script>alert("잘못된 팀 ID입니다."); history.back();</script>'
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({"_id": team_object_id})
    
    if not team:
        return '<script>alert("해당 팀을 찾을 수 없습니다."); history.back();</script>'
    
    # 현재 사용자가 팀장인지 확인
    is_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master"
        for member in team.get("members", [])
    )
    
    if not is_master:
        return '<script>alert("팀장만 팀을 삭제할 수 있습니다."); history.back();</script>'
    
    try:
        # 팀의 모든 이미지 삭제
        deleted_images = delete_team_images(team)
        if deleted_images:
            print(f"팀 '{team['teamName']}'에서 {len(deleted_images)}개의 이미지를 삭제했습니다.")
        
        # 팀 삭제
        result = db["teams"].delete_one({"_id": team_object_id})
        
        if result.deleted_count > 0:
            # 성공 시 메인 페이지로 리다이렉트
            return '<script>alert("팀이 성공적으로 삭제되었습니다."); window.location.href="/main_page";</script>'
        else:
            return '<script>alert("팀 삭제에 실패했습니다."); history.back();</script>'
            
    except Exception as e:
        print(f"팀 삭제 중 오류 발생: {e}")
        return '<script>alert("팀 삭제 중 오류가 발생했습니다."); history.back();</script>'
    
@app.route("/user/<username>")
def user_profile(username):
    current_username = get_current_user(request)
    if not current_username:
        return redirect(url_for("login"))
    
    # 현재 로그인한 사용자 정보
    current_user = users_collection.find_one({"username": current_username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 조회할 사용자 정보
    target_user = users_collection.find_one({"username": username})
    if not target_user:
        return '<script>alert("사용자를 찾을 수 없습니다."); history.back();</script>'
    
    # 해당 사용자가 속한 팀들 조회
    user_teams = []
    teams = list(db["teams"].find({"members.userId": target_user["_id"]}))
    
    for team in teams:
        # 팀 멤버들의 상세 정보 조회
        team_members = []
        for member in team.get("members", []):
            member_info = users_collection.find_one({"_id": member["userId"]})
            if member_info:
                team_members.append({
                    "username": member_info["username"],
                    "nickname": member_info["nickname"],
                    "profile_img": member_info.get("profile_img"),
                    "role": member["role"]
                })
        
        # 역할별로 정렬 (팀장 -> 관리자 -> 멤버 순)
        role_order = {"master": 0, "admin": 1, "member": 2}
        team_members.sort(key=lambda x: role_order.get(x["role"], 999))
        
        user_teams.append({
            "id": str(team["_id"]),
            "teamName": team["teamName"],
            "description": team.get("description", ""),
            "week": team["week"],
            "upvote": team.get("upvote", 0),
            "members": team_members,
            "member_count": len(team_members)
        })
    
    # 주차별로 정렬 (최신 주차부터)
    user_teams.sort(key=lambda x: x["week"])
    
    # 자신의 프로필인지 확인
    is_own_profile = (current_username == username)
    
    return render_template("user_profile.html", 
                         target_user=target_user,
                         user_teams=user_teams,
                         current_user=current_user,
                         is_own_profile=is_own_profile)

@app.route("/mypage")
def mypage():
    """현재 사용자의 프로필 페이지로 리다이렉트"""
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    return redirect(url_for("user_profile", username=username))

# 기존 my_page 라우트 수정
@app.route("/my_page")
def my_page():
    """하위 호환성을 위해 mypage로 리다이렉트"""
    return redirect(url_for("mypage"))

@app.route("/update_profile_image", methods=["POST"])
def update_profile_image():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    if 'profile_image' not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400
    
    file = request.files['profile_image']
    if file.filename == '':
        return jsonify({"error": "파일이 선택되지 않았습니다."}), 400
    
    if file and allowed_file(file.filename):
        # 안전한 파일명 생성 및 확장자 처리 개선
        original_filename = secure_filename(file.filename)
        
        # 확장자 추출 (소문자로 변환)
        if '.' in original_filename:
            ext = '.' + original_filename.rsplit('.', 1)[1].lower()
        else:
            # 확장자가 없는 경우 MIME 타입으로부터 추정
            mime_type = file.content_type
            if mime_type == 'image/jpeg':
                ext = '.jpg'
            elif mime_type == 'image/png':
                ext = '.png'
            elif mime_type == 'image/gif':
                ext = '.gif'
            elif mime_type == 'image/webp':
                ext = '.webp'
            else:
                ext = '.jpg'  # 기본값
        
        # 새 파일명 생성
        new_filename = f"{username}_profile{ext}"
        
        # 기존 프로필 이미지 삭제 (모든 가능한 확장자 확인)
        current_user = users_collection.find_one({"username": username})
        if current_user and current_user.get("profile_img"):
            old_file_path = os.path.join(app.config["PROFILE_FOLDER"], current_user["profile_img"])
            if os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                    print(f"기존 프로필 이미지 삭제: {old_file_path}")
                except Exception as e:
                    print(f"기존 파일 삭제 실패: {e}")
        
        # 추가로 같은 사용자명의 다른 확장자 파일들도 정리
        possible_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        for possible_ext in possible_extensions:
            possible_file = f"{username}_profile{possible_ext}"
            possible_path = os.path.join(app.config["PROFILE_FOLDER"], possible_file)
            if os.path.exists(possible_path) and possible_file != new_filename:
                try:
                    os.remove(possible_path)
                    print(f"중복 프로필 이미지 정리: {possible_path}")
                except Exception as e:
                    print(f"중복 파일 정리 실패: {e}")
        
        # 새 파일 저장
        try:
            filepath = os.path.join(app.config["PROFILE_FOLDER"], new_filename)
            file.save(filepath)
            print(f"새 프로필 이미지 저장: {filepath}")
        except Exception as e:
            print(f"파일 저장 실패: {e}")
            return jsonify({"error": "파일 저장에 실패했습니다."}), 500
        
        # 데이터베이스 업데이트
        try:
            result = users_collection.update_one(
                {"username": username},
                {"$set": {"profile_img": new_filename}}
            )
            
            if result.matched_count > 0:
                print(f"데이터베이스 업데이트 성공: {username} -> {new_filename}")
                return jsonify({
                    "success": True,
                    "new_profile_img": new_filename
                })
            else:
                return jsonify({"error": "데이터베이스 업데이트에 실패했습니다."}), 500
                
        except Exception as e:
            print(f"데이터베이스 업데이트 실패: {e}")
            return jsonify({"error": "데이터베이스 업데이트 중 오류가 발생했습니다."}), 500
    
    return jsonify({"error": "허용되지 않는 파일 형식입니다."}), 400

@app.route("/add_comment", methods=["POST"])
def add_comment():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    post_title = data.get("post_title")
    team_id = data.get("team_id")
    comment_content = data.get("comment_content")
    
    if not all([post_title, team_id, comment_content]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    # 팀 정보 조회 (team_id 기반)
    try:
        team = db["teams"].find_one({"_id": ObjectId(team_id)})
    except:
        return jsonify({"error": "잘못된 team_id 형식입니다."}), 400
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 게시글 작성자 찾기 (알림을 위해)
    post_author = None
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            post_author = users_collection.find_one({"_id": post.get("authorId")})
            break
    
    # 새 댓글 생성
    new_comment = {
        "_id": ObjectId(),
        "content": comment_content,
        "author": current_user["nickname"],
        "authorId": current_user["_id"],
        "isReply": False,
        "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    }
    
    # 포스트에 댓글 추가
    result = db["teams"].update_one(
        {"_id": ObjectId(team_id), "posts.title": post_title},
        {"$push": {"posts.$.comments": new_comment}}
    )
    
    # 댓글 추가 성공시 알림 생성 (자신의 글이 아닌 경우만)
    if result.modified_count > 0 and post_author and post_author["_id"] != current_user["_id"]:
        notification = {
            "userId": post_author["_id"],
            "type": "comment",
            "title": f"{current_user['nickname']}님이 댓글을 달았습니다",
            "message": f'"{post_title}" 글에 새 댓글이 있습니다: "{comment_content[:50]}{"..." if len(comment_content) > 50 else ""}"',
            "postTitle": post_title,
            "teamId": ObjectId(team_id),
            "teamName": team["teamName"],
            "commentAuthor": current_user["nickname"],
            "commentAuthorId": current_user["_id"],
            "commentContent": comment_content,
            "isRead": False,
            "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        }
        db["notifications"].insert_one(notification)
    
    if result.modified_count > 0:
        return jsonify({
            "success": True,
            "comment": {
                "_id": str(new_comment["_id"]),
                "content": new_comment["content"],
                "author": new_comment["author"],
                "authorId": str(new_comment["authorId"]),
                "isReply": False,
                "createdAt": new_comment["createdAt"].strftime("%Y-%m-%d %H:%M")
            }
        })
    else:
        return jsonify({"error": "댓글 추가에 실패했습니다."}), 500

@app.route("/edit_comment", methods=["POST"])
def edit_comment():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_id = data.get("team_id")
    post_title = data.get("post_title")
    comment_id = data.get("comment_id")
    new_content = data.get("new_content")
    
    if not all([team_id, post_title, comment_id, new_content]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    team = db["teams"].find_one({"_id": ObjectId(team_id)})
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 댓글 찾기
    post_index, comment_index = None, None
    for p_idx, post in enumerate(team.get("posts", [])):
        if post.get("title") == post_title:
            for c_idx, comment in enumerate(post.get("comments", [])):
                if str(comment.get("_id")) == comment_id and comment.get("authorId") == current_user["_id"]:
                    post_index, comment_index = p_idx, c_idx
                    break
            break
    
    if post_index is None or comment_index is None:
        return jsonify({"error": "댓글을 찾을 수 없거나 수정 권한이 없습니다."}), 404
    
    result = db["teams"].update_one(
        {"_id": ObjectId(team_id), "posts.title": post_title},
        {"$set": {
            f"posts.{post_index}.comments.{comment_index}.content": new_content,
            f"posts.{post_index}.comments.{comment_index}.updatedAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        }}
    )
    
    if result.modified_count > 0:
        return jsonify({"success": True})
    else:
        return jsonify({"error": "댓글 수정에 실패했습니다."}), 500


@app.route("/delete_comment", methods=["POST"])
def delete_comment():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_id = data.get("team_id")
    post_title = data.get("post_title")
    comment_id = data.get("comment_id")
    
    if not all([team_id, post_title, comment_id]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    team = db["teams"].find_one({"_id": ObjectId(team_id)})
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 현재 사용자가 팀 마스터인지 확인
    is_master = any(
        member["userId"] == current_user["_id"] and member["role"] == "master"
        for member in team.get("members", [])
    )
    
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            comments = post.get("comments", [])
            
            comment_to_delete = None
            for comment in comments:
                if str(comment.get("_id")) == comment_id:
                    # 권한 확인: 본인이 작성한 댓글이거나 팀 마스터인 경우
                    if comment.get("authorId") == current_user["_id"] or is_master:
                        comment_to_delete = comment
                        break
            
            if not comment_to_delete:
                return jsonify({"error": "댓글을 찾을 수 없거나 삭제 권한이 없습니다."}), 404
            
            # 댓글과 해당 댓글의 모든 대댓글 삭제
            new_comments = []
            for comment in comments:
                # 삭제할 댓글 자체 제외
                if str(comment.get("_id")) == comment_id:
                    continue
                # 삭제할 댓글의 대댓글들도 제외
                if comment.get("isReply", False) and str(comment.get("parentCommentId")) == comment_id:
                    continue
                new_comments.append(comment)
            
            result = db["teams"].update_one(
                {"_id": ObjectId(team_id), "posts.title": post_title},
                {"$set": {"posts.$.comments": new_comments}}
            )
            
            if result.modified_count > 0:
                return jsonify({"success": True, "message": "댓글이 삭제되었습니다."})
            else:
                return jsonify({"error": "댓글 삭제에 실패했습니다."}), 500
    
    return jsonify({"error": "해당 글을 찾을 수 없습니다."}), 404

@app.route("/add_reply", methods=["POST"])
def add_reply():
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401

    data = request.get_json()
    team_id = data.get("team_id")
    post_title = data.get("post_title")
    parent_comment_id = data.get("parent_comment_id")
    reply_content = data.get("reply_content")

    if not all([team_id, post_title, parent_comment_id, reply_content]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400

    team = db["teams"].find_one({"_id": ObjectId(team_id)})
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404

    # 부모 댓글 작성자 찾기 (알림을 위해)
    parent_comment_author = None
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            for comment in post.get("comments", []):
                if str(comment.get("_id")) == parent_comment_id:
                    parent_comment_author = users_collection.find_one({"_id": comment.get("authorId")})
                    break
            break

    new_reply = {
        "_id": ObjectId(),
        "content": reply_content,
        "author": current_user["nickname"],
        "authorId": current_user["_id"],
        "isReply": True,
        "parentCommentId": ObjectId(parent_comment_id),
        "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    }

    result = db["teams"].update_one(
        {"_id": ObjectId(team_id), "posts.title": post_title},
        {"$push": {"posts.$.comments": new_reply}}
    )

    # 답댓글 추가 성공시 알림 생성 (자신의 댓글이 아닌 경우만)
    if result.modified_count > 0 and parent_comment_author and parent_comment_author["_id"] != current_user["_id"]:
        notification = {
            "userId": parent_comment_author["_id"],
            "type": "reply",
            "title": f"{current_user['nickname']}님이 답댓글을 달았습니다",
            "message": f'"{post_title}" 글의 댓글에 답댓글이 있습니다: "{reply_content[:50]}{"..." if len(reply_content) > 50 else ""}"',
            "postTitle": post_title,
            "teamId": ObjectId(team_id),
            "teamName": team["teamName"],
            "replyAuthor": current_user["nickname"],
            "replyAuthorId": current_user["_id"],
            "replyContent": reply_content,
            "parentCommentId": parent_comment_id,
            "isRead": False,
            "createdAt": datetime.datetime.utcnow() + datetime.timedelta(hours=9)
        }
        db["notifications"].insert_one(notification)

    if result.modified_count > 0:
        return jsonify({
            "success": True,
            "reply": {
                "_id": str(new_reply["_id"]),
                "content": new_reply["content"],
                "author": new_reply["author"],
                "authorId": str(new_reply["authorId"]),
                "createdAt": new_reply["createdAt"].strftime("%Y-%m-%d %H:%M")
            }
        })
    else:
        return jsonify({"error": "답댓글 추가에 실패했습니다."}), 500

@app.route("/api/notifications")
def api_notifications():
    """알림 목록과 읽지 않은 개수를 함께 반환 (HTML과 일치)"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    # 알림 목록 조회
    notifications = list(db["notifications"].find(
        {"userId": current_user["_id"]}
    ).sort([("isRead", 1), ("createdAt", -1)]).limit(20))
    
    # 읽지 않은 알림 개수
    unread_count = db["notifications"].count_documents({
        "userId": current_user["_id"],
        "isRead": False
    })
    
    # 직렬화
    serialized_notifications = []
    for notification in notifications:
        serialized_notifications.append({
            "_id": str(notification["_id"]),
            "userId": str(notification["userId"]),
            "type": notification.get("type", ""),
            "title": notification.get("title", ""),
            "message": notification.get("message", ""),
            "postTitle": notification.get("postTitle", ""),
            "teamId": str(notification.get("teamId", "")),
            "teamName": notification.get("teamName", ""),
            "isRead": notification.get("isRead", False),
            "createdAt": notification["createdAt"].strftime("%Y-%m-%d %H:%M:%S") if notification.get("createdAt") else ""
        })
    
    return jsonify({
        "notifications": serialized_notifications,
        "unread_count": unread_count
    })

@app.route("/api/notifications/mark_read", methods=["POST"])
def api_mark_notifications_read():
    """알림 읽음 처리 (HTML과 일치)"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    notification_ids = data.get("notification_ids", [])
    
    if notification_ids:
        # 특정 알림들 읽음 처리
        object_ids = [ObjectId(nid) for nid in notification_ids]
        result = db["notifications"].update_many(
            {"_id": {"$in": object_ids}, "userId": current_user["_id"]},
            {"$set": {"isRead": True}}
        )
    else:
        # 모든 알림 읽음 처리
        result = db["notifications"].update_many(
            {"userId": current_user["_id"], "isRead": False},
            {"$set": {"isRead": True}}
        )
    
    return jsonify({"success": True, "marked_count": result.modified_count})

@app.route("/api/notifications/delete", methods=["POST"])
def api_delete_notifications():
    """알림 삭제 (HTML과 일치)"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    notification_ids = data.get("notification_ids", [])
    
    if notification_ids:
        # 특정 알림들 삭제
        object_ids = [ObjectId(nid) for nid in notification_ids]
        result = db["notifications"].delete_many(
            {"_id": {"$in": object_ids}, "userId": current_user["_id"]}
        )
    else:
        # 모든 알림 삭제
        result = db["notifications"].delete_many(
            {"userId": current_user["_id"]}
        )
    
    return jsonify({"success": True, "deleted_count": result.deleted_count})
@app.route("/mark_notification_read", methods=["POST"])
def mark_notification_read():
    """알림을 읽음으로 표시"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    notification_id = data.get("notification_id")
    
    if not notification_id:
        return jsonify({"error": "알림 ID가 필요합니다."}), 400
    
    try:
        result = db["notifications"].update_one(
            {"_id": ObjectId(notification_id), "userId": current_user["_id"]},
            {"$set": {"isRead": True}}
        )
        
        if result.modified_count > 0:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "알림을 찾을 수 없습니다."}), 404
    except Exception as e:
        return jsonify({"error": f"잘못된 알림 ID입니다: {str(e)}"}), 400

@app.route("/get_unread_count")
def get_unread_count():
    """읽지 않은 알림 개수 조회"""
    username = get_current_user(request)
    if not username:
        return jsonify({"count": 0})
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"count": 0})
    
    count = db["notifications"].count_documents({
        "userId": current_user["_id"],
        "isRead": False
    })
    
    return jsonify({"count": count})

@app.route("/mark_all_notifications_read", methods=["POST"])
def mark_all_notifications_read():
    """모든 알림을 읽음으로 표시"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    result = db["notifications"].update_many(
        {"userId": current_user["_id"], "isRead": False},
        {"$set": {"isRead": True}}
    )
    
    return jsonify({
        "success": True,
        "marked_count": result.modified_count
    })

@app.route("/delete_notification", methods=["POST"])
def delete_notification():
    """특정 알림 삭제"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    notification_id = data.get("notification_id")
    
    if not notification_id:
        return jsonify({"error": "알림 ID가 필요합니다."}), 400
    
    try:
        result = db["notifications"].delete_one(
            {"_id": ObjectId(notification_id), "userId": current_user["_id"]}
        )
        
        if result.deleted_count > 0:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "알림을 찾을 수 없습니다."}), 404
    except Exception as e:
        return jsonify({"error": f"잘못된 알림 ID입니다: {str(e)}"}), 400

if __name__ == "__main__":
    app.run('0.0.0.0', port=5001, debug=True)