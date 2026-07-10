# Homework App — 변경 이력

**위치:** `~/Kusuk HQ/Homework-Generation/changelogs/homework-app.md` (SyntaxPitching Engineering 부서 폴더 안 — 2026-06-19 HQ 산하 이관, 별도 마운트 불필요. 2026-07-08 md정리로 옛 주소·'Kusuk Staff 본부' 표기 정정)
**작성:** SyntaxPitching Engineering 부서가 버전 올릴 때마다 추가
**참조:** 본부 = `~/Kusuk HQ/` (HQ 정독 규약에 이 changelog 포함).

각 버전 항목:
- **변경**: 기술적 변경 내역 (불릿)
- **의도**: 왜 바꿨는지 (사업적·운영적 배경)
- **수강생 효과**: 기대하는 학습/사용 효과

새 버전은 위에 추가 (최신이 맨 위). 부서 지침 = `../CLAUDE.md`.

---

## ⚠️ 교차 의존 (2026-06-22) — 이 공개 레포가 kusukmap-webapp 자산 소스가 됨
- 이 레포(`github.com/sanslowli/Homework-Generation`, **public**)의 **이미지(`Syntax Pitching/.../*.png`)·음원(`audio/{챕터}/{pane}_{owner}.mp3`)**을, 이관 중인 통합 웹앱이 **jsDelivr CDN**(`cdn.jsdelivr.net/gh/sanslowli/Homework-Generation@main/<경로>`)으로 직접 끌어 씀(R2 업로드 대신). → **레포를 private 전환하거나 자산 폴더 경로·파일명 규칙을 바꾸면 웹앱 피칭 화면이 깨짐.** 변경 시 `kusukmap-webapp` 경로 매핑과 함께 손봐야 함.
- 보안 OK: `service_key.json`·`openai_key.txt`는 `.gitignore`라 미커밋(공개돼도 키 노출 없음). 공개 자산 = 교재 이미지·레퍼런스 TTS뿐(학생 본인 녹음 아님).
- 상세·진행 = `~/Kusuk HQ/kusukmap-webapp/docs/kusukban-integration.md` §4 + 그 폴더 `changelogs/kusukmap-webapp.md`(P2).

---

## ★ app.py 전체 명세 (베이스라인 — 무엇을 하는 앱인가)

> **이 섹션 = 코드를 안 봐도 app.py가 *하는 일 전체*를 알 수 있는 단일 명세.** 아래 변경이력(version)이 *무엇이 바뀌었나*라면, 이 섹션은 *현재 무엇인가*다. **app.py 기능이 바뀌면 변경이력 추가와 함께 이 명세도 갱신**(동기화 규약 = §G·`../CLAUDE.md` §6). 마지막 정독: 2026-06-22(app.py ~2210줄).

### A. 한 줄 정체
Syntax Bingo 수강생이 **수업에서 만든 자기/동료 손그림을 보고, 그 자리에서 영어로 발화하며 강세·리듬을 혼자 반복 훈련**하는 Streamlit 웹앱(`syntax-pitching.streamlit.app`). 야구 피칭 머신 비유 — 그림이 공처럼 날아오면 즉시 발화. 주1회 대면 수업 사이의 **평일 데일리 루틴 장치**. 정규 수강생 전용 무료 부속물(별도 결제 X). 녹음은 **100% 브라우저 메모리, 서버 송신 0**(신뢰 약속).

### B. 사용자 플로우 (세션 모드)
세션 상태 = `setup` / `playing`(챕터 선택 연습) / `daily_playing`(데일리) / `daily_result`(데일리 완료·인증) / `help`(매뉴얼).
- **진입**: 사이드바 selectbox로 학생 선택 **또는 URL `?student={이름}`** 딥링크(미등록 이름이면 경고 후 수동). `?view=manual`이면 사용법 페이지로 라우팅.
- **두 갈래 출제**:
  1. **Daily Homework**(메인 버튼) → `daily_playing`: 자동 **3장**(현행 챕터 2 + 지난 챕터 1, 한쪽 부족 시 다른 쪽 보충). 끝나면 `daily_result`에서 **카톡 인증 이미지** 생성.
  2. **챕터 선택 연습** → `playing`: 사이드바에서 챕터 복수선택 + **타율 필터**(약점만 골라내기) → "훈련 시작". "피칭 기록 보기"로 누적 기록 조회.

