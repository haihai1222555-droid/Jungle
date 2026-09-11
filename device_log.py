# -*- coding: utf-8 -*-
"""기기에 있었던 일(오류·일시정지·값 끊김)을 적어 둔다.

왜 남기나. 지금은 무언가 잘못돼도 그때 화면을 본 사람만 안다.
"어제 밤에 3호기 건조기가 멈춰 있었다" 는 제보가 들어와도 확인할 방법이 없다.
언제 어떤 기기가 어떻게 됐는지가 남아 있어야 같은 고장이 되풀이되는지,
특정 기기만 그러는지를 알 수 있다.

무엇을 남기나.
  - 오류가 났다 / 풀렸다        (에러 코드까지 온다)
  - 일시정지됐다 / 다시 돌았다  (얼마나 멈춰 있었는지도)
  - 값이 끊겼다 / 돌아왔다

일시정지 이유는 기기가 알려주지 않는다. 그래도 갈라낼 수 있다.
멈추기 직전이 오류였으면 오류 때문에 멈춘 것이고, 멀쩡히 돌다가 멈췄으면
사람이 버튼을 누른 것이다. 기기가 말해 준 것은 아니지만 상태 변화로
알 수 있는 것이라 적는다. 다만 서버가 막 떠서 직전을 못 본 경우에는
가릴 수 없으므로 그렇다고 적는다. 모르는 것을 아는 척하지는 않는다.

무엇을 안 남기나. 누가 썼는지는 남기지 않는다. 그런 값이 오지도 않고,
남길 이유도 없다. 여기 있는 것은 기계 상태뿐이다.

얼마나 두나. 일주일. 넘긴 것은 지운다.
서버가 5초마다 상태를 보므로 기록은 그때그때 쌓이고,
쌓일 때마다 오래된 것을 함께 걷어낸다.

누가 보나. 관리자만. 디스코드에서 /이력 로 본다.
"""
import threading
import time

import state_store

STORE_NAME = "device_events"
KEEP_SEC = 7 * 24 * 3600      # 일주일
MAX_ITEMS = 3000              # 일주일 안이라도 무한정 쌓이지 않게

# 에러 코드를 한 줄로. 자세한 조치는 봇의 ERROR_GUIDE 가 따로 가지고 있다.
ERROR_SHORT = {
    "EMPTY_WATER_ALERT_ERROR": "건조기 배수 이상 (호스 꺾임·필터 막힘)",
    "FILTER_CLEAN_ERROR": "건조기 먼지 필터 막힘",
    "DRAIN_ERROR": "세탁기 배수 이상 (OE)",
    "UNBALANCE_ERROR": "세탁물 뭉침 (UE)",
    "DOOR_OPEN_ERROR": "도어 덜 닫힘 (dE)",
}

# 사람이 읽는 사건 이름
EVENT_LABEL = {
    "error": "오류 발생",
    "error_cleared": "오류 해제",
    "pause": "일시정지",
    "resume": "다시 가동",
    "nodata": "값 끊김",
    "nodata_cleared": "값 복구",
}

_LOCK = threading.Lock()
_ITEMS = None                 # 처음 쓸 때 불러온다
_LOADED_AT = 0                # 언제 불러온 것인지
_IS_WRITER = False            # 이 프로세스가 기록을 쓰는 쪽인지 (웹 서버)
RELOAD_SEC = 20               # 읽는 쪽은 이만큼 지나면 다시 불러온다
_PREV = {}                    # (타워, 유닛) -> 직전에 본 모습
_PAUSE_SINCE = {}             # (타워, 유닛) -> 멈춘 시각. 다시 돌 때 얼마나였는지 적으려고


# 예전에 적어 둔 문장. 기기가 알려준 것이 아니라 우리가 지어낸 판정이었다.
_LEGACY_PAUSE = "사용자가 일시정지를 함"


def _fix_legacy(items):
    """예전에 근거 없이 '사용자가 일시정지를 함' 이라고 적은 것을 고친다.

    기기는 왜 멈췄는지 알려주지 않는다. 오류를 못 봤다는 것뿐이었는데
    사람이 눌렀다고 단정했다. 실제로 배수 오류로 멈춘 건조기를
    사람 탓으로 적었고, 관리자는 /이력 에서 그 문장을 읽었다.

    기기가 준 값(상태·에러 코드)은 건드리지 않는다.
    우리가 지어낸 문장만 바꾼다.
    """
    for x in items:
        if not isinstance(x, dict) or x.get("event") != "pause":
            continue
        if _LEGACY_PAUSE in (x.get("reason") or ""):
            x["reason"] = reason_of("pause", x.get("error"), False)
            x["cause"] = "unknown"
    return items


