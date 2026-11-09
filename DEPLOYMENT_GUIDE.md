# 🚀 배포 가이드

> 이 문서는 **지금 돌고 있는 서버**를 기준으로 적었다. 마지막으로 서버와 맞춰 본 날은
> 2026-11-09 이다. 서버를 옮기거나 바꿨다면 이 문서도 같이 고친다.

## 구조

```
브라우저 ─→ Caddy (443, HTTPS 자동)
              └─→ start_server.py (127.0.0.1:8000)
                    ├─ 사이트 (index.html / app.js / style.css)
                    ├─ /api/status, /api/stats  → 원본 서버 프록시 (5초마다 갱신)
                    ├─ 웹 푸시 발송 (5초마다 기기 상태 확인)
                    └─ 디스코드 봇 (같은 프로세스)

Upstash     ←─ 알림·설정·제보·통살균 횟수 보관 (재시작해도, 서버를 옮겨도 안 사라진다)
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
| 메모리 1GB 이상 | 파이썬 프로세스 하나가 약 110MB, 서버 전체로 약 0.7GB 쓴다 (봇 포함) |

무료로 이 셋을 만족하는 곳이 드물다. 이 프로젝트는 **Oracle Cloud Always Free** 에서 돌고 있다.

| | 지금 |
| --- | --- |
| 종류 | `VM.Standard.A1.Flex` (ARM) |
| 크기 | 2 OCPU · 12GB 메모리 · 디스크 46GB |
| 운영체제 | Ubuntu 24.04 |
| 리전 | 오사카 (`ap-osaka-1`) |
| 시간대 | **UTC** (로그 시각이 한국 시각보다 9시간 느리다) |

**알아둘 것**

* A1 은 자리가 잘 안 난다. 이 프로젝트는 빈자리를 잡는 데 한 달쯤 걸렸다.
  처음엔 `VM.Standard.E2.1.Micro`(1GB)에서 돌았고, 거기서 옮겨 왔다.
* Always Free 에서 **2 OCPU / 12GB 가 한도**다. 더 키우려면 유료로 전환해야 한다.
* Oracle 은 사용량이 아주 낮은 Always Free 인스턴스를 회수할 수 있다고 안내한다.
  정확한 기준은 이 문서에서 확인하지 않았다. Oracle 문서를 본다. 지금 이 서버는 부하가
  매우 낮은데(메모리 약 6%) 5주 넘게 문제없이 돌았다.
* 유료라면 Hetzner 같은 곳이 편하다.

---

## 1. 서버 준비

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git rsync iptables-persistent
git clone <이 저장소> ~/jungle-laundry
cd ~/jungle-laundry
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Caddy 는 우분투 기본 저장소에 없다. [Caddy 공식 설치 안내](https://caddyserver.com/docs/install#debian-ubuntu-raspbian)대로
저장소를 추가한 뒤 `sudo apt install caddy` 한다.

**저장소에 없는 것 셋**을 따로 둔다. 서버를 옮길 때 이것을 챙기지 않으면 기능이 조용히 죽는다.

| 파일 | 없으면 |
| --- | --- |
| `.env` | 키가 없어 AI·봇·보관이 안 된다 |
| `vapid_private.pem` | **알림 구독이 전부 무효가 된다** (아래 환경변수 설명 참고) |
| `jungle_kb.py` · `assets/` | 캠퍼스·기숙사 생활 안내와 안내 사진이 안 나온다 |

`jungle_kb.py` 는 내부 자료라 저장소에 없다. 본보기만 있다 (`jungle_kb.example.py`).
**가장 새 판은 서버에만 있다.** 서버에서 따로 백업해 둔다.

### 방화벽

클라우드 방화벽과 인스턴스 방화벽이 **따로** 있다. 둘 다 열어야 한다.

```bash
# 인스턴스 쪽 (우분투 이미지는 기본이 거부다)
sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 2 -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

클라우드 콘솔에서도 443 을 열어준다. Oracle 이면 VCN → 보안 목록.

지금 서버는 이렇다 (밖에서 접속을 시험해 본 값).

| 포트 | 바깥에서 |
| --- | --- |
| 22 (SSH) | 열림 |
| 443 | 열림 |
| 80 | **막혀 있음** |
| 8000 (파이썬) | 막혀 있음 |

