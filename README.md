# Billywear KKLLA Sales Server

Billywear KKLLA 영업관리 서버 운영판입니다.

## 실행

로컬에서만 테스트:

```bash
./start-local.sh
```

도메인 없이 공개 주소로 사용:

```bash
./start-public.sh
```

현재 실행 중인 공개 주소는 아래 파일에도 기록됩니다.

```text
runtime/current-public-url.txt
```

## 초기 계정

```text
관리자 이메일: admin@billywear-kklla.kr
관리자 비밀번호: runtime/admin-login.txt 파일 확인
```

## 포함된 기능

- 서버 세션 로그인
- PBKDF2 기반 비밀번호 해시 저장
- 영업사원 회원가입
- 관리자 승인/중지
- 거래처 등록 및 중복 의심 감지
- 영업 활동 기록
- 계약 등록 및 관리자 정산 승인
- 월별 정산표
- 감사 로그
- SQLite 데이터베이스 저장

## 데이터 위치

```text
data/kklla.sqlite3
```

실제 운영 배포 전에는 관리자 초기 비밀번호 변경, HTTPS 적용, DB 백업, 계좌정보 암호화, 서버 접근 권한 분리가 필요합니다.

## 공개 주소 방식 안내

`start-public.sh`는 Cloudflare quick tunnel을 사용합니다. 터미널에 표시되는 `https://...trycloudflare.com` 주소를 직원들에게 전달하면 됩니다.

주의: 이 방식은 서버와 터널이 켜져 있는 동안만 유지되는 임시 주소입니다. 안정 운영용으로는 Cloudflare named tunnel, Render, Fly.io 같은 배포 방식이 필요합니다.

## 계속 사용할 수 있는 주소 만들기

가장 쉬운 방식은 Render Web Service로 배포하는 것입니다.

이 폴더에는 Render 배포용 `render.yaml`이 포함되어 있습니다.

Render에 배포하면 서비스마다 고유한 `onrender.com` 주소가 생성됩니다. 예를 들면 아래와 같은 형태입니다.

```text
https://billywear-kklla-sales.onrender.com
```

실제 주소는 Render에서 서비스 생성 후 표시되는 값을 사용하면 됩니다.

### Render 배포 절차

1. 이 `kklla-sales-server` 폴더를 GitHub 저장소에 올립니다.
2. Render에서 New > Blueprint를 선택합니다.
3. 이 저장소를 연결합니다.
4. `render.yaml` 설정을 확인하고 배포합니다.
5. 배포가 끝나면 Render가 제공하는 `https://...onrender.com` 주소를 직원들에게 전달합니다.

### 중요한 운영 메모

- `render.yaml`은 SQLite DB를 `/var/data/kklla`에 저장하도록 설정되어 있습니다.
- `/var/data`는 persistent disk로 잡혀 있어야 데이터가 재배포 후에도 남습니다.
- `KKLLA_ADMIN_PASSWORD`는 Render가 자동 생성하도록 설정했습니다.
- 배포 후 Render 환경변수 화면에서 관리자 비밀번호를 확인하거나 원하는 값으로 재설정하세요.
- 실제 운영 전에는 관리자 비밀번호를 반드시 별도로 보관하고, 주기적으로 DB 백업을 해야 합니다.