### C. 화면별 상세
- **플레이 화면(그림 1장)**: 손그림 1장 표시 → 보고 발화. 하단 **3-Row 오디오 위젯**:
  - ① 🎙️ **Hold to Record**(빨강, 떼면 자동재생 ~250ms) — MediaRecorder, 외부 오버레이 배너로 녹음상태 시각화(손가락이 작은 버튼 가리는 문제 해결).
  - ② 🔈 **내 녹음 듣기**(빨강, 명시 재생).
  - ③ ▶️ **정답 듣기**(파랑, 클릭만 — 자동재생 X = 자기 녹음 전 정답 누설 차단).
  - \+ 🎙️ **합본 듣기**(구간 전체 정답 이어듣기). **Safari 오디오 unlock priming**(무음 WAV로 element unlock — 건드릴 때 주의).
  - **O(통과)/X(미통과)** 마킹 → Google Sheet 저장. 이전/다음·셔플·연습 이동. 빈 슬롯은 회색 아닌 **미표시**.
  - 미매칭(그림 주인 미상)이면 녹음 줄 통째 잠금 + 회색 안내("아직 그림 주인 매칭 전이라 잠겨 있어요").
- **정답 음원 매칭 경로**: 그림 파일 → `image_to_pane`(구간·slot) → ImageMatching 시트(slot→**ContentOwner**) → SentenceBank(정답·구간) → `audio/{챕터}/{Pane}_{Owner}.mp3`. 그림↔주인 매칭은 **앱 내 self-serve 드롭다운** + **파일명 기반**(`{구간}-{slot}{주인}.png`) 양방향.
- **데일리 완료 인증**: `create_summary_image_base64`가 그날 푼 그림들 + 출석 달력 + 오픈형 질문을 한 장으로 합성 → 단톡방에 도장 찍는 출석 의례.
- **피칭 기록**: 챕터별 O/X 누적·타율 조회.
- **매뉴얼**(`?view=manual`): 사용법 설명 페이지.

### D. 함수 지도 (코드 구조, ~2210줄)
- **설정·연결**: `init_connection`(gspread, st.secrets) · `get_data_from_sheet` · `save_to_sheet`(O/X 기록).
- **데이터 로더**: `load_sentence_bank`(정답·구간) · `load_chapter_mapping`(구간 경계) · `load_image_matchings`(slot→주인) · `save_image_matching` · `try_rename_image_on_github`(앱 매칭 시 GitHub 파일명 rename 커밋, 비차단).
- **파일명/매칭 파서**: `extract_section_slot_from_filename` · `match_image_key`(맨이름 정규화) · `owner_suffix_from_filename` · `image_to_pane` · `extract_section_from_filename` · `get_audio_path_pane`/`get_audio_relative_path`/`get_audio_absolute_path`.
- **렌더링(핵심·대형)**: `render_audio_player`(3-Row 위젯·Safari unlock, 348~663) · `render_section_audio_grid`(플레이 그리드 본체, 664~1230) · `render_match_picker` · `render_image_answer_widget`.
- **탐색·통계**: `get_all_student_names`/`get_students_with_chapter_folder`/`get_chapters`/`get_images`/`get_all_students` · `get_attendance`(출석 달력) · `get_random_question`(오픈형 질문 `questions.json`) · `calculate_batting_average`(최근 5회 타율) · `get_daily_target_images`(데일리 3장 선정).
- **인증 이미지**: `get_label_bg_rgba` · `create_summary_image_base64`(PIL 합성).
- **UI 본체**: 사이드바(1740~) · 메인 로직(1825~) · 매뉴얼(2172~).

### E. 출제·학습 알고리즘 (코드만 봐선 의도 모름)
- **데일리 = 매일 3장**(현행 2 + 지난 1). **0608 확정 — 10장으로 되돌리지 말 것**(양<깊이, 3분 루틴).
- **출제 우선순위**: ① 타율 낮은 그림(최근 5회) ② 5회 미만 신규. = 약점 보강 + 데이터 수집 동시. **미통과 누를수록 다음 출제 확률↑ → 기록 자체가 커리큘럼.**
- 커닝페이퍼(화면 꾹 누르면 정답 노출). 빙고판 40문장(자기10+동료30)이 유효기간 — 잊기 전 반복이 핵심.

