// Jungle Laundry 2.0 - Service Worker (Web Push & Offline Engine)
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
    data: { url: data.url || '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const urlToOpen = event.notification.data?.url || '/';

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