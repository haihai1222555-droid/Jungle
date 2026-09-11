import sys
import os
import http.server
import socketserver
import urllib.request
import urllib.error
import urllib.parse
import json
import re
import threading
import state_store
import washtower
import device_log
import security
import cafeteria
import time
from datetime import datetime, timedelta, timezone
import base64

# 로그를 줄 단위로 즉시 내보낸다.
# (출력이 파이프로 갈 때 파이썬이 버퍼링을 해서, Render 로그에 오류가 제때 안 뜬다.
#  알림이 안 갈 때 원인을 볼 수 있어야 하므로 반드시 필요하다.)
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

# Render 등 PaaS 는 실행 포트를 PORT 로 지정해준다. 없으면 로컬 기본값.
# 콘솔이 이모지나 특수문자를 못 찍는 환경(윈도우 cp949 등)에서도
# print 가 UnicodeEncodeError 로 죽지 않게 한다.
# 특히 오류를 알리는 print 가 죽으면 그 스레드가 통째로 멈춘다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

PORT = int(os.environ.get('PORT') or 8000)
TARGET_BASE = os.environ.get('TARGET_BASE') or "https://miracle-beautifully-onto-ser.trycloudflare.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBS_FILE = os.environ.get('SUBS_FILE') or os.path.join(BASE_DIR, 'push_subscriptions.json')

try:
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    from pywebpush import webpush
    HAS_WEBPUSH = True
except Exception as e:
    HAS_WEBPUSH = False
    print(f"[Warn] pywebpush load failed: {e}")

VAPID_PRIV_PATH = os.path.join(BASE_DIR, 'vapid_private.pem')
VAPID_PUB_PATH = os.path.join(BASE_DIR, 'vapid_public.pem')
VAPID_PUBLIC_KEY_B64 = ""

# 환경변수로 VAPID 개인키를 주면 그것을 쓴다.
# (Render 는 파일시스템이 재시작마다 초기화되므로, 파일에만 두면 키가 바뀌어
#  이미 등록된 구독이 전부 무효가 된다. 환경변수로 고정해야 알림이 계속 간다.)
_env_vapid = os.environ.get('VAPID_PRIVATE_KEY_PEM')
if HAS_WEBPUSH and _env_vapid:
    try:
        with open(VAPID_PRIV_PATH, 'w', encoding='utf-8') as f:
            f.write(_env_vapid.replace('\\n', '\n'))
    except Exception as e:
        print(f"[Warn] VAPID env write failed: {e}")

if HAS_WEBPUSH:
    v = Vapid()
    if not os.path.exists(VAPID_PRIV_PATH):
        v.generate_keys()
        v.save_key(VAPID_PRIV_PATH)
        v.save_public_key(VAPID_PUB_PATH)
    else:
        v = Vapid.from_file(VAPID_PRIV_PATH)
    
    raw_pub = v.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    VAPID_PUBLIC_KEY_B64 = base64.urlsafe_b64encode(raw_pub).decode('utf-8').rstrip('=')

CACHED_STATUS = {}
CACHED_STATUS_AT = 0.0     # 마지막으로 받아온 시각

# 원본이 LG 를 마지막으로 확인한 시각. 우리가 얼마나 자주 가져오든
# 값 자체는 이보다 새로울 수 없다. 원본이 /api/health 로 알려준다.
SOURCE_UPDATED_AT = 0.0    # epoch 초. 모르면 0
SOURCE_INTERVAL = ""       # 원본이 말하는 갱신 주기 (예: "300초 (작동 중)")
# 위 문장에서 숫자만 뽑아 둔 것. HTTP 머리말은 latin-1 만 실을 수 있어서
# 한글이 든 문장을 그대로 넣으면 응답이 터진다. 머리말에는 이것을 쓴다.
SOURCE_INTERVAL_SEC = 0
_SOURCE_CHECKED = 0.0
# 미리 만들어 둔 응답 본문. 요청마다 json.dumps 를 다시 도는 것은 낭비다.
# 200명이 동시에 볼 때는 이 직렬화 비용이 그대로 지연으로 나타난다.
CACHED_STATUS_BODY = b'{}'

# 원본 서버로 나가는 요청을 모아 두는 곳.
# 예전에는 /api/stats 가 요청마다 원본으로 나갔다. 200명이면 200번이다.
# 같은 것을 여러 명이 물으면 한 번만 다녀와서 나눠 준다.
# 한 사람이 몰아쳐 두드려 서버를 재우는 것을 막는다.
# 넉넉하게 잡는다. 화면 한 번 열면 파일 열댓 개를 받고, 그 뒤로는
# 10초에 한 번 상태를 물어본다. 1분에 300번이면 사람이 쓰는 방식으로는
# 절대 닿지 않고, 몰아치는 것만 걸린다.
REQ_LIMITER = security.Limiter(300, 60, "요청")
POST_BODY_MAX = 64 * 1024          # 알림 등록 같은 것은 몇 KB 면 충분하다
AI_STREAM_MAX = 4 * 1024 * 1024    # 한 번의 답이 이보다 길 수는 없다

PROXY_CACHE_TTL = {'/api/stats': 60}
_PROXY_CACHE = {}                    # 경로 -> (만료시각, 상태, 헤더, 본문)
_PROXY_FETCH_LOCKS = {}              # 경로 -> Lock (같은 것을 두 번 안 가져오게)
_PROXY_LOCK = threading.Lock()
# 캐시 키에 쿼리 문자열이 들어가므로 그냥 두면 무한정 늘어난다.
# 웹은 공개돼 있어서 ?days=1,2,3... 같은 요청만으로도 메모리가 샌다.
PROXY_CACHE_MAX = 32


def _proxy_evict():
    """오래된 것부터 정리해 캐시가 무한정 늘어나지 않게 한다."""
    if len(_PROXY_CACHE) <= PROXY_CACHE_MAX:
        return
    now = time.time()
    for k in [k for k, v in _PROXY_CACHE.items() if v[0] <= now]:
        _PROXY_CACHE.pop(k, None)
        _PROXY_FETCH_LOCKS.pop(k, None)
    over = len(_PROXY_CACHE) - PROXY_CACHE_MAX
    if over > 0:                       # 그래도 많으면 이른 만료순으로 버린다
        for k, _ in sorted(_PROXY_CACHE.items(), key=lambda kv: kv[1][0])[:over]:
            _PROXY_CACHE.pop(k, None)
            _PROXY_FETCH_LOCKS.pop(k, None)


def _proxy_lock_for(key):
    with _PROXY_LOCK:
        lk = _PROXY_FETCH_LOCKS.get(key)
        if lk is None:
            if len(_PROXY_FETCH_LOCKS) > PROXY_CACHE_MAX * 2:
                _proxy_evict()
            lk = _PROXY_FETCH_LOCKS[key] = threading.Lock()
        return lk
CACHED_STATUS_MAX_AGE = 20  # 이보다 오래된 것은 못 믿고 직접 물어본다

# 이보다 오래된 알림 등록은 지난 빨래로 보고 정리한다 (한 사이클은 길어야 2시간)
MAX_ALARM_AGE_SEC = 4 * 60 * 60
# 기기 값이 이만큼 계속 안 오면 모른다고 알린다.
NODATA_GRACE_SEC = 180

# 세탁이 끝난 뒤 이 시간이 지나도록 기기가 그대로면 '수거 안 함' 으로 보고 한 번 더 알린다.
# 환경변수로 조정할 수 있다 (기본 15분).
STALE_PICKUP_SEC = int(os.environ.get('STALE_PICKUP_SEC') or 15 * 60)

# 가동 중으로 볼 상태들 (완료 후 이 상태가 되면 = 다음 사람이 새로 돌린 것)
RUNNING_STATES = ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING')
# DETECTING(무게 감지 중)은 방금 돌리기 시작한 것이다.
# 이때는 남은 시간이 아직 0 이라 완료로 오해하기 쉽다.
# RESERVED(예약)도 넣는다. 예약 시간이 다 되어 남은 시간이 0 이 되는 순간
# '끝났다' 로 읽히면, 기계가 이제 막 돌기 시작하는데 완료 알림이 나간다.
STARTED_STATES = RUNNING_STATES + ('DETECTING', 'RESERVED')

# 구독 파일에 대한 읽기/쓰기를 직렬화한다 (워커 스레드와 요청 스레드가 동시에 접근)
SUBS_LOCK = threading.Lock()

def load_subscriptions():
    with SUBS_LOCK:
        if not os.path.exists(SUBS_FILE):
            return []
        try:
            with open(SUBS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Subs Load Error] {e}")
            return []

def save_subscriptions(subs):
    with SUBS_LOCK:
        try:
            # 임시파일에 먼저 쓰고 통째로 교체한다.
            # 이렇게 해야 읽는 쪽이 '쓰다 만 파일'을 보지 않는다.
            tmp = SUBS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(subs, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SUBS_FILE)
            # 파일은 Render 재시작 때 사라진다. 바깥에도 남겨 둔다.
            state_store.state_push('push_subscriptions', subs)
        except Exception as e:
            print(f"[Subs Save Error] {e}")

# 다시 살아날 수 없는 구독의 endpoint. 다음 바퀴에서 목록에서 뺀다.
# 여기에 담아두지 않으면 못 쓰는 구독을 5초마다 영영 다시 두드린다.
DEAD_ENDPOINTS = set()
DEAD_ENDPOINTS_MAX = 500          # 이 표시 자체가 새는 일이 없게 상한을 둔다


