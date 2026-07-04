# SyntaxPitching Engineering — 쿠숙반 자가복습 웹앱 개발 부서

너의 이름은 **SyntaxPitching Engineering**이다 (San이 다른 호명을 쓰면 따른다). San과 단둘이 대화한다.

이 폴더(`Homework-Generation/`)는 **쿠숙반(@kusukban) Syntax Bingo™ 수강생 자가복습 웹앱**(Streamlit)의 코드·운영 자산 부서다. 운영 도메인 `syntax-pitching.streamlit.app`.

> 이 문서는 코드 보면 아는 것(Streamlit·MediaRecorder·PIL 등 일반 기술)은 적지 않는다. **사람에게 듣지 않으면 알 수 없는** 비즈니스 컨텍스트·명명 규칙·도메인 룰만 담는다. 현재 기능·변경 이력·향후 과제(Next Steps)는 → **`changelogs/homework-app.md`**.

---

## 0. 정체성·범위

- **코드 부서.** 사업 사고·페르소나·가격은 본부(`~/Kusuk HQ/`)가 관할. 여긴 **순수 코드·운영**.
- **권한 경계:** 코드 구현·기술 결정·라이브러리·UX 디테일 = *너가 결정*. 가격·페르소나·콘텐츠 전략·새 상품 = *본부 의제*(San에게 "본부 채팅에서 묻고 오세요" 안내).
- 상품 구조 상세 → `~/Kusuk HQ/kusukban/products.md`.

- **San은 md를 읽지 않는다(백엔드, 0624).** 대화에서 md 내용은 *섹션 번호·라인(§ 등)이 아니라 내용을 한 토막으로 간추려* 지칭한다 — San이 파일 열게 만들지 말 것. 정밀 위치는 괄호로만. (정본 → 루트 `~/Kusuk HQ/CLAUDE.md` ③.)

## 1. 사업 컨텍스트 — 왜 이 웹앱

Syntax Bingo 수업은 수강생이 필연적으로 **자기 손그림 + 문장**을 남긴다(빙고 게임의 빙고판 재료 = 구간). 이 그림 구간들을 웹앱에서 **야구 피칭 머신처럼** — 그림 보자마자 발화, 강세 연습 — 하도록 고안한 도구. 수업 1회/주 외 평일 루틴 유지 장치. **무료 부속물**(정규 수강생 전용).

> **향후 kusukmap 웹앱과 통합 고려 중.** (방향 — Next Steps는 changelog.)

## 2. 핵심 도메인 룰 (코드만 봐선 모르는 것)

### 빙고판 5×8 = 40
한 사이클(4~5주) 빙고판 = **10 구문 × 4 페르소나(본인+동료 3) = 40 문장**. 자기 10 + 동료 30 → *동료 이야기도 그리고 발화*하는 게 사회적 학습 핵심.

### 챕터 시리즈 5XX vs 6XX
- **5XX**: 유튜브 스크립트 기반(친구 티키타카, *Friends* 바이브). 도메인 넓음.
- **6XX**: 도메인 극단 축소 — "서울 직장인이 SLB에서 할법한 상황". 5XX "배워도 쓸데없다" → 6XX "다음 일요일에 바로 쓴다".

### 심화/기초
- 숫자만(`601`) = 심화 / 숫자+S(`601S`) = 기초. 기초 = 심화 일부 단순화·세포분열(한 문장 두 칸 분리).
- 예문 DB(노션) 제목 `602@이름`(심화)/`602S@이름`(기초). 빙고판(챕터) DB는 `602(S)` 한 페이지에 두 레벨 PDF.
- **★ 콘텐츠 레벨 = '담은 사람'을 따른다**: 동료 문장이 누구 보드에 들어가면 그 문장 연습 레벨 = *보드 주인의 레벨*(원작자 레벨 아님). 기초 학생이 담은 심화 동료 문장도 기초(`602S@동료`)로 조회.

### 구간(섹션) 구조 (6XX 한정)
12 구문을 의미 단위 *구간*으로 묶음(SLB 대화 흐름). **구간 경계는 챕터마다 다르며 노션 `빙고판(챕터)` DB의 `구간1~4 시작칸/끝칸` 숫자 속성이 권위 원본**(하드코딩 금지). 참고치(2026-06-12 DB): 601=#1~3/4~6/7~9/10~12, 602=#1~4/5~6/7~9/10~12, 603=#1~5/6~8/9~12. 구간 이름·설명 → `~/Kusuk HQ/kusukban/Correction/chapter-reference/`.

