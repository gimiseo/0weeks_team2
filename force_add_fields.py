#!/usr/bin/env python3
"""간단한 필드 추가 스크립트"""

from pymongo import MongoClient

client = MongoClient('mongodb://hwiskim:Gnltj7_AA13@15.164.218.130', 27017)
db = client['flask_jwt_auth']

print('모든 팀에 upvotedUsers 필드 강제 추가...')
result1 = db['teams'].update_many(
    {},
    {'$set': {'upvotedUsers': []}}
)
print(f'{result1.modified_count}개 팀 업데이트됨')

print('모든 글에 likedUsers 필드 강제 추가...')
# 모든 팀의 모든 글에 likedUsers 필드 추가
result2 = db['teams'].update_many(
    {},
    {'$set': {'posts.$[].likedUsers': []}}
)
print(f'{result2.modified_count}개 팀의 글 업데이트됨')

print('완료!')
