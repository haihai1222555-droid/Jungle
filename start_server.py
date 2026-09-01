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

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

PORT = 8000
TARGET_BASE = "https://miracle-beautifully-onto-ser.trycloudflare.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBS_FILE = os.path.join(BASE_DIR, 'push_subscriptions.json')

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

def load_subscriptions():
    if not os.path.exists(SUBS_FILE):
        return []
    try:
        with open(SUBS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_subscriptions(subs):
    try:
        with open(SUBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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

                tower_id = alarm.get('towerId')
                unit_type = alarm.get('unitType')
                device_name = alarm.get('deviceName', '세탁기')
                target_ms = alarm.get('targetMs', 0)
                remain_min = (target_ms - now_ms) / (60 * 1000)

                notified_5min = alarm.get('notified5Min', False)
                notified_0min = alarm.get('notified0Min', False)

                tower_key = f"워시타워_{tower_id}"
                tower_data = CACHED_STATUS.get(tower_key, {})
                unit_data = tower_data.get('dryer' if unit_type == 'dryer' else 'washer', {})
                run_state = unit_data.get('runState', {}).get('currentState', 'POWER_OFF')

                if not notified_5min and remain_min <= 5.0 and remain_min > 0:
                    alarm['notified5Min'] = True
                    changed = True
                    send_push_notification(sub_info, {
                        'title': f"[정글 세탁실] {device_name} 완료 5분 전!",
                        'body': f"회원님이 등록하신 {device_name} 가동이 약 5분 뒤 완료됩니다. 세탁실로 이동해 주세요!",
                        'tag': f"5min-{device_name}"
                    })

                elif not notified_0min and (remain_min <= 0 or run_state in ('END', 'COMPLETE', 'WRINKLE_CARE')):
                    alarm['notified0Min'] = True
                    changed = True
                    send_push_notification(sub_info, {
                        'title': f"[정글 세탁실] {device_name} 완료!",
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
        except Exception:
            pass

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
                    subs = [s for s in subs if s.get('alarm', {}).get('key') != key]
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

        if req_path == '/api/unsubscribe-push':
            try:
                data = json.loads(post_data.decode('utf-8'))
                key = data.get('key')
                if key:
                    subs = load_subscriptions()
                    subs = [s for s in subs if s.get('alarm', {}).get('key') != key]
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

    with ThreadedTCPServer(("", PORT), RobustHandler) as httpd:
        print("============================================================")
        print("  Jungle Laundry 2.0 Local Server Running!")
        print(f"  URL: http://localhost:{PORT}")
        print("============================================================")
        httpd.serve_forever()
