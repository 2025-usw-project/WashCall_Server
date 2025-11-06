// firebase-messaging-sw.js
// 이 파일은 웹 클라이언트의 public 폴더에 위치해야 합니다.

importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js');

// Firebase 초기화
firebase.initializeApp({
  apiKey: "AIzaSyD0MBr9do9Hl3AJsNv0yZJRupDT1l-8dVE",
  authDomain: "washcallproject.firebaseapp.com",
  projectId: "washcallproject",
  storageBucket: "washcallproject.firebasestorage.app",
  messagingSenderId: "401971602509",
  appId: "1:401971602509:web:45ee34d4ed2454555aa804"
});

const messaging = firebase.messaging();

// 백그라운드 메시지 수신 (앱이 닫혀있거나 백그라운드일 때)
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] 백그라운드 메시지 수신:', payload);
  
  const notificationTitle = payload.notification?.title || '알림';
  const notificationOptions = {
    body: payload.notification?.body || '',
    icon: '/icon.png',
    badge: '/badge.png',
    data: payload.data || {},
    tag: payload.data?.machine_id || 'default',
    requireInteraction: true,  // 사용자가 클릭할 때까지 알림 유지
  };

  return self.registration.showNotification(notificationTitle, notificationOptions);
});

// 알림 클릭 이벤트 처리
self.addEventListener('notificationclick', (event) => {
  console.log('[firebase-messaging-sw.js] 알림 클릭:', event.notification);
  
  event.notification.close();
  
  const data = event.notification.data;
  const clickAction = data.click_action || '/';
  
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // 이미 열려있는 창이 있으면 포커스
        for (const client of clientList) {
          if (client.url.includes(clickAction) && 'focus' in client) {
            return client.focus();
          }
        }
        // 열려있는 창이 없으면 새 창 열기
        if (clients.openWindow) {
          return clients.openWindow(clickAction);
        }
      })
  );
});