### F. 데이터 통합 (권위 원본)
`Syntax Pitching DB`(Google Sheets: `ImageMatching`·`SentenceBank`·피칭기록) ← `sync_notion.py`로 노션(`SYNTAX INDEX`·예문 DB·빙고판 DB·수강증 DB) 동기화. TTS = `generate_tts.py`(SentenceBank→`audio/`). GitHub Actions 정기 sync + Make.com(노션 버튼→웹훅). 상세 = `../CLAUDE.md` §3.

### G. 역할 (사업·커리큘럼에서의 위치)
- **리텐션 장치**: 주1회 대면의 효과를 평일에 이어 붙여 망각 방지 → 수강생 경험·완주율·재결제에 기여(`~/Kusuk HQ/kusukban/persona.md` Retention economy).
- **데이터 수집기**: 발화 타율·약점이 쌓여 커리큘럼·첨삭 피드백 루프의 원료.
- **상품 페이지 자산(예정)**: bio 링크 수업소개를 더 효과적인 상품 페이지로 만들 때의 핵심 demo. → kusukmap-webapp 통합 시 정식 웹앱으로 이주 검토(Next Steps).
- ⚠️ **앱 ≠ 상품**: 이 앱(SyntaxPitching 자가복습툴) ≠ Syntax Pitching™ 1:1 프라이빗 코칭 상품(`~/Kusuk HQ/kusukban/products.md`, 현재 보류).

### G-2. 이 명세 동기화 규약
app.py의 **기능·플로우·알고리즘·데이터 경로가 바뀌면** → 해당 version 항목 추가 *그리고* 위 A~G에서 바뀐 부분 갱신(둘 다). "마지막 정독" 날짜도 갱신. 코드만 고치고 이 명세를 안 고치면 = 다음 세션이 거짓 명세를 읽음(드리프트). 작업 방식 = `../CLAUDE.md` §6.

---

## Next Steps (향후 개발 과제)

> San과 바이브코딩하며 *개발하기로 정한* 과제를 여기 쌓는다(결정된 것만, 날짜 동반). 막연한 아이디어 X.

- **(진행 골조 확정 0622) kusukmap 웹앱과 통합** — SyntaxPitching 학생 경험을 kusukmap.com Next 플랫폼으로 이관 + 쿠숙반 상품 페이지. **골조·MVP선·Phase = `~/Kusuk HQ/kusukmap-webapp/docs/kusukban-integration.md`.** 요지: 프론트(UX)+상품페이지만 이관(딥링크 신원·기존 Sheets/Notion 백엔드 그대로), 회원/결제/DB이관은 Step 2. 이 ★app.py 명세가 이관 원본.
- _(이후 합의된 과제를 여기 추가)_

---

## v0.9.2 (2026-07-06) — sync_notion.py 시트 기록 견고화 (구글 503 실사고 방어)

- **변경**: `write_to_sheet` ①구글 API 호출(시트 열기·워크시트 조회·쓰기)에 5xx 지수 백오프 재시도 3회(`with_retry` — 4xx는 즉시 raise) ②**clear() 선행 폐기** — 덮어쓰기 먼저 하고 새 데이터가 짧을 때만 잔여 아래 행을 범위 clear.
- **의도**: 2026-07-06 새벽 스케줄 런이 구글 Sheets 503(일시 장애)으로 실패(실사고 — 이번엔 clear 전에 죽어 피해 0). 구조상 '지우기→쓰기' 사이에 죽으면 SentenceBank가 텅 빈 채 남아 웹앱 피칭 정답·음원 lookup 전면 마비 위험이 있었음. 재시도가 일시 장애를 흡수하고, 쓰기 우선 순서가 어느 시점 실패에도 시트를 온전하게 유지.
- **수강생 효과**: 동기화 실패로 피칭 '정답 듣기'가 비는 사고 가능성 제거. 체감 변화 없음(안정성).

---

