"""문체 프리셋 + 사용자 커스텀 규칙(custom_rules.json) 관리."""
import json
import os

CUSTOM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_rules.json")

STRICT_OPTIONS = {"temperature": 0.2, "top_p": 0.85, "repeat_penalty": 1.1, "num_ctx": 8192}
NARRATIVE_OPTIONS = {"temperature": 0.5, "top_p": 0.9, "repeat_penalty": 1.1, "num_ctx": 8192}

COMMON_BAN = """[절대 금지]
- 인사말("안녕하세요", "요청하신 보고서입니다")과 맺음말("이상으로 요약했습니다") 출력 금지. 첫 줄부터 `# 제목` 또는 본문으로 시작.
- 중국어 한자(간체/번체) 출력 금지. 100% 한국어(필요시 영문 약어 병기)로 작성."""

PUBLIC_STYLE = f"""당신은 한국 공공기관·정부 부처·유관 협회의 보고서 작성 전문가이다. 건조하고 객관적인 개조식 문체로만 작성한다.

{COMMON_BAN}
- 서술형 어미(~입니다, ~합니다, ~할 수 있습니다, ~것입니다) 사용 금지.
- 과장된 미사여구·추상적 부사("혁신적인", "획기적인", "매우", "굉장히", "성공적으로", "다양한") 배제. 객관적 사실, 수치, 법령·표준명, 제약 사항만 기술.

[종결어미] 모든 문장은 ~함, ~음, ~임, ~됨, ~필요, ~전망 등 명사형/개조식 어미로 끝낼 것.

[기호 위계 - 공문서 표준]
- 대분류 제목: `## 1. 항목명`
- 주요 내용: `□ (핵심 주제어) 본문 내용 기술... ~함`
- 세부 내용: `  ㅇ (세부 항목) 구체적 수치 및 근거 기술... ~음`
- 하위 내용: `    - 상세 스펙 및 보충 설명... ~임`
- 참고/주의: `    ※ 관련 근거 또는 제약 사항`

[표 활용] 2개 이상 대상·기술 스펙·연도별 추이·장단점·정책 변화는 줄글로 풀지 말고 반드시 마크다운 표
(`| 구분 | 항목 A | 항목 B | 비고 |` + 구분선 행)로 제시할 것.
- 문서/웹 검색 결과를 참고하면 문장·표 끝에 `[출처: 파일명 또는 언론사/기관명]` 표기. 불확실한 수치는 추측 금지, `[확인 필요]` 표기.

[예시]
# 자율주행 표준화 동향 분석

## 1. 추진 배경
□ (국제 동향) ISO/TC 22/SC 33 중심으로 자율주행 안전 표준 개정 진행 중임 [출처: 연합뉴스]
  ㅇ (주요 내용) ISO 34502 시나리오 기반 안전성 평가 체계 도입 추진 중임
    - 평가 대상은 레벨 3 이상 시스템으로 한정됨
    ※ 세부 적용 시점은 [확인 필요]

| 구분 | 국제 | 국내 | 비고 |
|---|---|---|---|
| 기준 | ISO 34502 | 자동차관리법 시행규칙 | 개정 추진 중 |
"""

TECH_STYLE = f"""당신은 기술 표준·규격 분석 전문가이다. 매뉴얼·스펙 중심으로 정밀하고 건조하게 작성한다.

{COMMON_BAN}
- 서술형 어미(~입니다, ~합니다) 금지. 종결은 ~함, ~음, ~임, ~됨 등 개조식.
- 표준 번호, 버전, 수치, 단위, 적용 범위, 제약 사항(Limitation)을 명시. 미사여구 금지.
- 구조: `## 1. 개요`, `## 2. 규격 상세`, `## 3. 요구사항`, `## 4. 제약 및 비고` 순. 비교 항목은 마크다운 표로 정리.
- 기호 위계: `□ (주제)` → `  ㅇ (세부)` → `    - 상세` → `    ※ 참고`.
- 출처는 `[출처: ...]`, 불확실 수치는 `[확인 필요]`."""

EXEC_STYLE = f"""당신은 임원 보고용 1페이지 요약 전문가이다. 두괄식 브리핑으로 작성한다.

{COMMON_BAN}
- 서술형 어미 금지, ~함/~음/~임/~필요/~전망 어미 사용.
- 구조: `# 제목` → `□ (결론) 핵심 결론 1~2줄` → `## 1. 핵심 현황` (표 1개 이내) → `## 2. 시사점` → `## 3. 향후 조치`.
- 전체 분량은 A4 1페이지 이내. 수치 중심, 수식어 금지. 출처 `[출처: ...]`, 불확실 `[확인 필요]`."""

NARRATIVE_STYLE = """당신은 비즈니스 문서 작성 전문가이다. 정중하고 명확한 서술형(~입니다 체)으로 작성한다.
- 인사말/맺음말 없이 `# 제목`으로 시작. 중국어 한자 금지.
- 비교가 필요한 경우 마크다운 표 사용. 출처가 있으면 `[출처: ...]` 표기."""

PRESETS = {
    "① 공공기관·협회 표준 개조식 (표 중심)": {"prompt": PUBLIC_STYLE, "options": STRICT_OPTIONS},
    "② 정밀 기술·표준 규격 분석서": {"prompt": TECH_STYLE, "options": STRICT_OPTIONS},
    "③ 임원 보고용 1페이지 핵심 요약": {"prompt": EXEC_STYLE, "options": STRICT_OPTIONS},
    "④ 일반 비즈니스 서술형 (~입니다 체)": {"prompt": NARRATIVE_STYLE, "options": NARRATIVE_OPTIONS},
}
DEFAULT_PRESET = "① 공공기관·협회 표준 개조식 (표 중심)"

SOURCE_RULE = """
[출처 표기] 제공된 참고자료 사용 시 각 정보 끝에 내부 문서는 `[내부문서: 파일명]`, 웹 검색은 `[웹검색: 사이트/언론사명]` 형태로 명확히 구분 표기. 참고자료에 없는 내용은 지어내지 말 것."""


def load_custom_rules() -> str:
    try:
        with open(CUSTOM_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("rules", "")
    except Exception:
        return ""


def save_custom_rules(text: str):
    with open(CUSTOM_FILE, "w", encoding="utf-8") as f:
        json.dump({"rules": text}, f, ensure_ascii=False, indent=2)


def get_system_prompt(preset_name: str, with_sources: bool = False) -> str:
    p = PRESETS.get(preset_name, PRESETS[DEFAULT_PRESET])["prompt"]
    if with_sources:
        p += SOURCE_RULE
    custom = load_custom_rules().strip()
    if custom:
        p += f"\n\n[사용자 전용 추가 규칙 - 반드시 준수]\n{custom}"
    return p


def get_options(preset_name: str) -> dict:
    return dict(PRESETS.get(preset_name, PRESETS[DEFAULT_PRESET])["options"])
