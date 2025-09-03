from flask import Flask, render_template, request, redirect, url_for, make_response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
import jwt
import datetime
import os
import re
import glob

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
            return '<script>alert("이미 존재하는 사용자명입니다!"); history.back();</script>'
        
        existing_nickname = users_collection.find_one({"nickname": nickname})
        if existing_nickname:
            return '<script>alert("이미 존재하는 닉네임입니다!"); history.back();</script>'

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
        return '<script>alert("회원가입이 완료되었습니다!"); window.location.href="' + url_for("login") + '";</script>'

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

        return '<script>alert("사용자명 또는 비밀번호가 잘못되었습니다!"); history.back();</script>'

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

    # URL 파라미터에서 주차 정보 가져오기
    default_week = request.args.get("week", type=int)

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
            return f'<script>alert("{week}주차에 \'{team_name}\' 팀 이름이 이미 존재합니다!"); history.back();</script>'

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

        success_message = f"'{team_name}' 팀이 성공적으로 생성되었습니다!"
        return f'<script>alert("{success_message}"); window.location.href="/teampage?team={team_name}&week={week}";</script>'

    return render_template("team_signup.html", default_week=default_week, current_user=users_collection.find_one({"username": username}))

@app.route("/main_page")
@app.route("/main_page/<int:week>")
def main_page(week=None):
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
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
                         selected_teams=teams_with_members,
                         current_user=current_user)

@app.route("/teams_partial/<int:week>")
def teams_partial(week):
    """특정 주차의 팀 목록 HTML 부분만 반환"""
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
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
                         selected_teams=teams_with_members,
                         current_user=current_user)

@app.route("/team_join", methods=["GET", "POST"])
def team_join():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))

    if request.method == "POST":
        team_password = request.form["team_password"]
        
        # 현재 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return redirect(url_for("login"))
        
        # URL 파라미터에서 특정 팀 정보를 확인
        team_name = request.form.get("team_name") or request.args.get("team")
        week = request.form.get("week") or request.args.get("week")
        if week:
            week = int(week)
        
        target_team = None
        
        if team_name and week is not None:
            # 특정 팀에 가입하는 경우
            target_team = db["teams"].find_one({
                "teamName": team_name,
                "week": week
            })
            
            if not target_team:
                return '<script>alert("해당 팀을 찾을 수 없습니다!"); history.back();</script>'
            
            # 비밀번호 확인
            if not check_password_hash(target_team["roomPasswordHash"], team_password):
                return '<script>alert("비밀번호가 틀렸습니다!"); history.back();</script>'
        else:
            # 비밀번호로 팀 찾기 (기존 로직)
            all_teams = list(db["teams"].find({}))
            
            if not all_teams:
                return '<script>alert("생성된 팀이 없습니다!"); history.back();</script>'
            
            # 비밀번호가 맞는 팀 찾기
            for team in all_teams:
                if check_password_hash(team["roomPasswordHash"], team_password):
                    target_team = team
                    break
            
            if not target_team:
                return '<script>alert("해당 비밀번호를 가진 팀이 없습니다!"); history.back();</script>'
        
        # 이미 해당 팀의 멤버인지 확인
        is_already_member = any(
            member["userId"] == current_user["_id"] 
            for member in target_team["members"]
        )
        
        if is_already_member:
            return f'<script>alert("이미 \\"{target_team["teamName"]}\\" 팀의 멤버입니다!"); history.back();</script>'
        
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
        
        success_message = f'"{target_team["teamName"]}" 팀에 성공적으로 가입되었습니다!'
        return f'<script>alert("{success_message}"); window.location.href="/teampage?team={target_team["teamName"]}&week={target_team["week"]}";</script>'

    # GET 요청 시 팀 정보를 URL 파라미터로 받음
    team_name = request.args.get("team")
    week = request.args.get("week", type=int)
    
    if team_name and week is not None:
        # 특정 팀에 가입하는 경우
        team_data = {
            "teamName": team_name,
            "week": week
        }
        current_user = users_collection.find_one({"username": username})
        return render_template("team_join.html", team=team_data, current_user=current_user)
    else:
        # 일반적인 팀 가입 (비밀번호로 찾기)
        current_user = users_collection.find_one({"username": username})
        return render_template("team_join.html", current_user=current_user)

