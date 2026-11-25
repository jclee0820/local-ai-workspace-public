"""공개 저장소 소개 카드 이미지 만들기: docs/cards/01-*.png … (1200×675, 16:9)
사용: .venv\\Scripts\\python.exe packaging\\make_intro_cards.py
HTML 로 그린 뒤 Windows 의 Edge(헤드리스)로 PNG 를 찍는다. 글꼴: Gmarket Sans(제목)·Noto Sans KR(본문), 설치돼 있지 않으면 맑은 고딕."""
import html
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "cards")
sys.path.insert(0, HERE)
from build_packages import VERSION  # noqa: E402

EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)
W, H = 1200, 675
C = {"bg": "#FAF9F5", "bg2": "#F0EEE6", "ink": "#2B2A27", "mu": "#6B675F", "ac": "#C96442", "ac2": "#E89A7E",
     "line": "#E3DED2", "dark": "#262624", "dark2": "#30302E", "on": "#F2F0E8"}

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{font-family:'Noto Sans KR','Malgun Gothic',sans-serif;background:{C['bg']};color:{C['ink']};position:relative}}
.t{{font-family:'Gmarket Sans TTF Bold','Noto Sans KR','Malgun Gothic',sans-serif;letter-spacing:-.02em}}
.mark{{color:{C['ac']}}}
.frame{{position:absolute;inset:0;padding:56px 64px}}
.eyebrow{{display:inline-flex;align-items:center;gap:10px;font-size:20px;font-weight:600;color:{C['ac']};letter-spacing:.04em}}
.eyebrow b{{display:inline-grid;place-items:center;width:34px;height:34px;border-radius:10px;background:{C['ac']};color:#fff;font-size:17px}}
h1{{font-size:54px;line-height:1.18;margin-top:18px}}
.lead{{font-size:23px;line-height:1.6;color:{C['mu']};margin-top:16px;max-width:620px}}
ul.pts{{list-style:none;margin-top:26px;display:grid;gap:14px;max-width:600px}}
ul.pts li{{font-size:21px;line-height:1.45;padding-left:30px;position:relative}}
ul.pts li::before{{content:'';position:absolute;left:4px;top:11px;width:12px;height:12px;border-radius:3px;background:{C['ac']}}}
ul.pts li span{{color:{C['mu']};font-size:18px;display:block}}
.foot{{position:absolute;left:64px;right:64px;bottom:34px;display:flex;justify-content:space-between;align-items:center;
  font-size:17px;color:{C['mu']};border-top:1px solid {C['line']};padding-top:14px}}
.foot .brand{{font-weight:700;color:{C['ink']}}}
.art{{position:absolute;right:56px;top:104px;width:430px;height:440px}}
.panel{{background:#fff;border:1px solid {C['line']};border-radius:18px;box-shadow:0 18px 40px rgba(60,40,20,.10)}}
.chip{{display:inline-block;padding:6px 14px;border-radius:999px;background:{C['bg2']};color:{C['ink']};font-size:16px;font-weight:600;margin:0 8px 8px 0}}
.dark{{background:{C['dark']};color:{C['on']}}}
.dark .lead,.dark ul.pts li span,.dark .foot{{color:#BDB8AC}} .dark .foot{{border-color:#3D3C38}} .dark .foot .brand{{color:{C['on']}}}
"""


def page(body, dark=False, n=0, total=0):
    foot = (f'<div class="foot"><span class="brand"><span class="mark">✳</span> 로컬 AI 작업실</span>'
            f'<span>v{VERSION} · 오픈소스 · Windows 10/11</span><span>{n:02d} / {total:02d}</span></div>') if n else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body class="{"dark" if dark else ""}"><div class="frame">{body}</div>{foot}</body></html>')


def e(s):
    return html.escape(s)


def feature(eyebrow, icon, title, lead, points, art):
    pts = "".join(f"<li>{e(a)}<span>{e(b)}</span></li>" if b else f"<li>{e(a)}</li>" for a, b in points)
    return (f'<div class="eyebrow"><b>{icon}</b>{e(eyebrow)}</div><h1 class="t">{title}</h1>'
            f'<p class="lead">{e(lead)}</p><ul class="pts">{pts}</ul><div class="art">{art}</div>')


# ------------------------------------------------------------------ 그림(도형으로만 — 실제 화면·개인 자료 없이)
def art_cover():
    rows = "".join(f'<div style="display:flex;gap:10px;align-items:center;margin:10px 0"><span style="width:28px;height:28px;border-radius:8px;'
                   f'background:{c};display:inline-block"></span><span style="font-size:19px;color:{C["on"]}">{t}</span></div>'
                   for c, t in (("#C96442", "AI 비서 · 문서 요약 · 문서 비교"), ("#D9895F", "보고서 · 발표 슬라이드(PPTX)"),
                                ("#E8B07E", "웹페이지 · 다이어그램 · 마인드맵"), ("#9DB4A0", "WBS · 간트 차트(엑셀)"),
                                ("#8FA7C9", "이미지 생성 · 작업 보관함")))
    return (f'<div style="position:absolute;inset:0;border-radius:22px;background:{C["dark2"]};padding:34px 32px;'
            f'border:1px solid #3D3C38">'
            f'<div style="font-size:16px;color:#BDB8AC;letter-spacing:.06em;margin-bottom:12px">한 화면에서 쓰는 메뉴</div>{rows}'
            f'<div style="margin-top:26px;padding:16px 18px;border-radius:14px;background:#1F1E1D;font-size:17px;color:#E89A7E;line-height:1.6">'
            f'🔒 문서·질문이 PC 밖으로 나가지 않습니다<br><span style="color:#BDB8AC">언어 모델(Ollama) · 문서 검색 · 이미지 생성 모두 내 PC에서</span></div></div>')


def art_docs():
    bubble = lambda t, me=False: (f'<div style="max-width:300px;margin:{"0 0 12px auto" if me else "0 0 12px"};padding:12px 16px;border-radius:14px;'
                                  f'font-size:17px;line-height:1.5;background:{C["ac"] if me else C["bg2"]};color:{"#fff" if me else C["ink"]}">{t}</div>')
    return (f'<div class="panel" style="position:absolute;inset:0;padding:26px">'
            + bubble("첨부한 지침에서 보안 요구사항이 뭐야?", True)
            + bubble("데이터는 암호화해 저장해야 합니다 <b style='color:#C96442'>(p.12)</b>. 접근 기록은 1년 보관합니다 <b style='color:#C96442'>(p.15)</b>.")
            + f'<div style="margin-top:18px;border:1px solid {C["line"]};border-radius:12px;overflow:hidden;font-size:15px">'
              f'<div style="display:grid;grid-template-columns:1fr 1fr;background:{C["bg2"]};font-weight:700"><div style="padding:9px 12px">현행</div><div style="padding:9px 12px">개정안</div></div>'
              f'<div style="display:grid;grid-template-columns:1fr 1fr"><div style="padding:9px 12px">보관 기간 6개월</div>'
              f'<div style="padding:9px 12px;color:#C96442;font-weight:700">보관 기간 1년</div></div></div>'
              f'<div style="margin-top:10px;font-size:14px;color:{C["mu"]}">신구대조표 자동 작성 (워드·엑셀)</div></div>')


def art_slides():
    bar = lambda w, c="#E3DED2": f'<div style="height:9px;width:{w}%;background:{c};border-radius:5px;margin:6px 0"></div>'
    slide = (f'<div class="panel" style="position:absolute;left:0;top:30px;width:420px;height:236px;padding:18px 20px">'
             f'<div style="display:flex;gap:12px;align-items:center"><div class="t" style="font-size:30px;color:{C["ac"]}">03</div>'
             f'<div style="font-size:18px;font-weight:700">장·절 흐름대로 한 장씩</div></div>'
             f'<div style="margin:10px 0;height:30px;border-radius:6px;background:linear-gradient(90deg,{C["ac"]},{C["ac2"]});color:#fff;font-size:14px;padding:6px 12px">KEY POINT · 원문 수치 그대로</div>'
             f'<div style="display:grid;grid-template-columns:1fr 1.2fr;gap:12px"><div>{bar(90)}{bar(70)}{bar(80)}{bar(60)}</div>'
             f'<div style="border:1px solid {C["line"]};border-radius:8px;overflow:hidden">'
             + "".join(f'<div style="display:grid;grid-template-columns:1fr 1fr;font-size:12px;{"background:#C96442;color:#fff" if i == 0 else ""}">'
                       f'<div style="padding:4px 8px">{a}</div><div style="padding:4px 8px">{b}</div></div>'
                       for i, (a, b) in enumerate((("구분", "값"), ("항목 A", "12.4"), ("항목 B", "8.1"), ("항목 C", "15.0"))))
             + '</div></div></div>')
    doc = (f'<div class="panel" style="position:absolute;left:150px;top:282px;width:270px;height:150px;padding:16px 18px;font-size:14px">'
           f'<div style="font-weight:700;margin-bottom:6px">📄 원 소스 보고서 60쪽</div>{bar(95)}{bar(85)}{bar(75)}'
           f'<div style="color:{C["mu"]};margin-top:6px">→ 요청한 장수 그대로 · 원문 표·그림 삽입</div></div>')
    return slide + doc


def art_web():
    cards = "".join(f'<div style="display:flex;gap:12px;align-items:center;padding:10px;border-bottom:1px solid {C["line"]}">'
                    f'<div style="width:46px;height:66px;border-radius:6px;background:linear-gradient(160deg,{c1},{c2})"></div>'
                    f'<div><div style="font-size:16px;font-weight:700">{t}</div><div style="font-size:13px;color:{C["mu"]}">{s}</div></div></div>'
                    for c1, c2, t, s in (("#2B2A27", "#C96442", "11월 현재 상영작", "개봉일 · 주연 · 줄거리 · 포스터"),
                                         ("#3D5A80", "#98C1D9", "12월 개봉 예정작", "다른 달 개봉작은 자동 제외"),
                                         ("#5B4636", "#E8B07E", "작품 속 시간 순 연표", "예) 32 BBY → 35 ABY")))
    return (f'<div class="panel" style="position:absolute;inset:0;overflow:hidden">'
            f'<div style="height:120px;background:radial-gradient(circle at 70% 30%,{C["ac2"]},{C["ac"]} 55%,#7A3B26);color:#fff;padding:26px">'
            f'<div style="font-size:13px;letter-spacing:.2em;opacity:.85">NOW</div><div class="t" style="font-size:28px;margin-top:6px">요청 문장 그대로 OK</div></div>'
            f'<div style="padding:6px 14px">{cards}</div>'
            f'<div style="padding:10px 18px;font-size:14px;color:{C["mu"]}">포스터는 제목·개봉일·배우를 읽어 확인한 것만</div></div>')


def art_plan():
    rows = (("1", "현황 조사", 0, 30, "#C96442"), ("1.1", "동향 분석", 0, 18, "#E89A7E"), ("1.2", "요구 분석", 14, 20, "#E89A7E"),
            ("2", "설계·개발", 30, 45, "#3D5A80"), ("2.1", "기능 설계", 30, 18, "#98C1D9"), ("2.2", "개발·시험", 46, 29, "#98C1D9"),
            ("3", "정책 제언", 72, 26, "#5B8C5A"))
    g = "".join(f'<div style="display:grid;grid-template-columns:44px 96px 1fr;align-items:center;font-size:14px;height:32px">'
                f'<span style="color:{C["mu"]}">{c}</span><span style="font-weight:{700 if "." not in c else 400}">{t}</span>'
                f'<span style="position:relative;height:14px"><span style="position:absolute;left:{s}%;width:{w}%;top:0;bottom:0;border-radius:4px;background:{col}"></span></span></div>'
                for c, t, s, w, col in rows)
    mm = (f'<svg width="380" height="150" viewBox="0 0 380 150"><g stroke="{C["ac2"]}" stroke-width="3" fill="none">'
          f'<path d="M190 75 C140 75 130 30 80 30"/><path d="M190 75 C140 75 130 120 80 120"/><path d="M190 75 C240 75 250 30 300 30"/>'
          f'<path d="M190 75 C240 75 250 120 300 120"/></g><rect x="140" y="56" width="100" height="38" rx="19" fill="{C["ac"]}"/>'
          f'<text x="190" y="81" text-anchor="middle" fill="#fff" font-size="16" font-family="Noto Sans KR" font-weight="700">핵심 주제</text>'
          + "".join(f'<rect x="{x - 48}" y="{y - 15}" width="96" height="30" rx="15" fill="#fff" stroke="{C["line"]}"/>'
                    f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-size="14" font-family="Noto Sans KR" fill="{C["ink"]}">{t}</text>'
                    for x, y, t in ((80, 30, "배경"), (80, 120, "현황"), (300, 30, "방안"), (300, 120, "기대효과")))
          + '</svg>')
    return (f'<div class="panel" style="position:absolute;left:0;top:0;width:430px;padding:16px 18px">'
            f'<div style="font-size:15px;font-weight:700;margin-bottom:6px">WBS · 간트 (엑셀)</div>{g}</div>'
            f'<div class="panel" style="position:absolute;left:30px;top:282px;width:400px;padding:8px 10px">{mm}</div>')


def art_install():
    steps = (("1", "setup.exe 더블클릭", "관리자 권한 필요 없음"), ("2", "다음 → 설치", "Python·라이브러리는 설치 파일에 포함"),
             ("3", "모델 자동 받기", "메모리에 맞춰 언어 모델 선택"), ("4", "바탕화면 아이콘", "누르면 브라우저에서 열림"))
    s = "".join(f'<div style="display:flex;gap:16px;align-items:center;padding:14px 0;border-bottom:1px dashed {C["line"]}">'
                f'<div class="t" style="width:46px;height:46px;border-radius:14px;background:{C["ac"]};color:#fff;display:grid;place-items:center;font-size:22px">{n}</div>'
                f'<div><div style="font-size:19px;font-weight:700">{a}</div><div style="font-size:15px;color:{C["mu"]}">{b}</div></div></div>'
                for n, a, b in steps)
    return f'<div class="panel" style="position:absolute;inset:0;padding:18px 26px">{s}</div>'


def art_trust():
    items = (("🔒", "로컬 실행", "문서·질문이 외부로 전송되지 않음"), ("🔎", "근거 확인", "자료에 없는 내용·수치는 빼고 출처 표시"),
             ("🔢", "수치 대조", "만든 결과의 숫자를 원문과 자동 대조"), ("📱", "휴대폰 접속", "PC에서 정한 비밀번호로만 로그인"))
    s = "".join(f'<div style="background:{C["dark2"]};border:1px solid #3D3C38;border-radius:16px;padding:18px">'
                f'<div style="font-size:30px">{i}</div><div style="font-size:19px;font-weight:700;margin-top:6px;color:{C["on"]}">{a}</div>'
                f'<div style="font-size:15px;color:#BDB8AC;margin-top:4px;line-height:1.45">{b}</div></div>' for i, a, b in items)
    return f'<div style="position:absolute;inset:0;display:grid;grid-template-columns:1fr 1fr;gap:14px">{s}</div>'


def art_image():
    tiles = "".join(f'<div style="border-radius:14px;background:{bg};position:relative;overflow:hidden">'
                    f'<div style="position:absolute;left:10px;bottom:10px;font-size:13px;color:#fff;background:rgba(0,0,0,.35);padding:3px 9px;border-radius:999px">{t}</div></div>'
                    for bg, t in (("linear-gradient(160deg,#F2C14E,#C96442)", "포스터 시안"), ("linear-gradient(160deg,#98C1D9,#3D5A80)", "삽화"),
                                  ("linear-gradient(160deg,#9DB4A0,#4F6D57)", "배경"), ("linear-gradient(160deg,#E89A7E,#5B4636)", "참조 사진 편집")))
    return (f'<div class="panel" style="position:absolute;inset:0;padding:18px">'
            f'<div style="padding:12px 14px;border-radius:12px;background:{C["bg2"]};font-size:16px">💬 "노을 진 해안 도로를 달리는 자율주행 버스, 수채화 느낌"</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;grid-template-rows:150px 150px;gap:12px;margin-top:14px">{tiles}</div></div>')


CARDS = [
    ("01-overview", True,
     f'<div class="eyebrow" style="color:{C["ac2"]}"><b>✳</b>OPEN SOURCE · v{VERSION}</div>'
     f'<h1 class="t" style="font-size:66px;margin-top:22px">로컬 AI 작업실</h1>'
     f'<p class="lead" style="font-size:26px;color:#E5E1D6;max-width:600px">내 PC 안에서만 동작하는<br>공공기관용 생성형 AI 업무 도구</p>'
     f'<div style="margin-top:30px;max-width:590px">'
     + "".join(f'<span class="chip" style="background:#3A3936;color:{C["on"]}">{t}</span>'
               for t in ("외부 전송 없음", "클릭 한 번 설치", "한국어·개조식 문체", "HWPX·PPTX·XLSX", "무료·오픈소스"))
     + f'</div><div class="art">{art_cover()}</div>'),
    ("02-assistant", False, feature("AI 비서 · 문서", "💬", "올린 문서에<br>쪽 번호까지 달아 답합니다",
                                    "질문하면 근거가 된 문서와 쪽을 함께 보여 주고, 긴 문서는 나눠 요약합니다.",
                                    [("문서 요약·추출", "PDF·한글(HWP/HWPX)·워드·파워포인트·엑셀 등"),
                                     ("문서 비교 → 신구대조표", "개정 전·후를 대조해 워드·엑셀로"),
                                     ("지식보관함", "폴더를 연결하면 바뀐 문서만 자동 색인")], art_docs())),
    ("03-slides", False, feature("보고서 · 발표 슬라이드", "📊", "60쪽 보고서도<br>장수 그대로 알차게",
                                 "원 소스 보고서의 장·절을 따라 한 장씩 만들고, 원문 표와 그림을 그대로 넣습니다.",
                                 [("편집 가능한 PPTX", "슬라이드 마스터에 배경·로고, 각 장엔 내용만"),
                                  ("공공기관 개조식 보고서", "HWPX·DOCX·PDF로 바로 저장"),
                                  ("수치 자동 대조", "슬라이드 속 숫자를 원문과 비교해 표시")], art_slides())),
    ("04-web", False, feature("웹페이지", "🌐", "요청 문장 하나로<br>근거 있는 웹페이지",
                              "주제·목록·연표·기관 소개 등 6가지 틀과 3D·인터랙티브 부품. 확인된 내용만 싣습니다.",
                              [("최신 목록은 실시간 웹 검색", "'현재 상영작·12월 개봉작' 같은 요청 자동 전환"),
                               ("포스터·사진 검증", "제목·개봉일·배우를 읽어 맞는 것만"),
                               ("위키백과 기반 소개·연표", "작품 속 시간 순 정렬도 가능")], art_web())),
    ("05-planning", False, feature("WBS · 간트 · 마인드맵", "🗓️", "계획서를 올리면<br>일정표가 나옵니다",
                                   "작업분류체계(WBS)와 일정을 뽑아 막대가 자동으로 바뀌는 엑셀 간트 차트로 만듭니다.",
                                   [("날짜 없는 작업도 배치", "공수·선후 관계를 추정해 사업 기간 안에"),
                                    ("마인드맵 · 다이어그램", "문서 구조화, 마우스로 편집, 발표자료로 변환"),
                                    ("근거 표시", "추정한 일정은 빨간 글씨로 구분")], art_plan())),
    ("06-image", False, feature("이미지 생성", "🎨", "한국어 설명으로<br>그림을 그립니다",
                                "포스터 시안·삽화·배경을 만들고, 참조 사진을 주면 그 느낌으로 편집합니다.",
                                [("내 PC에서 생성", "ComfyUI 기반 (FLUX.2 Klein · Z-Image-Turbo) · 별도 설치"),
                                 ("참조 사진 편집", "올린 사진을 바탕으로 수정"),
                                 ("작업 보관함 자동 저장", "만든 결과물을 언제든 다시 내려받기")], art_image())),
    ("07-install", False, feature("설치", "⚡", "클릭 한 번이면<br>설치가 끝납니다",
                                  "설치 파일 하나로 Python·라이브러리까지 들어갑니다. 명령어 입력이 필요 없습니다.",
                                  [("필요 사양", "Windows 10/11 64비트 · 메모리 16GB 이상(32GB 권장)"),
                                   ("디스크", "여유 30GB 이상 (언어 모델 5~17GB 포함)"),
                                   ("받는 곳", "GitHub 릴리스의 LocalAIWorkspace-Setup.exe")], art_install())),
    ("08-trust", True, feature("안심하고 쓰는 이유", "🛡️", "내 문서는<br>내 PC에만",
                               "언어 모델·문서 검색·이미지 생성을 모두 로컬에서 실행합니다. 클라우드 계정이 필요 없습니다.",
                               [("근거 없는 내용은 빼기", "자료에서 확인되지 않은 문장·숫자는 싣지 않음"),
                                ("오픈소스", "코드를 직접 확인하고 고쳐 쓸 수 있음")], art_trust())),
]


def main():
    if not EDGE:
        sys.exit("Microsoft Edge 를 찾지 못했습니다.")
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp()
    total = len(CARDS)
    for i, (name, dark, body) in enumerate(CARDS, 1):
        hp = os.path.join(tmp, name + ".html")
        open(hp, "w", encoding="utf-8").write(page(body, dark, i, total))
        png = os.path.join(OUT, name + ".png")
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={W},{H}", f"--screenshot={png}", "file:///" + hp.replace("\\", "/")],
                       check=True, capture_output=True, timeout=60)
        print("saved", png)


if __name__ == "__main__":
    main()