80 이 막혀 있어도 HTTPS 는 정상이다. Caddy 가 TLS-ALPN-01(443)로 인증서를 받기 때문이다.
다만 주소창에 `http://` 로 들어오는 사람은 연결이 안 된다.

> **8000 에 대해.** `start_server.py` 는 모든 주소(`0.0.0.0`)로 연다. 바깥에서 막혀 있는 것은
> 인스턴스 방화벽과 클라우드 보안 목록 덕분이다. 그중 하나가 풀리면 Caddy 를 거치지 않고
> 들어올 수 있다. 8000 을 열지 않는다.

---

## 2. 환경변수

`.env` 를 만든다. **깃에 올리지 않는다** (`.gitignore` 에 있다). 이 저장소는 공개다.

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

| Key | 설명 |
| --- | --- |
| `DISCORD_BOT_TOKEN` | 있으면 봇도 함께 뜬다 |
| `RUN_DISCORD_BOT` | `0` 이면 웹만 |
| `ENABLE_MESSAGE_CONTENT` | 멘션 없이 채널 대화 (포털에서 먼저 켤 것) |
| `GEMINI_API_KEY` `..._2` … `..._8` | 여러 개면 막힌 키를 건너뛴다. **봇과 웹이 함께 쓴다** |
| `GROQ_API_KEY` | 제미나이가 늦거나 막혔을 때. 이것도 봇·웹 공용 |
| `UPSTASH_REDIS_REST_URL` / `..._TOKEN` | 알림·설정·제보·통살균 횟수 보관 |
| `STATE_PREFIX` | 보관소 이름표. **한번 정하면 바꾸지 않는다.** 바꾸면 쌓인 기록을 못 찾는다 |
| `TARGET_BASE` | 원본 API 주소. 바뀌면 여기만 고치고 재시작한다 |
| `PORT` | 기본 8000 |
| `SUPPORT_CONTACT` | 문의처. 비우면 번호 없이 안내 |
| `ADMIN_USER_IDS` / `ADMIN_PASSPHRASE` | 관리자 모드. 제보를 DM 으로 받을 사람 |
| `STALE_PICKUP_SEC` | 수거 요청까지 유예 (기본 900초) |
| `ALLOWED_GUILD_IDS` | 비우면 봇이 들어간 모든 서버에서 답한다. 적으면 그 서버에서만 |
| `ASSISTANT_CHANNEL_ID` | 멘션 없이 대화할 채널의 기본값 |
| `SOURCE_STALE_MIN_SEC` | 원본 값이 이만큼 멈추면 `/api/health` 가 503 을 준다 (기본 900초) |
| `DRYER_TUB_CLEAN_MINUTES` | 이 시간(분)보다 긴 건조 코스를 통살균으로 본다 (기본 185) |
| `DRYER_TUB_CLEAN_MAX_MINUTES` | 이보다 긴 것은 통살균으로 보지 않는다 (기본 300) |
| `DRYER_AUTO_CLEAN_OFF` | 자동 통살균 인식을 끌 호기 번호. 예) `3`. 횟수는 계속 센다 |

### 푸시 서명 키 (`vapid_private.pem`)

푸시 알림은 서버의 서명 키로 보낸다. **이 키가 바뀌면 지금까지 받은 구독이 전부 무효가 된다.**
사용자가 알림을 다시 걸어야 한다.

지금 서버는 키를 `.env` 가 아니라 **`vapid_private.pem` 파일**로 쓴다. 파일이 없으면 첫 실행 때
새로 만들어지는데, 그러면 기존 구독이 끊긴다. 서버를 옮길 때는 이 파일을 그대로 복사한다 (권한 600).

파일 대신 환경변수 `VAPID_PRIVATE_KEY_PEM` 에 내용을 통째로 넣어도 된다. 파일 시스템이
재시작마다 지워지는 곳(Render 등)에서는 이쪽이 필수다.

---

## 3. 서비스 등록

서비스 파일은 `deploy/jungle-wash.service` 에 있다. 지금 서버에서 쓰는 것과 같다.

