# -*- coding: utf-8 -*-
"""밖에서 들어오는 것과 밖으로 나가는 것을 지킨다.

여기 있는 것은 전부 순수한 판단 함수다. 서버를 띄우지 않고도 시험할 수 있게
따로 뒀다. 실제로 막는 일은 start_server.py 와 discord_bot.py 가 한다.

무엇을 막나.

  들어오는 쪽
    · 다른 사이트가 우리 API 와 AI 중계를 제 것처럼 쓰는 것 (CORS)
      지금까지 모든 응답에 'Access-Control-Allow-Origin: *' 이 붙어 있었다.
      아무 사이트나 자기 페이지에서 우리 AI 를 불러 우리 키를 태울 수 있었다.
    · 한 사람이 몰아쳐서 서버를 재우거나 AI 한도를 태우는 것 (횟수 제한)
    · 우리가 열어 준 적 없는 주소를 원본 서버로 넘겨 대신 두드리게 하는 것
    · 브라우저 안에서 벌어지는 끼워넣기·감싸기 (보안 헤더)

  나가는 쪽
    · 남의 서버가 끝없이 보내는 응답으로 우리 기억을 채우는 것 (크기 상한)
    · 남이 준 주소를 우리가 아무거나 대신 받아다 주는 것 (주소 확인)
      그 주소가 127.0.0.1 이나 사내 주소를 가리키면, 밖에서 못 보는 것을
      우리가 대신 꺼내 주는 꼴이 된다.

이것으로 막히지 않는 것도 적어 둔다. 모르면 막은 줄 안다.
    · 서버에 직접 들어온 사람. 그건 SSH 열쇠와 방화벽의 몫이다.
    · 사람이 curl 로 두드리는 것. Origin 은 브라우저만 붙이므로 없을 수도
      있고, 그때는 막지 않는다. 다만 횟수 제한에는 똑같이 걸린다.
    · 이미 밖으로 나간 값. 그건 바꾸는 수밖에 없다.
"""
import os
import threading
import time
from urllib.parse import urlsplit


def _env_list(name, default):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return tuple(default)
    return tuple(x.strip().lower() for x in raw.split(",") if x.strip())


# 우리 사이트로 인정하는 곳. 여기에 없는 곳에서 온 요청에는
# 브라우저가 응답을 읽도록 허락하지 않는다(CORS 헤더를 안 준다).
SITE_HOSTS = _env_list("SITE_HOSTS", (
    "krafton-jungle.duckdns.org",
    "localhost",
    "127.0.0.1",
))

# 우리 앞에 서 있는 것. 여기서 온 요청만 X-Forwarded-For 를 믿는다.
LOCAL_PEERS = ("127.0.0.1", "::1", "localhost", "")


def is_local(peer):
    return (peer or "").strip() in LOCAL_PEERS


