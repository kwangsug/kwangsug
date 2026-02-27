"""인크루트 RSS → 6축 구조화 JSON 파서.

Usage:
    python scripts/parse_incruit_rss.py data/rss_sample.xml
    python scripts/parse_incruit_rss.py data/rss_sample.xml -o data/parsed_output.json
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# ── 프로젝트 루트 기준으로 온톨로지 로드 ─────────────────────────
ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_DIR = ROOT / "ontology"


def load_ontology(name: str) -> dict:
    path = ONTOLOGY_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 온톨로지 → 역방향 인덱스 구축 ────────────────────────────────
def _build_location_index(taxonomy: list, parent_code: str = "") -> dict[str, str]:
    """지역 택소노미에서 label_ko → code 역인덱스 생성."""
    index: dict[str, str] = {}
    for node in taxonomy:
        code = node["code"]
        label = node.get("label_ko", "")
        if label:
            index[label] = code
        for child in node.get("children", []):
            child_label = child.get("label_ko", "")
            if child_label:
                index[child_label] = child["code"]
            for grandchild in child.get("children", []):
                gc_label = grandchild.get("label_ko", "")
                if gc_label:
                    index[gc_label] = grandchild["code"]
    return index


def _build_alias_index(ontology: dict) -> dict[str, str]:
    """aliases 맵 반환 (소문자 키)."""
    aliases = ontology.get("aliases", {})
    return {k.lower(): v for k, v in aliases.items() if v is not None}


# ── RSS description 필드 파싱 ─────────────────────────────────────
_FIELD_RE = re.compile(r"▨\s*(.+?)\s*:\s*(.*?)(?=▨|$)", re.DOTALL)


def parse_description(raw_html: str) -> dict[str, str]:
    """description의 ▨ 구분자 기반으로 필드 추출."""
    text = re.sub(r"<[^>]+>", " ", raw_html).strip()
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(text):
        key = m.group(1).strip()
        val = m.group(2).strip()
        fields[key] = val
    return fields


# ── 경력 텍스트 → seniority 구조화 ───────────────────────────────
_EXP_YEAR_RE = re.compile(r"(\d+)\s*년")


def parse_experience(exp_text: str) -> dict:
    """경력 텍스트 → {level, exp_years_min, raw}."""
    result: dict = {"raw": exp_text, "level": None, "exp_years_min": None}

    if "경력무관" in exp_text or "무관" in exp_text:
        result["level"] = "any"
        return result

    is_entry = "신입" in exp_text
    is_experienced = "경력" in exp_text

    year_match = _EXP_YEAR_RE.search(exp_text)
    if year_match:
        years = int(year_match.group(1))
        result["exp_years_min"] = years
        if years >= 9:
            result["level"] = "SEN-SENIOR"
        elif years >= 4:
            result["level"] = "SEN-MID"
        elif years >= 1:
            result["level"] = "SEN-JUNIOR"
    elif is_entry and not is_experienced:
        result["level"] = "SEN-ENTRY"
    elif is_entry and is_experienced:
        result["level"] = "SEN-ENTRY+"

    return result


# ── 지역 텍스트 → location 구조화 ────────────────────────────────
_LOC_REGION_MAP = {
    "서울": "LOC-KR-SEL",
    "경기": "LOC-KR-GGI",
    "인천": "LOC-KR-GGI-ICN",
    "부산": "LOC-KR-BSN",
    "대구": "LOC-KR-DGU",
    "대전": "LOC-KR-DJN",
    "광주": "LOC-KR-GJU",
    "울산": "LOC-KR-ULS",
    "제주": "LOC-KR-JJU",
    "충북": "LOC-KR-CBK",
    "충남": "LOC-KR-CNM",
    "경북": "LOC-KR-GBK",
    "경남": "LOC-KR-GNM",
    "전북": "LOC-KR-JBK",
    "전남": "LOC-KR-JNM",
    "강원": "LOC-KR-GWN",
    "세종": "LOC-KR-SJG",
}

# 서울 구 → 권역 매핑
_SEOUL_GU_MAP = {
    "강남구": "LOC-KR-SEL-GN", "서초구": "LOC-KR-SEL-GN",
    "구로구": "LOC-KR-SEL-GD", "금천구": "LOC-KR-SEL-GD",
    "영등포구": "LOC-KR-SEL-YS", "여의도": "LOC-KR-SEL-YS",
    "종로구": "LOC-KR-SEL-JG", "중구": "LOC-KR-SEL-JG",
    "마포구": "LOC-KR-SEL-MP",
    "송파구": "LOC-KR-SEL-SC", "잠실": "LOC-KR-SEL-SC",
}

# 경기 시 → 권역 매핑
_GGI_CITY_MAP = {
    "성남시": "LOC-KR-GGI-SNG", "분당구": "LOC-KR-GGI-SNG",
    "수원시": "LOC-KR-GGI-SWN", "화성시": "LOC-KR-GGI-SWN",
    "용인시": "LOC-KR-GGI-YIN",
    "이천시": "LOC-KR-GGI-ETC",
}


def parse_location(loc_text: str) -> dict:
    """지역 텍스트 (|서울>송파구) → 구조화된 location."""
    result: dict = {
        "raw": loc_text,
        "country": "KR",
        "regions": [],
    }
    if not loc_text:
        return result

    # 복수 지역: |대구|경북
    parts = [p.strip() for p in loc_text.split("|") if p.strip()]
    for part in parts:
        region: dict = {"code": None, "city": None, "district": None}
        if ">" in part:
            tokens = part.split(">")
            sido = tokens[0].strip()
            detail = tokens[1].strip() if len(tokens) > 1 else ""
            region["city"] = sido
            region["district"] = detail or None
            region["code"] = _LOC_REGION_MAP.get(sido)

            # 세부 매핑
            if sido == "서울" and detail:
                region["code"] = _SEOUL_GU_MAP.get(detail, "LOC-KR-SEL-ETC")
            elif sido == "경기" and detail:
                for key, code in _GGI_CITY_MAP.items():
                    if key in detail:
                        region["code"] = code
                        break
                else:
                    region["code"] = "LOC-KR-GGI-ETC"
        else:
            region["city"] = part
            region["code"] = _LOC_REGION_MAP.get(part)

        result["regions"].append(region)

    return result


# ── 제목에서 직무 키워드 추론 ─────────────────────────────────────
_ROLE_KEYWORDS: dict[str, str] = {
    "백엔드": "ROLE-DEV-BE", "서버 개발": "ROLE-DEV-BE",
    "프론트엔드": "ROLE-DEV-FE", "웹 개발": "ROLE-DEV-FE",
    "풀스택": "ROLE-DEV-FS",
    "앱 개발": "ROLE-DEV-APP", "iOS": "ROLE-DEV-APP", "Android": "ROLE-DEV-APP",
    "게임 개발": "ROLE-DEV-GAME",
    "데이터 엔지니어": "ROLE-DATA-DE",
    "데이터 사이언": "ROLE-DATA-DS",
    "ML": "ROLE-DATA-ML", "AI": "ROLE-DATA-ML", "머신러닝": "ROLE-DATA-ML",
    "DevOps": "ROLE-INFRA-DEVOPS", "SRE": "ROLE-INFRA-SRE",
    "클라우드": "ROLE-INFRA-CLOUD", "Cloud": "ROLE-INFRA-CLOUD",
    "보안": "ROLE-INFRA-SEC", "보안관제": "ROLE-INFRA-SEC",
    "DBA": "ROLE-INFRA-DBA",
    "서비스 기획": "ROLE-PM-SP", "기획자": "ROLE-PM-SP",
    "Product Manager": "ROLE-PM-PO", "PM": "ROLE-PM-PO",
    "프로젝트 매니저": "ROLE-PM-PJM",
    "UX": "ROLE-DESIGN-UX", "UI": "ROLE-DESIGN-UX",
    "디자이너": "ROLE-DESIGN-GR", "광고 디자이너": "ROLE-DESIGN-GR",
    "마케터": "ROLE-MKT-DIG", "마케팅": "ROLE-MKT-DIG",
    "영업": "ROLE-SALES-B2B",
    "회계": "ROLE-FIN-ACC", "세무": "ROLE-FIN-TAX",
    "인사": "ROLE-HR-REC", "채용 담당": "ROLE-HR-REC",
    "QA": "ROLE-QA-MAN", "테스트": "ROLE-QA-MAN",
    "CS": "ROLE-CS-OPS", "고객": "ROLE-CS-OPS",
    "간호": "ROLE-OTHER-NURSE",
    "엔지니어": "ROLE-OTHER-ENG",
}


def infer_role_from_title(title: str) -> list[dict]:
    """제목에서 직무 코드를 추론 (best-effort)."""
    matched = []
    # "채용", "모집", "공고" 등 공통 단어를 제거한 제목으로 매칭
    cleaned = re.sub(r"(경력직|정규직|계약직)?\s*(채용|모집|공고|구인)\s*(공고)?", "", title)
    for keyword, code in _ROLE_KEYWORDS.items():
        # 단어 경계를 고려 — 영문 약어(ML, AI, PM 등)가 다른 단어에 포함되지 않도록
        pattern = re.compile(
            r"(?<![A-Za-z])" + re.escape(keyword) + r"(?![A-Za-z])",
            re.IGNORECASE,
        )
        if pattern.search(cleaned):
            matched.append({"keyword": keyword, "code": code})
    # 중복 코드 제거 (첫 매칭 우선)
    seen_codes: set[str] = set()
    unique = []
    for m in matched:
        if m["code"] not in seen_codes:
            seen_codes.add(m["code"])
            unique.append(m)
    return unique


# ── 학력 파싱 ─────────────────────────────────────────────────────
_EDU_MAP = {
    "무관": "any",
    "고졸": "high_school",
    "초대졸": "associate",
    "대졸": "bachelor",
    "석사": "master",
    "박사": "doctorate",
}


def parse_education(edu_text: str) -> dict:
    raw = edu_text.strip()
    for key, level in _EDU_MAP.items():
        if key in raw:
            return {"raw": raw, "min_level": level}
    return {"raw": raw, "min_level": None}


# ── 마감일 파싱 ───────────────────────────────────────────────────
def parse_deadline(deadline_text: str) -> dict:
    raw = deadline_text.strip()
    if raw in ("채용시", "상시"):
        return {"raw": raw, "type": "open"}
    return {"raw": raw, "type": "fixed"}


# ── 제목에서 회사명 추출 ──────────────────────────────────────────
_TITLE_COMPANY_RE = re.compile(r"^\[(.+?)\]")


def extract_company_from_title(title: str) -> Optional[str]:
    m = _TITLE_COMPANY_RE.search(title.strip())
    return m.group(1) if m else None


# ── embedding_text 생성 ──────────────────────────────────────────
def build_embedding_text(job: dict) -> str:
    """6축 정보를 결합한 임베딩용 텍스트 생성."""
    parts = []

    # 회사
    company = job.get("company", {})
    if company.get("name"):
        parts.append(f"회사: {company['name']}")

    # 지역
    loc = job.get("location", {})
    regions = loc.get("regions", [])
    if regions:
        loc_strs = []
        for r in regions:
            s = r.get("city", "")
            if r.get("district"):
                s += f" {r['district']}"
            loc_strs.append(s)
        parts.append(f"지역: {', '.join(loc_strs)}")

    # 직무
    roles = job.get("role", {}).get("inferred", [])
    if roles:
        parts.append(f"직무: {', '.join(r['keyword'] for r in roles)}")

    # 직급
    sen = job.get("seniority", {})
    if sen.get("raw"):
        parts.append(f"경력: {sen['raw']}")

    # 역량 (RSS에서는 학력만 가능)
    skills = job.get("skills", {})
    if skills.get("education", {}).get("raw"):
        parts.append(f"학력: {skills['education']['raw']}")

    # 제목 전문 (가장 풍부한 정보)
    title = job.get("title_clean", "")
    if title:
        parts.append(f"공고: {title}")

    return " | ".join(parts)


# ── 메인 파서 ─────────────────────────────────────────────────────
def parse_rss_item(item_el: ET.Element) -> dict:
    """단일 RSS <item> → 6축 구조화 JSON."""
    title_raw = (item_el.findtext("title") or "").strip()
    link = (item_el.findtext("link") or "").strip()
    desc_raw = (item_el.findtext("description") or "").strip()
    author = (item_el.findtext("author") or "").strip()
    pub_date = (item_el.findtext("pubDate") or "").strip()

    # job_id 추출
    job_id_match = re.search(r"job=(\d+)", link)
    job_id = job_id_match.group(1) if job_id_match else None

    # title 정리 (앞의 [회사명] 제거)
    title_clean = re.sub(r"^\[.+?\]\s*", "", title_raw).strip()
    # 두번째 [회사명] 도 제거
    title_clean = re.sub(r"^\[.+?\]\s*", "", title_clean).strip()

    # description 필드 파싱
    fields = parse_description(desc_raw)

    # 회사명: author 또는 description에서
    company_name = author or fields.get("회사명", "") or extract_company_from_title(title_raw) or ""

    # 6축 구조화
    job: dict = {
        "job_id": job_id,
        "source": "incruit",
        "source_url": link,
        "pub_date": pub_date,
        "title_raw": title_raw,
        "title_clean": title_clean,

        # 1. 회사
        "company": {
            "name": company_name.strip(),
        },

        # 2. 지역
        "location": parse_location(fields.get("지역", "")),

        # 3. 직무 (제목 기반 추론)
        "role": {
            "inferred": infer_role_from_title(title_raw),
            "_note": "RSS에는 직무 카테고리가 없어 제목에서 추론. 정확한 매핑은 상세 JD 필요."
        },

        # 4. 직급
        "seniority": parse_experience(fields.get("경력", "")),

        # 5. 역량 (RSS에서는 학력만)
        "skills": {
            "education": parse_education(fields.get("학력", "")),
            "_note": "필수/우대 스킬은 RSS에 없음. 상세 JD에서 추출 필요."
        },

        # 6. 보수 (RSS에 없음)
        "compensation": {
            "_note": "RSS에 보수 정보 없음. 상세 JD에서 추출 필요."
        },

        "deadline": parse_deadline(fields.get("마감일", "")),
    }

    # embedding_text 생성
    job["embedding_text"] = build_embedding_text(job)

    return job


def parse_rss_file(xml_path: str) -> list[dict]:
    """RSS XML 파일 전체 파싱."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        return []

    items = channel.findall("item")
    return [parse_rss_item(item) for item in items]