## v0.9.1 (2026-06-20) — 미매칭 그림 안내 문구

- **변경**: 3-Row 오디오 위젯에서 `matched_owner`가 없으면(ImageMatching `ContentOwner` 비어 그림이 누구 콘텐츠인지 미매칭) 빨강 녹음 버튼 줄 바로 위에 10px 회색 안내("아직 그림 주인 매칭 전이라 잠겨 있어요") 표시. 매칭되면 자동 비표시. 음원만 없는 케이스(owner는 있음)에는 미표시 — 그 경우는 일부 칸만 잠기므로 별개.
- **의도**: 미매칭이면 전 칸 `ready=False`로 녹음 버튼이 통째 회색 잠금인데 이유 안내가 없어, 수강생(나진 사례)이 "왜 다 막혔지" 막막함. 원인을 화면에서 바로 인지하게.
- **수강생 효과**: 잠긴 이유를 스스로 파악 → 매칭 유도. 무음 실패 경험 감소.

---

## v0.9 (2026-06-12) — 선생님 모드(정답 입력·TTS 버튼·대시보드) 제거 + sync 쿼터 수정

**변경**
- app.py 에서 **선생님 모드(`?teacher=1`) 블록 전체 제거** — 정답 입력(AnswerBank) 화면, 인앱
  "🎙️ TTS 생성 시작" 버튼, 수강생 대시보드 뷰. (총 ~846줄 삭제: 3046 → 2200)
- 함께 죽은 코드 정리: `render_answer_reveal`, AnswerBank 함수 3종 + `ANSWER_BANK_HEADER`,
  "Answers" 시트 함수 3종(`get_or_create_answers_sheet`/`load_answers_for_student`/`save_answer`),
  `LEGACY_BACKFILL_CHAPTER`.
- **유지**: 학생이 정답을 듣는 쪽 전부(SentenceBank 로더, `render_audio_player`,
  `render_section_audio_grid`, `render_image_answer_widget`, `get_audio_path_pane`, `audio/`),
  그림 매칭(ImageMatching·`save_image_matching`·`try_rename_image_on_github`), TTS 파이프라인
  (`generate_tts.py`/`.yml`).
- `sync_imagematching.py` 버그픽스: 행마다 `ws.update`/`append_row` 개별 호출 → 매칭 파일 319개에서
  구글 쓰기 쿼터 초과로 워크플로 exit 1. **메모리 병합 후 1회 통째 쓰기**(`ws.clear()` + 단일
  `ws.update("A1", …)`)로 변경, `sync_notion.py` 와 동일 패턴. upsert(기존 행 보존)는 유지.

**의도**
- TTS 동기화를 노션 버튼 기반으로 옮기면서 인앱 정답 입력·TTS 트리거가 불필요해짐.
- 선생님 대시보드는 어차피 시트 데이터를 보여주는 것이라, 별도 빙고 예문 대시보드(아티팩트)로
  통합 가능 → 앱을 학생 전용으로 슬림화.
- 매칭 파일이 많아질수록(특히 backfill 후) sync 워크플로가 쿼터로 죽던 문제 해결.

**수강생/운영 효과**
- 학생 앱은 기능 변화 없음(보던 화면 그대로). 코드만 가벼워져 유지보수·배포 안정성 ↑.
- 파일명 → 시트 동기화가 대량 매칭에서도 한 번에 성공.

---

## v0.8 (2026-06-12) — 그림 매칭 ↔ 파일명 양방향 동기화 (선생님 사전 매칭)

**변경**
- 파일명 파서(`extract_section_slot_from_filename`)를 주인 이름 suffix 허용으로 변경:
  `1-3배해주.png` → 섹션 1, 슬롯 3 (슬롯의 앞 숫자만 파싱). 맨이름 `1-3.png` 동작은 그대로(하위호환).
- 신규 헬퍼 `match_image_key()` — ImageMatching 시트 키를 항상 맨이름 `1-3.png` 로 정규화.
  load/save/조회/오디오 그리드/활성칸 계산 등 매칭 키 사용 지점 전부 이 키로 통일(확장자도 `.png` 통일).