def send_push_notification(subscription_info, payload_data):
    if not HAS_WEBPUSH or not os.path.exists(VAPID_PRIV_PATH):
        return
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload_data),
            vapid_private_key=VAPID_PRIV_PATH,
            vapid_claims={"sub": "mailto:admin@jungle-laundry.local"}
        )
        print(f"[WebPush] 발송 성공: {payload_data.get('title', '')}")
    except Exception as e:
        # 410/404 는 구독이 사라진 것, 401/403 은 VAPID 열쇠가 안 맞는 것.
        # 어느 쪽이든 다시 보내도 소용없다.
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if code in (401, 403, 404, 410):
            ep = (subscription_info or {}).get('endpoint')
            if ep and len(DEAD_ENDPOINTS) < DEAD_ENDPOINTS_MAX:
                DEAD_ENDPOINTS.add(ep)
            print(f"[WebPush] 못 쓰는 구독({code}) — 목록에서 뺍니다")
        else:
            print(f"[WebPush Error] {e}")

# =========================================================
# 시간대별 혼잡도 관측
# ---------------------------------------------------------
# 5초마다 "돌고 있는 기기 수 / 전체 기기 수" 를 시간별로 쌓는다.
# 주가 바뀌면(= 월요일이 되면) 그 주의 관측치를 확정판으로 올리고 새로 센다.
# =========================================================
KST = timezone(timedelta(hours=9))
CONGESTION_FILE = os.environ.get('CONGESTION_FILE') or os.path.join(BASE_DIR, 'congestion_stats.json')
CONGESTION_SAVE_SEC = 60          # 디스크에는 1분에 한 번만 쓴다
CONGESTION_MIN_SAMPLES = 60       # 시간대별 최소 관측 수 (5초 간격이면 5분치)
CONGESTION_LOCK = threading.Lock()

# 화면에 보여줄 시간대 구간. app.js 와 같은 기준이다.
CONGESTION_SLOTS = [
    ("dawn",       2,  8, "새벽 야간 골든타임", "대기 0명! 야간 코딩러 강력 추천"),
    ("morning",    8, 12, "오전 등교/학습 시간", "등교 전후 여유로운 세탁 가능"),
    ("afternoon", 12, 18, "오후 틈새 타임", "점심/오후 1~2대 대기 없이 사용 가능"),
    ("evening",   18, 21, "저녁 식사/복귀 시간", "식사 후 몰림 시작 (잔여시간 확인)"),
    ("night_peak", 21, 2, "몰입 종료 심야 피크", "코딩 종료 후 샤워&빨래 집중 (대기 필수)"),
]

CONGESTION = {"week": None, "hours": {}, "published": None}
_CONGESTION_SAVED_AT = 0.0


def _week_key(now=None):
    y, w, _ = (now or datetime.now(KST)).isocalendar()
    return "%d-W%02d" % (y, w)


