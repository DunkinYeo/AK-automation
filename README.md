# S-Patch AccurKardia Automation

S-Patch AccurKardia 앱 장기 실행 테스트 자동화 도구.
24/48/72/144h ECG 측정 중 주기적으로 증상 주입(Log Symptoms)을 실행하고,
앱 상태 이상 감지 시 자동 복구 + Slack 알림을 발송합니다.

---

## 기능

- **장기 실행 자동화**: 설정한 시간 동안 일정 간격으로 증상 주입
- **자동 복구**: 팝업 감지, 앱 재시작, Appium 세션 복구
- **Slack 알림**: 시작 / 주입 결과 / 완료 / 실패 알림
- **Quiet Hours**: 새벽 시간대 주입 자동 스킵
- **Regression 테스트**: 7개 suite, UI TC 자동 검증
- **웹 UI**: 브라우저에서 설정·실행·로그 확인 (포트 5002)
- **배포 ZIP**: Mac / Windows 배포 패키지 자동 생성

---

## 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 |
| Node.js | 18 이상 |
| Appium | 2.x |
| ADB (android-platform-tools) | 최신 |
| Android 기기 | USB 디버깅 활성화 |

AccurKardia 앱이 **검사 진행 중** 상태 (측정 메인 화면 — "My Study Progress" 표시) 여야 합니다.

---

## 빠른 시작 (macOS)

```bash
# 1. 최초 1회 — 환경 설치
./install.command        # 또는: bash scripts/setup_env.sh

# 2. 실행
./run.command            # Appium + 웹서버 + 브라우저 자동 오픈

# 3. 종료
./STOP.command
```

## 빠른 시작 (Windows)

```
install.bat   ← 최초 1회
run.bat       ← 실행
STOP.bat      ← 종료
```

---

## CLI 실행

```bash
# 가상환경 활성화
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 장기 실행 테스트
python src/main.py --config config/accurkardia.yaml

# 설정 확인만 (기기 연결 없음)
python src/main.py --config config/accurkardia.yaml --dry-run

# 한 번만 주입 후 종료
python src/main.py --config config/accurkardia.yaml --once
```

---

## 웹 UI

```bash
make web
# → http://127.0.0.1:5002
```

- 기기 선택 / S-Patch 시리얼 입력 / 실행 시간·간격 설정
- Regression 테스트 실행 및 결과 확인
- 실패 아티팩트 브라우저 (`/failures`)
- 헤더의 **⬇ Mac** / **⬇ Windows** 버튼으로 배포 ZIP 즉시 다운로드

---

## Makefile

```bash
make install          # 가상환경 + 패키지 설치
make run              # 장기 실행 테스트
make web              # 웹 UI (포트 5002)
make dry-run          # 설정 확인

# Regression
make regression       # 전체 suite 실행
make reg-main         # 측정 메인 화면 TC
make reg-diary        # Log Symptoms/Diary TC
make reg-menu-study   # 측정 중 메뉴 TC
make reg-serial       # 시리얼 입력 TC
make reg-menu         # 설정 메뉴 TC
make reg-signal       # Check Incoming Signal TC
make reg-study        # Review Study Setting TC

# 배포 ZIP 빌드
make dist             # Mac + Windows 모두 (→ ~/Desktop)
make dist-mac
make dist-windows
make dist OUT=/tmp    # 출력 경로 지정
```

---

## 설정 파일

`config/accurkardia.yaml` 주요 항목:

```yaml
run:
  duration_hours: 72            # 실행 시간 (h)
  symptom_interval_hours: 1     # 증상 주입 간격 (h)
  quiet_hours: {start: 2, end: 6}  # 새벽 스킵 구간

android:
  udid: "55ETQWBXYE1RA1"        # adb devices 로 확인
  test_serial_number: "610260"  # S-Patch 시리얼

slack:
  enabled: true
  webhook_url: ""               # .env의 SLACK_WEBHOOK_URL 또는 직접 입력
  mention: ""                   # Slack User ID (예: U0123ABC)
```

Slack webhook은 `.env` 파일로 관리할 수 있습니다:

```bash
echo "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..." > .env
```

---

## Regression 테스트 Suite

| Suite | 선행 조건 | TC 수 | 내용 |
|-------|-----------|-------|------|
| `serial` | 기기 연결 | 6 | 시리얼 번호 입력 화면 |
| `menu` | 기기 연결 | — | Step 1 설정 메뉴 |
| `signal` | BLE 연결, 검사 미등록 | — | Check Incoming Signal |
| `study` | BLE 연결, 검사 미등록 | — | Review Study Setting |
| `main` | **검사 진행 중** | 6 | 측정 메인 화면 UI |
| `diary` | **검사 진행 중** | 6 | Log Symptoms / Diary |
| `menu-study` | **검사 진행 중** | 6 | 측정 중 사이드 메뉴 |

웹 UI에서 실행 시 기본 suite: `main, diary, menu-study` (검사 중 상태 기준)

---

## 프로젝트 구조

```
AK-automation/
├── install.command / run.command / STOP.command   # macOS 런처
├── install.bat / run.bat / STOP.bat               # Windows 런처
├── Makefile
├── requirements.txt
├── config/
│   ├── accurkardia.yaml       # 메인 실행 설정
│   └── run.example.yaml       # 새 앱 추가용 템플릿
├── src/
│   ├── main.py                # 장기 실행 진입점
│   ├── run_regression.py      # Regression 진입점
│   ├── scheduler.py           # 주입 스케줄러
│   ├── driver.py              # AndroidDriver (텍스트 기반 셀렉터)
│   ├── slack.py               # Slack 알림
│   ├── workflows/
│   │   ├── measurement_start.py   # 측정 메인 화면 복귀
│   │   └── symptom_inject.py      # 증상 주입 플로우
│   └── regression/
│       ├── runner.py          # TC 실행기
│       ├── main_screen.py     # Main Screen TC
│       ├── add_diary.py       # Diary TC
│       ├── menu_study.py      # Menu-Study TC
│       ├── serial_input.py    # Serial TC
│       └── helpers.py         # reset_to_step1, go_to_main
├── web/
│   ├── app.py                 # Flask 웹 서버 (포트 5002)
│   └── templates/
│       ├── index.html         # 메인 UI
│       ├── failures.html      # 실패 아티팩트 목록
│       └── failure_detail.html
├── scripts/
│   ├── build_dist.py          # 배포 ZIP 빌드
│   └── setup_env.sh           # macOS 환경 설치
├── artifacts/                 # 실패 스크린샷 / 로그
└── output/                    # 실행 결과 (JSONL 이벤트 로그)
```

---

## 배포 ZIP 생성

```bash
# 직접 빌드
python scripts/build_dist.py                  # Mac + Windows → ~/Desktop
python scripts/build_dist.py --out /tmp       # 경로 지정
python scripts/build_dist.py --platform mac   # Mac만

# Makefile
make dist
```

생성되는 파일:
- `AccurKardia-Mac-YYYYMMDD.zip`
- `AccurKardia-Windows-YYYYMMDD.zip`

ZIP 내부 구조: 루트에 런처 스크립트, `automation/` 아래에 소스 코드

---

## 앱 정보

| 항목 | 값 |
|------|-----|
| 패키지 | `com.wellysis.accurkardia.accurkardia.mobile` |
| Activity | `com.wellysis.accurkardia.accurkardia.mobile.MainActivity` |
| 언어 | 영어 (기기 언어 설정 따름) |
| UI 방식 | React Native — resource-id 없음, 텍스트 기반 셀렉터 |
| Appium Driver | UiAutomator2 |
