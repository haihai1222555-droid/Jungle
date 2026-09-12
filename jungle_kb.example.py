# -*- coding: utf-8 -*-
"""안내 지식 파일의 본보기.

이 파일을 `jungle_kb.py` 로 복사해 내용을 채워 넣으면 된다.
봇과 웹의 AI 가 질문에 답할 때 근거로 삼는 자료다.

    cp jungle_kb.example.py jungle_kb.py

실제 `jungle_kb.py` 는 저장소에 올리지 않는다(.gitignore).
기관 내부 자료가 들어가기 때문이다.
파일이 없어도 세탁실 기능은 그대로 동작한다 — 생활 안내만 답하지 못한다.
"""

# 언제나 함께 보내는 기본 정보. 짧게 유지한다.
BASE = """[기본 정보]
- 여기에 조직 이름, 위치, 문의처 같은 것을 적는다.
- 매 질문마다 통째로 보내므로 꼭 필요한 것만 남긴다."""


# 질문에 맞는 것만 골라 보낼 항목들.
# keywords 는 사용자가 쓸 법한 말을 넉넉히 적어 둔다. 하나라도 걸리면 뽑힌다.
SECTIONS = [
    {
        "id": "laundry",
        "keywords": ["세탁", "빨래", "건조", "세탁실", "세탁기", "건조기"],
        "text": """[세탁실]
- 이용 시간, 위치, 주의사항 같은 것을 적는다.
- 줄바꿈으로 구분하면 AI 가 읽기 좋다.""",
    },
    {
        "id": "example",
        "keywords": ["예시", "샘플"],
        "text": """[예시 항목]
- 항목을 필요한 만큼 늘리면 된다.""",
    },
]


# 질문에 맞춰 함께 보낼 사진. assets/ 에 같은 이름으로 넣는다.
# 사진이 없으면 글로만 답하므로 비워 두어도 된다.
IMAGES = [
    # {"file": "example.webp", "caption": "사진 설명",
    #  "keywords": ["사진", "어디"]},
]


# 답변 끝에 붙일 수 있는 링크 목록. 질문과 무관하게 늘 같으므로
# 프롬프트 앞쪽에 놓여 캐시된다.
LINK_BLOCK = """[안내 페이지 링크]
- 예시: 이용 안내 https://example.com"""


def _kw_match(text, keywords):
    """질문에 이 항목의 낱말이 들어 있는지."""
    t = (text or "").replace(" ", "").lower()
    return any(k.replace(" ", "").lower() in t for k in keywords)


def find_sections(text, limit=None):
    """질문에 걸리는 항목을 앞에서부터 골라 돌려준다."""
    hits = [s for s in SECTIONS if _kw_match(text, s["keywords"])]
    return hits[:limit] if limit else hits


def find_image(text):
    """질문에 맞는 사진 하나. 없으면 None."""
    for img in IMAGES:
        if _kw_match(text, img["keywords"]):
            return img
    return None


def build_context(text=None, limit=None):
    """AI 에게 넘길 안내 지식 문자열을 만든다.

    링크 목록은 질문과 무관하게 늘 같아서 앞에 둔다.
    앞부분이 매번 같아야 AI 서버가 캐시를 쓸 수 있고,
    그만큼 토큰 한도에서도 빠진다.
    """
    parts = [BASE, LINK_BLOCK]
    if limit:
        # 요청 크기 제한이 빡빡한 엔진에는 관련 있는 것만 넣는다
        parts.extend(sec["text"] for sec in find_sections(text or "", limit=limit))
    elif text:
        picked = find_sections(text, limit=len(SECTIONS))
        seen = {id(sec) for sec in picked}
        parts.extend(sec["text"] for sec in picked)
        parts.extend(sec["text"] for sec in SECTIONS if id(sec) not in seen)
    else:
        parts.extend(sec["text"] for sec in SECTIONS)
    return "\n\n".join(parts)
