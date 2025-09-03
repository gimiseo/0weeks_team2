#!/usr/bin/env python3
"""팀 추천수 필드 초기화 스크립트"""

from pymongo import MongoClient
import datetime

def init_upvote_fields():
    try:
        # MongoDB 연결
        client = MongoClient('mongodb://hwiskim:Gnltj7_AA13@15.164.218.130', 27017)
        db = client['flask_jwt_auth']
        
        print('MongoDB 연결 성공')
        
        # 모든 팀의 upvote 필드 확인
        teams_count = db['teams'].count_documents({})
        print(f'총 {teams_count}개 팀 존재')
        
        if teams_count == 0:
            print('팀이 없습니다. 초기화할 것이 없습니다.')
            return
        
        # upvote 필드가 없는 팀들 찾기
        teams_without_upvote = db['teams'].count_documents({'upvote': {'$exists': False}})
        print(f'upvote 필드가 없는 팀: {teams_without_upvote}개')
        
        if teams_without_upvote > 0:
            print('upvote 필드가 없는 팀들을 0으로 초기화합니다...')
            result = db['teams'].update_many(
                {'upvote': {'$exists': False}},
                {'$set': {'upvote': 0}}
            )
            print(f'{result.modified_count}개 팀의 upvote 필드를 0으로 초기화했습니다.')
        else:
            print('모든 팀에 이미 upvote 필드가 존재합니다.')
        
        # 글의 likes 필드도 확인하고 초기화
        print('\n=== 글의 likes 필드 확인 ===')
        teams_with_posts = list(db['teams'].find({'posts': {'$exists': True, '$ne': []}}))
        
        posts_updated = 0
        for team in teams_with_posts:
            team_id = team['_id']
            posts = team.get('posts', [])
            
            for i, post in enumerate(posts):
                if 'likes' not in post:
                    # likes 필드가 없는 글에 0으로 초기화
                    db['teams'].update_one(
                        {'_id': team_id},
                        {'$set': {f'posts.{i}.likes': 0}}
                    )
                    posts_updated += 1
        
        print(f'{posts_updated}개 글의 likes 필드를 초기화했습니다.')
        
        # 몇 개 팀의 현재 상태 확인
        sample_teams = list(db['teams'].find({}, {'teamName': 1, 'week': 1, 'upvote': 1, 'posts': 1}).limit(3))
        print('\n=== 샘플 팀들의 현재 상태 ===')
        for team in sample_teams:
            upvote = team.get('upvote', '필드없음')
            team_name = team.get('teamName', 'Unknown')
            week = team.get('week', 'Unknown')
            posts_count = len(team.get('posts', []))
            print(f'팀: {team_name} (주차: {week}) - 추천수: {upvote}, 글 수: {posts_count}')
            
            # 각 글의 likes 상태도 확인
            for j, post in enumerate(team.get('posts', [])[:2]):  # 최대 2개 글만 확인
                likes = post.get('likes', '필드없음')
                title = post.get('title', 'No title')[:20]
                print(f'  - 글: {title}... - 좋아요: {likes}')
        
        print('\n초기화 완료! 이제 추천/좋아요 기능을 사용할 수 있습니다.')
        
    except Exception as e:
        print(f'오류 발생: {e}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    init_upvote_fields()
