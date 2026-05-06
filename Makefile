PYTHON := $(shell [ -f .venv/bin/python ] && echo .venv/bin/python || echo python3)
CONFIG ?= config/accurkardia.yaml

.PHONY: install run web dry-run regression reg-serial reg-menu reg-signal reg-study reg-main reg-diary help

help:
	@echo ""
	@echo "  S-Patch Accurkardia Automation"
	@echo ""
	@echo "  make install        — 최초 1회: 가상환경 + 패키지 설치"
	@echo "  make run            — 풀 자동화 실행 (longrun + 증상 주입)"
	@echo "  make dry-run        — 설정 확인만 (실제 실행 없음)"
	@echo ""
	@echo "  Regression suites (기기 연결 불필요):"
	@echo "  make reg-serial     — TC-SN: 시리얼 입력 화면"
	@echo "  make reg-menu       — TC-MENU: 설정 메뉴 (기어 아이콘)"
	@echo ""
	@echo "  Regression suites (BLE 연결 필요, 검사 미등록):"
	@echo "  make reg-signal     — TC-SIG: Check Incoming Signal"
	@echo "  make reg-study      — TC-STUDY: Review Study Setting"
	@echo ""
	@echo "  Regression suites (검사 진행 중):"
	@echo "  make reg-main       — TC-MAIN: 측정 메인 화면"
	@echo "  make reg-diary      — TC-DIARY: Add Diary"
	@echo "  make reg-menu-study — TC-MENU-STUDY: 측정 중 메뉴"
	@echo ""
	@echo "  make regression     — 전체 regression 실행"
	@echo ""

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip -q
	$(PYTHON) -m pip install -r requirements.txt -q
	@echo ""
	@echo "  설치 완료. 'make run' 또는 'make web' 으로 시작하세요."
	@echo ""

run:
	PYTHONPATH=. $(PYTHON) src/run.py --config $(CONFIG)

web:
	PYTHONPATH=. $(PYTHON) web/app.py --port 5002

dry-run:
	PYTHONPATH=. $(PYTHON) src/run.py --config $(CONFIG) --dry-run

regression:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite all

reg-serial:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite serial

reg-menu:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite menu

reg-signal:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite signal

reg-study:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite study

reg-main:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite main

reg-diary:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite diary

reg-menu-study:
	PYTHONPATH=. $(PYTHON) src/run_regression.py --config $(CONFIG) --suite menu-study
