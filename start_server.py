import sys
import os
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import threading
import time
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
PORT = int(os.environ.get('PORT') or 8000)
TARGET_BASE = os.environ.get('TARGET_BASE') or "https://miracle-beautifully-onto-ser.trycloudflare.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBS_FILE = os.environ.get('SUBS_FILE') or os.path.join(BASE_DIR, 'push_subscriptions.json')

try:
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    from pywebpush import webpush, WebPushException
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
CACHED_STATS = {}

# 이보다 오래된 알림 등록은 지난 빨래로 보고 정리한다 (한 사이클은 길어야 2시간)
MAX_ALARM_AGE_SEC = 4 * 60 * 60

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

def background_push_worker():
    global CACHED_STATUS, CACHED_STATS
    while True:
        try:
            time.sleep(5)
            try:
                req = urllib.request.Request(f"{TARGET_BASE}/api/status", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=3) as res:
                    CACHED_STATUS = json.loads(res.read().decode('utf-8'))
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
                        'tag': f"5min-{device_name}"
                    })

                elif not notified_0min and (
                    remain_min <= 0
                    or (has_live and run_state in ('END', 'COMPLETE', 'WRINKLE_CARE', 'POWER_OFF', 'INITIAL'))
                ):
                    alarm['notified0Min'] = True
                    changed = True
                    send_push_notification(sub_info, {
                        'title': f"🏁 [선택 기기 완료] {device_name} 완료!",
                        'body': f"회원님이 등록하신 {device_name} 가동이 끝났습니다. 세탁실에서 빨래를 즉시 수거해 주세요!",
                        'tag': f"complete-{device_name}"
                    })
                    continue

                if notified_0min:
                    changed = True
                    continue

                active_subs.append(item)

            if changed:
                save_subscriptions(active_subs)
        except Exception as e:
            print(f"[Worker Error] {e}")

class RobustHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

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
                "alarms": len(load_subscriptions())
            }).encode('utf-8'))
            return

        if req_path == '/api/vapid-public-key':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"publicKey": VAPID_PUBLIC_KEY_B64}).encode('utf-8'))
            return

        if req_path.startswith('/api/'):
            target_url = TARGET_BASE + self.path
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
                self.send_response(502)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return

        return super().do_GET()

    def do_POST(self):
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

if __name__ == '__main__':
    os.chdir(BASE_DIR)
    if HAS_WEBPUSH:
        t = threading.Thread(target=background_push_worker, daemon=True)
        t.start()
        print("[WebPush] 백그라운드 알림 워커 시작됨 (5초 주기)")
    else:
        print("[WebPush] 라이브러리 없음 - 백그라운드 알림 비활성")

    with ThreadedTCPServer(("", PORT), RobustHandler) as httpd:
        print("============================================================")
        print("  Jungle Laundry 2.0 Local Server Running!")
        print(f"  URL: http://localhost:{PORT}")
        print("============================================================")
        httpd.serve_forever()
