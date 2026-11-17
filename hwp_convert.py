"""구형 .hwp → .hwpx 변환 (설치된 한컴오피스 사용). 별도 프로세스로 실행해 대화상자 등으로 멈추면 시간 제한 후 종료.
사용: python hwp_convert.py 입력.hwp 출력.hwpx"""
import os
import sys


def convert(src: str, dst: str) -> bool:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")      # (창 숨김 호출은 .hwp 열기에서 멈춤을 유발해 쓰지 않음)
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        try:
            hwp.SetMessageBoxMode(0x2FFF1)        # 확인·예 등 메시지 상자를 자동으로 응답
        except Exception:
            pass
        fmt = "HWP" if src.lower().endswith(".hwp") else ""
        if not hwp.Open(os.path.abspath(src), fmt, "forceopen:true"):
            return False
        ok = bool(hwp.SaveAs(os.path.abspath(dst), "HWPX", ""))
        hwp.Clear(1)
        return ok and os.path.exists(dst)
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def convert_safe(src: str, dst: str, timeout: int = 120) -> bool:
    """별도 프로세스에서 변환 (한컴 대화상자에 걸려도 앱이 멈추지 않게)."""
    import subprocess
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), src, dst],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        return False
    return p.returncode == 0 and os.path.exists(dst)


def _kill_tree(pid):
    import psutil
    try:
        parent = psutil.Process(pid)
        kids = parent.children(recursive=True)
        start = parent.create_time()
        # 이 변환 프로세스가 띄운 한컴(Hwp.exe)도 함께 종료 (변환 시작 이후 생성된 것만)
        hwps = [p for p in psutil.process_iter(["name", "create_time"])
                if (p.info["name"] or "").lower() == "hwp.exe" and p.info["create_time"] >= start]
        for p in kids + [parent] + hwps:
            try:
                p.kill()
            except Exception:
                pass
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(0 if convert(sys.argv[1], sys.argv[2]) else 1)
