"""다이어그램: Qwen → Draw.io mxGraphModel XML, 임베드 에디터 HTML, Mermaid 뷰어."""
import html
import json
import re
import xml.etree.ElementTree as ET

DRAWIO_SYSTEM = """당신은 diagrams.net(Draw.io) 다이어그램 작성기이다. 사용자의 설명을 표준 Draw.io mxGraphModel XML로만 출력한다.
규칙:
- 설명·인사말·마크다운 코드펜스 없이 <mxGraphModel>로 시작해 </mxGraphModel>로 끝낼 것.
- 구조: <mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/> ... </root></mxGraphModel>
- 각 박스(Vertex)는 id를 "n1","n2"...로 하고 value에 한국어 라벨, style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;", vertex="1" parent="1" 와
  <mxGeometry x=".." y=".." width="140" height="60" as="geometry"/> 를 가진다. 박스 간 간격은 가로/세로 최소 60 이상, 좌표가 겹치지 않게 배치.
- 각 화살표(Edge)는 id를 "e1","e2"...로 하고 style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;", edge="1" parent="1" source="n1" target="n2" 와 <mxGeometry relative="1" as="geometry"/>.
- 순서도는 위→아래 또는 왼쪽→오른쪽, 시스템 구성도는 계층(상/중/하)으로 배치. 판단 노드는 style="rhombus;whiteSpace=wrap;html=1;".
- value의 특수문자는 XML 이스케이프(&amp; &lt; &gt;)할 것. 라벨은 한국어, 중국어 한자 금지."""

MERMAID_SYSTEM = """당신은 Mermaid 다이어그램 작성기이다. 사용자의 설명을 Mermaid 코드로만 출력한다.
- 코드펜스·설명 없이 `flowchart TD`, `flowchart LR`, `sequenceDiagram` 등으로 시작.
- 노드 라벨은 한국어, 반드시 따옴표 사용: A["라벨"] --> B["라벨"]. 중국어 한자 금지."""


def extract_mxgraph(text: str) -> str:
    m = re.search(r"<mxGraphModel.*?</mxGraphModel>", text, re.S)
    return m.group(0) if m else ""