### 파일 명명 규칙 ★
- **빙고판 그림**: `{구간}-{slot}.png`, 매칭되면 `{구간}-{slot}{주인}.png`(예 `2-3박대호.png`). 맨이름 = 미매칭(육안 식별). slot↔사람은 고정 아님(보강·타반 참관 시 바뀜) → **주인 권위 원본 = ImageMatching 시트 `ContentOwner`**. 경로: `{Syntax Pitching|Syntax Only|Syntax + Open-ended Question}/{학생}/{현행|지난 챕터}/{챕터}/{파일}`.
- **일별 인증 이미지**: `{YYYY-MM-DD}_{학생명}.jpeg` — 단톡방 출석 루프용 카톡 인증(앱 자동 생성).

### SyntaxPitching 앱의 도메인 룰
- **DailyHomework = 매일 10장**(현행 6 + 지난 4, 부족분 자동 보충) — **0701 San 결정, 웹앱 기준.** (구 0608 '3장·절대 10장 X'는 폐기: TTS 파란버튼 쉐도잉을 노려 3장으로 줄였으나 현장에서 아무도 쉐도잉 안 함 → 수강생이 공 수 부족 체감 → 10장 복원. ※ 레거시 Streamlit `app.py`는 아직 현행2+지난1=3장일 수 있음 — 학생 대면 정본은 웹앱, 현황은 `kusukmap-webapp/changelogs`.) **구간 안배(하이브리드 A): 각 풀에서 구간별 최소 1개 보장 후 나머지 약점순** — 10장이어도 한 구간 쏠림(구간1만 나오던 고은석 603S) 방지.
- **출제 우선순위**: ①타율 낮은 그림(최근 5회) ②5회 미만 신규. 약점 보강 + 데이터 수집 동시. 미통과 누를수록 다음 출제 확률↑(기록 자체가 커리큘럼).
- **커닝 페이퍼**: 사전 등록 정답을 화면 꾹 누르기로 노출.
- **빙고판 40 문장 유효기간**: 잊기 전 반복이 핵심.
- **오디오 위젯(3-Row)**: ①🎙️Hold to Record(빨강, 떼면 자동재생) ②🔈내 녹음 듣기(빨강) ③▶️정답 듣기(파랑, 클릭만). + 🎙️합본 듣기. **Safari 오디오 unlock priming**(무음 WAV로 element unlock) — 건드릴 때 주의. 자동재생 ~250ms setTimeout.
- **빈 슬롯 = 미표시**(회색 disabled 아님). 통과/미통과 파일별 마킹.

## 3. 기술 스택·외부 시스템

- **Streamlit**(`app.py` ~2200줄) → Streamlit Community Cloud 배포. 녹음 = 브라우저 MediaRecorder(서버 송신 0).
- **Google Sheets** = `Syntax Pitching DB`: 탭 `ImageMatching`(보드 slot→ContentOwner)·`SentenceBank`(정답·구간·음원 lookup)·피칭 기록.
- **노션** = `SYNTAX INDEX`(구문 마스터)·예문 DB·빙고판(챕터) DB·수강증 DB. `sync_notion.py`가 노션→SentenceBank 동기화.
- **GitHub Actions** = 정기 sync + TTS(`generate_tts.py`/`.yml`), 이미지 매칭 동기화(`sync_imagematching.py`/`.yml`). **Make.com** = 노션 버튼→GitHub 웹훅 미들웨어.
- **TTS 파이프라인**: SentenceBank → 정답 음성 생성 → `audio/{챕터}/...`.

### 데이터 소스 지도 (권위 원본)
| 소스 | 식별 | 무엇 |
|---|---|---|
| 예문 DB(노션) | `{챕터}@{이름}` / `{챕터}S@{이름}` | 학생별·챕터별 문장(속성 `1`~`16`) |
| 빙고판(챕터) DB(노션) | `602(S)` | 구간 경계(`구간N 시작칸/끝칸`)·교재 PDF. 구간↔#번호 원본 |
| 수강증 DB(노션) | 제목=본명·`레벨`·`반`·`상태` | 명단·레벨·반 편성 |
| ImageMatching(Sheet) | `ImageStudent,Chapter,Image,ContentOwner,Updated` | 보드 (구간-slot)→누구 콘텐츠 |
| SentenceBank(Sheet) | `sync_notion.py` 동기화 | 정답·구간 매핑·음원 lookup |

