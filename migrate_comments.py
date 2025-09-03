#!/usr/bin/env python3
"""
기존 댓글들에 _id 필드를 추가하는 마이그레이션 스크립트
"""

from pymongo import MongoClient
from bson import ObjectId
import datetime

# MongoDB 연결
client = MongoClient('mongodb://hwiskim:Gnltj7_AA13@15.164.218.130', 27017)
db = client["flask_jwt_auth"]

def migrate_comments():
    """모든 팀의 댓글들에 _id를 추가"""
    teams = db["teams"].find({})
    updated_count = 0
    
    for team in teams:
        team_updated = False
        posts = team.get("posts", [])
        
        for post_idx, post in enumerate(posts):
            comments = post.get("comments", [])
            
            for comment_idx, comment in enumerate(comments):
                # _id가 없는 댓글에만 추가
                if "_id" not in comment:
                    comment["_id"] = ObjectId()
                    team_updated = True
                    print(f"팀 '{team['teamName']}' 주차 {team['week']} 글 '{post['title']}' 댓글에 _id 추가")
        
        # 팀이 업데이트된 경우 저장
        if team_updated:
            db["teams"].replace_one({"_id": team["_id"]}, team)
            updated_count += 1
    
    print(f"\n마이그레이션 완료: {updated_count}개 팀의 댓글이 업데이트되었습니다.")

if __name__ == "__main__":
    print("댓글 _id 마이그레이션 시작...")
    migrate_comments()
    print("마이그레이션 완료!")
