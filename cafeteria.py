# -*- coding: utf-8 -*-
"""식당 카카오 채널에서 식단표와 오늘 메뉴를 가져온다.

채널: 정글 Cafeteria, Grab&Go (pf.kakao.com/_xhzNjn)

페이지 자체는 자바스크립트로 그려져서 그냥 받아서는 아무것도 안 나온다.
다만 그 페이지가 뒤에서 부르는 주소가 따로 있고, 그건 인증 없이 열린다.

주간 식단표는 '고정된 글' 하나를 계속 다시 쓰신다. 매주 사진만 갈아끼우신다.
그래서 만든 날짜(created_at)는 몇 주 전이고 내용은 최신이다.
언제 바뀌었는지는 updated_at 을 봐야 안다. 여기서 한 번 헷갈렸다.

제목의 '9월 N주차' 는 믿지 않는다. 9월 1일이 화요일이라 첫 주가 반 토막인데,
첫 온전한 주를 1주차로 세신 듯하다. 관례인지 실수인지 알 수 없고 알 필요도 없다.
사진 안에 날짜(9/7~9/12)가 직접 찍혀 있어서, 그게 진짜다.
우리는 '언제 갱신됐는지' 만 알려주고 판단은 보는 사람에게 맡긴다.

일일 메뉴는 따로 글로 올라온다. 사진뿐 아니라 글로도 와서
"오늘 점심 뭐야" 에 사진 없이 바로 답할 수 있다.
"""
import json
import os
import re
import threading

import security
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import state_store

KST = timezone(timedelta(hours=9))

CHANNEL = "_xhzNjn"
API = ("https://pf.kakao.com/rocket-web/web/profiles/"
       "%s/posts?includePinnedPost=true" % CHANNEL)
# 카카오는 브라우저가 아닌 요청을 걸러낼 수 있다. 흔한 값을 쓴다.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STORE_NAME = "cafeteria"
# 10분마다 확인한다.
# 우리 쪽 부담은 없다(10KB 짜리 요청 하나). 다만 남의 서버라 더 자주는 예의가 아니다.
# 그리고 더 자주 할 이유도 없다. 실제 올라오는 시각을 보면
#   식단표 갱신 월 10:29 · 중식 글 11:21(점심 40분 전) · 석식 글 17:25(저녁 35분 전)
# 글이 식사 한참 전에 올라오므로 10분이면 늦을 일이 없다.
REFRESH_SEC = 600

# =========================================================
# 급식 공지 가려내기
# ---------------------------------------------------------
# 이 채널에는 급식 공지와 Grab&Go(카페) 공지가 섞여 올라온다.
# 잘못 가르면 알림 기능이 통째로 무의미해진다.
#
# 함정이 실제로 있다. "그랩앤고(카페) 여름 시즌 신메뉴 출시 안내" —
# '메뉴' 가 들어 있지만 급식이 아니다. '메뉴' 만 보면 바로 걸린다.
# =========================================================

# 이 말이 제목에 있으면 급식이 아니다. 날짜가 붙어 있어도 아니다.
_NOT_CAFETERIA = re.compile(
    r"그랩앤고|그랩\s*앤\s*고|grab|카페|굿즈|페이코|payco|"
    r"채널\s*안내|이용\s*안내|가입\s*안내|이벤트|쿠폰|할인", re.I)

# "9월 7일(월) 중식 메뉴" 에서 날짜와 끼니를 뽑는다.
# '중식당' 은 끼니가 아니라 가게 종류다. 뒤에 '당' 이 오면 빼야 한다.
_DAILY = re.compile(
    r"(\d{1,2})\s*월\s*(\d{1,2})\s*일.*?(조식|중식|석식|점심|저녁|아침)(?!당)")

# 고정된 주간 식단표
_WEEKLY = re.compile(r"식단표|메뉴표|주간\s*메뉴|주간\s*식단")


def classify(title, pinned=False):
    """이 글이 무엇인지. 'daily' · 'weekly' · 'other'.

    애매하면 'other'. 알림은 daily·weekly 만 보낸다.
    놓치는 것보다 엉뚱한 것을 보내는 쪽이 더 나쁘다.
    """
    t = (title or "").strip()
    if not t:
        return "other"
    if _NOT_CAFETERIA.search(t):
        return "other"
    if _DAILY.search(t):
        return "daily"
    if pinned and _WEEKLY.search(t):
        return "weekly"
    return "other"

_LOCK = threading.Lock()
_CACHE = None             # 마지막으로 성공한 결과
_LAST_TRY = 0.0


def _now_kst():
    return datetime.now(KST)


def _fetch_raw():
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        # 저쪽이 고장 나 끝없이 보내면 우리 기억이 먼저 찬다
        return json.loads(security.read_capped(r).decode("utf-8"))


