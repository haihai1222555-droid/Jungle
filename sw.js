// Jungle Laundry 2.0 - Service Worker (Web Push)
// fetch/cache 핸들러가 없어 오프라인 캐싱은 하지 않는다. 탭이 닫혀도
// 알림이 오게 하는 것(Web Push)만 이 파일의 역할이다.
self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

// 🔔 탭이 닫히거나 앱이 종료되어도 Google FCM / OS 푸시 서비스를 통해 알림 수신
self.addEventListener('push', event => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: '🧺 세탁실 알림', body: event.data.text() };
    }
  }

  const title = data.title || '🧺 정글 스마트 세탁실';
  const options = {
    body: data.body || '세탁/건조 상태가 업데이트되었습니다.',
    icon: data.icon || '/jungle-logo-192.png',
    badge: '/jungle-logo-192.png',
    vibrate: [300, 100, 300, 100, 400],
    tag: data.tag || 'laundry-alarm-' + Date.now(),
    renotify: true,
    requireInteraction: true,
    // 기기가 문 열림을 알려주지 않아서, 수거 여부는 본인이 눌러줘야 알 수 있다
    actions: Array.isArray(data.actions) ? data.actions : [],
    data: {
      url: data.url || '/',
      key: data.key || null,
      endpoint: data.endpoint || null
    }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const info = event.notification.data || {};
  const urlToOpen = info.url || '/';

  // 🧺 '가져갔어요' 를 누른 경우: 창을 열지 않고 서버에만 알린다
  if (event.action === 'picked') {
    event.waitUntil(
      fetch('/api/picked-up', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: info.key, endpoint: info.endpoint })
      }).catch(err => console.warn('[SW] 수거 확인 전송 실패', err))
    );
    return;
  }

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});