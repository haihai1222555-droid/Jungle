# 🚀 배포 가이드

## 구조

```
브라우저 ─→ Caddy (443, HTTPS 자동)
              └─→ start_server.py (127.0.0.1:8000)
                    ├─ 사이트 (index.html / app.js / style.css)
                    ├─ /api/status, /api/stats  → 원본 서버 프록시 (5초마다 갱신)
                    ├─ 웹 푸시 발송 (5초마다 기기 상태 확인)
                    └─ 디스코드 봇 (같은 프로세스)

Upstash     ←─ 알림·설정·제보 보관 (재시작해도 안 사라진다)
UptimeRobot ─→ /api/health  5분마다 (죽으면 메일)
```

`start_server.py` 하나가 **사이트 · API 프록시 · 웹 푸시 · 디스코드 봇**을 모두 맡는다.
원본 세탁기 데이터는 별도 서버(Cloudflare 터널)에서 받아온다. 이 프로젝트 소유가 아니다.

> **서버리스(Vercel 등)로는 안 된다.** 5초마다 도는 감시 루프와 디스코드 게이트웨이 연결이
> 필요해서 상시 실행 프로세스가 있어야 한다.

---

## 어떤 서버가 필요한가

| 조건 | 왜 |
| --- | --- |
| 24시간 안 자는 것 | 봇이 게이트웨이 연결을 계속 물고 있어야 한다 |
| 전용 IP | 공유 IP 는 디스코드가 막아둔 대역일 수 있다 |
| 메모리 1GB 이상 | 실측 480MB 쓴다 |

무료로 이 셋을 만족하는 곳이 드물다. 이 프로젝트는 **Oracle Cloud Always Free**
(`VM.Standard.E2.1.Micro`, 1GB)에서 돌고 있다. 유료라면 Hetzner 같은 곳이 편하다.

---

## 1. 서버 준비

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
git clone <이 저장소> ~/jungle-laundry
cd ~/jungle-laundry
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

안내 지식은 저장소에 없다. 본보기를 복사해 채운다.

```bash
cp jungle_kb.example.py jungle_kb.py
```

### 방화벽

클라우드 방화벽과 인스턴스 방화벽이 **따로** 있다. 둘 다 열어야 한다.

```bash
# 인스턴스 쪽 (우분투 이미지는 기본이 거부다)
sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 2 -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

클라우드 콘솔에서도 443(과 80)을 열어준다. Oracle 이면 VCN → 보안 목록.

> 80 을 안 열어도 HTTPS 는 된다. Caddy 가 TLS-ALPN-01(443)로 인증서를 받기 때문이다.
> 다만 주소창에 `http://` 로 들어오는 사람은 연결이 안 된다.

---

## 2. 환경변수

`.env` 를 만든다. **깃에 올리지 않는다** (`.gitignore` 에 있다).

```bash
cp .env.example .env
nano .env
```

| Key | 필수 | 설명 |
| --- | --- | --- |
| `VAPID_PRIVATE_KEY_PEM` | ✅ | 푸시 서명용 개인키. 바뀌면 **기존 구독이 전부 무효화된다** |
| `TARGET_BASE` | | 원본 API 주소. 바뀌면 여기만 고치면 된다 |
| `PORT` | | 기본 8000 |
| `DISCORD_BOT_TOKEN` | | 있으면 봇도 함께 뜬다 |
| `RUN_DISCORD_BOT` | | `0` 이면 웹만 |
| `ENABLE_MESSAGE_CONTENT` | | 멘션 없이 채널 대화 (포털에서 먼저 켤 것) |
| `GEMINI_API_KEY` `..._2` `..._3` | | 여러 개면 막힌 키를 건너뛴다. **봇과 웹이 함께 쓴다** |
| `GROQ_API_KEY` | | 제미나이가 늦거나 막혔을 때. 이것도 봇·웹 공용 |
| `UPSTASH_REDIS_REST_URL` / `..._TOKEN` | | 알림·설정·제보 보관 |
| `SUPPORT_CONTACT` | | 문의처. 비우면 번호 없이 안내 |
| `ADMIN_USER_IDS` | | 제보를 DM 으로 받을 사람 |
| `STALE_PICKUP_SEC` | | 수거 요청까지 유예 (기본 900초) |
| `BIXBY_SECRET` / `BIXBY_USER_ID` | | 음성 비서 연동(선택). 둘 다 채워야 `/api/voice/ask` 가 열린다 |

VAPID 키가 없으면 첫 실행 때 `vapid_private.pem` 이 자동 생성된다.
그 내용을 통째로 `VAPID_PRIVATE_KEY_PEM` 에 넣어두면 서버를 옮겨도 구독이 살아 있다.

```bash
cat vapid_private.pem
```

---

## 3. 서비스 등록

`/etc/systemd/system/jungle-wash.service`