# ── 커버리지 리포트 ───────────────────────────────────────────────
def coverage_report(jobs: list[dict]) -> dict:
    """6축별 데이터 커버리지 요약."""
    total = len(jobs)
    report = {
        "total_jobs": total,
        "coverage": {
            "company_name": sum(1 for j in jobs if j["company"]["name"]),
            "location": sum(1 for j in jobs if j["location"]["regions"]),
            "role_inferred": sum(1 for j in jobs if j["role"]["inferred"]),
            "seniority": sum(1 for j in jobs if j["seniority"]["level"]),
            "education": sum(1 for j in jobs if j["skills"]["education"]["min_level"]),
            "compensation": 0,  # RSS에 없음
        },
    }
    for k, v in report["coverage"].items():
        report["coverage"][k] = f"{v}/{total}"
    return report


# ── CLI ───────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <rss_xml_path> [-o output.json]")
        sys.exit(1)

    xml_path = sys.argv[1]
    output_path = None
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    jobs = parse_rss_file(xml_path)
    report = coverage_report(jobs)

    result = {
        "_meta": {
            "source": "incruit_rss",
            "parser_version": "0.1",
            "total_items": len(jobs),
            "coverage": report["coverage"],
        },
        "jobs": jobs,
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Parsed {len(jobs)} jobs → {output_path}")
    else:
        print(output_json)

    # 커버리지 요약 출력
    print(f"\n── 6축 커버리지 ({len(jobs)}건) ──", file=sys.stderr)
    for k, v in report["coverage"].items():
        print(f"  {k:20s} {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
