# Skill: semantic-job-matching-v0.1

## 목표

- 채용공고(JD)를 **회사-지역-직무-직급-역량-보수** 6개 축으로 구조화한다.
- 각 축별로 임베딩에 사용할 텍스트(`embedding_text`)를 생성한다.
- 벡터 DB(Qdrant 또는 pgvector)와 연동해 Job–Candidate 시맨틱 매칭 기반을 만든다.

## 워크플로우

1. JD 원문 붙여넣기
2. JSON 스키마로 파싱 (6축 구조화)
3. `embedding_text` 필드 생성
4. 벡터 DB에 저장

## 프로젝트 구조

```
semantic-job-matching-v0.1/
├── CLAUDE.md                        # 프로젝트 목적·범위·Claude 협업 원칙
├── docs/
│   ├── 01_problem_statement.md      # 시맨틱 매칭 필요성·문제 정의
│   └── 02_schema_design.md          # 6축 스키마 설계·필드 명세
├── schemas/
│   ├── job_schema.json              # 채용공고 JSON 스키마
│   ├── job_example.json             # 샘플 (비워둠)
│   └── candidate_schema.json        # 후보자 JSON 스키마
└── prompts/
    ├── jd_to_schema_ko.txt          # JD → 구조화 프롬프트 (한국어)
    └── resume_to_schema_ko.txt      # 이력서 → 구조화 프롬프트 (한국어)
```

## 6축 요약

| 축 | 설명 | 예시 |
|---|---|---|
| 회사 (company) | 기업명, 그룹, 업종, 기업 설명 | 삼성전자 / 삼성 / 반도체 |
| 지역 (location) | 국가, 도시, 해외 여부, 근무형태 | 한국 / 서울 / onsite |
| 직무 (role) | 직무명, 카테고리, 상세 업무 | 백엔드 개발자 / IT·개발 |
| 직급 (seniority) | 직급, 경력 연차 범위 | 대리~과장 / 3~7년 |
| 역량 (skills) | 필수·우대 스킬, 자격증, 학력 | Python, AWS / 정보처리기사 |
| 보수 (compensation) | 급여 범위, 통화, 복리후생 | 5000만~7000만 KRW |

## Claude 기본 원칙

- 공고/이력서에 **없는 정보는 추측하지 않는다**.
- 한국어 필드는 한국어 유지, 필요 시 영문 병기.
- 스키마 변경 시 반드시 `docs/02_schema_design.md`도 함께 업데이트.
