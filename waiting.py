# -*- coding: utf-8 -*-
"""끝났는데 아직 안 꺼낸 기기가 얼마나 오래 그대로인지 기록한다.

대시보드의 '실시간 기기 점검 & 방치 알리미' 는 이름에 '방치' 가 있는데 방치를
찾는 코드가 없었다. 설명 문구는 "장기 방치물이 없습니다 👍" 라고 했지만 확인한
적이 없는 말이었다. 이 모듈이 그 빈자리를 채운다.

왜 서버가 적어야 하나. 원본이 주는 값에는 '끝난 시각' 이 없다. 지금 상태가
END 인지만 안다. 화면이 열려 있던 동안만 세면 방금 연 사람에게는 늘 0분이다.
그래서 서버가 '처음 끝난 것으로 본 시각' 을 적어 둔다.

정직하게 말할 수 있는 만큼만.
    원본이 5분에 한 번만 알려주므로 실제로 끝난 때는 적어 둔 시각보다
    최대 5분 앞선다. 그래서 '몇 분째' 가 아니라 '몇 분 이상' 이라고 쓴다.
    실제보다 길게 말하는 일이 없도록 아래에서 두 군데를 막았다.

  1) 값이 안 오는 동안(UNKNOWN)은 '떠났다' 로 읽지 않는다. 그러나 오래 못 봤으면
     (GAP_RESET_SEC) 그 사이에 꺼내고 다른 사람이 다시 돌렸을 수 있으므로, 그때는
     처음부터 다시 센다. 길게 말하느니 짧게 말한다.
  2) 서버를 다시 켜도 이어서 센다. 다시 켜기 전 마지막으로 본 시각도 함께 적어 두고
     (SAVE_EVERY_SEC 마다), 그 이후 공백이 길었으면 1) 로 처리한다.
"""
import threading
import time

import state_store

STORE_NAME = "waiting_pickup"

# 끝났는데 안 꺼낸 상태. 건조기의 구김 방지도 옷이 안에 그대로 있는 상태다.
FINISHED_STATES = ("END", "COMPLETE", "WRINKLE_CARE")

# 이만큼 못 봤으면 그 사이에 바뀌었을 수 있다고 본다.
GAP_RESET_SEC = 15 * 60
# 마지막으로 본 시각을 저장소에 적는 간격. 5초마다 적으면 저장소가 낭비다.
SAVE_EVERY_SEC = 60

_LOCK = threading.Lock()
_DATA = None
_LAST = {}          # key -> 가장 최근에 본 시각 (메모리에만)


def _load():
    global _DATA
    if _DATA is None:
        raw = state_store.state_load(STORE_NAME, {})
        _DATA = raw if isinstance(raw, dict) else {}
    return _DATA


def _key(label, unit_type):
    return "%s/%s" % (label, unit_type)


def observe(label, unit_type, state, now=None):
    """기기 하나를 보고, 저장할 것이 바뀌었으면 True 를 돌려준다.

    state 가 UNKNOWN(값이 안 옴)이면 부르지 않는다. 부르는 쪽 책임이다.
    저장은 부르는 쪽에서 한 번에 한다.
    """
    now = now or time.time()
    key = _key(label, unit_type)
    with _LOCK:
        data = _load()
        entry = data.get(key)
        last = _LAST.get(key)
        if last is None and isinstance(entry, dict):
            last = entry.get("seen")          # 서버를 막 켰다. 저장된 것을 쓴다.
        _LAST[key] = now

        if state in FINISHED_STATES:
            gap_too_long = last is not None and (now - last) > GAP_RESET_SEC
            if not isinstance(entry, dict) or gap_too_long:
                data[key] = {"since": round(now, 3), "seen": round(now, 3)}
                return True
            if now - (entry.get("seen") or 0) >= SAVE_EVERY_SEC:
                entry["seen"] = round(now, 3)
                return True
            return False

        # 끝난 상태가 아니다. 꺼냈거나 다시 돌렸다는 뜻이므로 지운다.
        _LAST.pop(key, None)
        if key in data:
            del data[key]
            return True
        return False


def snapshot(now=None):
    """보여줄 값. {호기: {washer|dryer: 처음 끝난 것으로 본 시각}}"""
    out = {}
    with _LOCK:
        for key, entry in _load().items():
            if not isinstance(entry, dict) or not entry.get("since"):
                continue
            label, _, unit_type = key.partition("/")
            out.setdefault(label, {})[unit_type] = entry["since"]
    return out


def save():
    with _LOCK:
        state_store.state_save(STORE_NAME, _load())


def reset_for_test():
    global _DATA
    with _LOCK:
        _DATA = {}
        _LAST.clear()