```bash
sudo cp deploy/jungle-wash.service /etc/systemd/system/jungle-wash.service
sudo systemctl daemon-reload
sudo systemctl enable --now jungle-wash
sudo systemctl status jungle-wash
```

사용자·경로(`ubuntu`, `/home/ubuntu/jungle-laundry`)가 다르면 파일에서 고친다.
로그는 `server.log` 에 쌓인다 (journald 가 아니다).

---

## 4. HTTPS (Caddy)

본보기는 `deploy/Caddyfile.example` 이다.

`/etc/caddy/Caddyfile`

```
example.duckdns.org {
	encode gzip zstd
	reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy      # 끊김 없이 반영된다. restart 는 쓰지 않는다
```

인증서는 Caddy 가 알아서 받고 갱신한다. 도메인이 이 서버를 가리키고 있어야 한다.

**도메인(DuckDNS).** 서버에는 DuckDNS 주소를 자동으로 갱신하는 것이 없다. 공인 IP 가 바뀌면
(인스턴스를 새로 만들면 바뀐다) duckdns.org 에서 직접 갱신한다. DuckDNS 는 하위 이름도
같은 IP 로 풀어 준다 (`아무이름.example.duckdns.org`).

> **주의.** Caddy 뒤에 두면 모든 접속이 `127.0.0.1` 로 보인다.
> 제보 도배 방지 같은 것은 `X-Forwarded-For` 를 봐야 한다 (코드는 이미 그렇게 되어 있다).

---

## 5. 감시 (UptimeRobot)

`/api/health` 는 두 가지를 한다.

* 웹이 살아 있으면 `"ok": true` 를 준다. **봇이 죽어도 초록불이다.**
* **원본 값이 오래 멈추면 503 을 준다** (`"ok": false`). 우리 서버는 멀쩡한데 옛날 값을 보여 주고 있는
  상태를 밖에서 알아채려는 것이다. 감시 도구는 2xx 가 아니면 장애로 센다.

그래서 일반 HTTP 감시 대신 **키워드 감시**를 쓴다.

| 항목 | 값 |
| --- | --- |
| Monitor type | `Keyword` |
| URL | `https://<도메인>/api/health` |
| Keyword | `"botOnline": true` |
| Keyword type | `does not exist` 일 때 알림 |
| Case-sensitive | 켬 |

이러면 웹이 죽든, 봇만 끊기든, 원본 값이 멈추든 모두 잡힌다. 서버를 막 켠 직후에는
원본을 아직 못 본 것이라 503 을 주지 않는다.

---

## 갱신

```bash
ssh 서버
cd ~/jungle-laundry
git pull
sudo systemctl restart jungle-wash
```

화면 파일(`app.js` 등)만 바뀌었으면 재시작이 필요 없다. 파이썬 파일이 바뀌었을 때만 한다.

### 재시작 전에 꼭 볼 것: 공지

**봇은 `CHANGELOG.md` 맨 위 버전이 저장된 `announced_version` 과 다르면, 켜질 때 관리자 DM 과
참여 중인 모든 서버에 업데이트 공지를 보낸다.** 보낸 것은 되돌릴 수 없다.
"새 버전이면" 이 아니라 **"다르면"** 이라서, 버전을 되돌려도 공지가 나간다.

재시작하기 전에 둘이 같은지 본다. `.env` 를 읽어야 보관소에 닿는다.

```bash
cd ~/jungle-laundry
set -a; . ./.env; set +a
.venv/bin/python -c "import state_store as S; print(S.state_fetch('announced_version'))"
grep -m1 '^## ' CHANGELOG.md
```

`.env` 없이 확인하면 보관소에 연결되지 않은 채 옛 로컬 파일을 읽어 틀린 답을 얻는다.
다르면 재시작하지 않는다. 공지를 하려는 게 맞을 때만 재시작한다.

---

## 서버를 옮기거나 다시 만들 때

1. **옛 서버를 먼저 멈춘다.** 봇이 두 곳에서 떠 있으면 같은 질문에 답이 두 번 가고 알림이 두 번 간다.
2. 새 서버를 만든다. 위 **1. 서버 준비**대로 패키지·Caddy·저장소를 올린다.
3. 옛 서버에서 가져온다: `.env`, `vapid_private.pem`, `jungle_kb.py`, `assets/`.
   보관소(Upstash)에 있는 알림·설정·통살균 횟수는 `.env` 의 같은 `STATE_PREFIX` 로 이어진다.