def load_congestion():
    global CONGESTION
    try:
        if os.path.exists(CONGESTION_FILE):
            with open(CONGESTION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and "hours" in data:
                CONGESTION = data
                print("[Congestion] 관측 기록을 불러왔습니다 (%s주차)" % CONGESTION.get("week"))
    except Exception as e:
        print(f"[Congestion Load Error] {e}")


def save_congestion():
    try:
        tmp = CONGESTION_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(CONGESTION, f, ensure_ascii=False)
        os.replace(tmp, CONGESTION_FILE)
        state_store.state_push('congestion_stats', CONGESTION)
    except Exception as e:
        print(f"[Congestion Save Error] {e}")


def record_congestion_sample(status_data):
    """지금 몇 대가 돌고 있는지 한 번 센다. 주가 바뀌면 확정판을 올린다."""
    global _CONGESTION_SAVED_AT
    if not status_data:
        return
    busy = total = 0
    for tower in status_data.values():
        if not isinstance(tower, dict):
            continue
        for unit_type in ("washer", "dryer"):
            unit = tower.get(unit_type)
            if not isinstance(unit, dict):
                continue
            total += 1
            state = unit_state(unit)
            if state in RUNNING_STATES:
                busy += 1
    if not total:
        return

    now = datetime.now(KST)
    week = _week_key(now)
    with CONGESTION_LOCK:
        # 주가 바뀌었다 = 월요일이 되었다 -> 지난 주 관측을 확정판으로 올린다
        if CONGESTION.get("week") != week:
            if CONGESTION.get("hours") and _has_enough(CONGESTION["hours"]):
                CONGESTION["published"] = {
                    "hours": CONGESTION["hours"],
                    "week": CONGESTION.get("week"),
                    "at": now.strftime("%Y-%m-%d"),
                }
                print("[Congestion] %s주차 관측으로 혼잡도를 갱신했습니다" % CONGESTION.get("week"))
            CONGESTION["week"] = week
            CONGESTION["hours"] = {}

        slot = CONGESTION["hours"].setdefault(str(now.hour), {"s": 0, "b": 0})
        slot["s"] += total
        slot["b"] += busy

    if time.time() - _CONGESTION_SAVED_AT >= CONGESTION_SAVE_SEC:
        _CONGESTION_SAVED_AT = time.time()
        save_congestion()


def _has_enough(hours):
    """24시간이 모두 최소 관측 수를 넘겼는지."""
    if not hours:
        return False
    return all((hours.get(str(h)) or {}).get("s", 0) >= CONGESTION_MIN_SAMPLES for h in range(24))


def _rate(hours, start, end):
    """구간의 가동률(%)과 관측된 가동 횟수를 돌려준다."""
    span = range(start, end) if start < end else list(range(start, 24)) + list(range(0, end))
    s = sum((hours.get(str(h)) or {}).get("s", 0) for h in span)
    b = sum((hours.get(str(h)) or {}).get("b", 0) for h in span)
    return (round(b * 100 / s) if s else 0), b


def build_congestion_profile():
    """화면에 보여줄 시간대별 혼잡도를 만든다.

    확정판(지난 주 관측)이 있으면 그것을 쓰고,
    아직 없으면 이번 주에 모은 것을 잠정치로 쓴다.
    둘 다 모자라면 ready=False 로 알려 화면이 기존 추정값을 쓰게 한다.
    """
    with CONGESTION_LOCK:
        pub = CONGESTION.get("published") or {}
        hours, source, at, week = pub.get("hours"), "published", pub.get("at"), pub.get("week")
        if not (hours and _has_enough(hours)):
            hours, source, at, week = CONGESTION.get("hours"), "current", None, CONGESTION.get("week")
        hours = dict(hours or {})

    if not _has_enough(hours):
        return {"ready": False, "source": source, "week": week,
                "slots": [], "totalSamples": sum(v.get("s", 0) for v in hours.values())}

    slots, busy_total = [], 0
    for sid, start, end, label, desc in CONGESTION_SLOTS:
        rate, busy = _rate(hours, start, end)
        busy_total += busy
        slots.append({"id": sid, "startHour": start, "endHour": end,
                      "label": label, "desc": desc, "utilizationRate": rate, "_busy": busy})
    for sl in slots:
        sl["sharePercent"] = round(sl.pop("_busy") * 100 / busy_total) if busy_total else 0
    return {"ready": True, "source": source, "week": week, "publishedAt": at,
            "slots": slots, "totalSamples": sum(v.get("s", 0) for v in hours.values())}


def background_push_worker():
    global CACHED_STATUS, CACHED_STATUS_AT, CACHED_STATUS_BODY
    while True:
        try:
            time.sleep(5)
            try:
                req = urllib.request.Request(f"{TARGET_BASE}/api/status", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as res:
                    CACHED_STATUS = json.loads(res.read().decode('utf-8'))
                    CACHED_STATUS_BODY = json.dumps(
                        CACHED_STATUS, ensure_ascii=False).encode('utf-8')
                    CACHED_STATUS_AT = time.time()
                    record_congestion_sample(CACHED_STATUS)
                    record_device_events(CACHED_STATUS)
            except Exception:
                pass

            # 원본이 언제 갱신했는지 1분에 한 번 물어본다.
            # 매번 물을 이유는 없다. 어차피 원본은 5분에 한 번 움직인다.
            try:
                refresh_source_age()
            except Exception:
                pass

            # 식단은 10분에 한 번만 실제로 나간다 (안에서 시간을 잰다).
            # 기기 상태를 못 받아온 때에도 식단은 확인해야 하므로 밖에 둔다.
            try:
                cafeteria.refresh()
            except Exception as e:
                print(f"[식단] 갱신 중 오류: {e}")

            subs = load_subscriptions()
            if not subs:
                continue

            now_ms = time.time() * 1000
            changed = False
            active_subs = []

            for item in subs:
                sub_info = item.get('subscription')
                alarm = (item.get('alarm') or {})
                if not sub_info or not alarm:
                    continue

                # 이미 못 쓴다고 판명된 구독은 여기서 버린다
                if sub_info.get('endpoint') in DEAD_ENDPOINTS:
                    print(f"[Alarm] 못 쓰는 구독 정리: {alarm.get('deviceName', '?')}")
                    changed = True
                    continue

                # 안전망: 기기가 에러로 멈춰 타이머가 얼어붙으면 완료 판정이 영영 안 나서
                # 구독이 계속 남는다. 그 상태로 다음 사람이 쓰면 엉뚱한 사람에게 알림이 간다.
                # 세탁/건조 한 사이클은 길어야 2시간이므로 그보다 넉넉한 4시간에서 잘라낸다.
                created_at = item.get('createdAt', 0)
                if created_at and (time.time() - created_at) > MAX_ALARM_AGE_SEC:
                    print(f"[Alarm] 오래된 알림 정리: {alarm.get('deviceName', '?')}")
                    changed = True
                    continue

                tower_id = alarm.get('towerId')
                unit_type = alarm.get('unitType')
                device_name = alarm.get('deviceName', '세탁기')
                target_ms = alarm.get('targetMs', 0)

                notified_5min = alarm.get('notified5Min', False)
                notified_0min = alarm.get('notified0Min', False)

                tower_key = f"워시타워_{tower_id}"
                tower_data = (CACHED_STATUS.get(tower_key) or {})
                unit_data = (tower_data.get('dryer' if unit_type == 'dryer' else 'washer') or {})
                run_state = unit_state(unit_data)

                # 실시간 상태를 실제로 받아왔는지 (못 받아온 상태에서 '완료' 로 오판하면 안 된다)
                has_live = bool(unit_data)
                # 남은 시간 0분이 곧 완료는 아니다. 무게 감지(DETECTING) 중에는
                # 시간이 아직 안 잡혀서 0 분으로 온다.
                still_going = has_live and run_state in STARTED_STATES

                # ⭐ 기기가 알려주는 실제 남은 시간을 우선한다.
                #    건조기 옷감 감지로 9분 -> 4분처럼 줄거나, 반대로 늘어나는 경우가 잦은데
                #    등록 시점에 굳힌 targetMs 만 믿으면 알림 시점이 완전히 어긋난다.
                live_min = 0
                if has_live:
                    _t = unit_data.get('timer') or {}
                    live_min = (_t.get('remainHour') or 0) * 60 + (_t.get('remainMinute') or 0)

                # 기기 값이 한참 안 오면 완료로 오판하지 않는다.
                # 점검에 들어간 기기는 원본이 null 로 주는데, 그것을
                # 등록 시점 예상치로 메우면 '완료' 알림이 거짓으로 나간다.
                if not has_live:
                    since = alarm.get('noDataSince')
                    if not since:
                        alarm['noDataSince'] = time.time()
                        changed = True
                    elif (time.time() - since > NODATA_GRACE_SEC
                            and not alarm.get('notifiedNoData')):
                        alarm['notifiedNoData'] = True
                        changed = True
                        send_push_notification(sub_info, {
                            'title': f"\u2753 [확인 불가] {device_name}",
                            'body': (f"{device_name} 완료 여부를 알 수 없습니다. "
                                     "현재 정보가 없습니다. 점검 중이거나 워시타워 상태를 확인해 주세요."),
                            'tag': f"nodata-{device_name}",
                            'key': alarm.get('key'),
                            'endpoint': sub_info.get('endpoint'),
                        })
                    continue

                if alarm.get('noDataSince') or alarm.get('notifiedNoData'):
                    alarm.pop('noDataSince', None)
                    alarm.pop('notifiedNoData', None)
                    changed = True

                # 🚨 기기가 멈췄다. 오류든 일시정지든 알린다.
                #
                # 오류일 때만 알리면 놓친다. 원본이 5분에 한 번만 상태를 주므로
                # 오류가 났다가 일시정지로 넘어가면 오류 화면을 못 보고 지나간다.
                # 실제로 배수 오류로 멈춘 건조기를 아무에게도 못 알린 적이 있다.
                #
                # 그래서 멈춘 것 자체를 알리고, 이유는 단정하지 않는다.
                # 본인이 누른 것이면 넘기면 되고, 아니면 가서 봐야 한다.
                is_error = run_state == 'ERROR' or bool(unit_data.get('error'))
                is_stopped = device_log.is_stopped(run_state, unit_data.get('error'))
                if is_stopped and not alarm.get('notifiedStop'):
                    alarm['notifiedStop'] = True
                    changed = True
                    code = unit_data.get('error')
                    if not isinstance(code, str):
                        code = str(code) if code else None
                    if is_error:
                        detail = (device_log.ERROR_SHORT.get(code, '에러 코드 %s' % code)
                                  if code else '기기가 오류 상태로 보고했습니다')
                        body = ('%s 가 오류로 멈췄습니다 — %s. 세탁실에서 확인해 주세요.'
                                % (device_name, detail))
                    else:
                        body = ('%s 가 멈춰 있습니다. 직접 누르신 것이 아니면 오류일 수 '
                                '있습니다. 기기가 5분에 한 번만 상태를 알려줘서 그 사이에 '
                                '났던 오류는 보이지 않습니다.' % device_name)
                        hit = device_log.recent_error(
                            f"{tower_id}호기", unit_type)
                        if hit:
                            mins = int((time.time() - (hit.get('at') or 0)) / 60)
                            body += (' (%d분 전 같은 기기에서 %s 있었습니다)'
                                     % (mins, device_log.ERROR_SHORT.get(
                                         hit.get('error'), '오류')))
                    print(f"[Alarm] 멈춤: {device_name} ({run_state})")
                    send_push_notification(sub_info, {
                        'title': ("🚨 [오류로 멈춤] " if is_error
                                  else "⏸️ [멈춤] ") + device_name,
                        'body': body,
                        'tag': f"stop-{device_name}",
                        'key': alarm.get('key'),
                        'endpoint': sub_info.get('endpoint'),
                    })
                elif not is_stopped and alarm.get('notifiedStop'):
                    # 다시 돌기 시작했다. 다음에 또 멈추면 다시 알린다.
                    alarm.pop('notifiedStop', None)
                    changed = True

                if live_min > 0:
                    remain_min = float(live_min)
                else:
                    # 기기가 시간을 안 알려주는 구간에서는 등록 시점 예상치로 대체
                    remain_min = (target_ms - now_ms) / (60 * 1000)

                # 멈춰 있는 동안은 시계가 얼어붙는다. 그걸 보고 "5분 뒤 완료" 라고 하면 거짓말이다.
                if (not notified_5min and not is_stopped
                        and remain_min <= 5.0 and remain_min > 0):
                    alarm['notified5Min'] = True
                    changed = True
                    print(f"[Alarm] 5분전 조건 충족: {device_name} (실시간 {live_min}분 / 판정 {remain_min:.1f}분)")
                    send_push_notification(sub_info, {
                        'title': f"🧺 [선택 기기 알림] {device_name} 5분 전!",
                        'body': f"회원님이 등록하신 {device_name} 가동이 약 5분 뒤 완료됩니다. 세탁실로 이동해 주세요!",
                        'tag': f"5min-{device_name}",
                        # 바로 가져갈 사람은 눌러두면 수거 요청을 보내지 않는다
                        'actions': [{'action': 'picked', 'title': '🧺 가져갈게요'}],
                        'key': alarm.get('key'),
                        'endpoint': sub_info.get('endpoint'),
                    })

                elif not notified_0min and not still_going and not is_stopped and (
                    remain_min <= 0
                    or (has_live and run_state in ('END', 'COMPLETE', 'WRINKLE_CARE', 'POWER_OFF', 'INITIAL'))
                ):
                    alarm['notified0Min'] = True
                    alarm['completedAt'] = time.time()
                    changed = True
                    print(f"[Alarm] 완료: {device_name}")
                    send_push_notification(sub_info, {
                        'title': f"🏁 [선택 기기 완료] {device_name} 완료!",
                        'body': f"회원님이 등록하신 {device_name} 가동이 끝났습니다. 세탁실에서 빨래를 즉시 수거해 주세요!",
                        'tag': f"complete-{device_name}",
                        'actions': ([] if alarm.get('pickedUp')
                                    else [{'action': 'picked', 'title': '🧺 가져갔어요'}]),
                        'key': alarm.get('key'),
                        'endpoint': sub_info.get('endpoint'),
                    })
                    # 여기서 구독을 버리지 않는다. 빨래를 실제로 가져갔는지 계속 지켜본다.
                    active_subs.append(item)
                    continue

                # ── 완료 알림을 이미 보낸 뒤: 수거했는지 감시하는 구간 ──
                if notified_0min:
                    # 기기가 다시 돌기 시작했다 = 누군가 꺼내고 새로 돌렸다는 뜻 → 감시 종료
                    if has_live and run_state in RUNNING_STATES:
                        changed = True
                        continue

                    if alarm.get('notifiedStale'):
                        # 방치 알림까지 보냈으면 더 할 일이 없다
                        changed = True
                        continue

                    # 본인이 '가져갔어요' 를 눌렀으면 수거 요청을 보내지 않는다
                    if alarm.get('pickedUp'):
                        print(f"[Alarm] 수거 확인됨: {device_name}")
                        changed = True
                        continue

                    completed_at = alarm.get('completedAt') or 0
                    if not completed_at:
                        # 이 기능 이전에 등록된 알림은 기준 시각이 없으므로 지금부터 센다
                        alarm['completedAt'] = time.time()
                        changed = True
                        active_subs.append(item)
                        continue

                    waited = time.time() - completed_at
                    if waited >= STALE_PICKUP_SEC:
                        alarm['notifiedStale'] = True
                        changed = True
                        mins = int(waited // 60)
                        print(f"[Alarm] 방치 감지: {device_name} (완료 후 {mins}분 경과)")
                        send_push_notification(sub_info, {
                            'title': f"🚨 [수거 요청] {device_name} 빨래가 그대로 있어요",
                            'body': f"{device_name} 가동이 끝난 지 {mins}분이 지났습니다. 다음 정글러를 위해 빨래를 수거해 주세요!",
                            'tag': f"stale-{device_name}"
                        })
                        continue

                    # 아직 유예 시간 안 - 계속 지켜본다
                    active_subs.append(item)
                    continue

                active_subs.append(item)

            if changed:
                save_subscriptions(active_subs)
        except Exception as e:
            print(f"[Worker Error] {e}")

# =========================================================
# 웹으로 내줄 파일 (이 목록에 없으면 안 내준다)
# ---------------------------------------------------------
# 예전에는 폴더를 통째로 내주고 있었다. 그래서 .env(봇 토큰·API 키),
# vapid_private.pem(푸시 개인키), server.log, reports.json,
# 소스 코드까지 아무나 주소만 치면 받아 갈 수 있었다.
#
# 거부 목록으로 막으면 새 파일이 생길 때마다 빠뜨린다.
# 실제로 기기 이력 파일을 새로 만들면서 아무도 그 생각을 안 했다.
# 그래서 허용 목록으로 뒤집는다. 새 파일은 기본이 '안 내줌' 이다.
# =========================================================
PUBLIC_FILES = {
    "/", "/index.html", "/privacy.html", "/terms.html",
    "/app.js", "/style.css", "/doc.css", "/doc.js",
    "/sw.js",                 # 서비스 워커 (웹 푸시)
    "/manifest.json",         # 앱처럼 설치할 때 쓰는 것
    # /jungle_kb.js 는 더 이상 내주지 않는다.
    # 브라우저가 프롬프트를 만들 때 필요했지만, 이제 서버가 끼워 넣는다.
    # 그 안에는 출결·외출·공가 같은 기관 내부 안내가 들어 있다.
    "/favicon.ico",
}

# 그림은 파일이 계속 늘어나므로 확장자로 연다.
PUBLIC_DIRS = ("/assets/",)
PUBLIC_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg", ".ico")


def is_public_path(req_path):
    """이 주소를 웹으로 내줘도 되는지."""
    if req_path in PUBLIC_FILES:
        return True
    # 위로 거슬러 올라가는 주소는 무조건 막는다
    if ".." in req_path:
        return False
    if req_path.lower().endswith(PUBLIC_EXTS):
        # 그림은 최상위나 assets/ 아래만
        rest = req_path.lstrip("/")
        return "/" not in rest or req_path.startswith(PUBLIC_DIRS)
    return False


class RobustHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # 매번 서버에 물어봐야 하는 것 / 오래 담아 둬도 되는 것
    REVALIDATE_EXT = ('.html', '.js', '.css', '.json', '.webmanifest')
    LONG_CACHE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg',
                      '.ico', '.ttf', '.woff', '.woff2')

    def _cache_header_for(self, path):
        """이 파일을 얼마나 담아 둬도 되는지 정한다.

        Cache-Control 이 없으면 브라우저가 스스로 기간을 정해 버린다.
        그래서 코드를 고쳐 올려도 사용자는 한참 옛 것을 쓰게 된다.
        화면을 이루는 파일은 매번 확인시키고(no-cache 는 '쓰지 마'가 아니라
        '쓰기 전에 물어봐'라는 뜻이다), 그림·글꼴은 오래 담아 둔다.
        """
        p = (path or '').split('?')[0].lower()
        if p.endswith(self.LONG_CACHE_EXT):
            return 'public, max-age=604800'          # 일주일
        if p.endswith(self.REVALIDATE_EXT) or p.endswith('/'):
            return 'no-cache'
        return None

    def _allowed_origin(self):
        """이 요청에 응답을 읽도록 허락해도 되는 곳인지.

        예전에는 모든 응답에 '*' 를 붙였다. 아무 사이트나 자기 페이지에서
        우리 AI 중계를 불러 우리 키를 태울 수 있었고, 우리 API 도 마음대로
        읽어 갈 수 있었다.

        우리 페이지는 같은 주소에서 열리므로 이 헤더가 아예 없어도 된다.
        그래서 좁혀도 화면은 그대로 돈다.
        """
        hdrs = getattr(self, 'headers', None)
        origin = hdrs.get('Origin') if hdrs else None
        if not origin:
            return None
        if security.origin_ok(origin, None, hdrs.get('Host')) is True:
            return origin
        return None

    def end_headers(self):
        who = self._allowed_origin()
        if who:
            self.send_header('Access-Control-Allow-Origin', who)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # 같은 주소라도 Origin 에 따라 응답이 달라지므로 중간 저장소에 알린다
        self.send_header('Vary', 'Origin')
        for k, v in security.HEADERS:
            self.send_header(k, v)
        if not self._has_cache_header:
            cc = self._cache_header_for(getattr(self, 'path', ''))
            if cc:
                self.send_header('Cache-Control', cc)
        super().end_headers()

    _has_cache_header = False

    def send_header(self, keyword, value):
        if keyword.lower() == 'cache-control':
            self._has_cache_header = True
        super().send_header(keyword, value)

    def handle_one_request(self):
        self._has_cache_header = False     # 요청마다 새로 판단한다
        super().handle_one_request()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_HEAD(self):
        req_path = self.path.split('?')[0]
        # HEAD 로도 새면 안 된다. 크기만 알려줘도 있다는 것이 드러난다.
        if not req_path.startswith('/api/') and not is_public_path(req_path):
            self.send_response(404)
            self.end_headers()
            return
        if req_path in ('/api/health', '/api/status', '/api/stats', '/'):
            self.send_response(200)
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self):
        if not self._rate_ok():
            return
        req_path = self.path.split('?')[0]

        # /api/ 로 시작하지 않는 것은 파일 요청이다.
        # 허용 목록에 없으면 있는지 없는지도 알려주지 않고 404 로 끝낸다.
        if not req_path.startswith('/api/') and not is_public_path(req_path):
            print(f"[차단] 공개 대상이 아닌 파일 요청: {req_path}")
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('Not Found'.encode('utf-8'))
            return
        # UptimeRobot 등이 주기적으로 두드려 서비스가 잠들지 않게 하는 용도
        if req_path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "webpush": HAS_WEBPUSH,
                "alarms": len(load_subscriptions()),
                "store": state_store.store_enabled(),
                # 나가면 안 되는 파일이 나가고 있지 않은지. 밖에서도 보이게 둔다.
                "exposure": EXPOSURE_STATUS,
                # 원본이 LG 를 마지막으로 본 지 몇 초 됐는지.
                # 우리가 아무리 자주 가져와도 값은 이보다 새로울 수 없다.
                "sourceAgeSec": source_age_sec(),
                "sourceInterval": SOURCE_INTERVAL,
                **discord_bot_health(),
            }, ensure_ascii=False).encode('utf-8'))
            return

        if req_path == '/api/congestion':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(build_congestion_profile(), ensure_ascii=False).encode('utf-8'))
            return

        # 브라우저는 키를 받지 않는다. '몇 개나 있는지' 만 알면
        # 지금처럼 막힌 키를 건너뛰며 차례로 시도할 수 있다.
        # 이 기기에 어떤 코스가 있는지. 목록은 washtower.py 한곳에만 있다.
        # (지금 무슨 코스로 도는지는 원본 API 가 주지 않아 알 수 없다)
        # 식단표와 오늘 메뉴. 사진 주소는 카카오 것을 그대로 준다
        # (우리가 다시 올리지 않는다. 저쪽이 고치면 같이 바뀌는 편이 맞다)
        if req_path == '/api/menu':
            data = cafeteria.state() or {}
            self._json_out(200, {
                "weekly": data.get("weekly"),
                "today": cafeteria.today_menus(),
                "updatedLabel": cafeteria.fmt_when(
                    (data.get("weekly") or {}).get("updatedAt")),
            })
            return

        if req_path == '/api/courses':
            self._json_out(200, washtower.as_dict())
            return

        if req_path == '/api/ai/config':
            self._json_out(200, {
                "gemini": len(AI_GEMINI_KEYS),
                "groq": bool(AI_GROQ_KEY),
            })
            return

        if req_path == '/api/vapid-public-key':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"publicKey": VAPID_PUBLIC_KEY_B64}).encode('utf-8'))
            return

        # 배경 작업이 5초마다 받아둔 것을 그대로 돌려준다.
        # 매번 터널까지 다시 다녀오면 느리고, 그쪽이 늦으면 통째로 실패했다.
        if req_path == '/api/status' and CACHED_STATUS:
            # 나이와 상관없이 캐시를 준다. 워커가 5초마다 새로 받아 두기 때문에
            # 여기서 원본을 기다리면 200명이 동시에 200번 나가게 된다.
            age = int(time.time() - CACHED_STATUS_AT)
            body = CACHED_STATUS_BODY
            self.send_response(200)
            # 값이 실제로 몇 초 묵었는지. 본문 모양은 그대로 두고 머리말로 보낸다
            # (본문은 원본이 준 것 그대로여야 다른 코드가 안 깨진다).
            # X-Cache-Age 는 '우리가 받아온 지' 이고, 이것은 '원본이 LG 를 본 지' 다.
            # 우리가 아무리 자주 가져와도 값은 이보다 새로울 수 없다.
            # 머리말에는 숫자만 넣는다. HTTP 머리말은 latin-1 만 실을 수 있어서
            # "300초 (작동 중)" 같은 한글을 그대로 넣으면 응답이 통째로 터진다.
            # 실제로 그렇게 해서 /api/status 가 전부 502 가 됐다.
            _src = source_age_sec()
            if _src is not None:
                self.send_header('X-Source-Age', str(_src))
            if SOURCE_INTERVAL_SEC:
                self.send_header('X-Source-Interval', str(SOURCE_INTERVAL_SEC))
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Cache-Age', str(age))
            if age > CACHED_STATUS_MAX_AGE:
                self.send_header('X-Cache-Stale', '1')
            self.end_headers()
            self.wfile.write(body)
            return

        if req_path.startswith('/api/'):
            # 원본으로 넘기는 것은 정해진 주소뿐이다.
            # 예전에는 /api/ 로 시작하면 무엇이든 넘겼다. 우리 서버가 남의
            # 심부름꾼이 되는 길이었고, 원본(무료 터널)이 그 트래픽 때문에
            # 막히면 우리 화면도 같이 죽는다.
            if not security.proxy_path_ok(self.path):
                print(f"[차단] 넘기지 않는 주소: {req_path}")
                self._json_out(404, {"error": "not found"})
                return
            target_url = TARGET_BASE + self.path
            ttl = PROXY_CACHE_TTL.get(req_path)
            if ttl:
                cached = _PROXY_CACHE.get(self.path)
                if cached and cached[0] > time.time():
                    _, st, hdrs, content = cached
                    self.send_response(st)
                    for k, v in hdrs:
                        self.send_header(k, v)
                    self.send_header('Content-Length', str(len(content)))
                    self.send_header('X-Proxy-Cache', 'HIT')
                    self.end_headers()
                    self.wfile.write(content)
                    return
                # 캐시가 없으면 한 명만 다녀오고 나머지는 그 결과를 쓴다
                lk = _proxy_lock_for(self.path)
                with lk:
                    cached = _PROXY_CACHE.get(self.path)
                    if cached and cached[0] > time.time():
                        _, st, hdrs, content = cached
                        self.send_response(st)
                        for k, v in hdrs:
                            self.send_header(k, v)
                        self.send_header('Content-Length', str(len(content)))
                        self.send_header('X-Proxy-Cache', 'HIT')
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    try:
                        req = urllib.request.Request(
                            target_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=6) as response:
                            # 상대가 고장 나 끝없이 보내면 우리 기억이 먼저 찬다
                            content = security.read_capped(response)
                            # 원본이 붙인 CORS 헤더는 걷어낸다. 우리 것과 겹치면
                            # 브라우저가 둘 다 무시해 화면이 빈다.
                            hdrs = [(k, v) for k, v in response.headers.items()
                                    if k.lower() not in ('transfer-encoding',
                                                         'content-length',
                                                         'content-encoding')
                                    and not k.lower().startswith('access-control-')]
                            _PROXY_CACHE[self.path] = (time.time() + ttl,
                                                       response.status, hdrs, content)
                            with _PROXY_LOCK:
                                _proxy_evict()
                            self.send_response(response.status)
                            for k, v in hdrs:
                                self.send_header(k, v)
                            self.send_header('Content-Length', str(len(content)))
                            self.send_header('X-Proxy-Cache', 'MISS')
                            self.end_headers()
                            self.wfile.write(content)
                            return
                    except Exception as e:
                        stale = _PROXY_CACHE.get(self.path)
                        if stale:      # 원본이 죽어도 옛 값이라도 준다
                            _, st, hdrs, content = stale
                            self.send_response(st)
                            for k, v in hdrs:
                                self.send_header(k, v)
                            self.send_header('Content-Length', str(len(content)))
                            self.send_header('X-Proxy-Cache', 'STALE')
                            self.end_headers()
                            self.wfile.write(content)
                            return
                        print(f"[Proxy] {req_path} 실패: {e}")
                        self.send_response(502)
                        self.send_header('Content-Type',
                                         'application/json; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(b'{"error":"upstream"}')
                        return
            try:
                req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=6) as response:
                    content = security.read_capped(response)
                    self.send_response(response.status)
                    for k, v in response.headers.items():
                        if (k.lower() not in ['transfer-encoding', 'content-length', 'content-encoding']
                                and not k.lower().startswith('access-control-')):
                            self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(content)
                    return
            except Exception as e:
                # 터널이 잠깐 죽어도 502 를 던지기보다, 마지막으로 받아둔 값을
                # 나이와 함께 돌려준다. 화면은 그 나이를 보고 "N분 전" 이라 알린다.
                if req_path == '/api/status' and CACHED_STATUS:
                    age = int(time.time() - CACHED_STATUS_AT)
                    print(f"[Proxy] 실패 — {age}초 전 데이터로 대신 응답: {e}")
                    body = json.dumps(CACHED_STATUS, ensure_ascii=False).encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('X-Cache-Age', str(age))
                    self.send_header('X-Cache-Stale', '1')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                # 실패한 까닭을 그대로 내보내면 우리 안쪽 주소와 구조가 딸려 나간다.
                # 자세한 것은 로그에만 남긴다.
                print(f"[Proxy] {req_path} 실패: {e}")
                self.send_response(502)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'{"error":"upstream"}')
                return

        return super().do_GET()

    def _client_key(self):
        """요청을 보낸 사람을 구분할 값.

        Caddy 를 거치면 출발지가 늘 127.0.0.1 이라, 그대로 쓰면
        한 사람이 제보한 뒤 30초 동안 모두가 막힌다.
        Caddy 가 붙여 주는 X-Forwarded-For 의 맨 앞이 진짜 사용자다.
        """
        # 맨 앞은 보낸 사람이 제 손으로 적을 수 있다. Caddy 가 실제로 본
        # 주소는 맨 뒤에 붙는다. 자세한 것은 security.real_ip 에 적어 뒀다.
        peer = self.client_address[0] if self.client_address else '?'
        return security.real_ip(peer, self.headers.get('X-Forwarded-For'))

    def _rate_ok(self):
        """몰아쳐 두드리는 것을 막는다. 걸리면 여기서 응답까지 끝낸다.

        같은 기계에서 부르는 것(우리 봇)은 세지 않는다. 그것까지 세면
        봇이 먼저 멈춘다.
        """
        peer = self.client_address[0] if self.client_address else ''
        if security.is_local(peer) and not self.headers.get('X-Forwarded-For'):
            return True
        if REQ_LIMITER.allow(self._client_key()):
            return True
        self.send_response(429)
        self.send_header('Retry-After', '30')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'{"error":"too many requests"}')
        return False

    def _origin_not_ours(self):
        """남의 사이트에서 온 요청인지.

        브라우저는 POST 에 Origin 을 반드시 붙인다. 그래서 다른 사이트가
        우리 AI 중계나 제보를 제 것처럼 쓰는 것은 여기서 걸린다.
        헤더가 아예 없는 것(브라우저가 아닌 것)은 막지 않는다. 우리 봇이
        그렇게 부르기 때문이다. 그쪽은 횟수 제한으로 다룬다.
        """
        return security.origin_ok(self.headers.get('Origin'),
                                  self.headers.get('Referer'),
                                  self.headers.get('Host')) is False

    def _read_body(self, limit):
        """요청 본문을 바이트로 읽는다. 너무 크거나 형식이 틀리면 None.

        Content-Length 만 보면 안 된다. 브라우저가 HTTP/2 로 들어오면
        Caddy 는 그 헤더 없이 조각내어(chunked) 넘기기 때문이다.
        그때 길이가 0 으로 읽혀 본문이 통째로 사라졌다.
        """
        if 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
            buf = b''
            while True:
                line = self.rfile.readline(1024).strip()
                if not line:
                    return None
                try:
                    size = int(line.split(b';')[0], 16)
                except ValueError:
                    return None
                if size == 0:
                    self.rfile.readline(1024)      # 끝을 알리는 빈 줄
                    return buf
                if len(buf) + size > limit:
                    return None
                buf += self.rfile.read(size)
                self.rfile.read(2)                 # 조각 끝의 줄바꿈
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > limit:
            return None
        return self.rfile.read(n)

    def _read_json(self, limit=8000):
        """요청 본문을 JSON 으로 읽는다. 형식이 틀리면 None."""
        try:
            raw = self._read_body(limit)
            return json.loads(raw.decode('utf-8')) if raw else None
        except Exception:
            return None

    def _json_out(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ai_relay(self, url, body, headers):
        """AI 서버에 대신 물어보고, 오는 대로 브라우저에 흘려보낸다.

        받은 것을 모아뒀다 한꺼번에 주면 글자가 한 자씩 나타나는
        지금 모습이 사라진다. 그래서 조각이 오는 즉시 내보낸다.

        실패했을 때의 상태 코드(429·401·403 …)도 그대로 넘긴다.
        브라우저가 그 값을 보고 다음 키로 넘어가기 때문이다.
        """
        req = urllib.request.Request(
            url, data=json.dumps(body).encode('utf-8'), headers=headers)
        try:
            up = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', 'replace')[:300]
            except Exception:
                pass
            print(f"[웹AI] {e.code} {detail}")
            self._json_out(e.code, {"error": f"HTTP {e.code}"})
            return
        except Exception as e:
            print(f"[웹AI] 연결 실패: {e}")
            self._json_out(502, {"error": str(e)})
            return

        self.send_response(200)
        self.send_header('Content-Type',
                         up.headers.get('Content-Type') or 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        # 상대가 끝없이 보내면 계속 흘려보내게 된다. 한 번의 답으로
        # 있을 수 없는 크기에서 끊는다.
        sent = 0
        try:
            while True:
                chunk = up.read(1024)
                if not chunk:
                    break
                sent += len(chunk)
                if sent > AI_STREAM_MAX:
                    print(f"[웹AI] 응답이 너무 깁니다 ({sent}바이트). 끊습니다.")
                    break
                self.wfile.write(chunk)
        except Exception:
            # 브라우저가 먼저 끊은 것. 흔한 일이라 조용히 넘어간다.
            pass
        finally:
            try:
                up.close()
            except Exception:
                pass

    def _ai_precheck(self):
        """중계해도 되는 요청인지 본다. 되면 (본문, None), 아니면 (None, 이유)."""
        if not ai_allowed(self._client_key()):
            return None, (429, "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
        data = self._read_json(limit=AI_BODY_MAX)
        if not isinstance(data, dict) or not isinstance(data.get('body'), dict):
            return None, (400, "형식이 올바르지 않습니다.")
        return data, None

    def do_POST(self):
        if not self._rate_ok():
            return
        if self._origin_not_ours():
            print(f"[차단] 남의 사이트에서 온 요청: {self.headers.get('Origin')}")
            self._json_out(403, {"error": "허용되지 않은 요청입니다."})
            return
        _p = self.path.split('?')[0]

        # ── 제미나이 중계 ──
        # 브라우저가 보내는 것: {"model": 모델, "keyIndex": 몇 번째 키, "body": 요청}
        # 키는 서버가 붙인다.
        if _p == '/api/ai/gemini':
            data, bad = self._ai_precheck()
            if bad:
                self._json_out(bad[0], {"error": bad[1]})
                return
            model = str(data.get('model') or '')
            idx = data.get('keyIndex')
            if not AI_MODEL_OK.match(model):
                self._json_out(400, {"error": "모델 이름이 올바르지 않습니다."})
                return
            if not isinstance(idx, int) or not (0 <= idx < len(AI_GEMINI_KEYS)):
                self._json_out(503, {"error": "쓸 수 있는 키가 없습니다."})
                return
            body = data['body']
            # 안내 지식은 브라우저에 없다. 여기서 끼워 넣는다.
            body = fill_kb(body, last_user_text(body))
            ai_clamp_tokens(body)
            self._ai_relay(
                'https://generativelanguage.googleapis.com/v1beta/models/'
                f'{model}:streamGenerateContent?alt=sse'
                f'&key={urllib.parse.quote(AI_GEMINI_KEYS[idx])}',
                body, {'Content-Type': 'application/json'})
            return

        # ── Groq 중계 (제미나이가 막혔을 때 쓰는 예비 엔진) ──
        if _p == '/api/ai/groq':
            data, bad = self._ai_precheck()
            if bad:
                self._json_out(bad[0], {"error": bad[1]})
                return
            if not AI_GROQ_KEY:
                self._json_out(503, {"error": "쓸 수 있는 키가 없습니다."})
                return
            body = data['body']
            if not AI_MODEL_OK.match(str(body.get('model') or '')):
                self._json_out(400, {"error": "모델 이름이 올바르지 않습니다."})
                return
            # Groq 은 요청 크기 제한이 빡빡하다. 질문에 걸리는 항목만 넣는다.
            body = fill_kb(body, last_user_text(body), limit=4)
            ai_clamp_tokens(body)
            self._ai_relay(
                'https://api.groq.com/openai/v1/chat/completions', body,
                {'Content-Type': 'application/json',
                 'Authorization': f'Bearer {AI_GROQ_KEY}',
                 # 이 헤더가 없으면 Cloudflare 가 막는다 (403 error code 1010)
                 'User-Agent': 'JungleWash/1.0'})
            return

        if _p == '/api/report':
            data = self._read_json()
            if not isinstance(data, dict):
                self._json_out(400, {"ok": False, "error": "형식이 올바르지 않습니다."})
                return
            text = str(data.get('text') or '').strip()[:REPORT_MAX_LEN]
            kind = 'idea' if data.get('kind') == 'idea' else 'bug'
            if len(text) < 5:
                self._json_out(400, {"ok": False,
                                     "error": "조금 더 자세히 적어주세요. (5자 이상)"})
                return
            who = self._client_key()
            if not report_allowed(who):
                self._json_out(429, {"ok": False,
                                     "error": "방금 보내셨어요. 잠시 후 다시 시도해 주세요."})
                return
            if DISCORD_MODULE is None:
                self._json_out(503, {"ok": False,
                                     "error": "지금은 접수할 수 없어요. 잠시 후 다시 시도해 주세요."})
                return
            try:
                item = DISCORD_MODULE.submit_report(kind, text, 'web')
            except Exception as e:
                print(f"[제보] 접수 실패: {e}")
                item = None
            if not item:
                self._json_out(500, {"ok": False, "error": "접수하지 못했습니다."})
                return
            print(f"[제보] 웹에서 접수 #{item['id']} ({item['kind']})")
            self._json_out(200, {"ok": True, "id": item['id']})
            return

        req_path = self.path.split('?')[0]
        # 상한을 안 두면 보낸 만큼 다 읽는다. 큰 것 몇 개면 서버가 눕는다.
        # 본문이 비어 있는 것은 원래 되던 것이라 그대로 둔다(해제 요청 등).
        try:
            declared = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            declared = -1
        if declared < 0 or declared > POST_BODY_MAX:
            self._json_out(413, {"error": "요청이 너무 큽니다."})
            return
        post_data = self._read_body(POST_BODY_MAX) or b''

        if req_path == '/api/subscribe-push':
            try:
                data = json.loads(post_data.decode('utf-8'))
                sub_info = data.get('subscription')
                alarm_info = data.get('alarm')
                if sub_info and alarm_info:
                    subs = load_subscriptions()
                    key = alarm_info.get('key')
                    endpoint = sub_info.get('endpoint')
                    # 중복 판정은 (구독 기기 + 세탁기) 조합으로 한다.
                    # 세탁기 키만 보면, 같은 세탁기를 폰과 컴퓨터에서 각각 등록했을 때
                    # 나중에 등록한 기기가 먼저 등록한 기기의 구독을 지워버린다.
                    subs = [x for x in subs
                            if not ((x.get('alarm') or {}).get('key') == key
                                    and (x.get('subscription') or {}).get('endpoint') == endpoint)]
                    subs.append({'subscription': sub_info, 'alarm': alarm_info, 'createdAt': time.time()})
                    save_subscriptions(subs)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if req_path == '/api/picked-up':
            # 알림의 '가져갔어요' 버튼을 누르면 서비스워커가 여기로 알려준다.
            # 기기가 문 열림을 알려주지 않으므로 수거 여부는 이 신호로만 알 수 있다.
            try:
                data = json.loads(post_data.decode('utf-8')) if post_data else {}
                key = data.get('key')
                endpoint = data.get('endpoint')
                marked = 0
                if key and endpoint:
                    subs = load_subscriptions()
                    for x in subs:
                        if ((x.get('alarm') or {}).get('key') == key
                                and (x.get('subscription') or {}).get('endpoint') == endpoint):
                            x['alarm']['pickedUp'] = True
                            marked += 1
                    if marked:
                        save_subscriptions(subs)
                        print(f"[Alarm] 수거 확인 접수: {key}")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "marked": marked}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if req_path == '/api/test-push':
            # 빨래가 끝날 때까지 기다리지 않고 '알림이 실제로 폰에 도착하는지'만
            # 즉시 확인하기 위한 경로. 이미 등록된 구독에만 보내므로 아무나
            # 임의의 기기로 알림을 보낼 수는 없다.
            try:
                data = json.loads(post_data.decode('utf-8')) if post_data else {}
                key = data.get('key')
                subs = load_subscriptions()
                targets = [x for x in subs
                           if not key or (x.get('alarm') or {}).get('key') == key]

                sent = 0
                for x in targets:
                    device = (x.get('alarm') or {}).get('deviceName', '기기')
                    send_push_notification(x.get('subscription'), {
                        'title': f"🧪 [테스트] {device} 알림 도착",
                        'body': "이 알림이 보이면 전달 경로가 정상입니다. 실제 5분 전 알림도 같은 방식으로 옵니다.",
                        'tag': f"jungle-test-{int(time.time())}"
                    })
                    sent += 1

                print(f"[TestPush] {sent}개 구독으로 발송 시도 (전체 등록 {len(subs)}개)")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "sent": sent, "registered": len(subs),
                    "devices": [(x.get('alarm') or {}).get('deviceName') for x in targets]
                }, ensure_ascii=False).encode('utf-8'))
                return
            except Exception as e:
                print(f"[TestPush Error] {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        if req_path == '/api/unsubscribe-push':
            try:
                data = json.loads(post_data.decode('utf-8'))
                key = data.get('key')
                endpoint = data.get('endpoint')
                if key:
                    subs = load_subscriptions()
                    if endpoint:
                        # 해제를 요청한 그 기기의 등록만 지운다
                        subs = [x for x in subs
                                if not ((x.get('alarm') or {}).get('key') == key
                                        and (x.get('subscription') or {}).get('endpoint') == endpoint)]
                    else:
                        subs = [x for x in subs if (x.get('alarm') or {}).get('key') != key]
                    save_subscriptions(subs)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        self.send_response(404)
        self.end_headers()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

DISCORD_MODULE = None   # 봇을 띄웠으면 그 모듈. 상태를 물어보는 데 쓴다.

# 제보가 쏟아지는 것을 막는다. 같은 사람이 연달아 여러 번 보내지 못하게.
REPORT_MIN_GAP = 30          # 초
REPORT_MAX_LEN = 1000
_REPORT_LAST = {}            # 보낸 곳 -> 마지막 시각
_REPORT_LOCK = threading.Lock()


# =========================================================
# 웹 AI 중계
# ---------------------------------------------------------
# 키는 여기(서버)에만 있고 브라우저로는 절대 내려가지 않는다.
# .env 의 적는 방식은 봇과 같다:
#   GEMINI_API_KEY=키1,키2      (쉼표로 여러 개)
#   GEMINI_API_KEY_2=키3        (따로따로도 된다)
#   GROQ_API_KEY=키
# =========================================================
def _load_ai_gemini_keys():
    """봇과 같은 방식으로 제미나이 키를 모은다.

    봇 모듈을 import 하지 않는다. RUN_DISCORD_BOT=0 으로 웹만 띄우는
    경우에도 AI 가 동작해야 하기 때문이다.
    """
    keys, seen = [], set()
    raw = [os.environ.get("GEMINI_API_KEY") or "",
           os.environ.get("GEMINI_API_KEYS") or ""]
    for i in range(2, 9):
        raw.append(os.environ.get(f"GEMINI_API_KEY_{i}") or "")
    for chunk in raw:
        for k in chunk.split(","):
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


AI_GEMINI_KEYS = _load_ai_gemini_keys()
AI_GROQ_KEY = (os.environ.get("GROQ_API_KEY") or "").strip()

# 모델 이름은 브라우저가 정해서 보낸다. 그대로 주소에 넣으므로
# 이상한 글자가 섞이지 못하게 막는다(주소 조작 방지).
AI_MODEL_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,60}$')