def host_of(url_or_host):
    """주소에서 호스트만 떼어낸다. 포트와 사용자 부분은 버린다."""
    s = (url_or_host or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = urlsplit(s).netloc
    if "@" in s:
        s = s.split("@")[-1]
    if s.startswith("["):                 # IPv6 [::1]:8000
        return s.split("]")[0] + "]"
    return s.split(":")[0]


def real_ip(peer, xff):
    """진짜 보낸 사람의 주소.

    Caddy 뒤에 있어서 peer 는 늘 127.0.0.1 이다. 그래서 X-Forwarded-For 를
    봐야 하는데, 그 값의 맨 앞은 보낸 사람이 제 손으로 적을 수 있다.
    헤더 한 줄만 바꿔 가며 횟수 제한을 무한정 피할 수 있다는 뜻이다.

    Caddy 는 '자기가 실제로 본 주소' 를 목록 맨 뒤에 붙인다.
    그래서 맨 뒤를 쓴다. 앞의 것은 보낸 사람이 지어낸 것일 수 있다.

    앞에 아무도 없이 바로 들어온 요청이면 헤더는 아예 믿지 않는다.
    """
    peer = (peer or "?").strip()
    if not is_local(peer):
        return peer
    parts = [x.strip() for x in (xff or "").split(",") if x.strip()]
    return parts[-1] if parts else peer


def origin_ok(origin, referer, host_header):
    """브라우저가 말해 준 출처가 우리 것인지.

    돌려주는 값은 셋이다.
      True  — 우리 사이트에서 왔다
      False — 남의 사이트에서 왔다
      None  — 알 수 없다 (헤더가 없다. 브라우저가 아닌 것일 수 있다)

    None 을 막지 않는 이유. 브라우저는 POST 에 Origin 을 반드시 붙이지만,
    봇이 우리 서버에 물어보는 것처럼 브라우저가 아닌 것은 안 붙인다.
    그것까지 막으면 우리 봇이 먼저 멈춘다. 대신 횟수 제한으로 다룬다.
    """
    src = (origin or "").strip() or (referer or "").strip()
    if not src:
        return None
    if src.lower() == "null":
        # 모래상자 안의 프레임이나 file:// 에서 온 것. 우리 페이지는 이렇게 안 온다.
        return False
    h = host_of(src)
    if not h:
        return None
    if h in SITE_HOSTS:
        return True
    return h == host_of(host_header)


class Limiter:
    """일정 시간 안에 몇 번까지 되는지 센다.

    요청마다 도는 것이라 가벼워야 한다. 사람마다 시각 목록 하나만 두고,
    셀 때 오래된 것을 함께 버린다.

    같은 것을 두 곳(웹·봇)에서 쓰므로 잠금을 안에 둔다.
    """

    MAX_KEYS = 4000        # 주소를 바꿔 가며 두드려도 기억이 새지 않게

    def __init__(self, limit, window, name=""):
        self.limit = int(limit)
        self.window = float(window)
        self.name = name
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, now=None):
        """한 번 쓴 것으로 치고, 써도 되면 True."""
        now = now or time.time()
        key = key or "?"
        with self._lock:
            seen = [t for t in self._hits.get(key, ()) if now - t < self.window]
            if len(seen) >= self.limit:
                self._hits[key] = seen
                return False
            seen.append(now)
            self._hits[key] = seen
            if len(self._hits) > self.MAX_KEYS:
                self._sweep(now)
            return True

    def _sweep(self, now):
        """다 지난 것들을 버린다. 잠금 안에서만 부른다."""
        dead = [k for k, v in self._hits.items()
                if not v or now - v[-1] > self.window]
        for k in dead:
            self._hits.pop(k, None)
        if len(self._hits) > self.MAX_KEYS:
            # 그래도 많으면 오래된 순으로 절반을 버린다.
            order = sorted(self._hits.items(), key=lambda kv: kv[1][-1])
            for k, _ in order[:len(order) // 2]:
                self._hits.pop(k, None)


# 원본 서버로 넘겨 주는 주소. 여기 없는 것은 넘기지 않는다.
#
# 예전에는 /api/ 로 시작하기만 하면 무엇이든 원본으로 넘겼다. 우리 서버가
# 남의 심부름꾼이 되는 길이었고, 원본(무료 터널)이 그 트래픽 때문에
# 막히면 우리 화면도 같이 죽는다.
PROXY_ALLOW = ("/api/status", "/api/stats")
QUERY_MAX = 200                 # 물음표 뒤가 이보다 길면 받지 않는다


def proxy_path_ok(path):
    p = (path or "")
    head, _, query = p.partition("?")
    if head not in PROXY_ALLOW:
        return False
    return len(query) <= QUERY_MAX


# 브라우저에게 주는 규칙.
#
# script-src 'self' — 우리 파일에서 온 코드만 돈다. 어딘가에서 글이 끼어들어
#   <script> 가 심어져도 남의 주소에서는 못 불러온다.
# style-src 에 'unsafe-inline' 이 있는 것은 화면 코드가 style="" 을 쓰기
#   때문이다. 이것까지 막으면 화면이 무너진다. 지금은 여기까지가 한계다.
# img-src 에 https: 를 연 것은 식단표 사진이 카카오 주소로 오기 때문이다.
# frame-ancestors 'none' — 남의 사이트가 우리 화면을 액자에 넣어
#   가짜 버튼을 덧씌우는 것을 막는다.
CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
    "https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net",
    "img-src 'self' data: blob: https:",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
))

HEADERS = (
    ("X-Content-Type-Options", "nosniff"),        # 확장자와 다른 것으로 읽지 마라
    ("X-Frame-Options", "DENY"),                  # 액자에 넣지 마라 (옛 브라우저용)
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy",
     "geolocation=(), microphone=(), camera=(), payment=(), usb=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    # 우리 파일(그림·코드·응답)을 남의 페이지가 끌어다 쓰지 못하게 한다.
    # 링크 미리보기는 저쪽 서버가 직접 받아 가는 것이라 그대로 나온다.
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Content-Security-Policy", CSP),
)


# ── 나가는 쪽 ──────────────────────────────────────────────────────────
# 남의 서버에서 받아 오는 것에 상한을 둔다. 상대가 무한정 보내면
# 우리 기억이 먼저 찬다. 상대가 나빠서가 아니라, 고장 나도 그렇게 된다.
FETCH_MAX = 3 * 1024 * 1024          # 3MB
IMAGE_MAX = 8 * 1024 * 1024          # 사진은 좀 더 크다


def read_capped(resp, limit=FETCH_MAX):
    """응답을 읽되 상한을 둔다. 넘치면 읽지 않고 버린다."""
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("응답이 너무 큽니다 (%d바이트 넘음)" % limit)
    return data


# 우리가 대신 받아 와도 되는 곳. 식단표 사진이 오는 카카오 쪽이다.
IMAGE_HOSTS = ("kakaocdn.net", "daumcdn.net", "kakao.com", "kakaoentcdn.com")


def outbound_url_ok(url, hosts=IMAGE_HOSTS):
    """남이 알려준 주소를 우리가 받아 와도 되는지.

    https 여야 하고, 아는 곳이어야 한다.
    이것을 안 보면 주소가 127.0.0.1 이나 사내 주소를 가리킬 때
    밖에서 못 보는 것을 우리가 대신 꺼내 주게 된다.
    """
    s = (url or "").strip()
    if not s.lower().startswith("https://"):
        return False
    h = host_of(s)
    if not h:
        return False
    return any(h == d or h.endswith("." + d) for d in hosts)