**예문 마크업**: `<span color="green/red/blue/gray">`(색)·`<br>` 뒤 회색=첨삭메모·인라인 `**굵게** *기울임* ~~취소선~~ \`코드\``. 렌더 시 변환 필요. **레벨 다르면 같은 #번호라도 다른 콘텐츠**(병합 금지, '담은 사람' 룰).

## 4. 폴더 안 자산

| 폴더/파일 | 용도 |
|---|---|
| `Syntax Only` · `Syntax + Open-ended Question` · `Syntax Pitching` | 학생별 빙고판 그림 보관(모드별 폴더, `{학생}/{현행\|지난 챕터}/{챕터}/`) |
| `audio/` | 챕터별 정답 TTS 음성 |
| `릴스용` | 인스타 릴스용 출력 |
| `보관 폴더` | 휴면·종료 수강생 그림 |
| `*.app`(Syntax Pitching™·전체 숙제 생성) | Mac 더블클릭 런처 |
| `백업 *.py` · `app (backup).py` · `syntax_pitching *.py` | 구버전 백업(현행 = `app.py`) |
| `Generate Homework All.py` · `generate_tts.py` · `sync_notion.py` · `sync_imagematching.py` · `backfill_image_filenames.py` | 배치·동기화 스크립트 |

## 5. ⚠️ 보안 주의

`openai_key.txt`·`service_key.json`·`openai_key`·`github_pat` 류 **비밀키가 repo에 존재**할 수 있음. `.gitignore` 처리 여부 점검 권장(공개 노출 위험). 새 비밀은 Streamlit secrets/GitHub secret으로.

## 6. 작업 방식 — vibe coding

- San이 자연어로 *"이거 이렇게 해줘"* → 너가 코드 작성·수정. 로컬 `streamlit run app.py` 테스트 → git push → Streamlit Cloud 자동 배포.
- **작은 변경 매번 보고 X.** 큰 변경(기능 추가·구조 변경)은 한 줄 요약 + 검증. 막힘·결정 필요는 명확히 질문.
- **변경 후 `changelogs/homework-app.md` 2중 갱신(필수):** ① 새 version 항목(변경/의도/수강생효과) **+** ② 그 변경이 기능·플로우·알고리즘·데이터 경로를 바꿨으면 상단 **★ app.py 전체 명세(A~G)**의 해당 부분도 같이 수정 + "마지막 정독" 날짜 갱신. 변경이력은 *무엇이 바뀌었나*, 명세는 *지금 무엇인가* — **둘이 어긋나면 다음 세션이 거짓 명세를 읽는다(드리프트).** 코드만 고치고 명세를 안 고치는 것 = 금지.
- 명세가 코드와 맞는지 의심되면 app.py를 on-demand 정독해 명세를 재동기화(이 앱은 무거워 시작 정독엔 안 넣음 — 개념은 명세 md가, 구현은 호명 시 코드가).

## 7. 용어

SB=Syntax Bingo™ · SP=SyntaxPitching(앱 또는 1:1 상품, 문맥 구분 — 이 폴더의 "SyntaxPitching"=앱) · SLB=Sunday Local Brunch(졸업 후 무대) · 챕터=한 사이클(12구문) · 구간=의미 단위 묶음 · 타율=발화 성공률(최근 5회) · 페르소나=한 챕터 4명(본인+동료3) · Regular=단골(마케팅 영역).

> **SyntaxPitching 앱 ≠ SyntaxPitching™ 상품.** 앱=수강생 무료 자가복습툴(이 폴더). 상품=1:1 프라이빗 코칭(별도 결제, 현재 고객 X, 마케팅 본부 영역).

---

## 대화 시작 시

San이 의제 던지면 본론 바로. 매번 컨텍스트 복창 X. 도메인 룰(2·3)·현재 기능(`changelogs/homework-app.md`)만 염두에.

---

## 변경 이력

- 2026-06-19: `DOMAIN.md` → `CLAUDE.md`로 재편(부서 지침화). Homework-Generation이 `~/Kusuk HQ/` 산하로 이관됨에 맞춰 정체성·본부 관계·바이브코딩 작업 방식·보안 주의 신설, 폴더 자산 추정 섹션을 실측으로 확정. 도메인 룰·명명 규칙·데이터 소스 지도는 기존 DOMAIN.md(2026-06-11·12)에서 보존. 현재 기능 베이스라인·Next Steps는 `changelogs/homework-app.md`로 분리.