# 한 사람이 계속 두드려 하루 한도를 혼자 태우지 못하게 한다.
# 채팅창은 원래부터 누구나 쓸 수 있으니 새로 열리는 문은 없다.
# 다만 사람이 손으로 쓰는 속도를 넘는 것만 걸러낸다.
AI_RATE_WINDOW = 300           # 초
AI_RATE_BURST = 30             # 5분에 30번
AI_RATE_DAY = 300              # 하루 300번
AI_BODY_MAX = 200_000          # 요청 본문 크기 상한 (바이트)
AI_OUT_TOKENS_MAX = 1200       # 답변 길이 상한
_AI_HITS = {}                  # 보낸 곳 -> [시각, ...]
_AI_LOCK = threading.Lock()


def ai_allowed(who):
    """너무 자주 부르는 것을 막는다. 불러도 되면 True."""
    now = time.time()
    with _AI_LOCK:
        hits = [t for t in _AI_HITS.get(who, []) if now - t < 86400]
        if len(hits) >= AI_RATE_DAY:
            _AI_HITS[who] = hits
            return False
        if len([t for t in hits if now - t < AI_RATE_WINDOW]) >= AI_RATE_BURST:
            _AI_HITS[who] = hits
            return False
        hits.append(now)
        _AI_HITS[who] = hits
        if len(_AI_HITS) > 500:        # 무한정 쌓이지 않게
            for k in [k for k, v in _AI_HITS.items()
                      if not v or now - v[-1] > 86400]:
                _AI_HITS.pop(k, None)
    return True


