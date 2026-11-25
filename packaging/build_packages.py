"""설치 패키지 만들기: dist/LocalAIWorkspace-<버전>-linux.tar.gz, dist/LocalAIWorkspace-<버전>-windows-server.zip
사용: .venv\\Scripts\\python.exe packaging\\build_packages.py
- 프로그램 파일만 담고 사용자 데이터(보관함·지식보관함·로그·가상환경·이미지 모델)는 넣지 않음
- 셸 스크립트는 LF, PowerShell 은 UTF-8 BOM + CRLF 로 변환 (PowerShell 5.1 한글 깨짐 방지)"""
import datetime as dt
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

VERSION = "1.9.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

EXCLUDE_DIRS = {".venv", "chroma_db", "outputs", "dist", "packaging", "tmp", "__pycache__", "샘플결과", "_cache",
                "ComfyUI", "refs", ".git", ".claude"}
EXCLUDE_FILES = {"last_metrics.json", "app_backup_before_redesign.py", "model.json", "requirements.txt",
                 "start_workspace.bat", "로컬AI_작업실_실행.bat", "settings.json", "comfyui.zip"}
EXCLUDE_EXT = {".log", ".pyc", ".part"}


def app_files():
    for dp, dns, fns in os.walk(ROOT):
        rel = os.path.relpath(dp, ROOT)
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS and not (rel == "." and d.startswith("."))
                  or (rel == "." and d == ".streamlit")]
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS and not (rel == "." and d.startswith("_"))]  # 최상위 _시험 폴더 제외
        for f in fns:
            if f in EXCLUDE_FILES or os.path.splitext(f)[1].lower() in EXCLUDE_EXT:
                continue
            p = os.path.join(dp, f)
            yield p, os.path.relpath(p, ROOT).replace("\\", "/")


def requirements():
    out = subprocess.run([sys.executable, "-m", "pip", "freeze", "--exclude-editable"], capture_output=True,
                         text=True, check=True).stdout
    pins = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith(("-e", "#")) and "@" not in l]
    torch = next((l.split("==")[1].split("+")[0] for l in pins if l.lower().startswith("torch==")), "")
    base = [l for l in pins if not l.lower().startswith(("torch==", "pywin32=="))]
    win = base + [l for l in pins if l.lower().startswith("pywin32==")]
    hdr = f"# 로컬 AI 작업실 {VERSION} — {dt.date.today()} 개발 환경(Python {sys.version.split()[0]})에서 검증된 버전\n" \
          "# torch 는 설치 스크립트가 CPU 판으로 따로 설치합니다 (TORCH_VERSION)\n"
    return hdr + "\n".join(base) + "\n", hdr + "\n".join(win) + "\n", torch


def text_conv(data: bytes, name: str) -> bytes:
    if name.endswith((".sh", ".command")):
        return data.replace(b"\r\n", b"\n")
    if name.endswith(".ps1"):
        t = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\n", "\r\n")
        return b"\xef\xbb\xbf" + t.encode("utf-8")
    return data


def build(target: str, req_linux: str, req_win: str, torch: str):
    name = f"LocalAIWorkspace-{VERSION}-{target}"        # 맥: LocalAIWorkspace-<버전>-mac.zip
    entries = {}                                          # 패키지 안 경로 → bytes
    for p, rel in app_files():
        with open(p, "rb") as f:
            entries[f"{name}/app/{rel}"] = text_conv(f.read(), rel)
    for d in ("docs",):
        for f in os.listdir(os.path.join(HERE, d)):
            with open(os.path.join(HERE, d, f), "rb") as fh:
                entries[f"{name}/docs/{f}"] = fh.read().replace(b"{VERSION}", VERSION.encode())
    with open(os.path.join(ROOT, "사용_가이드.md"), "rb") as fh:
        entries[f"{name}/docs/사용_가이드.md"] = fh.read()
    with open(os.path.join(ROOT, "icons", "LICENSES.md"), "rb") as fh:
        entries[f"{name}/docs/아이콘_라이선스.md"] = fh.read()
    sub = {"linux": "linux", "mac": "mac"}.get(target, "windows-server")
    for f in os.listdir(os.path.join(HERE, sub)):
        with open(os.path.join(HERE, sub, f), "rb") as fh:
            data = text_conv(fh.read(), f)
        if target == "mac" and f == "install.command":       # 압축을 풀면 맨 위에 보이는 더블클릭용 파일
            entries[f"{name}/설치하기.command"] = data
        else:
            entries[f"{name}/{sub}/{f}"] = data
    entries[f"{name}/requirements-{'windows' if target == 'windows-server' else target}.txt"] = \
        (req_win if target == "windows-server" else req_linux).encode("utf-8")
    entries[f"{name}/TORCH_VERSION"] = (torch + "\n").encode()
    entries[f"{name}/VERSION"] = f"{VERSION} ({dt.date.today()})\n".encode()
    if target == "mac":
        quick = ("로컬 AI 작업실 (맥북 · Apple 실리콘 M1 이후)\n\n"
                 "1) 이 압축을 푼 폴더에서 '설치하기.command' 를 우클릭 → 열기 → 열기 (처음 한 번만 경고가 뜹니다)\n"
                 "2) 터미널 창에서 자동으로 설치됩니다 (인터넷 필요, 수십 분). 관리자 암호는 필요 없습니다.\n"
                 "3) 끝나면 바탕화면의 '로컬 AI 작업실' 아이콘을 더블클릭하면 브라우저에서 열립니다.\n"
                 "※ 한컴오피스가 없어서 구형 .hwp 파일은 읽지 못합니다 (HWPX·PDF 는 가능). 인텔 맥은 지원하지 않습니다.\n")
    elif target == "linux":
        quick = ("로컬 AI 작업실 (리눅스 서버)\n\n설치:  sudo ./linux/install.sh --password '접속비밀번호' --open-firewall\n"
                 "옵션·관리 방법: docs/INSTALL.md\n")
    else:
        quick = ("로컬 AI 작업실 (Windows Server)\r\n\r\n관리자 PowerShell 에서:\r\n"
                 "  powershell -ExecutionPolicy Bypass -File .\\windows-server\\install.ps1 -Password \"접속비밀번호\" -OpenFirewall\r\n"
                 "옵션·관리 방법: docs\\INSTALL.md\r\n")
    entries[f"{name}/README.txt"] = quick.encode("utf-8")

    os.makedirs(DIST, exist_ok=True)
    if target == "linux":
        out = os.path.join(DIST, name + ".tar.gz")
        with tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT) as tf:
            for arc, data in sorted(entries.items()):
                ti = tarfile.TarInfo(arc)
                ti.size = len(data)
                ti.mtime = int(dt.datetime.now().timestamp())
                ti.mode = 0o755 if arc.endswith(".sh") else 0o644
                tf.addfile(ti, io.BytesIO(data))
    else:
        out = os.path.join(DIST, name + ".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, data in sorted(entries.items()):
                zi = zipfile.ZipInfo(arc, dt.datetime.now().timetuple()[:6])
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.create_system = 3                              # 유닛스 권한 보존: 맥에서 .command 가 실행되려면 필요
                zi.external_attr = (0o755 if arc.endswith((".sh", ".command")) else 0o644) << 16
                zf.writestr(zi, data)
    return out, len(entries)


if __name__ == "__main__":
    rl, rw, tv = requirements()
    for t in ("linux", "windows-server", "mac"):
        path, n = build(t, rl, rw, tv)
        print(f"{os.path.basename(path)}  파일 {n}개  {os.path.getsize(path) / 2**20:.1f} MB")
