# 🚀 크래프톤 정글 스마트 세탁실 2.0 배포 가이드

## 구조

```
브라우저 ─→ Render (jungle-wash.onrender.com)
              ├─ 사이트 (index.html / app.js / style.css)
              ├─ /api/status, /api/stats  → 원본 서버 프록시
              └─ /api/subscribe-push 등    → 앱을 꺼도 오는 알림
                    └─ 5초마다 기기 상태 확인 → 5분 전 / 완료 시 발송

UptimeRobot ─→ /api/health  5분마다 핑 (Render 가 잠들지 않게)

원본 세탁기 데이터는 별도 서버(Cloudflare 터널)에서 받아온다. 이 프로젝트 소유가 아니다.
```

`start_server.py` 하나가 **사이트 서빙 + API 프록시 + 알림 발송**을 모두 담당한다.
Vercel 은 백그라운드 알림을 돌릴 수 없어서(서버리스라 상시 실행 프로세스가 없음) 사용하지 않는다.

---

## Render 배포

### 1. 서비스 생성
1. Render → `New +` → `Web Service` → 이 저장소 연결
2. Instance Type: **Free**
3. Region: **Singapore** (한국에서 가장 가깝다. ⚠️ 생성 후 변경 불가)
4. Build Command: `pip install -r requirements.txt`
5. **Start Command: `python start_server.py`**
   → 기본값(gunicorn)으로 두면 `gunicorn: command not found` 로 실패한다.

### 2. 환경변수

| Key | 필수 | 설명 |
| --- | --- | --- |
| `VAPID_PRIVATE_KEY_PEM` | ✅ | 로컬 `vapid_private.pem` 내용 **전체** (`-----BEGIN PRIVATE KEY-----` 줄 포함) |
| `TARGET_BASE` | | 원본 API 주소. 주소가 바뀌면 **여기만** 바꾸면 된다 (코드 수정·재배포 불필요) |
| `SUBS_FILE` | | 알림 구독 저장 경로 |

> ⚠️ `VAPID_PRIVATE_KEY_PEM` 을 빼먹으면 안 된다.
> Render 는 재시작마다 파일시스템이 초기화되므로, 환경변수가 없으면 매번 새 키가 생성되어
> **이미 등록된 알림이 전부 무효화된다.**

클립보드로 바로 복사:

```bash
cat vapid_private.pem | clip
```

### 3. 잠들지 않게 하기 (필수)

Render 무료 서비스는 **15분간 접속이 없으면 잠든다.** 잠들면 알림도 안 간다.

1. [UptimeRobot](https://uptimerobot.com) 무료 가입
2. `New Monitor` → HTTP(s) → `https://<렌더주소>/api/health`
3. Monitoring Interval: **5 minutes**

정상이면 이렇게 응답한다.

```json
{"ok": true, "webpush": true, "alarms": 0}
```

`webpush: false` 면 VAPID 환경변수가 안 들어간 것이다.

---

## 로컬 실행

```bash
python start_server.py
```

`http://localhost:8000` 에서 열린다. `vapid_private.pem` 이 없으면 자동 생성된다.

Docker 로도 실행할 수 있다.

```bash
docker compose up -d --build
```

---

## 알림이 안 올 때

Render 로그를 먼저 본다. 로그는 버퍼링 없이 즉시 출력되도록 해두었다.

| 로그 | 의미 |
| --- | --- |
| `[WebPush] 백그라운드 알림 워커 시작됨` | 서버 정상 기동 |
| `[Alarm] 5분전 조건 충족: ...` | 발송 조건 판정됨 |
| `[WebPush] 발송 성공: ...` | 실제 발송 완료 |
| `[WebPush Error] ...` | 판정은 맞았으나 전송 실패 — 원인이 여기 찍힌다 |
| `[Alarm] 오래된 알림 정리` | 4시간 지난 등록 자동 삭제 |

**아이폰**은 사파리 탭에서 웹 푸시가 오지 않는다.
공유 → **홈 화면에 추가**로 설치한 뒤 그 아이콘으로 실행해야 동작한다 (iOS 16.4+).
안드로이드는 크롬에서 알림만 허용하면 된다.

---

## 알아둘 제약

* 무료 750시간/월 = 한 달 내내 켜두면 744시간. **서비스 하나만** 상시 가동 가능.
* 재배포하면 등록돼 있던 알림 목록이 초기화된다 (VAPID 키는 환경변수라 유지).
* UptimeRobot 핑이 멈추면 서비스가 잠들어 그 사이 알림을 놓친다.
* 원본 서버(Cloudflare 터널)는 이 프로젝트 소유가 아니라서, 그쪽이 꺼지면 실시간 데이터가 끊긴다.
  이때 화면은 마지막으로 받은 데이터를 "연결 끊김 · N분 전 데이터"로 표시한다.