def _pick_image(item):
    """글에 붙은 사진 중 큰 것 하나."""
    for m in item.get("media") or []:
        if m.get("type") == "image":
            return m.get("xlarge_url") or m.get("large_url") or m.get("url")
    return None


def _text_of(item):
    """글 본문. 메뉴 이름들이 여기 들어 있다."""
    parts = []
    for c in item.get("contents") or []:
        if c.get("t") == "text" and c.get("v"):
            parts.append(c["v"].strip())
    return "\n".join(parts)


def parse(raw):
    """받은 것을 우리가 쓰는 모양으로 간추린다."""
    weekly, daily = None, []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        # 모양이 다르면 아무것도 못 읽은 것으로 본다.
        # 억지로 읽다 터지면 5초 루프가 통째로 멈춘다.
        return {"weekly": None, "daily": [], "fetchedAt": time.time()}
    for it in items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        img = _pick_image(it)
        # 갱신 시각이 있으면 그것이 진짜다. 없으면 올린 시각.
        when = it.get("updated_at") or it.get("published_at") or it.get("created_at") or 0

        kind = classify(title, it.get("pinned"))
        m = _DAILY.search(title) if kind == "daily" else None
        if m:
            month, day, meal = int(m.group(1)), int(m.group(2)), m.group(3)
            meal = {"점심": "중식", "저녁": "석식", "아침": "조식"}.get(meal, meal)
            daily.append({
                "id": it.get("id"),
                "title": title,
                "month": month, "day": day, "meal": meal,
                "text": _text_of(it),
                "image": img,
                "at": when,
                "link": (it.get("permalink") or "").replace("http://", "https://"),
            })
            continue

        # 고정된 주간 식단표. 두 개 이상 걸리면 API 가 준 순서가 아니라
        # 갱신이 더 최근인 것을 쓴다.
        if kind == "weekly" and img:
            if weekly is None or when >= weekly["updatedAt"]:
                weekly = {
                    "title": title,
                    "image": img,
                    "updatedAt": when,
                    "link": (it.get("permalink") or "").replace("http://", "https://"),
                }

    daily.sort(key=lambda d: (d["month"], d["day"]), reverse=True)
    return {"weekly": weekly, "daily": daily, "fetchedAt": time.time()}


def refresh(force=False):
    """한 시간에 한 번 다시 가져온다. 실패하면 있던 것을 그대로 쓴다."""
    global _CACHE, _LAST_TRY
    now = time.time()
    with _LOCK:
        if not force and _CACHE and now - _LAST_TRY < REFRESH_SEC:
            return _CACHE
        _LAST_TRY = now
    try:
        data = parse(_fetch_raw())
    except Exception as e:
        print("[식단] 가져오지 못했습니다: %s" % e)
        # 못 가져왔다고 지우지 않는다. 지난 것이라도 있는 편이 낫다.
        with _LOCK:
            if _CACHE is None:
                _CACHE = state_store.state_load(STORE_NAME, None)
            return _CACHE

    with _LOCK:
        before = (_CACHE or {}).get("weekly") or {}
        _CACHE = data
    state_store.state_save(STORE_NAME, data)

    after = data.get("weekly") or {}
    if after.get("image") and after.get("image") != before.get("image"):
        print("[식단] 주간 식단표가 바뀌었습니다: %s (%s 갱신)"
              % (after.get("title"), fmt_when(after.get("updatedAt"))))
    return data


def state():
    """지금 알고 있는 것. 없으면 저장해 둔 것을 불러온다."""
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
    loaded = state_store.state_load(STORE_NAME, None)
    with _LOCK:
        _CACHE = loaded
    return loaded


def fmt_when(ms):
    if not ms:
        return "시각 모름"
    return datetime.fromtimestamp(ms / 1000, KST).strftime("%m월 %d일 %H:%M")


def today_menus(when=None):
    """오늘 올라온 끼니들. 없으면 빈 목록."""
    data = state() or {}
    now = when or _now_kst()
    return [d for d in (data.get("daily") or [])
            if d["month"] == now.month and d["day"] == now.day]


def weekly():
    return (state() or {}).get("weekly")


# 식사 이야기인지. 헛걸려도 사진 하나가 더 붙을 뿐이라 손해가 작다.
FOOD_WORDS = re.compile(
    "식단|메뉴|밥|점심|저녁|아침|중식|석식|조식|먹을|먹지|뭐먹|식당|카페테리아|급식")