def ai_clamp_tokens(body):
    """답변 길이 상한을 서버가 다시 정한다.

    브라우저가 보낸 값을 그대로 믿으면 한 번에 한도를 다 태울 수 있다.
    """
    if not isinstance(body, dict):
        return
    cfg = body.get("generationConfig")
    if isinstance(cfg, dict):
        want = cfg.get("maxOutputTokens")
        cfg["maxOutputTokens"] = min(int(want), AI_OUT_TOKENS_MAX) \
            if isinstance(want, int) and want > 0 else AI_OUT_TOKENS_MAX
    if "max_tokens" in body:
        want = body.get("max_tokens")
        body["max_tokens"] = min(int(want), AI_OUT_TOKENS_MAX) \
            if isinstance(want, int) and want > 0 else AI_OUT_TOKENS_MAX


def report_allowed(who):
    """너무 자주 보내는 것을 막는다. 보내도 되면 True."""
    now = time.time()
    with _REPORT_LOCK:
        last = _REPORT_LAST.get(who, 0)
        if now - last < REPORT_MIN_GAP:
            return False
        _REPORT_LAST[who] = now
        if len(_REPORT_LAST) > 500:      # 무한정 쌓이지 않게
            for k in [k for k, v in _REPORT_LAST.items()
                      if now - v > 3600]:
                _REPORT_LAST.pop(k, None)
    return True