@app.route("/teampage")
def teampage():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    team_name = request.args.get("team")
    week = request.args.get("week", type=int)
    
    if not team_name or week is None:
        return redirect(url_for("main_page"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return redirect(url_for("main_page"))
    
    # 현재 사용자가 해당 팀의 멤버인지 확인
    current_user = users_collection.find_one({"username": username})
    is_member = any(
        member["userId"] == current_user["_id"] 
        for member in team.get("members", [])
    )
    
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
    
    team_data = {
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "upvote": team.get("upvote", 0),
        "members": team_members,
        "posts": team.get("posts", [])
    }
    
    return render_template("teampage.html", team=team_data, current_user=current_user, is_member=is_member)

@app.route("/teampagewrite", methods=["GET", "POST"])
def teampagewrite():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    team_name = request.args.get("team")
    week = request.args.get("week", type=int)
    
    if request.method == "POST":
        # 폼에서 데이터 가져오기
        author = request.form["author"]
        title = request.form["title"]
        content = request.form["content"]
        
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
            return redirect(url_for("main_page"))
        
        # 현재 사용자가 해당 팀의 멤버인지 확인
        is_member = any(
            member["userId"] == current_user["_id"] 
            for member in team.get("members", [])
        )
        
        if not is_member:
            return redirect(url_for("main_page"))
        
        # 새 포스트 생성
        new_post = {
            "title": title,
            "content": content,
            "author": author,
            "authorId": current_user["_id"],
            "createdAt": datetime.datetime.utcnow(),
            "likes": 0
        }
        
        # 팀에 포스트 추가
        db["teams"].update_one(
            {"_id": team["_id"]},
            {"$push": {"posts": new_post}}
        )
        
        # 글 작성 완료 후 사용되지 않는 최근 업로드 이미지들 정리
        recent_deleted = cleanup_unused_recent_images()
        if recent_deleted:
            print(f"글 작성 완료 후 미사용 이미지 {len(recent_deleted)}개를 정리했습니다.")
        
        success_message = "글이 성공적으로 작성되었습니다!"
        return f'<script>alert("{success_message}"); window.location.href="/teampage?team={team_name}&week={week}";</script>'
    
    # GET 요청 시 글 작성 폼 표시
    if not team_name or week is None:
        return redirect(url_for("main_page"))
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return redirect(url_for("main_page"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    
    # 현재 사용자가 해당 팀의 멤버인지 확인
    is_member = any(
        member["userId"] == current_user["_id"] 
        for member in team.get("members", [])
    )
    
    if not is_member:
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
    
    team_data = {
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "members": team_members
    }
    
    return render_template("teampagewrite.html", team=team_data, current_user=current_user)

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
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    if request.method == "GET":
        title = request.args.get("title")
        team_name = request.args.get("team")
        week = request.args.get("week", type=int)
        
        if not title or not team_name or week is None:
            return redirect(url_for("main_page"))
        
        # 팀 정보 조회
        team = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        
        if not team:
            return redirect(url_for("main_page"))
        
        # 해당 포스트 찾기
        post = None
        for p in team.get("posts", []):
            if p["title"] == title and p["authorId"] == current_user["_id"]:
                post = p
                break
        
        if not post:
            return redirect(url_for("main_page"))
        
        return render_template("edit_post.html", post=post, team=team, current_user=current_user)
    
    # POST 요청 시 포스트 업데이트
    elif request.method == "POST":
        old_title = request.form.get("old_title")
        new_title = request.form.get("title")
        new_content = request.form.get("content")
        team_name = request.form.get("team_name") or request.args.get("team")
        week = request.form.get("week", type=int) or request.args.get("week", type=int)
        
        if not all([old_title, new_title, new_content, team_name, week]):
            return '<script>alert("필수 정보가 누락되었습니다."); history.back();</script>'
        
        # 팀 정보 조회
        team = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        
        if not team:
            return '<script>alert("팀을 찾을 수 없습니다."); history.back();</script>'
        
        # 수정 전 포스트의 기존 콘텐츠 찾기 (이미지 삭제를 위해)
        old_post_content = None
        for post in team.get("posts", []):
            if post.get("title") == old_title and post.get("authorId") == current_user["_id"]:
                old_post_content = post.get("content", "")
                break
        
        # 포스트 업데이트
        result = db["teams"].update_one(
            {
                "teamName": team_name,
                "week": week,
                "posts.title": old_title,
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
        
        # 수정이 성공했고 기존 콘텐츠가 있다면 사용하지 않는 이미지 삭제
        if result.modified_count > 0 and old_post_content:
            deleted_images = delete_unused_images_on_edit(old_post_content, new_content)
            if deleted_images:
                print(f"포스트 수정으로 {len(deleted_images)}개의 이미지를 삭제했습니다.")
            
            # 추가로 최근 업로드된 사용되지 않는 이미지들도 정리
            recent_deleted = cleanup_unused_recent_images()
            if recent_deleted:
                print(f"최근 업로드된 미사용 이미지 {len(recent_deleted)}개를 추가로 삭제했습니다.")
        
        if result.modified_count > 0:
            success_message = "글이 성공적으로 수정되었습니다!"
            return f'<script>alert("{success_message}"); window.location.href="/teampage?team={team_name}&week={week}";</script>'
        else:
            return '<script>alert("글 수정에 실패했습니다."); history.back();</script>'

@app.route("/delete_post", methods=["POST"])
def delete_post():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    post_title = request.form.get("post_title")
    team_name = request.form.get("team_name")
    week = request.form.get("week", type=int)
    
    if not all([post_title, team_name, week]):
        return '<script>alert("필수 정보가 누락되었습니다."); history.back();</script>'
    
    # 삭제할 포스트 찾기 (이미지 삭제를 위해)
    team = db["teams"].find_one({"teamName": team_name, "week": week})
    if team:
        posts = team.get("posts", [])
        post_to_delete = None
        for post in posts:
            if post.get("title") == post_title and post.get("authorId") == current_user["_id"]:
                post_to_delete = post
                break
        
        # 포스트에서 이미지 삭제
        if post_to_delete:
            deleted_images = delete_post_images(post_to_delete.get("content", ""))
            if deleted_images:
                print(f"포스트 '{post_title}'에서 {len(deleted_images)}개의 이미지를 삭제했습니다.")
    
    # 포스트 삭제
    result = db["teams"].update_one(
        {"teamName": team_name, "week": week},
        {
            "$pull": {
                "posts": {
                    "title": post_title,
                    "authorId": current_user["_id"]
                }
            }
        }
    )
    
    if result.modified_count > 0:
        success_message = "글이 성공적으로 삭제되었습니다!"
        return f'<script>alert("{success_message}"); window.location.href="/teampage?team={team_name}&week={week}";</script>'
    else:
        return '<script>alert("글 삭제에 실패했습니다."); history.back();</script>'

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

@app.route("/admin/cleanup_images", methods=["POST"])
def admin_cleanup_images():
    """관리자용 전체 이미지 정리 (개발/테스트용)"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    # 간단한 관리자 확인 (실제 운영시에는 더 강화된 인증 필요)
    if username != "admin":  # 실제 관리자 계정명으로 변경
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403
    
    deleted_files = cleanup_all_unused_images()
    return jsonify({
        "message": f"{len(deleted_files)}개의 미사용 이미지를 정리했습니다.",
        "deleted_count": len(deleted_files)
    })

@app.route("/mypage")
def mypage():
    username = get_current_user(request)
    if not username:
        return redirect(url_for("login"))
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return redirect(url_for("login"))
    
    # 사용자가 속한 팀들 조회
    user_teams = []
    teams = list(db["teams"].find({"members.userId": current_user["_id"]}))
    
    for team in teams:
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
        
        user_teams.append({
            "teamName": team["teamName"],
            "week": team["week"],
            "description": team.get("description", ""),
            "members": team_members,
            "member_count": len(team_members)
        })
    
    # 주차별로 정렬
    user_teams.sort(key=lambda x: x["week"])
    
    return render_template("mypage.html", current_user=current_user, teams=user_teams)

@app.route("/delete_all_teams", methods=["POST"])
def delete_all_teams():
    """모든 팀 삭제 (관리자용)"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    try:
        # 모든 팀 조회 후 이미지 삭제
        teams = list(db["teams"].find({}))
        total_deleted_images = 0
        
        for team in teams:
            deleted_images = delete_team_images(team)
            total_deleted_images += len(deleted_images)
        
        # 모든 팀 삭제
        result = db["teams"].delete_many({})
        
        return jsonify({
            "success": True,
            "message": f"{result.deleted_count}개의 팀이 삭제되었습니다.",
            "deleted_teams": result.deleted_count,
            "deleted_images": total_deleted_images
        })
        
    except Exception as e:
        return jsonify({
            "error": f"팀 삭제 중 오류가 발생했습니다: {str(e)}"
        }), 500

@app.route("/create_test_teams", methods=["POST"])
def create_test_teams():
    """테스트용: 각 주차마다 팀을 자동 생성하는 매크로"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    try:
        # 현재 로그인한 사용자 정보 조회
        current_user = users_collection.find_one({"username": username})
        if not current_user:
            return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
        
        created_teams = []
        team_password_hash = generate_password_hash("4")
        
        # 0주차부터 20주차까지 팀 생성 (현재 로그인한 사용자만 팀장으로)
        for week in range(21):
            team_name = f"테스트팀{week}"
            
            # 이미 존재하는 팀인지 확인
            existing_team = db["teams"].find_one({
                "teamName": team_name,
                "week": week
            })
            
            if existing_team:
                continue  # 이미 존재하면 스킵
            
            # 새 팀 생성 (현재 로그인한 사용자만 팀장으로)
            team_members = [
                {
                    "userId": current_user["_id"],
                    "role": "master",
                    "joinedAt": datetime.datetime.utcnow()
                }
            ]
            
            new_team = {
                "teamName": team_name,
                "description": f"{week}주차 테스트 팀",
                "week": week,
                "roomPasswordHash": team_password_hash,  # 비밀번호: "4"
                "masterId": current_user["_id"],
                "createdAt": datetime.datetime.utcnow(),
                "upvote": 0,
                "members": team_members,
                "posts": []
            }
            
            # 팀 생성
            db["teams"].insert_one(new_team)
            created_teams.append(f"{week}주차 - {team_name}")
        
        return jsonify({
            "success": True,
            "message": f"{len(created_teams)}개의 테스트 팀이 생성되었습니다.",
            "created_teams": created_teams,
            "team_password": "4",
            "leader": current_user["nickname"] or current_user["username"],
            "members": [current_user["nickname"] or current_user["username"]]
        })
        
    except Exception as e:
        return jsonify({
            "error": f"팀 생성 중 오류가 발생했습니다: {str(e)}"
        }), 500

# ...existing code...

if __name__ == "__main__":
    app.run(debug=True, port=5001)