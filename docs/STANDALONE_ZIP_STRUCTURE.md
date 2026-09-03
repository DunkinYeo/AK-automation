# Standalone ZIP 구조 (2026-09-03)

AK-automation은 현재 raw-source 방식으로 배포 ZIP을 만든다. MA 자매
프로젝트가 v1.0.0부터 PyInstaller frozen 방식으로 전환했고(issue #46
방향을 MA가 먼저 적용, MA repo의 `docs/STANDALONE_ZIP_STRUCTURE.md`
참고), AK는 아직 이 문서가 설명하는 구조 그대로다.

## ZIP 최상위 구조

```
AccurKardia-Mac-Standalone-...zip
└── AccurKardia-Mac-Standalone-.../
    ├── README_MAC_EN.txt / README_MAC_KR.txt
    ├── run.command
    ├── STOP.command
    ├── smoke.command
    └── automation/
        ├── node/          ← Node.js 런타임 (Appium용)
        ├── runtime/       ← ADB platform-tools, iOS면 WDA.ipa도 포함
        ├── config/        ← accurkardia.yaml, accurkardia_ios.yaml 등
        ├── src/*.py       ← 압축만 풀면 텍스트로 그대로 읽힘
        │   ├── main.py         (Android 진입점)
        │   ├── main_ios.py     (iOS 진입점 — MA엔 없음, AK만 있음)
        │   └── run_regression.py
        ├── web/app.py     ← 마찬가지, 텍스트로 읽힘
        ├── scripts/*.py
        └── requirements.txt
```

Windows는 Python embeddable 배포판을 통째로 번들(`automation/python/`),
Mac은 시스템 `python3`로 첫 실행 시 `.venv`를 생성한다
(`scripts/build_dist_bundle.py` / `scripts/build_dist_bundle_mac.py`).

## 첫 실행 흐름 (raw-source, 지금 방식)

1. `python3 -m venv automation/.venv` (Mac) / 번들 Python 그대로 사용 (Windows)
2. `pip install -r requirements.txt` (~1분, 인터넷 필요, Mac만 해당)
3. `python automation/web/app.py` (또는 Windows는 번들 python.exe)

## 알려진 한계 — 소스 노출

`src/`, `web/app.py`가 압축만 풀면 그대로 읽혀서, 외부(협력사 등)에
공유하면 전체 자동화 로직이 노출된다. 지금 당장 급한 외부 공유 계획이
없어 issue #46으로 기록만 해두고 미착수 상태.

## MA가 먼저 검증한 전환 경로 (필요해지면 참고)

MA는 다음 구조로 전환해서 실기기 18시간+ 검증까지 마쳤다:

```
automation/
├── SPatchMA(.exe)     ← 단일 컴파일 실행파일, src/+web/*.py+scripts/*.py 전부 대체
├── _internal/         ← PyInstaller 런타임+의존성 (바이트코드, 텍스트 아님)
├── web/templates/     ← 그대로 loose 파일 유지 (숨길 이유 없음, sys._MEIPASS 복잡도 회피)
└── config/            ← 그대로 loose 파일 유지
```

핵심 부품 (MA repo 기준, AK로 이식 시 참고):
- `src/app_root.py`의 `get_app_root()` — `sys.executable`의 부모 디렉토리를
  ROOT로 계산 (frozen/unfrozen 양쪽 다 대응). **실행파일은 반드시
  `automation/` 바로 밑에 둬야 함** — 서브폴더(`automation/app/` 등)에
  넣으면 이 경로 계산이 한 단계 어긋나는 버그가 남 (MA가 실기기 검증 중
  실제로 겪고 고침).
- `scripts/pyinstaller_entry.py` — 단일 진입점 디스패처. MA는
  `--web`/`--main`/`--run-regression`/`--capture-logs`/`--smoke-test`
  5개 모드. **AK는 `main_ios.py`용 `--main-ios` 모드가 하나 더
  필요함** (AK-automation issue #46 spike 브랜치
  `spike-pyinstaller-multi-entrypoint`가 이 부분까지는 이미 시도해뒀음 —
  단, 2026-07-31 커밋 기준으로 현재 main보다 한 달 이상 뒤처져 있어
  rebase 필요).
- `scripts/pyinstaller_build.py` — freeze 실행 시 `--paths <project root>`
  없이는 PyInstaller가 `src.*`/`web.*`를 못 찾고, 동적 dispatch되는
  모듈은 `--hidden-import`로 각각 명시해야 함 (정적 분석이 `importlib.import_module()`
  문자열 인자를 못 따라감).
- `web/app.py`의 `Flask(__name__)` → `Flask(__name__, template_folder=...)`로
  명시 필요 (frozen 상태에서 기본 root_path 추론이 깨짐).
- CI: `frozen-smoke.yml` 신규 워크플로우로 기존 `mac-smoke.yml`/
  `windows-smoke.yml`/`release.yml`은 안 건드리고 병행 검증 → 실기기
  검증 끝난 뒤에만 `release.yml`을 frozen 스크립트로 전환.

## 기능 동일성

전환하더라도 대시보드/회귀 스위트/스케줄러 등 사용자가 보는 동작은
바뀌지 않는다 — 바뀌는 건 오직 "Python 소스가 압축 풀면 보이느냐"뿐.