```ini
[Unit]
Description=Jungle Laundry - 웹 대시보드 + 디스코드 봇
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/jungle-laundry
EnvironmentFile=/home/ubuntu/jungle-laundry/.env
ExecStart=/home/ubuntu/jungle-laundry/.venv/bin/python /home/ubuntu/jungle-laundry/start_server.py
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/jungle-laundry/server.log
StandardError=append:/home/ubuntu/jungle-laundry/server.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jungle-wash
sudo systemctl status jungle-wash
```

---

## 4. HTTPS (Caddy)

`/etc/caddy/Caddyfile`

```
example.duckdns.org {
	encode gzip zstd
	reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl restart caddy
```

인증서는 Caddy 가 알아서 받고 갱신한다. 도메인이 이 서버를 가리키고 있어야 한다.

> **주의.** Caddy 뒤에 두면 모든 접속이 `127.0.0.1` 로 보인다.
> 제보 도배 방지 같은 것은 `X-Forwarded-For` 를 봐야 한다 (코드는 이미 그렇게 되어 있다).

---

## 5. 감시 (UptimeRobot)

`/api/health` 는 웹이 살아 있으면 `"ok": true` 를 준다. **봇이 죽어도 초록불이다.**
그래서 일반 HTTP 감시 대신 **키워드 감시**를 쓴다.

| 항목 | 값 |
| --- | --- |
| Monitor type | `Keyword` |
| URL | `https://<도메인>/api/health` |
| Keyword | `"botOnline": true` |
| Keyword type | `does not exist` 일 때 알림 |
| Case-sensitive | 켬 |

이러면 웹이 죽든 봇만 끊기든 둘 다 잡힌다.

---

## 갱신

```bash
scp app.js style.css index.html start_server.py discord_bot.py 서버:~/jungle-laundry/
ssh 서버 "sudo systemctl restart jungle-wash"
```

`jungle_kb.py` 와 `assets/` 는 저장소에 없으므로 서버에 직접 둔다.

---

## 문제 해결

### 알림이 안 올 때

**1) 서버가 살아있는지**

```bash
curl https://<도메인>/api/health
```

`"ok": true, "webpush": true, "botOnline": true` 가 나와야 한다.
`webpush: false` 면 VAPID 키가 빠진 것이다.

**2) 전달 경로 — 빨래가 끝날 때까지 기다리지 않아도 된다**

```bash
curl -X POST https://<도메인>/api/test-push -H "Content-Type: application/json" -d "{}"
```

**3) 로그**

```bash
tail -f ~/jungle-laundry/server.log
```

| 로그 | 의미 |
| --- | --- |
| `[Alarm] 5분전 조건 충족` | 판정됨 |
| `[Alarm] 완료` | 완료 알림 발송 |
| `[WebPush] 발송 성공` | 실제 전송 완료 |
| `[WebPush] 못 쓰는 구독(410)` | 죽은 구독을 목록에서 뺐다 |

`[Alarm]` 이 없으면 판정 문제, 있는데 `발송 성공` 이 없으면 전송 문제,
둘 다 있는데 폰에 안 오면 폰 권한이나 iOS 설치 방식 문제다.

### 봇이 안 붙을 때

`429` 가 반복되면 디스코드가 이 IP 를 잠시 막은 것이다. 재시작을 되풀이하면 더 길어진다.
코드가 알아서 간격을 늘려가며 기다리므로 그냥 두면 된다.

`ENABLE_MESSAGE_CONTENT=1` 을 줬는데 포털에서 안 켰으면 접속 자체가 안 된다.
그때는 스스로 그 기능을 끄고 다시 붙어 멘션·DM 은 살린다.

### 숫자가 안 바뀔 때

화면에 **"연결 끊김 · N분 전 데이터"** 로 표시된다.
원본 서버가 꺼졌거나 터널 주소가 바뀐 것이다. `TARGET_BASE` 를 새 주소로 바꾼다.

---

## 알아둘 것

* **봇을 두 대에서 동시에 띄우면 알림이 두 번 간다.** 서버를 옮길 때는
  옛 쪽을 먼저 멈춘 뒤 새 쪽을 켠다.
* **시간대별 혼잡도는 24시간이 차야 제 값이 된다.** 5초마다 직접 세어 쌓는 실측값이고,
  매주 월요일에 지난 주 관측으로 갱신된다.
* **AI 키는 서버에만 둔다.** 브라우저는 `/api/ai/...` 로 서버에 물어보고,
  서버가 `.env` 의 키를 붙여 대신 부른다.
  한때는 브라우저가 직접 불렀는데, 그러려면 키를 `app.js` 에 적어야 했다.
  그 파일은 사이트에 들어온 누구나 받아 갈 수 있어서 F12 한 번이면 보이고,
  저장소를 공개하자 검색에도 잡혔다. 실제로 그렇게 새서 폐기 통보를 받았다.
  **키를 프런트엔드 파일에 적지 않는다.** 키를 새로 받아도 같은 자리에 넣으면 똑같이 샌다.
* **원본 서버는 이 프로젝트 소유가 아니다.** 그쪽이 꺼지면 실시간 데이터가 끊긴다.
