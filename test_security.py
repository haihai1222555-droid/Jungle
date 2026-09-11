# -*- coding: utf-8 -*-
"""잠근 것이 정말 잠겼는지 확인한다.

여기 있는 것은 전부 순수한 판단이라 서버 없이 돌아간다.
`python test_security.py` 로 돌리고, 하나라도 틀리면 0 이 아닌 값으로 끝난다.

시험이 통과한다고 안전한 것은 아니다. 여기서 보는 것은 우리가 짠 규칙이
우리 뜻대로 판단하는지까지다. 규칙 자체가 부족한 부분은 security.py 맨 위에
적어 뒀다.
"""
import sys
import time

import security

# 윈도우 콘솔은 기본이 cp949 라 '—' 같은 글자에서 터진다.
# 시험 결과보다 먼저 터져버리면 곤란하다.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append("%s → %r (%r 여야 함)" % (name, got, want))


# =========================================================
# 1. 진짜 보낸 사람 가려내기
#    헤더 한 줄로 횟수 제한을 피할 수 있으면 제한이 없는 것과 같다
# =========================================================
def test_real_ip():
    # Caddy 뒤. 맨 뒤가 Caddy 가 실제로 본 주소다.
    check("Caddy 뒤 정상", security.real_ip("127.0.0.1", "203.0.113.9"), "203.0.113.9")
    # 보낸 사람이 앞에 가짜를 적어 넣었다. 그래도 맨 뒤를 쓴다.
    check("지어낸 앞자리 무시",
          security.real_ip("127.0.0.1", "1.1.1.1, 203.0.113.9"), "203.0.113.9")
    # 헤더가 없으면 같은 기계에서 온 것 (우리 봇)
    check("헤더 없음", security.real_ip("127.0.0.1", None), "127.0.0.1")
    check("헤더 빈 값", security.real_ip("127.0.0.1", "  ,  "), "127.0.0.1")
    # 앞에 아무도 없이 바로 들어왔으면 헤더는 아예 안 믿는다
    check("직접 들어온 요청",
          security.real_ip("198.51.100.7", "1.1.1.1"), "198.51.100.7")

    check("같은 기계인가", security.is_local("127.0.0.1"), True)
    check("남의 기계인가", security.is_local("203.0.113.9"), False)


# =========================================================
# 2. 남의 사이트가 우리 것을 제 것처럼 쓰는 것
# =========================================================
def test_origin():
    ours = "krafton-jungle.duckdns.org"
    check("우리 사이트",
          security.origin_ok("https://%s" % ours, None, ours), True)
    check("우리 사이트 (포트까지)",
          security.origin_ok("http://localhost:8000", None, "localhost:8000"), True)
    check("남의 사이트",
          security.origin_ok("https://evil.example", None, ours), False)
    # 이름 앞에 우리 이름을 붙여 속이는 수법
    check("이름만 비슷한 곳",
          security.origin_ok("https://krafton-jungle.duckdns.org.evil.example",
                             None, ours), False)
    check("헤더 없음", security.origin_ok(None, None, ours), None)
    check("모래상자 프레임", security.origin_ok("null", None, ours), False)
    # Origin 이 없으면 Referer 라도 본다
    check("Referer 로 판단",
          security.origin_ok(None, "https://evil.example/a/b", ours), False)


# =========================================================
# 3. 몰아쳐 두드리는 것
# =========================================================
def test_limiter():
    lim = security.Limiter(3, 60)
    t = 1000.0
    check("1번째", lim.allow("a", t), True)
    check("2번째", lim.allow("a", t), True)
    check("3번째", lim.allow("a", t), True)
    check("4번째는 막힘", lim.allow("a", t), False)
    check("다른 사람은 안 막힘", lim.allow("b", t), True)
    check("시간이 지나면 풀림", lim.allow("a", t + 61), True)

    # 주소를 바꿔 가며 두드려도 기억이 새지 않아야 한다
    lim2 = security.Limiter(1, 1)
    now = time.time()
    for i in range(security.Limiter.MAX_KEYS + 500):
        lim2.allow("who-%d" % i, now)
    check("기억이 새지 않는지", len(lim2._hits) <= security.Limiter.MAX_KEYS, True)


# =========================================================
# 4. 원본 서버로 넘겨 주는 주소
#    아무거나 넘기면 우리 서버가 남의 심부름꾼이 된다
# =========================================================
def test_proxy_path():
    check("상태", security.proxy_path_ok("/api/status"), True)
    check("통계 (물음표 뒤 포함)", security.proxy_path_ok("/api/stats?days=7"), True)
    check("우리가 직접 답하는 것", security.proxy_path_ok("/api/health"), False)
    check("열어 준 적 없는 것", security.proxy_path_ok("/api/admin"), False)
    check("거슬러 올라가기", security.proxy_path_ok("/api/../secret"), False)
    check("물음표 뒤가 너무 김",
          security.proxy_path_ok("/api/stats?x=" + "9" * 300), False)
    check("빈 주소", security.proxy_path_ok(""), False)


# =========================================================
# 5. 우리가 대신 받아 오는 주소
#    확인 안 하면 안쪽 것을 대신 꺼내 주게 된다
# =========================================================
def test_outbound():
    check("카카오 사진",
          security.outbound_url_ok("https://img1.kakaocdn.net/a/b.jpg"), True)
    check("http 는 안 됨",
          security.outbound_url_ok("http://img1.kakaocdn.net/a.jpg"), False)
    check("우리 안쪽 주소",
          security.outbound_url_ok("https://127.0.0.1/admin"), False)
    check("사내망 주소",
          security.outbound_url_ok("https://169.254.169.254/latest/meta-data/"), False)
    check("모르는 곳",
          security.outbound_url_ok("https://evil.example/a.jpg"), False)
    # 이름 뒤에 붙여 속이는 수법
    check("이름만 비슷한 곳",
          security.outbound_url_ok("https://kakaocdn.net.evil.example/a.jpg"), False)


# =========================================================
# 6. 브라우저에게 주는 규칙
# =========================================================
def test_headers():
    names = [k.lower() for k, _ in security.HEADERS]
    for must in ("content-security-policy", "x-content-type-options",
                 "x-frame-options", "referrer-policy",
                 "cross-origin-resource-policy"):
        check("헤더 있나: %s" % must, must in names, True)
    # 남의 주소에서 온 코드가 돌면 안 된다
    check("남의 코드 막기", "script-src 'self'" in security.CSP, True)
    # 액자에 넣어 가짜 버튼을 덧씌우는 것을 막는다
    check("액자 금지", "frame-ancestors 'none'" in security.CSP, True)
    # 우리 화면이 쓰는 것들은 열려 있어야 한다. 막으면 화면이 깨진다.
    check("글꼴 열려 있나", "fonts.gstatic.com" in security.CSP, True)
    check("식단 사진 열려 있나", "img-src 'self' data: blob: https:" in security.CSP, True)


def main():
    tests = [test_real_ip, test_origin, test_limiter,
             test_proxy_path, test_outbound, test_headers]
    for t in tests:
        t()
    print("밖에서 들어오는 것을 제대로 막는지 — %d가지 확인" % len(tests))
    for f in FAILS:
        print("  틀림: " + f)
    if FAILS:
        print("\n%d개 틀렸습니다." % len(FAILS))
        sys.exit(1)
    print("모두 통과했습니다.")


if __name__ == "__main__":
    main()
