# -*- coding: utf-8 -*-
"""jungle_kb.py 의 안내 지식을 웹용 jungle_kb.js 로 옮긴다.

    python build_web_kb.py

지식의 원본은 언제나 jungle_kb.py 하나다.
내용을 고쳤으면 이 스크립트를 다시 돌려 웹 쪽에도 반영한다.
(디스코드 봇은 jungle_kb.py 를 직접 읽으므로 따로 할 일이 없다)
"""
import io
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE_DIR, "jungle_kb.js")

sys.path.insert(0, BASE_DIR)
import jungle_kb  # noqa: E402


def main():
    text = jungle_kb.build_context()

    # 템플릿 리터럴 안에서 문제가 되는 문자만 막아 준다
    safe = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    js = (
        "// 이 파일은 build_web_kb.py 가 jungle_kb.py 에서 자동 생성합니다.\n"
        "// 직접 고치지 마세요. 내용을 바꾸려면 jungle_kb.py 를 고치고 다시 생성하세요.\n"
        "// 생성 시점 기준 %d자, %d개 항목.\n"
        "const JUNGLE_KB = `%s`;\n"
    ) % (len(text), len(jungle_kb.SECTIONS), safe)

    io.open(OUT, "w", encoding="utf-8", newline="\n").write(js)
    print("만들었습니다: %s (%d자, %d개 항목)"
          % (os.path.basename(OUT), len(text), len(jungle_kb.SECTIONS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