4. 서비스(`deploy/jungle-wash.service`)와 Caddy 설정을 넣고 방화벽을 연다 (인스턴스 + 클라우드 둘 다).
5. **DuckDNS 를 새 IP 로 갱신**한다.
6. 위 **공지** 확인을 하고 서비스를 켠다.
7. `curl https://<도메인>/api/health` 로 `"ok": true, "botOnline": true` 를 본다.

---

## 같은 서버에 다른 프로세스를 올릴 때

세탁실이 우선이다. 다른 것이 세탁실을 흔들면 안 된다.

* **별도 사용자**로 돌린다 (`ubuntu` 가 아니라). 세탁실 파일을 못 읽게 된다.
* **자원 상한**을 건다. 지금 `jungle-wash` 와 `caddy` 에는 상한이 없다. 이 서버는 systemd 255 와
  cgroup v2 라서 쓸 수 있다.
* **`127.0.0.1` 에만** 열게 한다. 바깥은 Caddy(443) 하나로 받는다. 새 포트를 열 필요가 없다.
* Caddy 블록을 하나 더 두고 **reload** 한다 (`deploy/Caddyfile.example` 참고).
* 메모리 스왑이 없다. 상한을 넘으면 그 프로세스만 죽고 세탁실은 산다.

서비스 파일 예시 (이 서버에서 시험해 보지 않았다. 올리기 전에 한 번 돌려 본다).

```ini
[Service]
User=relay
MemoryMax=300M
CPUQuota=30%
NoNewPrivileges=true
Restart=always
```

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
| `[Alarm] 지난 사이클 정리` | 내 빨래가 끝났고 다른 사람이 새로 돌려서 알림을 뗐다 |

`[Alarm]` 이 없으면 판정 문제, 있는데 `발송 성공` 이 없으면 전송 문제,
둘 다 있는데 폰에 안 오면 폰 권한이나 iOS 설치 방식 문제다.

### 봇이 안 붙을 때

`429` 가 반복되면 디스코드가 이 IP 를 잠시 막은 것이다. 재시작을 되풀이하면 더 길어진다.
코드가 알아서 간격을 늘려가며 기다리므로 그냥 두면 된다.

`ENABLE_MESSAGE_CONTENT=1` 을 줬는데 포털에서 안 켰으면 접속 자체가 안 된다.
그때는 스스로 그 기능을 끄고 다시 붙어 멘션·DM 은 살린다.

### 숫자가 안 바뀔 때

화면에 **"연결 끊김 · N분 전 데이터"** 로 표시되고, `/api/health` 는 503 을 준다.
원본 서버가 꺼졌거나 터널 주소가 바뀐 것이다. `TARGET_BASE` 를 새 주소로 바꾸고 재시작한다
(재시작 전에 위 **공지** 확인).

### 건조기 통살균이 반영 안 될 때

서버는 건조기 횟수를 **직접 센다.** 기기가 건조기 누적 횟수를 안 알려 준다.
가동 시간이 `DRYER_TUB_CLEAN_MINUTES`(185분)보다 길고 `DRYER_TUB_CLEAN_MAX_MINUTES`(300분)
이하이면 통살균으로 보고 횟수를 0 으로 되돌린다.

* 도중에 오류를 거친 가동은 횟수만 세고 되돌리지 않는다.
* 배수 호스가 고장 나 시간이 부풀어 거짓으로 되돌아가는 호기는 `DRYER_AUTO_CLEAN_OFF` 에 적는다.
  그 호기는 사람이 직접 되돌려야 한다.
* 가동 도중 상태가 바뀐 가동은 `dryer_care` 기록에 그 순서가 남는다 (`runs[].path`).

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
* **이 저장소는 공개다.** 토큰, 키, 서버 IP, 계정 정보를 문서나 커밋에 적지 않는다.
* **원본 서버는 이 프로젝트 소유가 아니다.** 그쪽이 꺼지면 실시간 데이터가 끊긴다.
