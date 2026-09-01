# 🚀 크래프톤 정글 스마트 세탁실 2.0 서버 배포 가이드

본 프로젝트는 **Vercel / Cloudflare Pages / AWS EC2 / Docker / Ubuntu** 등 어떤 환경에서도 단 몇 분 만에 배포할 수 있도록 완벽하게 설계되었습니다.

---

## 📌 옵션 1: Vercel 무료 배포 (가장 추천! 1분 만에 완료)

1. GitHub 저장소에 이 프로젝트를 Push합니다.
2. [Vercel.com](https://vercel.com)에 로그인 후 `Add New Project` 클릭.
3. 해당 저장소를 선택하고 `Deploy` 버튼을 누르면 끝!
   * `vercel.json`이 자동으로 API 프록시 및 PWA Service Worker 헤더를 처리합니다.
   * 무료 HTTPS 도메인이 즉시 발급되어 모바일 PWA 및 Web Push 알림이 완벽 작동합니다.

---

## 📌 옵션 2: Docker / Docker Compose 배포 (기숙사/클라우드 서버)

```bash
# 1. 패키지 빌드 및 백그라운드 실행
docker compose up -d --build

# 2. 상태 확인
docker ps
```
* 포트 `8000`으로 즉시 서비스가 시작되며, `push_subscriptions.json`이 영구 저장됩니다.

---

## 📌 옵션 3: Linux / Ubuntu / AWS EC2 직접 실행

```bash
# 1. 의존성 설치
pip install -r requirements-docker.txt

# 2. 백그라운드 영구 실행 (PM2 또는 nohup)
nohup python start_server.py > server.log 2>&1 &
```

---

## 🛡️ 시스템 특징
* **HTTPS 완벽 지원**: PWA 및 Web Notifications / Web Push 동작.
* **0.1초 실시간 모니터링**: 9대 워시타워 상태 실시간 동기화.
* **초고속 AI 챗봇**: Google Gemini Flash Lite 엔진 탑재.

---

## 🔔 옵션 4: Render 무료 배포 — "앱을 꺼도 오는 알림" 전용 백엔드

Vercel 은 정적 파일만 서빙하므로 백그라운드 푸시가 **동작하지 않는다**
(`/api/subscribe-push` 가 404). 앱을 꺼도 알림을 받으려면 24시간 도는 서버가 필요하고,
그 역할을 Render 무료 웹 서비스가 맡는다.

```
브라우저 ─→ Vercel        사이트 + /api/status 프록시
        └→ Render        푸시 등록 + 5초마다 감시 + 발송
UptimeRobot ─→ Render     5분마다 /api/health 핑 (잠들지 않게)
```

### 1. Render 배포
1. Render 에서 `New +` → `Web Service` → 이 저장소 연결
2. Runtime 은 **Docker** 자동 인식 (`Dockerfile` 이 이미 있음)
3. Instance Type 은 **Free** 선택

### 2. 환경변수 설정 (⚠️ 필수)

Render 대시보드 → Environment 에 추가한다.

| Key | Value |
| --- | --- |
| `VAPID_PRIVATE_KEY_PEM` | 로컬 `vapid_private.pem` 파일 내용 **전체**를 복사해 붙여넣기 |

> ⚠️ **이걸 빼먹으면 안 된다.** Render 는 재시작마다 파일시스템이 초기화되므로,
> 환경변수가 없으면 매번 새 VAPID 키가 생성되어 **이미 등록된 알림이 전부 무효화된다.**

선택 항목: `TARGET_BASE` (원본 API 주소가 바뀌었을 때 재배포 없이 교체 가능)

### 3. 사이트에 Render 주소 연결

배포된 주소(예: `https://jungle-laundry.onrender.com`)를 `app.js` 상단에 넣는다.

```js
const PUSH_API_BASE = 'https://jungle-laundry.onrender.com';
```

비워두면 알림은 **화면을 보고 있는 동안만** 동작한다.

### 4. 잠들지 않게 하기 (⚠️ 필수)

Render 무료 웹 서비스는 **15분간 접속이 없으면 잠든다.** 잠들면 알림도 안 간다.

1. [UptimeRobot](https://uptimerobot.com) 무료 가입 (모니터 50개 / 5분 간격)
2. `New Monitor` → HTTP(s) → URL 에 `https://<렌더주소>/api/health`
3. Monitoring Interval 을 **5 minutes** 로 설정

`/api/health` 는 이 용도로 만든 엔드포인트이며 현재 등록된 알림 수도 함께 반환한다.

```json
{"ok": true, "webpush": true, "alarms": 0}
```

### 알아둘 제약
* 무료 750시간/월 = 한 달 내내 켜두면 744시간. **서비스 하나만** 무료로 상시 가동 가능.
* 재배포하면 등록돼 있던 알림 목록이 초기화된다 (VAPID 키는 환경변수라 유지됨).
* UptimeRobot 핑이 멈추면 서비스가 잠들어 그 사이 알림을 놓친다.