- `save_image_matching`: 저장 시 Image 정규화 + 기존 행 탐색도 정규화 비교(레거시 주인-붙은 행을 제자리 갱신).
- 신규 `try_rename_image_on_github()`: 웹앱에서 매칭하면 GitHub의 그림 파일을
  `1-1.png → 1-1배해주.png` 로 rename(커밋). 기존 `github_pat`/`github_repo` secret + GitHub Contents API 재사용.
  실패해도 매칭 저장엔 영향 없음(비차단), secret 없으면 조용히 skip.
- 신규 역방향 파이프라인:
  - `sync_imagematching.py` — `Syntax Pitching/…` 등 폴더의 *주인 붙은* 파일명을 파싱해 ImageMatching 탭에
    **upsert**(삭제 없음 → 앱이 직접 쓴 행 보존). 미매칭(맨이름) 파일은 무시.
  - `.github/workflows/sync_imagematching.yml` — 이미지 폴더 push 시(또는 수동) 위 스크립트 실행.
    `GCP_SERVICE_KEY_JSON` secret 사용(기존 sync 워크플로와 동일), `concurrency: homework-pipeline` 공유.

**의도**
- 학생이 아직 웹앱에서 그림 매칭을 안 하면 ImageMatching 시트가 비어, 선생님이 '오늘 수업 예문 망라'를
  미리 준비하기 어려웠다 → 선생님이 **로컬에서 파일명만 바꿔 push** 하면 매칭이 시트에 반영되는 사전 입력 경로 추가.
- 파일명을 '눈으로 보는 진실'로 삼아, origin pull 후 로컬 폴더에서 **이름 없는 파일 = 미매칭**을 한눈에 식별.
- 시트 쓰기는 upsert 로만 해서 앱(학생) 매칭과 파일명(선생님) 매칭이 충돌 없이 공존.

**수강생/운영 효과**
- 선생님이 수업 전, 학생 숙제 완료 여부와 무관하게 사용할 예문을 미리 망라·검토 가능.
- 매칭 진행 상황을 폴더에서 즉시 가시화(이름표 있는 파일 = 완료).
- 주의: 실제 동작은 Streamlit 배포 환경에서 1회 검증 필요(특히 rename 의 GitHub 권한·기본 브랜치 `main`,
  `GCP_SERVICE_KEY_JSON` secret 존재). 매칭 그림은 .png 가정.

---

## v0.7 (2026-06-08) — 빨간 버튼 듣기 분리 + 출제량 축소 + 인증 이미지 양식 변경

**변경**
- 출제량: 매일 10장 → **3장** (현행 2 + 지난 1)
- 빨간 버튼: hold-to-record + 떼면 자동 재생 (Safari unlock priming 적용)
- 신규 row 2 추가: 🔈 (개별 내 녹음 듣기) 버튼 + 🎙️ 합본 듣기
- 파란 버튼(정답): 클릭만 재생 (자동 재생 X)
- 빈 슬롯은 회색 disabled 대신 아예 미표시 (시각 깔끔)
- 인증 이미지: 두 컬럼 → 단일 컬럼 (Batting Average 섹션 제거, 그림 크기 2배)
- 인증 이미지: 그림 가로 정렬 = 좌측 정렬

**의도**
- 일일 5~10분 데일리 강세 쉐도잉 루틴화. 양 < 깊이.
- 손가락이 작은 버튼 가리는 문제 해결 위해 외부 오버레이 배너로 녹음 상태 시각화.
- 정답 자동 재생 → 학생이 자기 녹음 듣기 전에 정답 새어들어가는 누설 차단.
- 내 녹음 다시 듣기 = 재녹음으로만 가능했는데, 명시적 🔈 버튼 분리해 직관성 향상.
- 인증 이미지: "오늘도 한 번 도장" 의례 강조. 양 표시(타율 %)는 부담만 주고 의미 낮아 제거.

**수강생 효과**
- 매일 3분 안에 끝나는 부담 없는 루틴 → 데일리 습관 형성 가능성 ↑
- 강세 마스터링 컨셉(녹음 → 비교) 명확히 분리
- "정답 안 들어도 자기 녹음만 5번 반복" 같은 자율 학습 패턴 가능

---

## v0.6 (2026-06-07~08) — 음원 매칭 로직 재설계

