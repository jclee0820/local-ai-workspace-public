"""한컴오피스(설치된 경우)로 HWPX를 실제로 열어 쪽수·본문 글자 수를 확인하는 검증 도구.
사용: python hancom_check.py 파일.hwpx [--pdf 출력.pdf]"""
import json
import os
import sys


def check(path: str, pdf: str = None) -> dict:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass
        ok = bool(hwp.Open(os.path.abspath(path), "HWPX", "forceopen:true"))
        if not ok:
            return {"opened": False}
        text = hwp.GetTextFile("TEXT", "") or ""
        res = {"opened": True, "pages": int(hwp.PageCount), "chars": len(text.strip()), "head": text.strip()[:200]}
        if pdf:
            res["pdf_saved"] = bool(hwp.SaveAs(os.path.abspath(pdf), "PDF", ""))
        return res
    except Exception as e:
        return {"opened": False, "error": str(e)}
    finally:
        if hwp is not None:
            try:
                hwp.Clear(1)
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    pdf = sys.argv[sys.argv.index("--pdf") + 1] if "--pdf" in sys.argv else None
    print(json.dumps(check(sys.argv[1], pdf), ensure_ascii=False))
