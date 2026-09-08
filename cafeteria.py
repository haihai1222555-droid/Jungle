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
import re
import threading
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

# "9월 7일(월) 중식 메뉴" 같은 제목에서 날짜와 끼니를 뽑는다
_DAILY = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일.*?(조식|중식|석식|점심|저녁|아침)")

_LOCK = threading.Lock()
_CACHE = None             # 마지막으로 성공한 결과
_LAST_TRY = 0.0


def _now_kst():
    return datetime.now(KST)


def _fetch_raw():
    req = urllib.request.Request(API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


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
    for it in (raw.get("items") or []):
        title = (it.get("title") or "").strip()
        img = _pick_image(it)
        # 갱신 시각이 있으면 그것이 진짜다. 없으면 올린 시각.
        when = it.get("updated_at") or it.get("published_at") or it.get("created_at") or 0

        m = _DAILY.search(title)
        if m:
            month, day, meal = int(m.group(1)), int(m.group(2)), m.group(3)
            meal = {"점심": "중식", "저녁": "석식", "아침": "조식"}.get(meal, meal)
            daily.append({
                "title": title,
                "month": month, "day": day, "meal": meal,
                "text": _text_of(it),
                "image": img,
                "at": when,
                "link": (it.get("permalink") or "").replace("http://", "https://"),
            })
            continue

        # 고정된 글이면서 식단표로 보이는 것
        if it.get("pinned") and img and re.search(r"식단|메뉴표|주간", title):
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
        lines.append("- 주간 식단표 사진이 있습니다 (%s 갱신). "
                     "물어보면 사진을 함께 보여줍니다." % fmt_when(w.get("updatedAt")))
        lines.append("  ※ 제목의 'N주차' 는 식당 쪽 표기라 실제 주와 다를 수 있습니다. "
                     "날짜는 사진 안에 적혀 있으니 사진을 보라고 안내하세요.")

    todays = today_menus()
    if todays:
        now = _now_kst()
        lines.append("- 오늘(%d월 %d일) 메뉴:" % (now.month, now.day))
        for d in sorted(todays, key=lambda x: {"조식": 0, "중식": 1, "석식": 2}.get(x["meal"], 9)):
            lines.append("  · %s: %s" % (d["meal"], d["text"] or "(메뉴 글 없음, 사진만 올라옴)"))
    else:
        lines.append("- 오늘 메뉴 글은 아직 안 올라왔습니다. "
                     "지어내지 말고 아직 공지 전이라고 안내하세요.")

    if not lines:
        return ""
    return "[식당 메뉴 — 카카오 채널 '정글 Cafeteria, Grab&Go' 에서 가져옴]\n" + "\n".join(lines)
