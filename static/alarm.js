/**
 * 알림 시스템 JavaScript 모듈
 * WeeklyWeLearned 프로젝트용
 */

let notificationsOpen = false;

// 페이지 로드 시 알림 불러오기
document.addEventListener('DOMContentLoaded', function() {
  loadNotifications();
  
  // 30초 마다 알림 새로고침
  setInterval(loadNotifications, 30 * 1000);
});

// 알림 토글
function toggleNotifications() {
  const dropdown = document.getElementById('notification-dropdown');
  
  if (!notificationsOpen) {
    dropdown.classList.add('is-active');
    notificationsOpen = true;
    loadNotifications(); // 열 때마다 새로고침
  } else {
    dropdown.classList.remove('is-active');
    notificationsOpen = false;
  }
}

// 외부 클릭 시 알림 드롭다운 닫기
document.addEventListener('click', function(event) {
  const dropdown = document.getElementById('notification-dropdown');
  const icon = document.getElementById('notification-icon');
  
  if (!dropdown.contains(event.target) && !icon.contains(event.target)) {
    dropdown.classList.remove('is-active');
    notificationsOpen = false;
  }
});

// 알림 불러오기
async function loadNotifications() {
  try {
    const response = await fetch('/api/notifications');
    const data = await response.json();
    
    if (data.notifications) {
      displayNotifications(data.notifications);
      updateNotificationBadge(data.unread_count);
    }
  } catch (error) {
    console.error('알림 로드 실패:', error);
  }
}

// 알림 표시
function displayNotifications(notifications) {
  const listContainer = document.getElementById('notification-list');
  
  if (notifications.length === 0) {
    listContainer.innerHTML = `
      <div class="notification-empty">
        <i class="fas fa-bell-slash has-text-grey-light"></i>
        <p>알림이 없습니다</p>
      </div>
    `;
    return;
  }

  const notificationHTML = notifications.map(notification => {
    const timeAgo = getTimeAgo(notification.createdAt);
    const unreadClass = notification.isRead ? '' : 'is-unread';
    
    return `
      <div class="notification-item ${unreadClass}" onclick="handleNotificationClick('${notification._id}', '${notification.teamId}')">
        <div class="is-flex is-justify-content-between is-align-items-start">
          <div style="flex: 1;">
            <p class="has-text-weight-semibold is-size-7 mb-1">${notification.title}</p>
            <p class="is-size-7 has-text-grey-dark mb-2">${notification.message}</p>
            <p class="is-size-7 has-text-grey">
              <i class="fas fa-users mr-1"></i>${notification.postTitle}
            </p>
          </div>
          <div class="ml-2">
            <span class="is-size-7 has-text-grey">${timeAgo}</span>
            ${!notification.isRead ? '<div class="tag is-primary is-small">새</div>' : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');

  listContainer.innerHTML = notificationHTML;
}

// 알림 배지 업데이트
function updateNotificationBadge(count) {
  const badge = document.getElementById('notification-badge');
  
  if (count > 0) {
    badge.textContent = count > 99 ? '99+' : count;
    badge.style.display = 'block';
  } else {
    badge.style.display = 'none';
  }
}

// 알림 클릭 처리
async function handleNotificationClick(notificationId, teamId) {
  // 읽음 처리
  await markAsRead([notificationId]);
  
  // 팀 페이지로 이동
  window.location.href = `/team_page/${teamId}`;
}

// 읽음 처리
async function markAsRead(notificationIds) {
  try {
    const response = await fetch('/api/notifications/mark_read', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        notification_ids: notificationIds
      })
    });
    
    if (response.ok) {
      loadNotifications(); // 새로고침
    }
  } catch (error) {
    console.error('읽음 처리 실패:', error);
  }
}

// 모든 알림 읽음 처리
async function markAllAsRead() {
  try {
    const response = await fetch('/api/notifications/mark_read', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({})
    });
    
    if (response.ok) {
      loadNotifications();
    }
  } catch (error) {
    console.error('전체 읽음 처리 실패:', error);
  }
}

// 모든 알림 삭제
async function clearAllNotifications() {
  if (!confirm('모든 알림을 삭제하시겠습니까?')) {
    return;
  }

  try {
    const response = await fetch('/api/notifications/delete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({})
    });
    
    if (response.ok) {
      loadNotifications();
    }
  } catch (error) {
    console.error('알림 삭제 실패:', error);
  }
}

// 시간 경과 표시
function getTimeAgo(dateString) {
  const now = new Date();
  const date = new Date(dateString);
  const diffInSeconds = Math.floor((now - date) / 1000);

  if (diffInSeconds < 60) {
    return '방금 전';
  } else if (diffInSeconds < 3600) {
    return `${Math.floor(diffInSeconds / 60)}분 전`;
  } else if (diffInSeconds < 86400) {
    return `${Math.floor(diffInSeconds / 3600)}시간 전`;
  } else {
    return `${Math.floor(diffInSeconds / 86400)}일 전`;
  }
}

// 전역 스코프에 함수들 노출 (HTML에서 onclick으로 호출하기 위해)
window.toggleNotifications = toggleNotifications;
window.markAllAsRead = markAllAsRead;
window.clearAllNotifications = clearAllNotifications;
window.handleNotificationClick = handleNotificationClick;