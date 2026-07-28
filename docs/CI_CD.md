# CI/CD 현황과 방향 (2026-07-22)

## 지금 있는 것 — `windows-smoke.yml` (진짜 CI)
- main push 시(`src/`,`web/`,`scripts/`,`requirements.txt` 변경 한정) 자동 트리거
- `windows-latest` 클라우드 VM에서 실제 배포용 zip을 빌드 → 압축 해제 → 번들 Python으로 `smoke_test.py` 실행
- 목적: "테스터 PC에서 시작하자마자 죽는" 클래스의 버그(임포트 에러, tzdata 누락, 스케줄러/웹 부팅 실패)를 배포 전에 자동으로 잡는 것
- **주의(issue #19)**: `scripts/smoke_test.py`는 반드시 `.venv/bin/python` 또는 번들 자체 python으로 실행해야 함. 시스템 PATH의 맨 `python3`는 `requirements.txt`가 설치돼 있지 않아 [1/6](파이썬 버전)부터 모든 임포트 체크까지 실패한다.

## 없는 것 — CD, 게이팅, 하드웨어 테스트 자동화
- **배포 자동화 없음**: 태깅, Mac/Windows zip 빌드, GitHub Release 업로드/노트 작성이 전부 수동 (v1.1.1/v1.1.2 전부 사람이 터미널에서 `gh release create/upload/edit` 실행)
- **게이팅 없음**: CI 실패해도 main push/머지를 막지 않음. 참고용 신호일 뿐
- **Mac 빌드는 CI 미검증**: `windows-smoke.yml`의 Mac 버전이 없음 — Mac zip은 항상 로컬 수동 빌드
- **실기기 Android/iOS regression은 구조적으로 CI 불가**: GitHub Actions 클라우드 러너에 물리 USB 폰을 꽂을 수 없어서, 44개 TC 회귀 테스트는 항상 로컬 Mac + 실제 연결된 기기로 수동 실행

**결론**: "CI 파이프라인 하나 있다"까지는 맞지만, 엔드투엔드 CI/CD라 부르기엔 부족함. 갭 메우는 작업은 [이슈 #15](https://github.com/DunkinYeo/AK-automation/issues/15)에 정리 (태그 push 자동 릴리즈가 핵심, Mac 스모크 CI, 브랜치 게이팅 순).

## Jenkins 연계 검토 결과
가능하며, GitHub Actions 대비 유일하고 확실한 차별점은 **실기기 regression 자동화** — Jenkins는 self-hosted agent를 쓸 수 있어서, 이 Mac 자체를 agent로 등록하면 USB로 연결된 폰으로 44개 TC를 사람 개입 없이(push나 스케줄 트리거로) 돌릴 수 있음. GitHub Actions로는 원천적으로 불가능한 부분.

```
Jenkins 마스터 (이 Mac 또는 소형 클라우드 VM)
 ├─ Agent "mac-hardware" = 이 Mac (Pixel 7/삼성 USB 상시 연결, Appium 상시 기동)
 │    · Job: Android regression 44 TC 자동 실행 → 리포트
 │    · 트리거: GitHub webhook(push) 또는 스케줄
 └─ Agent "windows-build" (선택) = Windows PC/VM
      · windows-smoke.yml과 동일한 빌드+스모크 테스트 이식
```

트레이드오프: Jenkins 서버 직접 설치/운영/패치 필요, Windows agent는 무료 클라우드 러너가 없어 직접 확보해야 함, Jenkinsfile(Groovy) 러닝커브. 전제조건(Mac 24시간 가동 + 폰 상시 연결)은 지금의 장기 soak 운영 방식과 크게 다르지 않음.

**착수는 보류 상태** — #15(태그 자동 릴리즈)와는 독립적인 별도 트랙이고, 필요성이 명확해지면 이 문서의 아키텍처부터 시작하면 됨.
