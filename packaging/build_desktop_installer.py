"""개인 PC용 원클릭 설치 파일 만들기: dist/LocalAIWorkspace-Setup-<버전>.exe
사용: .venv\\Scripts\\python.exe packaging\\build_desktop_installer.py
- 독립 실행형 Python(embeddable 3.12) 에 라이브러리를 미리 설치해 넣는다 → 사용자 PC 에서 Python 설치·pip 다운로드가 없음
  (지인 PC 설치 실패의 주원인이 관리자 권한·Python 버전·pip 다운로드였음)
- 사용자 PC 에서는 Ollama·언어 모델·임베딩 모델만 받는다 (windows-desktop/install-desktop.ps1)
- 라이브러리 구성이 같으면 다음 빌드 때 Python 단계는 건너뜀(dist/desktop_stage/python/.req_hash)
- 필요: Inno Setup 6 (winget install JRSoftware.InnoSetup)"""
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_packages as bp                                    # noqa: E402  (버전·파일 목록·requirements 공용)

ROOT, DIST, VERSION = bp.ROOT, bp.DIST, bp.VERSION
STAGE = os.path.join(DIST, "desktop_stage")
DL = os.path.join(DIST, "_dl")
PYVER = "3.12.10"
EMBED_URL = f"https://www.python.org/ftp/python/{PYVER}/python-{PYVER}-embed-amd64.zip"
GETPIP_URL = "https://bootstrap.pypa.io/get-pip.py"
VC_DLLS = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140_1.dll", "concrt140.dll", "vcomp140.dll")


def fetch(url, name):
    os.makedirs(DL, exist_ok=True)
    p = os.path.join(DL, name)
    if not os.path.exists(p):
        print("  받는 중:", url)
        urllib.request.urlretrieve(url, p + ".part")
        os.replace(p + ".part", p)
    return p


def run(argv):
    print("  $", " ".join(argv[:6]), "…" if len(argv) > 6 else "")
    subprocess.run(argv, check=True)


def build_python(req_win, torch):
    pydir = os.path.join(STAGE, "python")
    h = hashlib.sha1((PYVER + req_win + torch).encode()).hexdigest()
    mark = os.path.join(pydir, ".req_hash")
    if os.path.exists(mark) and open(mark).read().strip() == h:
        print("[1/4] 내장 Python: 라이브러리 구성이 같아 그대로 씀")
        return
    print(f"[1/4] 내장 Python {PYVER} + 라이브러리 설치 (처음 한 번, 수십 분)")
    shutil.rmtree(pydir, ignore_errors=True)
    with zipfile.ZipFile(fetch(EMBED_URL, os.path.basename(EMBED_URL))) as z:
        z.extractall(pydir)
    pth = os.path.join(pydir, f"python{PYVER.split('.')[0]}{PYVER.split('.')[1]}._pth")
    s = open(pth, encoding="utf-8").read().replace("#import site", "import site")
    s += "\n..\\app\n"                                           # 작업실 모듈을 어느 스크립트에서든 import 가능하게
    open(pth, "w", encoding="utf-8").write(s)
    py = os.path.join(pydir, "python.exe")
    run([py, fetch(GETPIP_URL, "get-pip.py"), "--no-warn-script-location", "--disable-pip-version-check"])
    pip = [py, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check", "--no-cache-dir"]
    run(pip + [f"torch=={torch}" if torch else "torch", "--index-url", "https://download.pytorch.org/whl/cpu"])
    req = os.path.join(DL, "requirements-desktop.txt")
    open(req, "w", encoding="utf-8").write(req_win)
    run(pip + ["-r", req])
    sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for d in VC_DLLS:                                           # VC++ 런타임 동봉(앱 로컬 배포) — 런타임 없는 PC 대비
        src = os.path.join(sysdir, d)
        if os.path.exists(src) and not os.path.exists(os.path.join(pydir, d)):
            shutil.copy2(src, pydir)
    run([py, "-c", "import streamlit, chromadb, torch, sentence_transformers, pymupdf, pptx; print('import ok', torch.__version__)"])
    open(mark, "w").write(h)


def stage_files():
    print("[2/4] 프로그램 파일 모으기")
    app = os.path.join(STAGE, "app")
    shutil.rmtree(app, ignore_errors=True)
    for p, rel in bp.app_files():
        out = os.path.join(app, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(p, out)
    setup = os.path.join(STAGE, "setup")
    shutil.rmtree(setup, ignore_errors=True)
    os.makedirs(setup)
    src = os.path.join(HERE, "windows-desktop")
    for f in os.listdir(src):
        if f.endswith(".iss"):
            continue
        data = open(os.path.join(src, f), "rb").read()
        if f.endswith(".vbs"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        open(os.path.join(setup, f), "wb").write(bp.text_conv(data, f))   # .ps1 → UTF-8 BOM + CRLF (PowerShell 5.1 한글)
    docs = os.path.join(STAGE, "docs")
    os.makedirs(docs, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "사용_가이드.md"), os.path.join(docs, "사용_가이드.md"))
    shutil.copy2(os.path.join(ROOT, "icons", "LICENSES.md"), os.path.join(docs, "아이콘_라이선스.md"))
    open(os.path.join(STAGE, "VERSION"), "w", encoding="utf-8").write(VERSION + "\n")
    make_icon(os.path.join(STAGE, "app.ico"))


def make_icon(path):
    """✳ 모양(작업실 표지와 같은 테라코타) 아이콘."""
    import math
    from PIL import Image, ImageDraw
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=(201, 100, 66, 255))
    c, r = S / 2, S * 0.30
    for k in range(4):
        a = math.pi * k / 4
        d.line([(c - r * math.cos(a), c - r * math.sin(a)), (c + r * math.cos(a), c + r * math.sin(a))],
               fill=(255, 255, 255, 255), width=int(S * 0.085))
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def iscc():
    for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe")):
        if os.path.exists(p):
            return p
    sys.exit("Inno Setup 6 이 없습니다: winget install JRSoftware.InnoSetup")


def compile_setup():
    print("[3/4] 설치 파일 만들기 (Inno Setup, 압축에 수 분)")
    iss_src = open(os.path.join(HERE, "windows-desktop", "LocalAIWorkspace.iss"), encoding="utf-8").read()
    iss = os.path.join(DIST, "LocalAIWorkspace-desktop.iss")
    open(iss, "w", encoding="utf-8-sig").write(iss_src)          # Inno 는 BOM 있는 UTF-8 이어야 한글이 안 깨짐
    run([iscc(), "/Q", f"/DAppVer={VERSION}", f"/DStage={STAGE}", f"/DOutDir={DIST}", iss])
    out = os.path.join(DIST, f"LocalAIWorkspace-Setup-{VERSION}.exe")
    print(f"[4/4] 완료: {out}  {os.path.getsize(out) / 2**20:.0f} MB")
    return out


if __name__ == "__main__":
    os.makedirs(STAGE, exist_ok=True)
    _, req_win, torch = bp.requirements()
    build_python(req_win, torch)
    stage_files()
    compile_setup()
