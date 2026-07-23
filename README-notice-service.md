# 능동형 공지·일정 알림 서비스 (Proactive Notice Service)

새로운 공지나 일정이 등록되면 **AI가 먼저 사용자에게 알림을 보내고, 내용을 요약·설명**해 주는 능동형(proactive) 서비스입니다.

## 동작 방식

```
[게시판/캘린더/외부 소스]
        │  (1) 새 공지 등록 (POST /notices) 또는 (1') 주기적 폴링 감지
        ▼
   ingestNotice()  ── 저장 ──▶ AI 요약(summarizer) ──▶ 능동 알림(notifier)
                                (Bedrock/폴백)          (console/Slack/email)
        ▼
   사용자에게 "먼저" 요약된 알림 도착 🔔
```

핵심은 사용자가 요청하지 않아도 **서비스가 먼저** 공지를 감지하고, 요약해서 알려준다는 점입니다.

## 빠른 시작

```bash
npm install
cp .env.example .env      # 필요 시 값 수정 (설정 없이도 동작)
npm run demo              # 등록→요약→알림 전체 흐름 데모
npm start                 # HTTP 서버 실행 (http://localhost:3000)
```

> AWS 자격증명이 없으면 AI 요약은 자동으로 간단 추출 요약으로 폴백되므로 **설정 없이 바로 실행**됩니다.

## API

### 공지/일정 등록 — `POST /notices`
```bash
curl -X POST http://localhost:3000/notices \
  -H "Content-Type: application/json" \
  -d '{
    "title": "1분기 워크샵 안내",
    "content": "2026-02-14 10:00 본사 3층 대강당. 참가신청 2026-02-07 마감.",
    "type": "schedule",
    "startsAt": "2026-02-14T10:00:00+09:00",
    "url": "https://intra.example.com/notice/101",
    "sourceId": "notice-101"
  }'
```
| 필드 | 필수 | 설명 |
|------|------|------|
| `title` | title/content 중 하나 | 제목 |
| `content` | title/content 중 하나 | 본문 |
| `type` | 아니오 | `notice`(기본) 또는 `schedule` |
| `startsAt` | 아니오 | 일정 시작 시각(ISO8601) |
| `url` | 아니오 | 원문 링크 |
| `sourceId` | 아니오 | 외부 시스템 고유 ID (중복 방지에 사용) |

### 목록 조회 — `GET /notices`
### 헬스체크 — `GET /health`

## 설정 (.env)

| 변수 | 설명 |
|------|------|
| `AI_PROVIDER` | `bedrock` 또는 `none` |
| `BEDROCK_MODEL_ID` | 사용할 Bedrock 모델 ID |
| `NOTIFY_CHANNELS` | `console,slack,email` 중 콤마로 지정 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |
| `EMAIL_FROM` / `EMAIL_TO` | SES 발신/수신 이메일 |
| `POLL_ENABLED` / `POLL_SOURCE_URL` / `POLL_CRON` | 외부 소스 폴링 옵션 |

