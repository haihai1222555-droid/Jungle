# -*- coding: utf-8 -*-
"""웹 서버와 디스코드 봇이 함께 쓰는 상태 저장소.

Render 는 재배포·재시작마다 파일시스템이 초기화된다.
여기 있는 것을 파일에만 두면 배포할 때마다 사라진다.
  · 학생들이 걸어둔 알림
  · 웹 푸시 구독 정보
  · 혼잡도 관측 기록 (매주 월요일 갱신에 쓰는 것)

그래서 파일을 빠른 사본으로 쓰되, 바깥 저장소에도 남긴다.
바깥 저장소는 Upstash Redis 의 HTTP 방식을 쓴다. 따로 설치할 것이 없다.
설정하지 않으면 예전처럼 파일만 쓴다 — 동작은 그대로다.
옮길 일이 생기면 _remote_get / _remote_set 두 함수만 고치면 된다.
"""
import io
import json
import os
import threading
import time
import urllib.request

import security

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------
# Render 는 재시작마다 파일이 지워진다. 그러면 배포할 때마다
# 등록된 알림과 /채널설정 이 사라진다.
# 그래서 파일에 쓰되, 외부 저장소가 설정되어 있으면 거기에도 남긴다.
#
# 외부 저장소는 Upstash Redis 의 HTTP 방식을 쓴다.
# 따로 설치할 것이 없고(그냥 HTTP 요청이다), 무료 한도로 충분하다.
# 설정하지 않으면 예전처럼 파일만 쓴다 — 동작은 그대로다.
# 나중에 다른 곳으로 옮기려면 _remote_get / _remote_set 두 함수만 고치면 된다.
# =========================================================
# 웹 서버와 한 프로세스에서 도는 중인지. run_bot(embedded=True) 가 켠다.
EMBEDDED = False

STORE_URL = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").strip().rstrip("/")
STORE_TOKEN = (os.environ.get("UPSTASH_REDIS_REST_TOKEN") or "").strip()
STORE_PREFIX = (os.environ.get("STATE_PREFIX") or "junglewash").strip()

_STATE_DIRTY = {}          # 아직 외부에 못 보낸 것
_STATE_LOCK = threading.Lock()


def store_enabled():
    return bool(STORE_URL and STORE_TOKEN)


def _remote_call(command):
    req = urllib.request.Request(
        STORE_URL,
        data=json.dumps(command).encode("utf-8"),
        headers={"Authorization": f"Bearer {STORE_TOKEN}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(security.read_capped(res).decode("utf-8")).get("result")


def _remote_get(name):
    return _remote_call(["GET", f"{STORE_PREFIX}:{name}"])


def _remote_set(name, raw):
    return _remote_call(["SET", f"{STORE_PREFIX}:{name}", raw])


def _state_path(name):
    return os.path.join(BASE_DIR, f"{name}.json")


def state_load(name, default):
    """외부 저장소를 먼저 보고, 없으면 파일을 본다."""
    if store_enabled():
        try:
            raw = _remote_get(name)
            if raw:
                data = json.loads(raw)
                print(f"[State] '{name}' 을(를) 외부 저장소에서 불러왔습니다.")
                return data
        except Exception as e:
            print(f"[State] 외부 저장소 읽기 실패({name}): {e} — 파일로 대체합니다.")
    path = _state_path(name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[State] 파일 읽기 실패({name}): {e}")
    return default


def state_save(name, value):
    """파일에 바로 쓰고, 외부 저장소에는 뒤에서 따로 보낸다.

    외부로 보내는 일은 네트워크라 느릴 수 있다.
    여기서 기다리면 봇 전체가 멈추므로 표시만 해두고 넘어간다.
    """
    try:
        path = _state_path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[State] 파일 저장 실패({name}): {e}")
    if store_enabled():
        with _STATE_LOCK:
            _STATE_DIRTY[name] = json.dumps(value, ensure_ascii=False)


def _state_sync_worker():
    """밀린 것들을 몇 초에 한 번씩 외부 저장소로 보낸다."""
    while True:
        time.sleep(5)
        with _STATE_LOCK:
            pending = dict(_STATE_DIRTY)
            _STATE_DIRTY.clear()
        for name, raw in pending.items():
            try:
                _remote_set(name, raw)
            except Exception as e:
                print(f"[State] 외부 저장소 쓰기 실패({name}): {e} — 다음에 다시 시도합니다.")
                with _STATE_LOCK:      # 실패한 것은 되돌려 다음 차례에 다시 보낸다
                    _STATE_DIRTY.setdefault(name, raw)


def state_fetch(name):
    """바깥 저장소에서 값을 읽어온다. 없거나 실패하면 None.

    파일이 살아 있으면 굳이 부를 필요가 없다. 시작할 때 한 번만 쓴다.
    """
    if not store_enabled():
        return None
    try:
        raw = _remote_get(name)
        return json.loads(raw) if raw else None
    except Exception as e:
        print(f"[State] 외부 저장소 읽기 실패({name}): {e}")
        return None


def state_push(name, value):
    """바깥에 보낼 것으로 표시만 한다. 파일 쓰기는 부르는 쪽 책임이다.

    보내는 일은 네트워크라 느리다. 여기서 기다리면 요청 처리가 멈추므로
    표시만 하고 넘어가고, 뒤에서 도는 일꾼이 모아서 보낸다.
    """
    if store_enabled():
        with _STATE_LOCK:
            _STATE_DIRTY[name] = json.dumps(value, ensure_ascii=False)


def restore_file(name, path, label=None):
    """파일이 없으면 바깥 저장소에서 받아 파일로 되살린다.

    Render 에서 새 컨테이너로 뜨면 파일이 비어 있다. 그때만 부른다.
    한 번 되살린 뒤에는 파일을 읽으므로 매번 네트워크를 타지 않는다.
    """
    if os.path.exists(path) or not store_enabled():
        return False
    data = state_fetch(name)
    if data is None:
        return False
    try:
        with io.open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[State] {label or name} 을(를) 외부 저장소에서 되살렸습니다.")
        return True
    except Exception as e:
        print(f"[State] 되살리기 실패({name}): {e}")
        return False


def start_state_sync():
    """밀린 내용을 바깥으로 보내는 일꾼을 띄운다. 설정이 없으면 띄우지 않는다."""
    global _SYNC_STARTED
    with _STATE_LOCK:
        if _SYNC_STARTED:
            return
        _SYNC_STARTED = True
    if not store_enabled():
        print("[State] 외부 저장소가 설정되지 않았습니다. 파일에만 저장합니다.")
        print("        (Render 처럼 재시작 시 파일이 지워지는 곳에서는 기록이 사라집니다)")
        return
    threading.Thread(target=_state_sync_worker, daemon=True,
                     name="state-sync").start()
    print(f"[State] 외부 저장소를 사용합니다. (접두어 {STORE_PREFIX})")


_SYNC_STARTED = False