**변경**
- 파일 명명 규칙 명확화: `{section}-{n번째 학생 답안}.png` (Y는 학생 버전 인덱스)
- image_to_pane 잘못된 가정 (Y=slot in section) 수정
- 화면 파일의 owner 한 명을 구간 전체 panes 에 적용

**의도**
- 음원이 그림과 안 맞아 "이상한 음원이 나온다" 컴플레인 해결
- 새 파일 명명 규칙 = "구간 단위 이미지, owner 별로 다른 버전" 을 정확히 반영

**수강생 효과**
- 강세 잡기 버튼 누를 때 그림과 정확히 매치되는 정답 음원 재생
- 학생들의 신뢰 회복

---

## v0.5 (2026-06-06~07) — 노션 → SentenceBank 자동 동기화 인프라

**변경**
- `sync_notion.py` 신규: 노션 예문 DB → 구글 시트 SentenceBank 자동 동기화
- 빙고판(챕터) DB 에 구간 매핑 8개 속성 추가 (구간1~4 시작칸·끝칸)
- `generate_tts.py` 전면 개편: SentenceBank 읽기 + 사이드카 .txt 변경 감지
- 옛 mp3 127개 `_old` 접미사로 archive
- 통합 워크플로우 `sync_and_tts.yml` 신규 (한 트리거로 sync + TTS)
- 노션 sync 버튼 → make.com → GitHub Actions webhook 연결
- 동기화에서 회색·취소선·배경라벨·점수메모 자동 필터링

**의도**
- 노션-시트 수동 복붙 운영 부담 (주 30분) 거의 0으로
- 콘텐츠 제작 ↔ 음원 생성 파이프라인 자동화 (선생님이 노션에서 첨삭만 하면 음원까지 자동 생성)
- 데이터 단일 소스 (노션) 확보 → 일관성

**수강생 효과**
- 직접 체감 X. 백엔드 변경.
- 그러나 새 챕터 시작 시 학습 자료 가용성 빨라짐 (선생님이 첨삭 → 다음 날 음원 준비됨)

---

## v0.4 (2026-06-05~06) — 강세 잡기 위젯 + 녹음 lock 메커니즘 + 매칭 자동화

**변경**
- 강세 잡기 버튼: hold to pause / 떼면 재개
- ↻ 처음부터 재생 버튼 추가
- 녹음 위젯 + Lock 메커니즘 (MediaRecorder API)
- 솔로 챕터 (한 명만 가진 챕터) 자동 매칭

**의도**
- 학생이 정답 먼저 듣고 따라하는 게 아니라, 자기가 시도해본 후 정답 비교
- 녹음 데이터는 100% 브라우저 메모리 (서버 송신 0) — 신뢰 약속

**수강생 효과**
- 본인이 직접 발화해본 다음 정답을 비교하는 루프 형성
- "내가 어디서 다른가" 객관화 가능

---

## v0.3 (2026-06-04~05) — 앱 SentenceBank 읽기 전환 + 보류/보관 폴더 포함

**변경**
- app.py 가 AnswerBank (구간 단위) → SentenceBank (그림칸 단위) 읽기로 전환
- 매칭 드롭다운에 보류·보관 폴더 학생들도 포함

**의도**
- v0.5 의 자동 동기화 인프라 깔기 전 데이터 모델 정리
- 수업 잠시 쉬는 중인 학생의 그림도 매칭 가능하도록 (수업 흐름 끊김 방지)

**수강생 효과**
- 매칭 드롭다운에서 더 많은 학생 후보 보임 → 정답 매칭률 ↑

---

## 변경 이력 작성 가이드 (Homework-Generation 채팅에게)

1. **새 버전 = 새 섹션** (맨 위에). 버전 번호는 의미 단위로 (날짜 + v 패치).
2. **변경 / 의도 / 수강생 효과** 3개 섹션 필수.
3. 기술 디테일 (코드 패치 줄 수 등) 은 git log 에 있으니 생략. 여기는 **왜·무엇·누구에게 미치나** 중심.
4. 본부 (Kusuk Staff) 가 SYNC.md 에 반영할 수 있도록 사업 영향이 있는 변경은 명시.