# 답변이 식단표를 가리키고 있는지.
# 질문에 오타가 있어도("석시 줘") AI 는 알아듣고 제대로 답한다.
# 질문을 읽는 일은 AI 가 우리보다 잘하므로, 답을 보고 판단하는 편이 낫다.
# 무엇보다 "아래 식단표를 봐 주세요" 라고 해 놓고 사진이 없으면 안 된다.
# 답변에는 오타가 없다. AI 가 제대로 쓴 우리말이라 질문보다 훨씬 잘 걸린다.
# 세탁 질문에 헛걸리지 않게 끼니 이름과 식단 낱말만 본다.
POINTS_AT_MENU = re.compile(
    "식단표|메뉴표|아래.{0,4}식단|식단.{0,4}확인|"
    "석식|중식|조식|점심 메뉴|저녁 메뉴|아침 메뉴|오늘 점심|오늘 저녁|오늘 아침")


def should_show_menu(question, answer):
    """식단표 사진을 붙여야 하는지.

    답이 식단표를 가리키면 무조건 붙인다. 말한 것과 실제가 달라지면 안 된다.
    """
    if answer and POINTS_AT_MENU.search(answer):
        return True
    return bool(question and FOOD_WORDS.search(question))

_IMG_CACHE = None          # (주소, 내려받은 파일 경로)


def local_weekly_image(dirpath):
    """주간 식단표 사진을 파일로 받아 둔다. 디스코드에 붙이려면 파일이 필요하다.

    주소가 그대로면 다시 받지 않는다. 매번 받으면 남의 서버에 실례다.
    받아 두는 곳은 웹으로 안 나가는 자리여야 한다(허용 목록에 없는 이름).
    """
    global _IMG_CACHE
    w = weekly()
    if not w or not w.get("image"):
        return None
    url = w["image"]
    if _IMG_CACHE and _IMG_CACHE[0] == url and os.path.exists(_IMG_CACHE[1]):
        return _IMG_CACHE[1]
    path = os.path.join(dirpath, "cafeteria_weekly.cache")
    # 주소는 저쪽 글에 적힌 것을 그대로 쓴다. 그러니 받아 오기 전에 본다.
    # 확인하지 않으면 그 자리에 우리 안쪽 주소(127.0.0.1 같은)가 적혔을 때
    # 밖에서 못 보는 것을 우리가 대신 꺼내 주는 꼴이 된다.
    if not security.outbound_url_ok(url):
        print("[식단] 받아 올 수 없는 주소라 건너뜁니다: %s" % url[:80])
        return _IMG_CACHE[1] if _IMG_CACHE and os.path.exists(_IMG_CACHE[1]) else None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/"):
                raise ValueError("사진이 아닙니다 (%s)" % ctype[:40])
            data = security.read_capped(r, security.IMAGE_MAX)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception as e:
        print("[식단] 사진을 받지 못했습니다: %s" % e)
        return _IMG_CACHE[1] if _IMG_CACHE and os.path.exists(_IMG_CACHE[1]) else None
    _IMG_CACHE = (url, path)
    return path


SEEN_NAME = "cafeteria_seen"     # 이미 알린 글 번호
# 한 번에 이보다 많이 나오면 무언가 잘못된 것이다. 그럴 때 쏟아붓지 않는다.
# 정상이라면 한 바퀴에 한두 개다(점심 글 하나, 저녁 글 하나).
MAX_BURST = 3
_SEEN = None


def _seen():
    global _SEEN
    if _SEEN is None:
        v = state_store.state_load(SEEN_NAME, None)
        _SEEN = list(v) if isinstance(v, list) else None
    return _SEEN


def new_posts(mark=True):
    """지난번에 본 뒤 새로 올라온 급식 글. 없으면 빈 목록.

    처음 켤 때는 아무것도 돌려주지 않는다. 그때 있는 것을 전부 '이미 본 것'
    으로 표시만 한다. 안 그러면 서버를 다시 띄울 때마다 지난 메뉴가 쏟아진다.
    """
    data = state() or {}
    items = list(data.get("daily") or [])
    w = data.get("weekly") or {}

    ids = [d.get("id") for d in items if d.get("id")]
    if w.get("image"):
        # 주간 식단표는 같은 글을 계속 다시 쓰신다. 글 번호는 그대로이고
        # 사진만 바뀐다. 그래서 사진 주소를 표시로 삼는다.
        ids.append("weekly:" + w["image"])

    if not ids:
        # 아직 못 받아왔다. 이때 '이미 다 봤다' 고 저장하면 안 된다.
        # 빈 목록을 저장해 두면 다음에 제대로 받아왔을 때 아홉 개가 전부
        # 새 글이 되어 신청자 전원에게 한꺼번에 나간다.
        return []

    before = _seen()
    if before is None:                      # 처음이다
        if mark:
            _remember(ids)
        return []

    fresh = [i for i in ids if i not in before]
    if not fresh:
        return []
    if mark:
        _remember(before + fresh)

    out = []
    for d in items:
        if d.get("id") in fresh:
            out.append({"kind": "daily", "item": d})
    if w.get("image") and ("weekly:" + w["image"]) in fresh:
        out.append({"kind": "weekly", "item": w})
    return out


