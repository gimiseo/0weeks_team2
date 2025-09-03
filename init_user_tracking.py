#!/usr/bin/env python3
"""추천/좋아요 사용자 추적 필드 초기화 스크립트"""

from pymongo import MongoClient
import datetime

def init_user_tracking_fields():
    try:
        # MongoDB 연결
        client = MongoClient('mongodb://hwiskim:Gnltj7_AA13@15.164.218.130', 27017)
        db = client['flask_jwt_auth']
        
        print('MongoDB 연결 성공')
        
        # 모든 팀 조회
        teams = list(db['teams'].find({}))
        print(f'총 {len(teams)}개 팀 발견')
        
        teams_updated = 0
        posts_updated = 0
        
        for team in teams:
            team_id = team['_id']
            update_fields = {}
            
            # upvotedUsers 필드가 없으면 빈 배열로 초기화
            if 'upvotedUsers' not in team:
                update_fields['upvotedUsers'] = []
            
            # 팀 업데이트
            if update_fields:
                db['teams'].update_one(
                    {'_id': team_id},
                    {'$set': update_fields}
                )
                teams_updated += 1
            
            # 각 글의 likedUsers 필드 확인 및 초기화
            posts = team.get('posts', [])
            for i, post in enumerate(posts):
                if 'likedUsers' not in post:
                    db['teams'].update_one(
                        {'_id': team_id},
                        {'$set': {f'posts.{i}.likedUsers': []}}
                    )
                    posts_updated += 1
        
        print(f'{teams_updated}개 팀의 upvotedUsers 필드를 초기화했습니다.')
        print(f'{posts_updated}개 글의 likedUsers 필드를 초기화했습니다.')
        
        # 몇 개 팀의 현재 상태 확인
        sample_teams = list(db['teams'].find({}, {'teamName': 1, 'week': 1, 'upvote': 1, 'upvotedUsers': 1, 'posts': 1}).limit(3))
        print('\n=== 샘플 팀들의 현재 상태 ===')
        for team in sample_teams:
            upvote = team.get('upvote', 0)
            upvoted_users_count = len(team.get('upvotedUsers', []))
            team_name = team.get('teamName', 'Unknown')
            week = team.get('week', 'Unknown')
            posts_count = len(team.get('posts', []))
            print(f'팀: {team_name} (주차: {week}) - 추천수: {upvote}, 추천한 사용자: {upvoted_users_count}명, 글 수: {posts_count}')
            
            # 각 글의 상태도 확인
            for j, post in enumerate(team.get('posts', [])[:2]):  # 최대 2개 글만 확인
                likes = post.get('likes', 0)
                liked_users_count = len(post.get('likedUsers', []))
                title = post.get('title', 'No title')[:20]
                print(f'  - 글: {title}... - 좋아요: {likes}, 좋아요한 사용자: {liked_users_count}명')
        
        print('\n초기화 완료! 이제 중복 추천/좋아요 방지 기능이 활성화됩니다.')
        
    except Exception as e:
        print(f'오류 발생: {e}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    init_user_tracking_fields()