def validate_mxgraph(xml: str):
    """(ok, 메시지, 노드수, 엣지수). 구조·좌표·참조 검증."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        return False, f"XML 구문 오류: {e}", 0, 0
    cells = list(root.iter("mxCell"))
    ids = {c.get("id") for c in cells}
    if "0" not in ids or "1" not in ids:
        return False, "기본 셀(id=0,1) 누락", 0, 0
    v = [c for c in cells if c.get("vertex") == "1"]
    e = [c for c in cells if c.get("edge") == "1"]
    for c in v:
        g = c.find("mxGeometry")
        if g is None or g.get("x") is None or g.get("width") is None:
            return False, f"노드 {c.get('id')} 좌표 누락", len(v), len(e)
    for c in e:
        if c.get("source") not in ids or c.get("target") not in ids:
            return False, f"엣지 {c.get('id')} 참조 오류", len(v), len(e)
    return True, "OK", len(v), len(e)


def fix_mxgraph(xml: str) -> str:
    """흔한 오류 보정: 누락된 id=0/1 셀 추가, 없는 도형을 가리키는 연결선 제거, 좌표 없는 도형·연결선에 geometry 보충."""
    if 'id="0"' not in xml:
        xml = xml.replace("<root>", '<root><mxCell id="0"/><mxCell id="1" parent="0"/>', 1)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml
    parent = root.find("root")
    if parent is None:
        return xml
    cells = list(parent.iter("mxCell"))
    ids = {c.get("id") for c in cells}
    changed = False
    for i, c in enumerate(c for c in cells if c.get("vertex") == "1"):
        g = c.find("mxGeometry")
        if g is None:
            g = ET.SubElement(c, "mxGeometry", {"as": "geometry"})
        if g.get("x") is None or g.get("width") is None:          # 좌표 누락 도형은 격자로 배치
            g.set("x", g.get("x") or str(40 + (i % 4) * 200)); g.set("y", g.get("y") or str(40 + (i // 4) * 120))
            g.set("width", g.get("width") or "140"); g.set("height", g.get("height") or "60")
            changed = True
    for c in [c for c in cells if c.get("edge") == "1"]:
        if c.get("source") not in ids or c.get("target") not in ids:
            parent.remove(c)                                        # 없는 도형을 잇는 선은 지움(나머지 그림은 살림)
            changed = True
        elif c.find("mxGeometry") is None:
            ET.SubElement(c, "mxGeometry", {"relative": "1", "as": "geometry"})
            changed = True
    return ET.tostring(root, encoding="unicode") if changed else xml


def generate_drawio(description: str, chat_fn, retries: int = 2):
    """chat_fn(messages, options)->str. 검증 실패 시 재시도. 반환 (xml, 메시지)."""
    msg = "unknown"
    for i in range(retries + 1):
        out = chat_fn([{"role": "system", "content": DRAWIO_SYSTEM},
                       {"role": "user", "content": description + ("" if i == 0 else f"\n(이전 오류: {msg}. XML만 정확히 다시 출력)")}],
                      {"temperature": 0.2, "num_ctx": 8192})
        xml = fix_mxgraph(extract_mxgraph(out))
        ok, msg, _, _ = validate_mxgraph(xml) if xml else (False, "mxGraphModel 없음", 0, 0)
        if ok:
            return xml, "OK"
    return "", msg


def generate_mermaid(description: str, chat_fn) -> str:
    out = chat_fn([{"role": "system", "content": MERMAID_SYSTEM}, {"role": "user", "content": description}],
                  {"temperature": 0.2, "num_ctx": 8192})
    out = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", out.strip(), flags=re.M).strip()
    return out


def drawio_embed_html(xml: str, height: int = 750) -> str:
    """embed.diagrams.net(proto=json) 에 postMessage 로 XML 로드. 저장은 에디터 메뉴 [파일 > 내보내기]."""
    xml_js = json.dumps(xml)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;font-family:'Malgun Gothic',sans-serif}}
#bar{{padding:6px 8px;background:#f3f4f6;font-size:13px;border-bottom:1px solid #ddd}}
button{{margin-right:6px;padding:4px 10px;cursor:pointer}}
iframe{{width:100%;height:{height - 40}px;border:0}}</style></head><body>
<div id="bar">
 <button onclick="exp('png')">PNG 저장(300DPI급)</button>
 <button onclick="exp('svg')">SVG 저장</button>
 <button onclick="exp('xml')">.drawio 저장</button>
 <span>박스 드래그=이동 · 더블클릭=글자 수정 · 메뉴 [파일 &gt; 내보내기]도 사용 가능</span>
</div>
<iframe id="ed" src="https://embed.diagrams.net/?embed=1&ui=atlas&spin=1&proto=json&configure=1&lang=ko"></iframe>
<script>
const XML = {xml_js};
const ed = document.getElementById('ed');
let pending = null;
function send(o){{ ed.contentWindow.postMessage(JSON.stringify(o), '*'); }}
function dl(name, blob){{ const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; a.click(); }}
function exp(fmt){{ pending = fmt;
  if(fmt==='png') send({{action:'export', format:'png', scale:4, border:10, background:'#ffffff'}});
  else if(fmt==='svg') send({{action:'export', format:'svg'}});
  else send({{action:'export', format:'xml'}}); }}
window.addEventListener('message', function(evt){{
  if(evt.source !== ed.contentWindow || typeof evt.data !== 'string') return;
  let m; try{{ m = JSON.parse(evt.data); }}catch(e){{ return; }}
  if(m.event === 'configure') send({{action:'configure', config:{{defaultFonts:['Malgun Gothic']}}}});
  else if(m.event === 'init') send({{action:'load', autosave:1, xml: XML}});
  else if(m.event === 'export'){{
    const d = m.data;
    if(pending==='png'){{ const b=atob(d.split(',')[1]); const u=new Uint8Array(b.length); for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i); dl('diagram.png', new Blob([u],{{type:'image/png'}})); }}
    else if(pending==='svg'){{ let s=d; if(s.startsWith('data:')) s=atob(s.split(',')[1]); dl('diagram.svg', new Blob([s],{{type:'image/svg+xml'}})); }}
    else {{ let s=d; if(s.startsWith('data:')) s=atob(s.split(',')[1]); dl('diagram.drawio', new Blob([s],{{type:'application/xml'}})); }}
  }}
}});
</script></body></html>"""


def mermaid_html(code: str, height: int = 520) -> str:
    code_js = json.dumps(code)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:'Malgun Gothic',sans-serif}} #bar{{padding:6px}} button{{margin-right:6px;padding:4px 10px}}
#out{{padding:10px;overflow:auto;height:{height - 50}px}}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script></head><body>
<div id="bar"><button onclick="png()">PNG 다운로드</button><button onclick="svg()">SVG 다운로드</button><span id="msg"></span></div>
<div id="out"></div>
<script>
const CODE = {code_js};
mermaid.initialize({{startOnLoad:false, theme:'neutral', flowchart:{{curve:'linear'}}, securityLevel:'loose',
  themeVariables:{{fontFamily:'Malgun Gothic, sans-serif'}}}});
mermaid.render('g1', CODE).then(r=>{{ document.getElementById('out').innerHTML=r.svg; }})
 .catch(e=>{{ document.getElementById('msg').innerText='Mermaid 문법 오류: '+e.message; }});
function svgEl(){{ return document.querySelector('#out svg'); }}
function svg(){{ const s=new XMLSerializer().serializeToString(svgEl()); const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([s],{{type:'image/svg+xml'}})); a.download='diagram.svg'; a.click(); }}
function png(){{ const el=svgEl(); const bb=el.getBoundingClientRect(); const s=new XMLSerializer().serializeToString(el);
  const img=new Image(); img.onload=function(){{ const k=4; const c=document.createElement('canvas'); c.width=bb.width*k; c.height=bb.height*k;
  const x=c.getContext('2d'); x.fillStyle='#fff'; x.fillRect(0,0,c.width,c.height); x.drawImage(img,0,0,c.width,c.height);
  c.toBlob(b=>{{ const a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download='diagram.png'; a.click(); }}); }};
  img.src='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(s))); }}
</script></body></html>"""
