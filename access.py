"""휴대폰·원격 접속 설정.

- 이 PC(localhost)에서 쓸 때는 비밀번호를 묻지 않는다.
- 다른 기기(휴대폰 등)는 이 PC에서 비밀번호를 정해 둔 경우에만 접속할 수 있고, 로그인해야 한다.
  비밀번호는 원문이 아니라 PBKDF2 해시(소금 포함)로 outputs/.access.json 에 저장한다(저장소에 올라가지 않는 폴더).
- 접속 주소: 같은 공유기(와이파이) 주소와, Tailscale 이 설치·로그인돼 있으면 그 주소(밖에서 LTE 로도 접속)를 보여 준다.
- 기기 구분은 Streamlit 의 st.context.ip_address(실제 TCP 연결 상대 — 위조 불가, localhost 는 None)로 한다."""
import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import socket
import subprocess
import time

BASE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(os.environ.get("LAI_ACCESS_DIR") or os.path.join(BASE, "outputs"), ".access.json")
ITER = 240_000
_FAILS = {}                                                           # ip → [실패 시각…] (무차별 대입 지연)


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def is_local(ip) -> bool:
    """이 PC에서 접속했는지. None(Streamlit 이 localhost 로 판단)·127.x·::1·'::ffff:127.0.0.1'(IPv6 표기) 모두 이 PC로 본다."""
    if not ip:
        return True
    import ipaddress
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_loopback


def has_password() -> bool:
    return bool(_load().get("hash"))


def set_password(pw: str):
    if len(pw) < 6:
        raise ValueError("비밀번호는 6자 이상으로 정해 주세요.")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, ITER)
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(h).decode(), "iter": ITER,
                   "set_at": time.strftime("%Y-%m-%d %H:%M")}, f)
    os.replace(tmp, FILE)


def clear_password():
    try:
        os.remove(FILE)
    except FileNotFoundError:
        pass


def set_at() -> str:
    return _load().get("set_at", "")


def wait_seconds(ip: str) -> int:
    """최근 10분 안에 5번 이상 틀렸으면 마지막 실패 후 60초 동안 막음."""
    now = time.time()
    lst = [t for t in _FAILS.get(ip, []) if now - t < 600]
    _FAILS[ip] = lst
    return max(0, int(60 - (now - lst[-1]))) if len(lst) >= 5 else 0


def note_fail(ip: str):
    _FAILS.setdefault(ip, []).append(time.time())


def check(pw: str, ip: str = "") -> bool:
    d = _load()
    if not d.get("hash"):
        return False
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), base64.b64decode(d["salt"]), int(d.get("iter", ITER)))
    ok = hmac.compare_digest(h, base64.b64decode(d["hash"]))
    if not ok:
        _FAILS.setdefault(ip, []).append(time.time())
        time.sleep(1.0)
    return ok


# ------------------------------------------------------------------ 접속 주소
def lan_ips():
    """이 PC의 공유기 내부 주소(IPv4). 가상 어댑터·링크로컬 제외."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                                 # 실제로 보내지 않음 — 기본 경로의 내 주소만 알아냄
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.", "100.")) and ip.count(".") == 3)


def tailscale_exe():
    for p in (shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe"):
        if p and os.path.exists(p):
            return p
    return None


def tailscale_ip():
    """Tailscale 이 설치·로그인돼 있으면 100.x 주소, 아니면 None."""
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().splitlines()
        return out[0].strip() if out and out[0].strip().startswith("100.") else None
    except Exception:
        return None


def url(ip, port=8501):
    return f"http://{ip}:{port}"


def qr_png(text: str, scale: int = 6) -> bytes:
    import segno
    b = io.BytesIO()
    segno.make(text, error="m").save(b, kind="png", scale=scale, border=2, dark="#111111", light="#ffffff")
    return b.getvalue()
