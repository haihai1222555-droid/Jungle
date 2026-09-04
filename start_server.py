import sys
import os
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import threading
import state_store
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
# 미리 만들어 둔 응답 본문. 요청마다 json.dumps 를 다시 도는 것은 낭비다.
# 200명이 동시에 볼 때는 이 직렬화 비용이 그대로 지연으로 나타난다.
CACHED_STATUS_BODY = b'{}'

# 원본 서버로 나가는 요청을 모아 두는 곳.
# 예전에는 /api/stats 가 요청마다 원본으로 나갔다. 200명이면 200번이다.
# 같은 것을 여러 명이 물으면 한 번만 다녀와서 나눠 준다.
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

# 세탁이 끝난 뒤 이 시간이 지나도록 기기가 그대로면 '수거 안 함' 으로 보고 한 번 더 알린다.
# 환경변수로 조정할 수 있다 (기본 15분).
STALE_PICKUP_SEC = int(os.environ.get('STALE_PICKUP_SEC') or 15 * 60)

# 가동 중으로 볼 상태들 (완료 후 이 상태가 되면 = 다음 사람이 새로 돌린 것)
RUNNING_STATES = ('RUNNING', 'WASHING', 'RINSING', 'SPINNING', 'DRYING', 'COOLING')

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
            state = (unit.get("runState") or {}).get("currentState", "POWER_OFF")
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
            except Exception:
                pass

            subs = load_subscriptions()
            if not subs:
                continue

            now_ms = time.time() * 1000
            changed = False
            active_subs = []

            for item in subs:
                sub_info = item.get('subscription')
                alarm = item.get('alarm', {})
                if not sub_info or not alarm:
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
                tower_data = CACHED_STATUS.get(tower_key, {})
                unit_data = tower_data.get('dryer' if unit_type == 'dryer' else 'washer', {})
                run_state = unit_data.get('runState', {}).get('currentState', 'POWER_OFF')

                # 실시간 상태를 실제로 받아왔는지 (못 받아온 상태에서 '완료' 로 오판하면 안 된다)
                has_live = bool(unit_data)

                # ⭐ 기기가 알려주는 실제 남은 시간을 우선한다.
                #    건조기 옷감 감지로 9분 -> 4분처럼 줄거나, 반대로 늘어나는 경우가 잦은데
                #    등록 시점에 굳힌 targetMs 만 믿으면 알림 시점이 완전히 어긋난다.
                live_min = 0
                if has_live:
                    _t = unit_data.get('timer') or {}
                    live_min = (_t.get('remainHour') or 0) * 60 + (_t.get('remainMinute') or 0)

                if live_min > 0:
                    remain_min = float(live_min)
                else:
                    # 기기가 시간을 안 알려주는 구간에서는 등록 시점 예상치로 대체
                    remain_min = (target_ms - now_ms) / (60 * 1000)

                if not notified_5min and remain_min <= 5.0 and remain_min > 0:
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

                elif not notified_0min and (
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

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
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
        if req_path in ('/api/health', '/api/status', '/api/stats', '/'):
            self.send_response(200)
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self):
        req_path = self.path.split('?')[0]
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
                **discord_bot_health(),
            }, ensure_ascii=False).encode('utf-8'))
            return

        if req_path == '/api/congestion':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(build_congestion_profile(), ensure_ascii=False).encode('utf-8'))
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
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Cache-Age', str(age))
            if age > CACHED_STATUS_MAX_AGE:
                self.send_header('X-Cache-Stale', '1')
            self.end_headers()
            self.wfile.write(body)
            return

        if req_path.startswith('/api/'):
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
                            content = response.read()
                            hdrs = [(k, v) for k, v in response.headers.items()
                                    if k.lower() not in ('transfer-encoding',
                                                         'content-length',
                                                         'content-encoding')]
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
                    content = response.read()
                    self.send_response(response.status)
                    for k, v in response.headers.items():
                        if k.lower() not in ['transfer-encoding', 'content-length', 'content-encoding']:
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
                self.send_response(502)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        return super().do_GET()

    def _client_key(self):
        """요청을 보낸 사람을 구분할 값.

        Caddy 를 거치면 출발지가 늘 127.0.0.1 이라, 그대로 쓰면
        한 사람이 제보한 뒤 30초 동안 모두가 막힌다.
        Caddy 가 붙여 주는 X-Forwarded-For 의 맨 앞이 진짜 사용자다.
        """
        fwd = (self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        if fwd:
            return fwd
        return self.client_address[0] if self.client_address else '?'

    def _read_json(self, limit=8000):
        """요청 본문을 JSON 으로 읽는다. 형식이 틀리면 None."""
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n <= 0 or n > limit:
                return None
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return None

    def _json_out(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split('?')[0] == '/api/report':
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
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

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
                            if not (x.get('alarm', {}).get('key') == key
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
                        if (x.get('alarm', {}).get('key') == key
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
                           if not key or x.get('alarm', {}).get('key') == key]

                sent = 0
                for x in targets:
                    device = x.get('alarm', {}).get('deviceName', '기기')
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
                    "devices": [x.get('alarm', {}).get('deviceName') for x in targets]
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
                                if not (x.get('alarm', {}).get('key') == key
                                        and (x.get('subscription') or {}).get('endpoint') == endpoint)]
                    else:
                        subs = [x for x in subs if x.get('alarm', {}).get('key') != key]
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

        if req_path == '/api/chat':
            try:
                payload = json.loads(post_data.decode('utf-8'))
                user_msg = payload.get('message', '').strip()
                client_api_key = payload.get('apiKey', '').strip()
                selected_model = payload.get('model', 'gemini-flash-lite-latest').strip()
                api_key = client_api_key or '***REMOVED***'

                system_instruction = (
                    "당신은 크래프톤 정글 스마트 세탁실 & 기숙사 생활 전용 AI 비서입니다.\n"
                    "핵심만 친절하고 명쾌하게 답변하세요.\n"
                    f"[실시간 상태]:\n{json.dumps(CACHED_STATUS, ensure_ascii=False)}"
                )

                gemini_endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
                req_body = {
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 800}
                }

                gemini_req = urllib.request.Request(
                    gemini_endpoint,
                    data=json.dumps(req_body).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )

                with urllib.request.urlopen(gemini_req, timeout=12) as gemini_res:
                    gemini_json = json.loads(gemini_res.read().decode('utf-8'))
                    ai_reply = gemini_json['candidates'][0]['content']['parts'][0]['text']

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps({"reply": ai_reply}, ensure_ascii=False).encode('utf-8'))
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
        httpd.serve_forever()
