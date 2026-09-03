# Standalone ZIP 구조 (2026-09-03)

AK-automation은 두 가지 배포 ZIP 방식을 병행 보유하고 있다: 기존
raw-source(`release.yml`이 실제로 쓰는, v1.1.4까지 쭉 배포해온 방식)와
새 PyInstaller frozen 방식(issue #46, MA 자매 프로젝트의 이미 검증된
패턴을 이식 — MA repo의 `docs/STANDALONE_ZIP_STRUCTURE.md` 참고).
**아직 `release.yml`은 raw-source 그대로다** — frozen 쪽은 코드/CI
검증까지 끝났고 실기기 e2e만 남은 상태(issue #46).

## 공통 (두 방식 다 동일)

```
AccurKardia-Mac-Standalone-...zip
└── AccurKardia-Mac-Standalone-.../
    ├── README_MAC_EN.txt / README_MAC_KR.txt
    ├── run.command
    ├── STOP.command
    ├── smoke.command
    └── automation/
        ├── node/          ← Node.js 런타임 (Appium용, 항상 동일)
        ├── runtime/       ← ADB platform-tools + WDA.ipa (항상 동일)
        ├── config/        ← accurkardia.yaml 등 (항상 loose 파일)
        └── web/templates/ ← index.html 등 (항상 loose 파일 — 숨길 이유 없음)
```

바뀌는 건 오직 Python 애플리케이션 본체(`src/`, `web/*.py`,
`scripts/*.py`)가 어떻게 담기느냐뿐.

## Before/지금 — raw-source (v1.1.4 실제 배포 방식)

```
automation/
├── src/*.py           ← 압축만 풀면 텍스트로 그대로 읽힘
│   ├── main.py            (Android 진입점)
│   ├── main_ios.py        (iOS 진입점 — MA엔 없음, AK만 있음)
│   ├── driver_ios.py
│   └── run_regression.py
├── web/app.py         ← 마찬가지
├── scripts/*.py
├── requirements.txt
└── (.venv/ 는 첫 실행 시 사용자 PC에서 생성, Windows는 embeddable Python 번들)
```

빌드 스크립트: `scripts/build_dist_bundle_mac.py` /
`scripts/build_dist_bundle.py` — Windows는 Python embeddable 배포판
통째 번들, Mac은 시스템 `python3`로 첫 실행 시 `.venv` 생성.

## After/새로 검증됨 — PyInstaller frozen (issue #46, 코드+CI 검증 완료)

```
automation/
├── AKApp(.exe)        ← 단일 컴파일 실행파일, 21MB
├── _internal/         ← PyInstaller 런타임+의존성, 125MB (바이트코드, 텍스트 아님)
├── web/templates/     ← 그대로 유지
└── config/            ← 그대로 유지
```

`find automation -name "*.py"` 결과 **0건** (third-party 라이브러리 자체
번들 파일 제외 — 아래 "IPython 딸려오는 이유" 참고).

첫 실행 흐름: `automation/AKApp --web` 바로 실행.

빌드 스크립트: `scripts/build_dist_bundle_mac_frozen.py` /
`scripts/build_dist_bundle_frozen.py` — `scripts/pyinstaller_build.py`가
실제 freeze 수행. `scripts/pyinstaller_entry.py`가 단일 진입점, MA(5개
모드)보다 2개 많은 **7개 디스패치 모드**:
`--web`/`--main`/`--main-ios`/`--run-regression`/`--capture-logs`/
`--pymobiledevice3`/`--smoke-test`.

### `--pymobiledevice3` 모드 — MA엔 없는, AK만의 대응 필요 케이스

`web/app.py`와 `src/driver_ios.py`가 iOS 기기 제어를 위해
`[sys.executable, "-m", "pymobiledevice3", ...]` 형태로 3곳에서
서브프로세스를 띄운다(usbmux list/forward, WDA용 dvt xcuitest). frozen
상태에선 `sys.executable`이 더 이상 python 인터프리터가 아니라 `AKApp`
자기 자신이라 `-m` 옵션이 통하지 않는다.

해결: `pymobiledevice3.__main__`도 우리 자체 진입점처럼 `sys.argv`를
직접 읽는 `main()`을 갖고 있어서(Typer 기반), 우리 디스패처에
`"--pymobiledevice3": ("pymobiledevice3.__main__", "main")`를 그대로
추가하는 것만으로 동작함 — 별도 특수처리 코드 불필요. 호출부는
`src/app_root.py`의 `pymobiledevice3_argv()`로 통일:
`python -m pymobiledevice3 X` → frozen이면 `AKApp --pymobiledevice3 X`.

단, `python -c "..."`로 usbmux JSON을 파싱하던 한 줄짜리 코드는 대체
불가 — frozen 실행파일엔 범용 `-c`/eval 모드를 일부러 안 만들었음(임의
코드실행 표면을 이 편의 하나 때문에 여는 건 부적절). 대신 `grep`/`cut`
기반 파싱으로 대체(`run.command`/`run.bat`의 IOS_UDID 추출 부분).

### PyInstaller freeze 시 AK 전용으로 새로 겪은 이슈 2개

MA에도 있던 `--paths`/`--hidden-import` 필요성 외에, iOS 지원 때문에
추가로 필요했던 것:
- **`readchar` 메타데이터 누락**: `pymobiledevice3` → `inquirer3` →
  `readchar` 의존성 체인에서, `readchar`가 import 시점에
  `importlib.metadata.version("readchar")`로 자기 버전을 조회한다.
  PyInstaller는 기본적으로 설치된 패키지의 메타데이터(dist-info)를 안
  담아서 `PackageNotFoundError` 발생 → `--copy-metadata readchar`로 해결.
- **`pymobiledevice3.cli.*` 동적 import**: `pymobiledevice3.__main__`이
  서브커맨드(`usbmux`, `developer`, `mounter` 등 ~27개)를
  `importlib.import_module(f"pymobiledevice3.cli.{name}")` 형태로 우리
  자체 디스패처와 똑같은 패턴으로 동적 로드한다 → 빌드 시점엔 안 잡히고
  실제 서브커맨드 실행 시점에 `ModuleNotFoundError` → `--collect-submodules
  pymobiledevice3.cli`로 해결.

두 옵션 다 `scripts/pyinstaller_build.py`에 이미 반영돼 있어서, 이
헬퍼를 쓰는 한 Mac/Windows 어느 쪽을 빌드하든 자동으로 적용됨.

### IPython이 번들에 딸려오는 이유 (문제 아님)

`pymobiledevice3`가 `ipython`을 실제 의존성으로 선언하고 있어서,
`_internal/IPython/extensions/`에 `.py` 파일 몇 개가 그대로 딸려온다.
이건 AK/MA 자체 소스가 아니라 서드파티 오픈소스 코드라 issue #46의
목적(우리 비즈니스 로직 숨기기)과는 무관 — `frozen-smoke.yml`의
"소스 노출 없음" 체크도 이를 감안해서 "automation/ 전체에 .py가
하나도 없어야 한다"가 아니라 **"automation/src가 존재하지 않고,
automation/web에 loose .py가 없어야 한다"**로 범위를 좁혀놨다.

## 용량 비교 (Mac 기준, 2026-09-03 실측)

| 구성요소 | raw-source | frozen |
|---|---|---|
| node/ (Node.js) | 188MB | 188MB (동일) |
| runtime/ (ADB+WDA.ipa) | 44MB | 44MB (동일) |
| Python 앱 부분 | src+web+scripts ≈ 950KB (텍스트) | AKApp 21MB + _internal 125MB = 146MB |
| **압축된 zip 전체** | **71MB** | **131MB** |

frozen이 60MB나 더 큰 이유: MA(+22MB)보다 훨씬 큰 차이인데, iOS
지원용 `pymobiledevice3`와 그 의존성 트리(`ipython`, `jedi`,
`prompt_toolkit`, `cryptography` 등)를 통째로 실행파일에 구워넣기
때문 — MA는 Android-only라 이 부담이 없다.

## 검증 이력

- CI: `.github/workflows/frozen-smoke.yml` — Mac/Windows 양쪽에서 실제
  빌드 → 소스 미노출 확인 → `--smoke-test` → (Mac만) `--pymobiledevice3`
  디스패치 확인 → 실제 Appium 설치+uiautomator2 드라이버+세션생성까지
  검증. **Windows는 이 저장소에선 로컬 빌드가 아예 불가능해서(PyInstaller가
  플랫폼별 실행파일 생성) CI가 유일한 검증 수단** — 첫 실행에서 바로 통과.
- 로컬(Mac): 실제 zip 빌드 → 추출 → `smoke.command` 7/7 → `--pymobiledevice3
  usbmux list`로 실제 연결된 iPhone(Wellysis iPhone 13 mini) 인식 확인.
- 실기기 Android/iOS 장기런 e2e는 **아직 미완료** — 디바이스 확보되는
  대로 진행 예정. MA(#12)는 이미 18시간+ 실기기 검증까지 마치고
  `release.yml` 전환 완료.

## 기능 동일성

대시보드, 회귀 스위트, 스케줄러, iOS/Android 자동화 등 사용자가 보는
동작은 완전히 동일하다. 바뀐 건 오직 "Python 소스가 압축 풀면
보이느냐"뿐.

## 남은 것

- 실기기 e2e 검증 (Android 장기런 + iOS 세션)
- 검증 끝나면 `release.yml`을 frozen 스크립트로 전환 (MA가 이미 이
  순서로 v1.0.0을 전환한 전례 있음)
