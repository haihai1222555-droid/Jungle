# -*- coding: utf-8 -*-
"""이 세탁실에 놓인 기기가 무엇이고 어떤 코스를 가지고 있는지.

한곳에만 적는다. 봇은 이 파일을 그대로 읽고, 웹은 서버가 열어 주는
/api/courses 로 받아 간다. 두 곳에 따로 적으면 언젠가 한쪽만 고쳐진다.

⚠️ 여기 적힌 코스는 기기에서 읽어 온 것이 아니다. 원본 API 가 주는 값은
   runState · timer · cycleCount · error 넷뿐이고 코스는 오지 않는다.
   그래서 "지금 몇 호기가 무슨 코스로 도는지" 는 알 수 없다.
   예전에는 그걸 상태로부터 지어내 화면과 봇 이미지에 띄웠다.
   탈수 중이면 무조건 'AI 맞춤 세탁', 건조기 일시정지면 무조건 '이불 건조'.
   근거가 없는 말이라 걷어냈다. 대신 기기가 실제로 주는 '총 가동 시간' 을
   보여 준다. 코스마다 길이가 달라서 그편이 훨씬 쓸모 있다.

여기 목록은 '이 기기에 어떤 코스가 있는지' 를 알려주기 위한 것이다.
근거는 같은 해·같은 용량(세탁 25kg / 건조 22kg) 제품의 LG 공식 제품 정보다.
W22KJUR 자체는 공개된 제품 페이지가 없다(기관 납품 모델로 보인다).
그래서 조작부에 없는 이름이 섞여 있을 수 있고, 화면에도 그렇게 적어 둔다.
"""

MODEL = "LG 트롬 워시타워 W22KJUR"
MODEL_YEAR = "2024년형"
CAPACITY = "세탁 25kg / 건조 22kg"
CONTROL = "조작부는 세탁기와 건조기 사이의 Center Control 한 곳"

# 기기에 처음부터 들어 있는 코스.
# hint 는 "언제 쓰는 것인지" 한 줄. 없으면 이름만 보여 준다.
WASH_COURSES = [
    {"name": "표준",         "hint": "평소 빨래. 5방향 터보샷이 들어간다"},
    {"name": "인공지능세탁",  "hint": "무게·옷감·오염도를 기기가 재서 알아서 맞춘다"},
    {"name": "이불",         "hint": "이불·침구. 부피가 크면 나눠 넣는다"},
    {"name": "소량급속",     "hint": "적은 양을 빨리"},
    {"name": "울·섬세",      "hint": "니트·울·얇은 옷"},
    {"name": "알뜰삶음",     "hint": "수건·흰 면·찌든 냄새. 고온이라 색 있는 옷은 물이 빠진다"},
    {"name": "타올",         "hint": "수건. 섬유유연제는 넣지 않는다"},
    {"name": "셔츠한벌",     "hint": "셔츠 한두 장"},
    {"name": "아기옷",       "hint": "헹굼을 넉넉히 한다"},
    {"name": "헹굼+탈수",    "hint": "세제 없이 헹구고 짜기만"},
    {"name": "탈수단독",     "hint": "짜기만"},
    {"name": "통살균",       "hint": "세탁조 청소. 빨래를 모두 뺀 빈 상태로 돌린다"},
]

DRY_COURSES = [
    {"name": "표준",         "hint": "평소 건조"},
    {"name": "인공지능건조",  "hint": "습도를 재서 다 마르면 알아서 멈춘다"},
    {"name": "이불",         "hint": "이불·침구"},
    {"name": "소량급속",     "hint": "적은 양을 빨리"},
    {"name": "울·섬세",      "hint": "얇은 옷. 니트는 널어 말리는 편이 낫다"},
    {"name": "침구털기",     "hint": "말리지 않고 먼지만 턴다"},
    {"name": "타올",         "hint": "수건"},
    {"name": "패딩리프레쉬",  "hint": "세탁 후 뭉친 패딩을 털어 준다"},
    {"name": "시간건조",     "hint": "시간을 직접 정한다"},
    {"name": "스팀살균",     "hint": "찌든 냄새. 알뜰삶음 뒤에 쓰면 좋다"},
    {"name": "스팀리프레쉬",  "hint": "빨지 않고 냄새만 뺀다"},
    {"name": "스팀통살균",    "hint": "건조통 청소"},
]

# ThinQ 로 내려받아야 생기는 코스. 공용 기기에는 없을 수 있어 따로 적는다.
DOWNLOAD_NOTE = (
    "찌든 때 · 기능성 의류 · 컬러케어 · 찬물 세탁 · 조용조용 같은 코스는 "
    "ThinQ 앱에서 내려받아야 생깁니다. 공용 기기에는 없을 수 있어요."
)

DISCLAIMER = (
    "코스 이름은 같은 해·같은 용량 제품 기준입니다. "
    "조작부에서 안 보이면 조작부에 적힌 이름을 따라 주세요."
)


def total_minutes(unit):
    """이 기기가 잡아 둔 전체 가동 시간(분). 모르면 0.

    코스는 안 오지만 전체 시간은 온다. 코스마다 길이가 달라서
    '총 39분' 인지 '총 2시간' 인지만 알아도 짐작이 된다.
    """
    if not isinstance(unit, dict):
        return 0
    t = unit.get("timer")
    t = t if isinstance(t, dict) else {}
    out = 0
    for k, mul in (("totalHour", 60), ("totalMinute", 1)):
        try:
            out += int(t.get(k)) * mul
        except (TypeError, ValueError):
            pass          # 숫자가 아니면 없는 것으로 본다. 지어내지 않는다.
    return out


def format_minutes(m):
    """분을 사람이 읽는 말로. 0이면 빈 문자열."""
    m = int(m or 0)
    if m <= 0:
        return ""
    if m < 60:
        return "%d분" % m
    h, mm = divmod(m, 60)
    return "%d시간" % h if mm == 0 else "%d시간 %d분" % (h, mm)


def as_dict():
    """웹에 그대로 내려보낼 모양."""
    return {
        "model": MODEL,
        "year": MODEL_YEAR,
        "capacity": CAPACITY,
        "control": CONTROL,
        "washer": WASH_COURSES,
        "dryer": DRY_COURSES,
        "downloadNote": DOWNLOAD_NOTE,
        "disclaimer": DISCLAIMER,
    }