def _load():
    global _ITEMS, _LOADED_AT
    if _ITEMS is None:
        raw = state_store.state_load(STORE_NAME, [])
        _ITEMS = _fix_legacy(raw if isinstance(raw, list) else [])
        _LOADED_AT = time.time()
    return _ITEMS


def _fresh():
    """읽기 전에 저장소를 다시 본다.

    기록을 쓰는 것은 웹 서버, 읽는 것은 봇이다. 서로 다른 프로세스라
    한 번 불러온 채로 두면 봇의 /이력 이 옛날 것에 멈춰 있다.
    쓰는 쪽에서는 하지 않는다. 방금 자기가 넣은 것을 덮어쓸 일이다.

    잠금을 잡지 않고 부른다. 부르는 쪽이 곧바로 잡기 때문이다.
    """
    global _ITEMS, _LOADED_AT
    if _IS_WRITER:
        return
    if _ITEMS is not None and time.time() - _LOADED_AT < RELOAD_SEC:
        return
    try:
        raw = state_store.state_load(STORE_NAME, [])
    except Exception:
        return          # 못 불러오면 있던 것을 쓴다. 비우지는 않는다.
    with _LOCK:
        _ITEMS = _fix_legacy(raw if isinstance(raw, list) else [])
        _LOADED_AT = time.time()


def _prune(items, now=None):
    """일주일 지난 것과 넘치는 것을 걷어낸다."""
    now = now or time.time()
    kept = [x for x in items if now - (x.get("ts") or 0) <= KEEP_SEC]
    return kept[-MAX_ITEMS:]