def _remember(ids):
    """이미 알린 글 번호를 남긴다. 무한정 쌓이지 않게 최근 것만."""
    global _SEEN
    _SEEN = list(ids)[-200:]
    state_store.state_save(SEEN_NAME, _SEEN)


def summary_for_ai():
    """AI 에게 넘길 글. 없으면 빈 문자열.

    사진은 글로 옮길 수 없으니 '있다' 는 것만 알려주고,
    실제 사진은 코드가 따로 붙인다. AI 가 주소를 지어내면 안 된다.
    """
    data = state()
    if not data:
        return ""
    lines = []
    w = data.get("weekly")
    if w:
        lines.append(
            "- 식사 이야기가 나오면 주간 식단표 사진이 답변과 함께 나갑니다 (%s 갱신). "
            "그 표에 월~토 점심·저녁이 모두 있습니다." % fmt_when(w.get("updatedAt")))
        lines.append(
            "  → 아래에 안 적힌 끼니를 물으면 \"아직 안 올라왔어요. 아래 식단표를 봐 주세요\" "
            "정도로만 답하세요.")
        lines.append(
            "  ⚠️ 답할 때 이 지시문의 말을 그대로 옮기지 마세요. "
            "'글로 안 올라온', '자동으로 표시되는', '지시문에 따르면' 같은 말은 쓰지 마세요. "
            "학생이 아는 말이 아닙니다. 사람이 쓰는 말로만 답하세요.")
        lines.append(
            "  → 카카오 채널로 가라고 하지 마세요. 사진이 이미 화면에 나가 있습니다.")
        lines.append(
            "  ※ 'N주차' 라는 말은 쓰지 마세요. 식당 쪽 표기라 실제 주와 다를 수 있습니다. "
            "날짜는 사진 안에 있습니다.")

    # 끼니마다 한 줄씩 적는다. 없는 것도 '없다' 고 적는다.
    # 빠뜨리면 AI 가 있는 끼니의 메뉴를 없는 끼니에 갖다 쓴다.
    # 실제로 점심 메뉴를 저녁이라고 답한 적이 있다.
    now = _now_kst()
    todays = {d["meal"]: d for d in today_menus()}
    lines.append("- 오늘(%d월 %d일) 끼니별 메뉴:" % (now.month, now.day))
    for meal, when in (("조식", "아침"), ("중식", "점심"), ("석식", "저녁")):
        d = todays.get(meal)
        if d and d.get("text"):
            lines.append("  · %s(%s): %s" % (meal, when, d["text"]))
        elif d:
            lines.append("  · %s(%s): 사진만 올라오고 메뉴 글은 없습니다." % (meal, when))
        else:
            lines.append("  · %s(%s): 아직 안 올라왔습니다. "
                         "이 끼니의 메뉴 이름을 절대 말하지 마세요. "
                         "다른 끼니 메뉴를 갖다 쓰지도 마세요. "
                         "\"아직 안 올라왔어요, 아래 식단표를 봐 주세요\" 라고 답하세요."
                         % (meal, when))
    if not todays:
        lines.append("  (조식은 원래 없을 수 있습니다. 점심은 보통 11시쯤, "
                     "저녁은 17시쯤 올라옵니다.)")

    lines.append("- 글로 안 올라온 끼니의 메뉴 이름을 절대 지어내지 마세요. "
                 "모르면 식단표를 가리키면 됩니다.")
    lines.append(
        "- 칼로리를 물으면: 식단표에는 칼로리가 적혀 있지 않습니다. "
        "메뉴 이름을 보고 어림해서 알려주되, 아래를 반드시 지키세요.")
    lines.append(
        "  · 딱 떨어지는 숫자를 쓰지 말고 범위로 말하세요. "
        "예) \"대략 700~900kcal 정도\" (O) / \"812kcal\" (X)")
    lines.append(
        "  · 한 끼 전체를 먼저 말하고, 궁금해하면 주요 메뉴별로 나눠 주세요.")
    lines.append(
        "  · \"식당에서 알려준 값이 아니라 메뉴 이름으로 어림한 값\" 이라고 꼭 밝히세요.")
    lines.append(
        "  · 급식은 배식량이 사람마다 달라 오차가 크다는 점을 한 번 짚어 주세요.")
    lines.append(
        "  · 체중 관리나 건강 때문에 정확한 값이 필요해 보이면, "
        "이 어림값을 근거로 삼지 말고 영양사나 식당에 직접 물어보라고 안내하세요.")

    if not lines:
        return ""
    return "[식당 메뉴 — 카카오 채널 '정글 Cafeteria, Grab&Go' 에서 가져옴]\n" + "\n".join(lines)