### 알림 채널 확장
- **Slack**: [Incoming Webhook](https://api.slack.com/messaging/webhooks) URL을 `SLACK_WEBHOOK_URL`에 넣고 `NOTIFY_CHANNELS=console,slack`
- **이메일**: SES에서 발신 주소 인증 후 `NOTIFY_CHANNELS=console,email`
- 카카오톡/문자/푸시 등은 `src/services/notifier.js`의 `handlers`에 함수만 추가하면 됩니다.

### 외부 소스 자동 감지(폴링)
`POLL_ENABLED=true`, `POLL_SOURCE_URL=<공지 JSON API>` 설정 시 `POLL_CRON` 주기로 새 공지를 자동 감지합니다. 소스 응답 형식이 다르면 `src/poller.js`의 `normalize()`만 맞춰주세요.

---

## AWS EC2 인스턴스 만들기

이 서비스를 배포할 서버(EC2 인스턴스)를 만드는 두 가지 방법입니다.

### 방법 A: AWS 콘솔(웹 UI)

1. AWS 콘솔 로그인 → **EC2** 검색 → **인스턴스 시작(Launch instance)** 클릭
2. **이름**: `proactive-notice-service` 입력
3. **AMI(운영체제)**: `Amazon Linux 2023` (프리티어 가능) 선택
4. **인스턴스 유형**: `t3.micro`(또는 프리티어 `t2.micro`) 선택
5. **키 페어**: 새로 생성(`.pem` 파일 다운로드, SSH 접속에 사용) 또는 기존 키 선택
6. **네트워크 설정 → 보안 그룹**: 인바운드 규칙 추가
   - `SSH` (포트 22) — 내 IP 만 허용(권장)
   - `사용자 지정 TCP` (포트 3000) — 앱 접근용 (또는 80/443을 열고 Nginx 리버스 프록시 사용)
7. **스토리지**: 8~16GB gp3
8. **인스턴스 시작** 클릭

### 방법 B: AWS CLI

```bash
# 0) 사전: aws configure 로 자격증명 설정, 리전 예: ap-northeast-2(서울)

# 1) 키 페어 생성
aws ec2 create-key-pair --key-name notice-key \
  --query 'KeyMaterial' --output text > notice-key.pem
chmod 400 notice-key.pem

# 2) 보안 그룹 생성 및 포트 개방
SG_ID=$(aws ec2 create-security-group \
  --group-name notice-sg --description "proactive notice" \
  --query 'GroupId' --output text)

MY_IP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
  --protocol tcp --port 22 --cidr ${MY_IP}/32          # SSH: 내 IP만
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
  --protocol tcp --port 3000 --cidr 0.0.0.0/0          # 앱 포트

# 3) 인스턴스 시작 (Amazon Linux 2023 AMI는 리전마다 다름 - SSM에서 조회)
AMI_ID=$(aws ssm get-parameters \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)

aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type t3.micro \
  --key-name notice-key \
  --security-group-ids $SG_ID \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=proactive-notice-service}]' \
  --count 1
```

### 인스턴스에 배포하기

```bash
# 1) SSH 접속 (퍼블릭 IP는 콘솔 또는 describe-instances로 확인)
ssh -i notice-key.pem ec2-user@<퍼블릭_IP>

# 2) Node.js 설치 (Amazon Linux 2023)
sudo dnf install -y nodejs git

# 3) 코드 배포 후 실행
git clone <이 저장소 URL> && cd <프로젝트>
npm install
cp .env.example .env      # 필요한 값 채우기
# 24시간 유지하려면 pm2 권장
sudo npm install -g pm2
pm2 start src/index.js --name notice
pm2 save && pm2 startup   # 재부팅 후 자동 실행
```

### 권장: 자격증명은 키 대신 IAM Role

EC2에서 Bedrock/SES를 쓸 때는 `.env`에 액세스 키를 넣지 말고, **IAM Role**을 인스턴스에 연결하는 것이 안전합니다.
1. IAM → 역할 생성 → 신뢰 주체 `EC2`
2. `AmazonBedrockFullAccess`(또는 최소 권한 정책), 필요 시 SES 권한 부여
3. EC2 인스턴스 → 작업 → 보안 → **IAM 역할 수정**으로 연결
4. `.env`의 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`는 비워두면 SDK가 Role 자격증명을 자동 사용합니다.

> ⚠️ 보안 참고: 포트 3000을 `0.0.0.0/0`으로 열면 인증 없이 누구나 공지를 등록할 수 있습니다. 실제 운영에서는 API 키/토큰 인증을 추가하고, 가능하면 앱 포트를 외부에 직접 노출하지 말고 Nginx + HTTPS(443) 뒤에 두세요. `Bedrock` 모델은 콘솔의 **Model access**에서 사전 활성화가 필요합니다.

## 프로젝트 구조
```
src/
  index.js            # Express 서버 (진입점)
  config.js           # 환경변수 로딩
  store.js            # 공지 저장소(JSON, 중복 감지)
  pipeline.js         # 등록→요약→알림 오케스트레이션
  poller.js           # 외부 소스 주기 폴링(옵션)
  services/
    summarizer.js     # AI 요약 (Bedrock + 폴백)
    notifier.js       # 알림 발송 (console/slack/email)
scripts/demo.js       # 설정 없이 전체 흐름 데모
```

## 실서비스 전환 체크리스트
- 저장소를 JSON → DynamoDB/RDS로 교체 (`src/store.js`)
- `POST /notices`에 인증(API 키/HMAC 서명) 추가
- Bedrock 모델 접근 권한(Model access) 활성화
- 알림 실패 재시도/큐(SQS) 도입
