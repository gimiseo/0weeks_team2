from pymongo import MongoClient
from werkzeug.security import generate_password_hash
import datetime
import random

# MongoDB 연결
client = MongoClient("mongodb://localhost:27017/")
db = client["flask_jwt_auth"]
users_collection = db["users"]
teams_collection = db["teams"]

def clear_existing_data():
    """기존 데이터 삭제 (선택사항)"""
    print("기존 데이터를 삭제하시겠습니까? (y/n): ", end="")
    choice = input()
    if choice.lower() == 'y':
        users_collection.delete_many({})
        teams_collection.delete_many({})
        print("기존 데이터가 삭제되었습니다.")

def create_sample_users():
    """30명의 샘플 사용자 생성"""
    print("사용자 생성 중...")
    
    users = []
    for i in range(30):
        username = f"user{i+1:02d}"  # user01, user02, ...
        nickname = f"사용자_{i+1:02d}"  # 사용자_01, 사용자_02, ...
        
        user_data = {
            "username": username,
            "password": generate_password_hash("1234"),
            "nickname": nickname,
            "profile_img": None  # 프로필 이미지는 None으로 설정
        }
        users.append(user_data)
    
    # 사용자 데이터 삽입
    result = users_collection.insert_many(users)
    print(f"✅ {len(result.inserted_ids)}명의 사용자가 생성되었습니다.")
    return result.inserted_ids

def create_sample_teams(user_ids):
    """다양한 주차에 팀들 생성"""
    print("팀 생성 중...")
    
    teams = []
    
    # 각 주차별로 팀 생성
    for week in range(21):  # week 0 ~ 20
        num_teams_in_week = random.randint(2, 10)
        
        for team_idx in range(num_teams_in_week):
            # 팀 이름: 팀_0주차_0 형식
            team_name = f"팀_{week}주차_{team_idx + 1}"
            
            # 팀 비밀번호는 팀명과 동일
            team_password = team_name
            
            # 팀장 선택
            master_id = random.choice(user_ids)
            
            # 팀 멤버 선택 (팀장 포함 2~6명)
            member_count = random.randint(2, 6)
            selected_members = random.sample(user_ids, member_count)
            
            # 팀장을 첫 번째로 배치
            if master_id not in selected_members:
                selected_members[0] = master_id
            
            members = []
            for idx, user_id in enumerate(selected_members):
                role = "master" if user_id == master_id else "member"
                members.append({
                    "userId": user_id,
                    "role": role,
                    "joinedAt": datetime.datetime.utcnow() - datetime.timedelta(days=random.randint(0, 30))
                })
            
            team_data = {
                "teamName": team_name,
                "description": f"{week}주차 스터디 팀",
                "week": week,
                "roomPasswordHash": generate_password_hash(team_password),
                "masterId": master_id,
                "createdAt": datetime.datetime.utcnow() - datetime.timedelta(days=random.randint(0, 30)),
                "upvote": random.randint(0, 15),  # 랜덤 추천수
                "members": members,
                "posts": []
            }
            teams.append(team_data)
    
    # 팀 데이터 삽입
    if teams:
        result = teams_collection.insert_many(teams)
        print(f"✅ {len(result.inserted_ids)}개의 팀이 생성되었습니다.")
    else:
        print("⚠️ 생성된 팀이 없습니다.")
    
    return teams

def check_duplicate_password_in_week(team_data, password, existing_teams):
    """같은 주차에서 비밀번호 중복 체크 (더 이상 필요하지 않음)"""
    # 팀명 = 비밀번호이므로 팀명이 다르면 비밀번호도 다름
    # 이 함수는 사용되지 않지만 호환성을 위해 남겨둠
    return False

def print_sample_data():
    """생성된 데이터 요약 출력"""
    print("\n" + "="*50)
    print("📊 생성된 데이터 요약")
    print("="*50)
    
    # 사용자 수
    user_count = users_collection.count_documents({})
    print(f"👥 총 사용자 수: {user_count}명")
    
    # 팀 수
    team_count = teams_collection.count_documents({})
    print(f"🏠 총 팀 수: {team_count}개")
    
    # 주차별 팀 수
    print("\n📅 주차별 팀 분포:")
    for week in range(21):
        week_team_count = teams_collection.count_documents({"week": week})
        if week_team_count > 0:
            print(f"Week {week:2d}: {week_team_count}개 팀")
    
    print("\n🔑 모든 계정 비밀번호: 1234")
    print("🔐 팀 비밀번호 예시: team01, team02, team03, ...")
    
    # 샘플 사용자 몇 명 출력
    print("\n👤 샘플 사용자들:")
    sample_users = users_collection.find({}).limit(5)
    for user in sample_users:
        print(f"   • {user['username']} ({user['nickname']})")
    
    # 샘플 팀 몇 개 출력
    print("\n🏠 샘플 팀들:")
    sample_teams = teams_collection.find({}).limit(5)
    for team in sample_teams:
        print(f"   • {team['teamName']} (Week {team['week']}, 멤버 {len(team['members'])}명)")

def main():
    print("🚀 Flask JWT Auth DB 초기화 스크립트")
    print("="*50)
    
    # 기존 데이터 삭제 여부 확인
    clear_existing_data()
    
    # 사용자 생성
    user_ids = create_sample_users()
    
    # 팀 생성
    create_sample_teams(user_ids)
    
    # 요약 출력
    print_sample_data()
    
    print("\n✅ 데이터베이스 초기화가 완료되었습니다!")
    print("🌐 이제 웹 애플리케이션을 실행해보세요.")

if __name__ == "__main__":
    main()