def refresh_source_age():
    """원본이 LG 를 마지막으로 확인한 시각을 받아 둔다.

    화면에 '실시간' 이라고 적어 두었지만 사실이 아니다. 원본이 5분에
    한 번만 확인하므로 값은 최대 5분 묵은 것이다. 사실대로 적으려면
    원본이 언제 봤는지를 알아야 한다.
    """
    global SOURCE_UPDATED_AT, SOURCE_INTERVAL, _SOURCE_CHECKED
    now = time.time()
    if now - _SOURCE_CHECKED < 60:
        return
    _SOURCE_CHECKED = now
    req = urllib.request.Request(f"{TARGET_BASE}/api/health",
                                 headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as res:
        d = json.loads(res.read().decode('utf-8'))
    raw = d.get("last_update")
    if raw:
        # "2026-09-08 13:48:30.369750" — 원본 서버의 지역 시각(KST)이다
        try:
            t = datetime.strptime(str(raw)[:19], "%Y-%m-%d %H:%M:%S")
            SOURCE_UPDATED_AT = t.replace(tzinfo=KST).timestamp()
        except Exception:
            pass
    global SOURCE_INTERVAL_SEC
    SOURCE_INTERVAL = str(d.get("current_interval") or "")
    m = re.search(r"(\d+)", SOURCE_INTERVAL)
    SOURCE_INTERVAL_SEC = int(m.group(1)) if m else 0


def source_age_sec():
    """원본 값이 몇 초 묵었는지. 모르면 None.

    원본이 주는 시각에 시간대 표시가 없어서 KST 로 읽고 있다. 지금은 맞다.
    다만 원본이 서버를 옮기거나 설정을 바꾸면 아홉 시간이 어긋나고,
    화면에 '540분 전 값' 같은 것이 뜬다. 말이 안 되는 값이면 모른다고 한다.
    틀린 숫자를 보여주는 것보다 낫다.
    """
    if not SOURCE_UPDATED_AT:
        return None
    age = int(time.time() - SOURCE_UPDATED_AT)
    if age < 0 or age > 3600:
        return None
    return age


def record_device_events(status):
    """오류·일시정지·값 끊김이 생기거나 풀리면 적어 둔다.

    5초마다 불린다. 달라진 것이 없으면 아무 일도 하지 않는다.
    저장은 새 기록이 생겼을 때만 한 번에 한다.
    """
    if not isinstance(status, dict):
        return
    made = []
    for i in range(1, 10):
        tower = status.get("워시타워_%d" % i)
        label = "%d호기" % i
        for unit_type in ("washer", "dryer"):
            unit = (tower or {}).get(unit_type) if isinstance(tower, dict) else None
            made.extend(device_log.observe(label, unit_type, unit, unit_state(unit)))
    if made:
        device_log.append(made)
        for m in made:
            print("[이력] %s %s — %s (%s)"
                  % (m["tower"], m["unit"], m["label"], m["reason"]))


def _mins(timer):
    """남은 시간을 분으로. 숫자가 아니면 0 으로 본다.

    원본이 늘 숫자를 준다는 보장이 없다. 문자열이 한 번이라도 오면
    곱셈에서 터지고, 그 자리가 알림 루프 한가운데라 알림이 통째로 멈춘다.
    모르면 0 으로 두되, 그것만으로 '비었다' 가 되지는 않는다.
    상태(runState)를 따로 보기 때문이다.
    """
    t = timer if isinstance(timer, dict) else {}
    out = 0
    for k in ("remainHour", "remainMinute"):
        v = t.get(k)
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = 0
        out += v * (60 if k == "remainHour" else 1)
    return out


def unit_state(unit):
    """이 기기가 지금 무엇을 하는지. 상태가 안 왔으면 지어내지 않는다.

    원본이 runState 를 통째로 빼고 보낼 때가 있다. 남은 시간만 온다.
    예전에는 그럴 때 POWER_OFF 로 메웠는데, 그러면 완료 판정이
    POWER_OFF 를 '끝남' 으로 보기 때문에 아직 한참 남은 기기에
    완료 푸시가 나갈 수 있었다.
    """
    if not isinstance(unit, dict):
        return "UNKNOWN"
    state = (unit.get("runState") or {}).get("currentState")
    if state:
        return state
    return "UNKNOWN_RUNNING" if _mins(unit.get("timer")) > 0 else "UNKNOWN"


# =========================================================
# 스스로 하는 노출 검사
# ---------------------------------------------------------
# 서버가 뜰 때 자기 자신에게 요청을 보내, 나가면 안 되는 파일이
# 정말로 안 나가는지 확인한다.
#
# 왜 필요한가. 2026-09-04 부터 사흘 동안 .env 가 그대로 나갔다.
# 봇 토큰, AI 키, 저장소 토큰이 전부 그 안에 있었고, 자동 스캐너가
# 21번 받아 갔다. 코드를 고칠 때마다 사람이 기억해서 확인하는 것은
# 언젠가 빠뜨린다. 실제로 빠뜨렸다.
#
# 검사 목록을 손으로 적지 않는다. 그러면 새 파일이 생길 때 또 빠뜨린다.
# 폴더에 실제로 있는 파일 중 공개 대상이 아닌 것을 그때그때 골라 본다.
# =========================================================
EXPOSURE_STATUS = "확인 전"


# 브라우저가 보내오는 자리표시자. 이 자리에 안내 지식을 끼워 넣는다.
KB_PLACEHOLDER = "{{JUNGLE_KB}}"
_JUNGLE_KB = None


def _kb_module():
    """안내 지식 모듈. 없으면 None (그래도 세탁실 기능은 돌아간다)."""
    global _JUNGLE_KB
    if _JUNGLE_KB is None:
        try:
            import jungle_kb
            _JUNGLE_KB = jungle_kb
        except Exception as e:
            print(f"[안내지식] 불러오지 못했습니다: {e}")
            _JUNGLE_KB = False
    return _JUNGLE_KB or None


def fill_kb(body, question, limit=None):
    """요청 안의 자리표시자를 안내 지식으로 바꾼다.

    limit 을 주면 질문에 걸리는 항목 몇 개만 넣는다. Groq 은 요청 크기
    제한이 빡빡해서 통째로 넣으면 413 이 난다. 봇이 쓰는 것과 같은 함수다.
    """
    kb = _kb_module()
    if kb:
        try:
            text = kb.build_context(question or "", limit=limit)
        except Exception as e:
            print(f"[안내지식] 만들지 못했습니다: {e}")
            text = ""
    else:
        text = ""
    if not text:
        text = "(안내 지식을 불러오지 못했습니다. 세탁실 관련만 답하세요.)"

    # 오늘 메뉴를 함께 넣는다. 짧으므로 Groq 으로 갈 때도 그대로 넣는다.
    # 사진 주소는 넣지 않는다. AI 가 주소를 지어내면 엉뚱한 사진이 나간다.
    try:
        menu = cafeteria.summary_for_ai()
        if menu:
            text = text + "\n\n" + menu
    except Exception as e:
        print(f"[식단] AI 에게 넘길 글을 만들지 못했습니다: {e}")

    raw = json.dumps(body, ensure_ascii=False)
    if KB_PLACEHOLDER not in raw:
        return body
    # 지식 안의 따옴표·줄바꿈이 JSON 을 깨지 않도록 값으로 넣었다 뺀다
    safe = json.dumps(text, ensure_ascii=False)[1:-1]
    return json.loads(raw.replace(KB_PLACEHOLDER, safe))


def last_user_text(body):
    """이번에 사람이 물어본 말. 어떤 항목을 추릴지 정하는 데 쓴다."""
    try:
        for msg in reversed(body.get("contents") or []):        # 제미나이
            if msg.get("role") in (None, "user"):
                return "".join(p.get("text", "") for p in msg.get("parts") or [])
        for msg in reversed(body.get("messages") or []):        # Groq
            if msg.get("role") == "user":
                return str(msg.get("content") or "")
    except Exception:
        pass
    return ""


def check_secret_file_perms():
    """열쇠가 든 파일을 나 말고도 읽을 수 있는지 본다.

    웹으로 나가는 것만 막아서는 부족하다. 서버 안에서 아무나 읽을 수 있으면
    거기서도 새어 나간다. 고치지는 않는다. 남의 파일 권한을 말없이 바꾸는
    것이 더 위험하다. 어떻게 고치는지만 알려 준다.

    윈도우에는 이 권한 개념이 없어 건너뛴다. 서버는 리눅스다.
    """
    if os.name != "posix":
        return
    for name in (".env", "vapid_private.pem"):
        path = os.path.join(BASE_DIR, name)
        if not os.path.exists(path):
            continue
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            continue
        if mode & 0o077:
            print("=" * 60)
            print(f"[권한] {name} 을 다른 사용자도 읽을 수 있습니다 "
                  f"(지금 {oct(mode)[2:]}).")
            print(f"[권한] 고치기: chmod 600 {path}")
            print("=" * 60)


def run_exposure_check():
    """공개 대상이 아닌 파일이 웹으로 나가는지 스스로 확인한다."""
    global EXPOSURE_STATUS
    try:
        targets = []
        for name in sorted(os.listdir(BASE_DIR)):
            path = "/" + name
            if os.path.isdir(os.path.join(BASE_DIR, name)):
                continue
            if is_public_path(path):      # 내줘도 되는 것은 건너뛴다
                continue
            targets.append(path)
        # 폴더에 없더라도 늘 확인하는 것들
        for extra in ("/.env", "/.git/config", "/../.env"):
            if extra not in targets:
                targets.append(extra)

        leaked = []
        for path in targets:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{PORT}{path}", method="GET")
                with urllib.request.urlopen(req, timeout=3) as r:
                    if r.status == 200:
                        leaked.append(path)
            except urllib.error.HTTPError:
                pass                      # 404 면 정상이다
            except Exception:
                pass

        if leaked:
            EXPOSURE_STATUS = "새는 파일 %d개" % len(leaked)
            print("=" * 60)
            print("[노출 검사] 나가면 안 되는 파일이 웹으로 나가고 있습니다:")
            for p in leaked:
                print("   " + p)
            print("[노출 검사] start_server.py 의 PUBLIC_FILES 를 확인하세요.")
            print("=" * 60)
        else:
            EXPOSURE_STATUS = "정상"
            print(f"[노출 검사] {len(targets)}개 확인 — 모두 막혀 있습니다.")

        check_secret_file_perms()

    except Exception as e:
        EXPOSURE_STATUS = "검사 실패"
        print(f"[노출 검사] 검사하지 못했습니다: {e}")



def discord_bot_health():
    """봇 상태를 /api/health 에 실어 보낸다.

    로그를 뒤지지 않고도 밖에서 연결 여부를 알 수 있어야 한다.
    UptimeRobot 의 키워드 감시로 botOnline:false 를 잡아도 된다.
    """
    if DISCORD_MODULE is None:
        return {"botOnline": False, "bot": "꺼짐"}
    st = DISCORD_MODULE.BOT_STATUS
    out = {"botOnline": bool(st.get("online")), "bot": st.get("state")}
    if st.get("detail"):
        out["botDetail"] = st["detail"]
    if st.get("name"):
        out["botName"] = st["name"]
        out["botGuilds"] = st.get("guilds", 0)
    # 등록된 알림 수. 감시 루프가 얼마나 일하는지 가늠하는 데 쓴다.
    try:
        out["botAlarms"] = len(DISCORD_MODULE.active_alarms)
        out["botApi"] = DISCORD_MODULE.api_call_stats()
    except Exception:
        pass
    out["botSince"] = int(time.time() - st.get("since", time.time()))
    return out


def start_discord_bot():
    """디스코드 봇을 같은 프로세스에서 함께 띄운다.

    Render 무료 플랜에는 상주 작업(Background Worker)이 없어서,
    이미 떠 있는 웹 서비스 안에서 함께 돌린다.
    토큰이 없으면 조용히 넘어간다 (웹만 쓰는 배포도 있으므로).
    """
    if not (os.environ.get('DISCORD_BOT_TOKEN') or '').strip():
        print("[Bot] DISCORD_BOT_TOKEN 이 없어 봇은 띄우지 않습니다. (웹만 실행)")
        return
    if (os.environ.get('RUN_DISCORD_BOT') or '1').strip() in ('0', 'false', 'no'):
        print("[Bot] RUN_DISCORD_BOT 가 꺼져 있어 봇을 띄우지 않습니다.")
        return
    global DISCORD_MODULE
    try:
        import discord_bot
    except Exception as e:
        print(f"[Bot] 봇을 불러오지 못했습니다: {e}")
        return
    DISCORD_MODULE = discord_bot

    def runner():
        try:
            discord_bot.run_bot(embedded=True)
        except Exception as e:
            print(f"[Bot] 봇이 멈췄습니다: {e}")
            discord_bot.set_bot_status("멈춤", str(e)[:120])

    t = threading.Thread(target=runner, daemon=True, name="discord-bot")
    t.start()
    print("[Bot] 디스코드 봇을 함께 띄웠습니다.")


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    # Render 는 재배포마다 파일이 지워진다.
    # 파일이 없으면 바깥 저장소에서 되살린다. 없으면 그냥 새로 시작한다.
    state_store.start_state_sync()
    state_store.restore_file('push_subscriptions', SUBS_FILE, '웹 푸시 구독')
    state_store.restore_file('congestion_stats', CONGESTION_FILE, '혼잡도 관측 기록')
    load_congestion()
    start_discord_bot()
    # 이 작업은 알림 발송만 하는 게 아니라 실시간 데이터 갱신과
    # 혼잡도 관측도 함께 한다. 그래서 푸시 사용 여부와 상관없이 항상 돌린다.
    t = threading.Thread(target=background_push_worker, daemon=True)
    t.start()
    if HAS_WEBPUSH:
        print("[Worker] 백그라운드 작업 시작 (5초 주기: 상태 갱신 · 알림 · 혼잡도 관측)")
    else:
        print("[Worker] 백그라운드 작업 시작 (푸시 라이브러리 없음 - 알림 발송만 비활성)")

    with ThreadedTCPServer(("", PORT), RobustHandler) as httpd:
        print("============================================================")
        print("  Jungle Laundry 2.0 Web Server Running!")
        print(f"  URL: http://localhost:{PORT}")
        print("============================================================")
        # 문이 열린 뒤에 스스로 확인한다. 자기 자신에게 요청을 보내는 것이라
        # 서버가 받을 준비가 된 다음이어야 한다. 검사에 몇 초 걸리므로
        # 따로 돌려서 서비스 시작을 붙잡지 않는다.
        threading.Thread(target=run_exposure_check, daemon=True,
                         name="exposure-check").start()
        httpd.serve_forever()