def held_text(sec):
    """얼마나 멈춰 있었는지."""
    if not sec or sec < 0:
        return ""
    m = int(sec // 60)
    if m < 1:
        return "%d초" % int(sec)
    if m < 60:
        return "%d분" % m
    return "%d시간 %d분" % (m // 60, m % 60)


def reason_of(event, error_code, by_error=None, held=None):
    """왜 그렇게 됐는지.

    일시정지 이유는 기기가 알려주지 않는다. 그래도 갈라낼 수 있다.
    멈추기 직전에 오류가 있었으면 오류 때문에 멈춘 것이고,
    멀쩡히 돌다가 멈췄으면 사람이 버튼을 누른 것이다.
    기기가 알려준 것은 아니지만 상태 변화로 알 수 있는 것이라 적어 둔다.
    """
    # 에러 코드가 문자열이 아닐 수도 있다. dict 가 오면 사전 조회에서 터진다.
    if error_code is not None and not isinstance(error_code, str):
        error_code = str(error_code)
    if event in ("error", "error_cleared"):
        if error_code:
            return ERROR_SHORT.get(error_code, "에러 코드 %s" % error_code)
        return "기기가 오류 상태로 보고함 (코드 없음)"
    if event == "pause":
        if by_error:
            detail = (ERROR_SHORT.get(error_code, "에러 코드 %s" % error_code)
                      if error_code else "기기가 오류 상태로 보고함")
            return "오류로 멈춤 — " + detail
        # 오류를 못 봤다고 해서 사람이 누른 것은 아니다.
        # 기기 상태는 5분에 한 번만 오므로 그 사이에 났다 사라진 오류는 안 보인다.
        # 예전에는 여기서 "사용자가 일시정지를 함" 이라고 단정했고,
        # 실제로 배수 오류로 멈춘 것을 사람 탓으로 적은 적이 있다.
        return ("원인을 가릴 수 없음 — 기기가 5분에 한 번만 상태를 알려줘서 "
                "그 사이에 났던 오류는 보이지 않을 수 있음")
    if event == "resume":
        t = held_text(held)
        return ("%s 멈춰 있다가 다시 돌기 시작함" % t) if t else "다시 돌기 시작함"
    if event == "nodata":
        return "기기가 상태를 보내지 않음 (전원 차단·통신 끊김·점검 중)"
    if event == "nodata_cleared":
        return "다시 상태를 보내기 시작함"
    return ""


def _already_open(tower_label, unit_type, event):
    """그 기기에 아직 안 풀린 같은 일이 이미 적혀 있는지.

    서버를 다시 띄울 때마다 '지금 이미 이 상태' 를 적으면, 계속 멈춰 있는
    기기 하나가 재시작 횟수만큼 쌓인다. 이미 적혀 있으면 넘어간다.
    """
    unit_name = "건조기" if unit_type == "dryer" else "세탁기"
    closer = {"error": "error_cleared", "pause": "resume",
              "nodata": "nodata_cleared"}.get(event)
    with _LOCK:
        items = _load()
    for x in reversed(items):
        if x.get("tower") != tower_label or x.get("unit") != unit_name:
            continue
        e = x.get("event")
        if e == event:
            return True         # 열려 있는 채로 남아 있다
        if e == closer:
            return False        # 이미 풀린 뒤다
    return False


# 같은 기기에 최근 오류가 있었는지 볼 때 쓰는 시간 창.
# 원본이 5분에 한 번만 갱신하므로, 그 사이에 났다 사라진 오류를 놓친다.
# 넉넉히 잡아야 "아까 오류 났던 그 기기" 를 이어서 볼 수 있다.
RECENT_ERROR_SEC = 45 * 60


def recent_error(tower_label, unit_type, within=None, now=None):
    """최근에 같은 기기에서 본 오류. 없으면 None.

    일시정지 원인을 가릴 때 쓴다. 직전 관측에서 오류를 못 봤더라도,
    조금 전에 같은 기기가 오류를 냈다면 그 사실을 함께 적어야 한다.
    """
    now = now or time.time()
    within = within or RECENT_ERROR_SEC
    _fresh()
    unit_name = "건조기" if unit_type == "dryer" else "세탁기"
    with _LOCK:
        items = list(_load())
    for x in reversed(items):
        if now - (x.get("ts") or 0) > within:
            break
        if x.get("tower") != tower_label or x.get("unit") != unit_name:
            continue
        if x.get("event") in ("error", "error_cleared"):
            return {"at": x.get("ts"), "error": x.get("error")}
    return None


def is_stopped(state, error=None):
    """돌다가 멈춘 상태인지. 오류든 일시정지든 같이 본다.

    왜 같이 보나. 원본이 5분에 한 번만 상태를 주므로, 오류가 났다가
    일시정지로 넘어가면 오류 화면을 아예 못 보고 지나간다. 오류만 보고
    알리면 그런 것은 놓친다. 실제로 배수 오류로 멈춘 건조기를 놓쳤다.

    알림을 걸어 둔 사람 입장에서는 둘 다 '내 빨래가 멈췄다' 이다.
    """
    return state in ("ERROR", "PAUSE") or bool(error)


def _snapshot(unit, state):
    """이번에 본 모습 중 기록에 쓰이는 것만."""
    err = None
    if isinstance(unit, dict):
        err = unit.get("error") or None
        # 문자열이 아니면 사전 조회와 비교에서 문제가 된다. 글로 바꿔 둔다.
        if err is not None and not isinstance(err, str):
            err = str(err)
    return {
        "state": state,
        "error": err,
        "is_error": bool(err) or state == "ERROR",
        "is_pause": state == "PAUSE",
        "is_nodata": state in ("UNKNOWN", "UNKNOWN_RUNNING"),
    }


def observe(tower_label, unit_type, unit, state, now=None):
    """기기 하나를 보고, 달라진 것이 있으면 기록을 만들어 돌려준다.

    돌려주는 것은 이번에 새로 생긴 기록들(없으면 빈 목록)이다.
    저장은 부르는 쪽에서 한 번에 한다. 5초마다 아홉 대를 보므로
    기기마다 저장하면 같은 일을 열여덟 번 하게 된다.
    """
    now = now or time.time()
    key = (tower_label, unit_type)
    cur = _snapshot(unit, state)
    prev = _PREV.get(key)
    _PREV[key] = cur

    made = []

    def add(event, code=None, note=None, by_error=None, held=None):
        item = {
            "ts": round(now, 3),
            "tower": tower_label,
            "unit": "건조기" if unit_type == "dryer" else "세탁기",
            "event": event,
            "label": EVENT_LABEL.get(event, event),
            "state": cur["state"],
            "error": code,
            "reason": reason_of(event, code, by_error, held),
        }
        if note:
            item["reason"] = note + " " + item["reason"]
        if event == "pause":
            # 오류를 직접 봤을 때만 'error' 다. 못 봤으면 'unknown' 이지 'user' 가 아니다.
            # 5분에 한 번만 보는 값으로 사람이 눌렀다고 단정할 수는 없다.
            item["cause"] = "error" if by_error else "unknown"
        if held:
            item["heldSec"] = round(held)
        made.append(item)

    if prev is None:
        # 서버가 막 떴다. 멀쩡한 기기는 남길 것이 없다.
        # 다만 이미 고장나 있거나 멈춰 있으면 남긴다. 안 남기면 관리자가
        # /이력 을 열었을 때, 눈앞에 고장난 기기가 있는데도 기록이 비어 있다.
        # 언제부터인지는 모르므로 그렇게 적는다.
        #
        # 다만 아직 안 풀린 같은 일이 이미 적혀 있으면 또 적지 않는다.
        # 코드를 고쳐 서버를 몇 번 다시 띄우면, 계속 멈춰 있는 기기 하나가
        # 재시작 횟수만큼 '일시정지' 로 쌓인다. 실제로 한 번 그랬다.
        note = "(서버가 뜰 때 이미 이 상태였음 — 시작 시각은 알 수 없음)"
        # 오류와 일시정지가 동시에 관측될 수 있다(예: 에러 코드가 붙은 채 PAUSE).
        # elif 로 묶으면 그런 기기는 pause 기록이 통째로 빠진다.
        if cur["is_error"]:
            if not _already_open(tower_label, unit_type, "error"):
                add("error", cur["error"], note)
        if cur["is_pause"]:
            if not _already_open(tower_label, unit_type, "pause"):
                # 멈추기 직전을 못 봤으므로 사람이 눌렀는지 오류였는지 가릴 수 없다.
                # 다만 지금 에러 코드가 붙어 있으면 그건 오류 때문이다.
                _PAUSE_SINCE[key] = now
                add("pause", cur["error"],
                    note, by_error=True if cur["error"] else None)
        elif cur["is_nodata"]:
            if not _already_open(tower_label, unit_type, "nodata"):
                add("nodata", None, note)
        return made

    # 오류. 코드가 바뀐 것도 새로운 오류로 본다.
    if cur["is_error"] and not prev["is_error"]:
        add("error", cur["error"])
    elif cur["is_error"] and prev["is_error"] and cur["error"] != prev["error"]:
        add("error", cur["error"])
    elif prev["is_error"] and not cur["is_error"]:
        add("error_cleared", prev["error"])

    # 일시정지. 왜 멈췄는지는 기기가 말해 주지 않지만, 직전에 무엇이었는지는 안다.
    # 오류에서 넘어왔으면 오류 때문이고, 멀쩡히 돌다 멈췄으면 사람이 누른 것이다.
    if cur["is_pause"] and not prev["is_pause"]:
        code = cur["error"] or prev["error"]
        by_error = bool(cur["is_error"] or prev["is_error"] or code)
        _PAUSE_SINCE[key] = now
        note = None
        if not by_error:
            # 오류를 직접 못 봤어도, 조금 전에 같은 기기가 오류를 냈다면
            # 그 사실을 함께 적는다. 사람 탓으로 돌리지 않기 위해서다.
            hit = recent_error(tower_label, unit_type, now=now)
            if hit:
                mins = int((now - (hit["at"] or now)) / 60)
                note = ("(%d분 전 같은 기기에서 %s 있었음 — 그 때문일 수 있음)"
                        % (mins, ERROR_SHORT.get(hit.get("error"), "오류")))
        add("pause", code if by_error else None, by_error=by_error, note=note)
    elif prev["is_pause"] and not cur["is_pause"]:
        since = _PAUSE_SINCE.pop(key, None)
        add("resume", None, held=(now - since) if since else None)

    # 값 끊김. 이것도 남긴다. "그때 왜 정보 없음이었나" 를 나중에 물어보게 된다.
    if cur["is_nodata"] and not prev["is_nodata"]:
        add("nodata")
    elif prev["is_nodata"] and not cur["is_nodata"]:
        add("nodata_cleared")

    return made


def append(new_items):
    """새 기록을 넣고 오래된 것을 걷어낸 뒤 저장한다."""
    global _IS_WRITER
    if not new_items:
        return 0
    _IS_WRITER = True         # 이 프로세스가 쓰는 쪽이다. 다시 불러오지 않는다.
    with _LOCK:
        items = _load()
        items.extend(new_items)
        pruned = _prune(items)
        del items[:]
        items.extend(pruned)
        state_store.state_save(STORE_NAME, items)
    return len(new_items)


def recent(limit=30, tower=None, unit=None, event=None):
    """최근 것부터. 관리자가 볼 때 쓴다."""
    _fresh()
    with _LOCK:
        items = _prune(_load())
    out = []
    for x in reversed(items):
        if tower and x.get("tower") != tower:
            continue
        if unit and x.get("unit") != unit:
            continue
        if event and x.get("event") != event:
            continue
        out.append(x)
        if len(out) >= limit:
            break
    return out


def summary():
    """일주일치를 한눈에. 어떤 기기가 자주 말썽인지 보려는 것."""
    _fresh()
    with _LOCK:
        items = _prune(_load())
    by_device = {}
    by_event = {}
    by_cause = {}
    for x in items:
        if x.get("event") in ("error", "pause", "nodata"):
            k = "%s %s" % (x.get("tower"), x.get("unit"))
            by_device[k] = by_device.get(k, 0) + 1
        e = x.get("event")
        by_event[e] = by_event.get(e, 0) + 1
        if e == "pause":
            c = x.get("cause") or "unknown"
            by_cause[c] = by_cause.get(c, 0) + 1
    return {
        "total": len(items),
        "byDevice": sorted(by_device.items(), key=lambda kv: -kv[1]),
        "byEvent": by_event,
        "byCause": by_cause,
        "oldest": min((x.get("ts") or 0) for x in items) if items else None,
    }
