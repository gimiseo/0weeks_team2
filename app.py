from flask import Flask, render_template, request, redirect, url_for, make_response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson import ObjectId
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
            "upvotedUsers": [],  # 추천한 사용자 목록 초기화
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
    
    # 선택된 주차의 팀들을 가져오기 (upvote 기준 내림차순 정렬 - 높은 추천수부터)
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
    
    teams = list(db["teams"].find({"week": week}).sort("upvote", -1))  # 높은 추천수부터
    
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
        
        # 팀 가입 성공 후 팀페이지로 리다이렉트
        return redirect(url_for("teampage", team=target_team["teamName"], week=target_team["week"]))

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
    
    # 현재 사용자가 이미 추천했는지 확인
    has_upvoted = current_user["_id"] in team.get("upvotedUsers", [])
    
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
    
    # 각 글에 대해 현재 사용자가 좋아요했는지 확인하고 댓글 정렬
    posts_with_like_status = []
    for post in team.get("posts", []):
        post_copy = post.copy()
        post_copy["has_liked"] = current_user["_id"] in post.get("likedUsers", [])
        
        # 댓글을 부모-자식 관계에 따라 정렬
        sorted_comments = sort_comments_by_hierarchy(post.get("comments", []))
        post_copy["comments"] = sorted_comments
        
        posts_with_like_status.append(post_copy)
    
    team_data = {
        "teamName": team["teamName"],
        "description": team.get("description", ""),
        "week": team["week"],
        "upvote": team.get("upvote", 0),
        "has_upvoted": has_upvoted,
        "members": team_members,
        "posts": posts_with_like_status
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
            "likes": 0,
            "likedUsers": [],  # 좋아요한 사용자 목록 초기화
            "comments": []  # 댓글 배열 추가
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

@app.route("/team_upvote", methods=["POST"])
def team_upvote():
    """팀 추천 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_name = data.get("team_name")
    week = data.get("week")
    
    if not team_name or week is None:
        return jsonify({"error": "팀 정보가 필요합니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 이미 추천했는지 확인
    upvoted_users = team.get("upvotedUsers", [])
    if current_user["_id"] in upvoted_users:
        return jsonify({"error": "이미 추천하신 팀입니다."}), 400
    
    # 추천수 1 증가 및 추천한 사용자 목록에 추가
    result = db["teams"].update_one(
        {"teamName": team_name, "week": week},
        {
            "$inc": {"upvote": 1},
            "$addToSet": {"upvotedUsers": current_user["_id"]}
        }
    )
    
    if result.modified_count > 0:
        # 업데이트된 추천수 조회
        updated_team = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        new_upvote_count = updated_team.get("upvote", 0)
        
        return jsonify({
            "success": True,
            "new_upvote_count": new_upvote_count
        })
    else:
        return jsonify({"error": "추천 처리에 실패했습니다."}), 500

@app.route("/post_like", methods=["POST"])
def post_like():
    """글 좋아요 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_name = data.get("team_name")
    week = data.get("week")
    post_title = data.get("post_title")
    
    if not all([team_name, week, post_title]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 해당 글 찾기 및 이미 좋아요했는지 확인
    post_found = False
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            post_found = True
            liked_users = post.get("likedUsers", [])
            if current_user["_id"] in liked_users:
                return jsonify({"error": "이미 좋아요하신 글입니다."}), 400
            break
    
    if not post_found:
        return jsonify({"error": "해당 글을 찾을 수 없습니다."}), 404
    
    # 해당 글의 좋아요 수 1 증가 및 좋아요한 사용자 목록에 추가
    result = db["teams"].update_one(
        {
            "teamName": team_name,
            "week": week,
            "posts.title": post_title
        },
        {
            "$inc": {"posts.$.likes": 1},
            "$addToSet": {"posts.$.likedUsers": current_user["_id"]}
        }
    )
    
    if result.modified_count > 0:
        # 업데이트된 좋아요 수 조회
        updated_team = db["teams"].find_one({
            "teamName": team_name,
            "week": week
        })
        
        new_like_count = 0
        for post in updated_team.get("posts", []):
            if post.get("title") == post_title:
                new_like_count = post.get("likes", 0)
                break
        
        return jsonify({
            "success": True,
            "new_like_count": new_like_count
        })
    else:
        return jsonify({"error": "좋아요 처리에 실패했습니다."}), 500

@app.route("/add_comment", methods=["POST"])
def add_comment():
    print("=== ADD_COMMENT 요청 시작 ===")
    username = get_current_user(request)
    print(f"현재 사용자: {username}")
    if not username:
        print("로그인되지 않은 사용자")
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    print(f"사용자 정보: {current_user['nickname'] if current_user else 'None'}")
    if not current_user:
        print("사용자 정보를 찾을 수 없음")
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    # 요청 데이터 가져오기
    data = request.get_json()
    print(f"요청 데이터: {data}")
    post_title = data.get("post_title")
    team_name = data.get("team_name")
    week = data.get("week")
    comment_content = data.get("comment_content")
    
    if not all([post_title, team_name, week, comment_content]):
        print(f"필수 정보 누락 - post_title: {post_title}, team_name: {team_name}, week: {week}, comment_content: {comment_content}")
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    print(f"팀 정보 조회 결과: {team['teamName'] if team else 'None'}")
    
    if not team:
        print("팀을 찾을 수 없음")
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 게시글 작성자 찾기 (알림을 위해)
    post_author = None
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            post_author = users_collection.find_one({"_id": post.get("authorId")})
            break
    
    print(f"게시글 작성자: {post_author['nickname'] if post_author else 'None'}")
    
    # 새 댓글 생성
    new_comment = {
        "_id": ObjectId(),
        "content": comment_content,
        "author": current_user["nickname"],
        "authorId": current_user["_id"],
        "isReply": False,
        "createdAt": datetime.datetime.utcnow()
    }
    print(f"새 댓글: {new_comment}")
    
    # 포스트에 댓글 추가
    print(f"댓글 추가 시도 - 팀: {team_name}, 주차: {week}, 글 제목: {post_title}")
    result = db["teams"].update_one(
        {
            "teamName": team_name,
            "week": week,
            "posts.title": post_title
        },
        {
            "$push": {"posts.$.comments": new_comment}
        }
    )
    print(f"댓글 추가 결과 - 수정된 문서 수: {result.modified_count}")
    
    # 댓글 추가 성공시 알림 생성 (자신의 글이 아닌 경우만)
    if result.modified_count > 0 and post_author and post_author["_id"] != current_user["_id"]:
        print("알림 생성 중...")
        notification = {
            "userId": post_author["_id"],
            "type": "comment",
            "title": f"{current_user['nickname']}님이 댓글을 달았습니다",
            "message": f'"{post_title}" 글에 새 댓글이 있습니다: "{comment_content[:50]}{"..." if len(comment_content) > 50 else ""}"',
            "postTitle": post_title,
            "teamName": team_name,
            "week": week,
            "commentAuthor": current_user["nickname"],
            "commentAuthorId": current_user["_id"],
            "commentContent": comment_content,
            "isRead": False,
            "createdAt": datetime.datetime.utcnow()
        }
        db["notifications"].insert_one(notification)
        print("알림 생성 완료")
    
    if result.modified_count > 0:
        print("댓글 추가 성공")
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
        print("댓글 추가 실패")
        return jsonify({"error": "댓글 추가에 실패했습니다."}), 500

@app.route("/edit_comment", methods=["POST"])
def edit_comment():
    """댓글 수정 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_name = data.get("team_name")
    week = data.get("week")
    post_title = data.get("post_title")
    comment_id = data.get("comment_id")
    new_content = data.get("new_content")
    
    if not all([team_name, week, post_title, comment_id, new_content]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 해당 글과 댓글 찾기
    post_index = None
    comment_index = None
    
    for p_idx, post in enumerate(team.get("posts", [])):
        if post.get("title") == post_title:
            post_index = p_idx
            for c_idx, comment in enumerate(post.get("comments", [])):
                if str(comment.get("_id", "")) == comment_id and comment.get("authorId") == current_user["_id"]:
                    comment_index = c_idx
                    break
            break
    
    if post_index is None or comment_index is None:
        return jsonify({"error": "댓글을 찾을 수 없거나 수정 권한이 없습니다."}), 404
    
    # 댓글 수정
    result = db["teams"].update_one(
        {
            "teamName": team_name,
            "week": week,
            "posts.title": post_title
        },
        {
            "$set": {
                f"posts.{post_index}.comments.{comment_index}.content": new_content,
                f"posts.{post_index}.comments.{comment_index}.updatedAt": datetime.datetime.utcnow()
            }
        }
    )
    
    if result.modified_count > 0:
        return jsonify({"success": True})
    else:
        return jsonify({"error": "댓글 수정에 실패했습니다."}), 500

@app.route("/delete_comment", methods=["POST"])
def delete_comment():
    """댓글 삭제 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_name = data.get("team_name")
    week = data.get("week")
    post_title = data.get("post_title")
    comment_id = data.get("comment_id")
    
    if not all([team_name, week, post_title, comment_id]):
        return jsonify({"error": "필수 정보가 누락되었습니다."}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 해당 글과 댓글 찾기
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            comments = post.get("comments", [])
            
            # 삭제할 댓글이 본인 댓글인지 확인
            comment_to_delete = None
            for comment in comments:
                if str(comment.get("_id", "")) == comment_id and comment.get("authorId") == current_user["_id"]:
                    comment_to_delete = comment
                    break
            
            if not comment_to_delete:
                return jsonify({"error": "댓글을 찾을 수 없거나 삭제 권한이 없습니다."}), 404
            
            # 댓글과 답댓글 필터링
            # 1. 삭제할 댓글 자체 제거
            # 2. 삭제할 댓글에 달린 답댓글들도 모두 제거
            new_comments = []
            for comment in comments:
                comment_id_str = str(comment.get("_id", ""))
                # 삭제할 댓글이 아니고
                if comment_id_str != comment_id:
                    # 답댓글이 아니거나, 답댓글이지만 삭제할 댓글의 자식이 아닌 경우만 유지
                    if not comment.get("isReply", False):
                        # 일반 댓글은 유지
                        new_comments.append(comment)
                    else:
                        # 답댓글인 경우, 부모가 삭제할 댓글이 아닌 경우만 유지
                        parent_id = str(comment.get("parentCommentId", ""))
                        if parent_id != comment_id:
                            new_comments.append(comment)
            
            if len(new_comments) < len(comments):
                # 댓글이 삭제된 경우
                deleted_count = len(comments) - len(new_comments)
                result = db["teams"].update_one(
                    {
                        "teamName": team_name,
                        "week": week,
                        "posts.title": post_title
                    },
                    {
                        "$set": {"posts.$.comments": new_comments}
                    }
                )
                
                if result.modified_count > 0:
                    message = "댓글이 삭제되었습니다."
                    if deleted_count > 1:
                        message += f" (답댓글 {deleted_count - 1}개 포함)"
                    return jsonify({"success": True, "message": message, "deleted_count": deleted_count})
                else:
                    return jsonify({"error": "댓글 삭제에 실패했습니다."}), 500
            else:
                return jsonify({"error": "댓글을 찾을 수 없거나 삭제 권한이 없습니다."}), 404
    
    return jsonify({"error": "해당 글을 찾을 수 없습니다."}), 404

@app.route("/add_reply", methods=["POST"])
def add_reply():
    """답댓글 추가 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    data = request.get_json()
    team_name = data.get("team_name")
    week = data.get("week")
    post_title = data.get("post_title")
    parent_comment_id = data.get("parent_comment_id")
    reply_content = data.get("reply_content")
    
    # 디버깅용 로그 추가
    print(f"=== ADD_REPLY 요청 데이터 ===")
    print(f"team_name: {team_name}")
    print(f"week: {week}")
    print(f"post_title: {post_title}")
    print(f"parent_comment_id: {parent_comment_id}")
    print(f"reply_content: {reply_content}")
    
    # week는 0일 수 있으므로 별도 검증
    if not team_name or week is None or not post_title or not parent_comment_id or not reply_content:
        missing_fields = []
        if not team_name: missing_fields.append("team_name")
        if week is None: missing_fields.append("week")
        if not post_title: missing_fields.append("post_title")
        if not parent_comment_id: missing_fields.append("parent_comment_id")
        if not reply_content: missing_fields.append("reply_content")
        
        print(f"누락된 필드들: {missing_fields}")
        return jsonify({"error": f"필수 정보가 누락되었습니다: {', '.join(missing_fields)}"}), 400
    
    # 팀 정보 조회
    team = db["teams"].find_one({
        "teamName": team_name,
        "week": week
    })
    
    if not team:
        return jsonify({"error": "팀을 찾을 수 없습니다."}), 404
    
    # 부모 댓글 작성자 찾기 (알림을 위해)
    parent_comment_author = None
    for post in team.get("posts", []):
        if post.get("title") == post_title:
            for comment in post.get("comments", []):
                if str(comment.get("_id", "")) == parent_comment_id:
                    parent_comment_author = users_collection.find_one({"_id": comment.get("authorId")})
                    break
            break
    
    # 새 답댓글 생성
    new_reply = {
        "_id": ObjectId(),
        "content": reply_content,
        "author": current_user["nickname"],
        "authorId": current_user["_id"],
        "parentCommentId": ObjectId(parent_comment_id),
        "isReply": True,
        "createdAt": datetime.datetime.utcnow()
    }
    
    # 답댓글을 댓글 배열에 추가
    result = db["teams"].update_one(
        {
            "teamName": team_name,
            "week": week,
            "posts.title": post_title
        },
        {
            "$push": {"posts.$.comments": new_reply}
        }
    )
    
    # 답댓글 추가 성공시 알림 생성 (자신의 댓글이 아닌 경우만)
    if result.modified_count > 0 and parent_comment_author and parent_comment_author["_id"] != current_user["_id"]:
        notification = {
            "userId": parent_comment_author["_id"],
            "type": "reply",
            "title": f"{current_user['nickname']}님이 답댓글을 달았습니다",
            "message": f'"{post_title}" 글의 댓글에 답댓글이 있습니다: "{reply_content[:50]}{"..." if len(reply_content) > 50 else ""}"',
            "postTitle": post_title,
            "teamName": team_name,
            "week": week,
            "replyAuthor": current_user["nickname"],
            "replyAuthorId": current_user["_id"],
            "replyContent": reply_content,
            "parentCommentId": parent_comment_id,
            "isRead": False,
            "createdAt": datetime.datetime.utcnow()
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
                "parentCommentId": str(new_reply["parentCommentId"]),
                "isReply": True,
                "createdAt": new_reply["createdAt"].strftime("%Y-%m-%d %H:%M")
            }
        })
    else:
        return jsonify({"error": "답댓글 추가에 실패했습니다."}), 500

@app.route("/get_notifications")
def get_notifications():
    """사용자의 알림 목록 조회"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    # 최근 알림 20개 조회 (읽지 않은 것 우선)
    notifications = list(db["notifications"].find(
        {"userId": current_user["_id"]}
    ).sort([("isRead", 1), ("createdAt", -1)]).limit(20))
    
    # 모든 MongoDB 객체들을 JSON 직렬화 가능한 형태로 변환
    serialized_notifications = []
    for notification in notifications:
        serialized_notification = {
            "_id": str(notification["_id"]),
            "userId": str(notification["userId"]),
            "type": notification.get("type", ""),
            "title": notification.get("title", ""),
            "message": notification.get("message", ""),
            "postTitle": notification.get("postTitle", ""),
            "teamName": notification.get("teamName", ""),
            "week": notification.get("week", 0),
            "commentAuthor": notification.get("commentAuthor", ""),
            "commentAuthorId": str(notification.get("commentAuthorId", "")),
            "commentContent": notification.get("commentContent", ""),
            "isRead": notification.get("isRead", False),
            "createdAt": notification["createdAt"].strftime("%Y-%m-%d %H:%M") if isinstance(notification.get("createdAt"), datetime.datetime) else str(notification.get("createdAt", ""))
        }
        serialized_notifications.append(serialized_notification)
    
    return jsonify({"notifications": serialized_notifications})

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

@app.route("/test_notification", methods=["POST"])
def test_notification():
    """테스트용 알림 생성"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    # 테스트 알림 생성
    test_notification = {
        "userId": current_user["_id"],
        "type": "comment",
        "title": "테스트 알림",
        "message": "이것은 테스트 알림입니다",
        "postTitle": "테스트 글",
        "teamName": "테스트팀",
        "week": 0,
        "commentAuthor": "테스터",
        "commentAuthorId": current_user["_id"],
        "commentContent": "테스트 댓글 내용입니다.",
        "isRead": False,
        "createdAt": datetime.datetime.utcnow()
    }
    
    db["notifications"].insert_one(test_notification)
    
    return jsonify({"success": True, "message": "테스트 알림이 생성되었습니다."})

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

@app.route("/update_profile_image", methods=["POST"])
def update_profile_image():
    """프로필 이미지 업데이트 기능"""
    username = get_current_user(request)
    if not username:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    
    # 현재 사용자 정보 조회
    current_user = users_collection.find_one({"username": username})
    if not current_user:
        return jsonify({"error": "사용자 정보를 찾을 수 없습니다."}), 401
    
    # 파일 업로드 확인
    if 'profile_image' not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400
    
    file = request.files['profile_image']
    if file.filename == '':
        return jsonify({"error": "파일이 선택되지 않았습니다."}), 400
    
    if file and allowed_file(file.filename):
        try:
            # 기존 프로필 이미지 삭제 (파일 시스템에서)
            old_profile_img = current_user.get("profile_img")
            if old_profile_img:
                old_image_path = os.path.join(app.config["PROFILE_FOLDER"], old_profile_img)
                if os.path.exists(old_image_path):
                    os.remove(old_image_path)
                    print(f"기존 프로필 이미지 삭제: {old_image_path}")
            
            # 새 프로필 이미지 저장
            ext = os.path.splitext(file.filename)[1]
            new_filename = f"{username}_profile{ext}"
            save_path = os.path.join(app.config["PROFILE_FOLDER"], new_filename)
            file.save(save_path)
            
            # DB에서 프로필 이미지 정보 업데이트
            result = users_collection.update_one(
                {"username": username},
                {"$set": {"profile_img": new_filename}}
            )
            
            if result.modified_count > 0:
                return jsonify({
                    "success": True,
                    "message": "프로필 이미지가 성공적으로 업데이트되었습니다.",
                    "new_profile_img": new_filename
                })
            else:
                return jsonify({"error": "데이터베이스 업데이트에 실패했습니다."}), 500
                
        except Exception as e:
            print(f"프로필 이미지 업데이트 중 오류: {e}")
            return jsonify({"error": "이미지 업데이트 중 오류가 발생했습니다."}), 500
    
    return jsonify({"error": "허용되지 않는 파일 형식입니다."}), 400

@app.route("/user/<username>")
def user_profile(username):
    """다른 사용자의 프로필 페이지"""
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
        return redirect(url_for("main_page"))
    
    # 조회할 사용자가 속한 팀들 조회
    user_teams = []
    teams = list(db["teams"].find({"members.userId": target_user["_id"]}))
    
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
    
    return render_template("user_profile.html", 
                         current_user=current_user, 
                         target_user=target_user, 
                         teams=user_teams)

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
                "upvotedUsers": [],  # 추천한 사용자 목록 초기화
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
    app.run('0.0.0.0', port=5000, debug=True)