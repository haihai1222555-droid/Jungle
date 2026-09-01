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
pip install -r requirements.txt

# 2. 백그라운드 영구 실행 (PM2 또는 nohup)
nohup python start_server.py > server.log 2>&1 &
```

---

## 🛡️ 시스템 특징
* **HTTPS 완벽 지원**: PWA 및 Web Notifications / Web Push 동작.
* **0.1초 실시간 모니터링**: 9대 워시타워 상태 실시간 동기화.
* **초고속 AI 챗봇**: Google Gemini Flash Lite 엔진 탑재.
