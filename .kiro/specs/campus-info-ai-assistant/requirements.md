# Requirements Document

## Introduction

교내 공지·학사정보 통합 AI 도우미는 학교의 흩어진 정보(학사규정, 기업 협력사, 실무프로젝트 목록, 교육과정)를 하나의 지식베이스로 통합하고, 학생의 자연어 질문에 대해 RAG(Retrieval-Augmented Generation) 방식으로 답변하는 챗봇이다.

이 도우미는 세 가지 핵심 동작을 수행한다. (1) 질문 맥락 또는 학생 입력에서 학년과 학과를 식별하고, (2) 지식베이스에서 질문과 관련된 정보를 벡터 유사도 검색으로 찾으며, (3) 검색된 정보를 학생의 학년/학과와 학교 특성에 맞춰 맞춤형으로 설명한다. 모든 답변에는 근거가 된 문서 출처가 함께 표시된다.

시스템은 기존 인프라(Python 3.12 + Streamlit, Amazon Bedrock의 Claude LLM 및 Titan Embed Text v2 임베딩, FAISS 로컬 벡터 DB, LangChain, S3 문서 저장, EC2 배포)를 재활용하여 구현한다.

## Glossary

- **Campus_Assistant**: 교내 공지·학사정보 통합 AI 도우미 시스템 전체를 지칭한다.
- **Query_Interface**: 학생이 자연어 질문을 입력하고 답변을 확인하는 Streamlit 프론트엔드 구성요소이다.
- **Profile_Identifier**: 학생의 학년과 학과를 질문 텍스트 또는 명시적 입력에서 식별하는 구성요소이다.
- **Retriever**: 질문 임베딩과 지식베이스 벡터를 비교하여 관련 문서 청크를 검색하는 구성요소이다.
- **Answer_Generator**: 검색된 문서와 학생 프로파일을 기반으로 Claude LLM을 호출하여 맞춤형 답변을 생성하는 구성요소이다.
- **Knowledge_Base**: 학사규정, 기업 협력사, 실무프로젝트 목록, 교육과정 카테고리의 문서를 임베딩하여 저장한 FAISS 벡터 인덱스이다.
- **Indexer**: 원본 문서를 청크로 분할하고 임베딩하여 Knowledge_Base를 생성 및 갱신하는 구성요소이다.
- **Document_Category**: 지식베이스 문서의 분류로, "학사규정", "기업 협력사", "실무프로젝트 목록", "교육과정" 중 하나이다.
- **Student_Profile**: 식별된 학생의 학년(1~4 등)과 학과 정보를 담은 데이터 구조이다.
- **Source_Citation**: 답변 생성에 사용된 문서명과 원본 내용 발췌를 담은 출처 정보이다.
- **Grade**: 학생의 학년을 나타내는 값이다.
- **Department**: 학생의 학과를 나타내는 값이다.
- **Relevance_Score**: Retriever가 산출하는 질문과 문서 청크 간 유사도 점수이다.

## Requirements

### Requirement 1: 학생 질문 입력 및 답변 표시

**User Story:** 학생으로서, 자연어로 교내 정보에 대해 질문하고 답변을 받고 싶다. 그래야 흩어진 문서를 직접 찾지 않고도 필요한 정보를 얻을 수 있다.

#### Acceptance Criteria

1. WHEN 학생이 Query_Interface에 질문 텍스트를 제출하면, THE Campus_Assistant SHALL 해당 질문에 대한 답변을 생성하여 Query_Interface에 표시한다
2. WHEN 학생이 빈 질문을 제출하면, THE Query_Interface SHALL 질문 입력을 요청하는 안내 메시지를 표시하고 답변 생성을 수행하지 않는다
3. THE Query_Interface SHALL 이전 질문과 답변으로 구성된 대화 기록을 세션 동안 유지하여 표시한다
4. WHEN Answer_Generator가 답변을 반환하면, THE Query_Interface SHALL 답변과 함께 Source_Citation을 표시한다

### Requirement 2: 학생 학년/학과 식별

**User Story:** 학생으로서, 나의 학년과 학과에 맞는 답변을 받고 싶다. 그래야 나에게 해당되는 정확한 정보를 얻을 수 있다.

#### Acceptance Criteria

1. WHEN 학생이 Query_Interface에서 학년과 학과를 명시적으로 선택하면, THE Profile_Identifier SHALL 선택된 값을 Student_Profile로 설정한다
2. WHERE 학생이 학년 또는 학과를 명시적으로 선택하지 않은 경우, THE Profile_Identifier SHALL 질문 텍스트에서 Grade와 Department를 식별하여 Student_Profile을 구성한다
3. IF 질문 텍스트와 명시적 입력 모두에서 Grade 또는 Department를 식별하지 못하면, THEN THE Profile_Identifier SHALL 해당 항목을 "미지정" 상태로 설정한다
4. WHILE Student_Profile의 Grade 또는 Department가 "미지정" 상태인 동안, THE Answer_Generator SHALL 학년/학과 무관 정보를 기준으로 답변을 생성하고 학년/학과 확인을 요청하는 안내를 답변에 포함한다

### Requirement 3: 지식베이스 정보 검색 (RAG)

**User Story:** 학생으로서, 내 질문과 관련된 최신 학교 정보를 근거로 한 답변을 받고 싶다. 그래야 신뢰할 수 있는 정보를 얻을 수 있다.

#### Acceptance Criteria

1. WHEN 질문이 제출되면, THE Retriever SHALL 질문을 Titan Embed Text v2 모델로 임베딩하여 Knowledge_Base에서 관련 문서 청크를 검색한다
2. THE Retriever SHALL 질문당 상위 K개(기본값 4개)의 문서 청크를 Relevance_Score 순으로 반환한다
3. IF Knowledge_Base가 로드되지 않으면, THEN THE Campus_Assistant SHALL 지식베이스 준비가 필요하다는 메시지를 표시하고 답변 생성을 수행하지 않는다
4. WHEN Retriever가 문서 청크를 반환하면, THE Retriever SHALL 각 청크의 Document_Category와 문서명을 메타데이터로 함께 반환한다
5. IF 검색된 문서 청크의 Relevance_Score가 모두 설정된 임계값 미만이면, THEN THE Answer_Generator SHALL 지식베이스에 관련 정보가 없다는 취지의 답변을 생성한다

### Requirement 4: 학교 특성 맞춤형 답변 생성

**User Story:** 학생으로서, 검색된 정보가 내 상황과 학교 맥락에 맞게 설명되기를 원한다. 그래야 정보를 쉽게 이해하고 활용할 수 있다.

#### Acceptance Criteria

1. WHEN Answer_Generator가 답변을 생성하면, THE Answer_Generator SHALL 검색된 문서 청크만을 근거로 사용하고 검색된 문서에 없는 내용을 생성하지 않는다
2. WHEN Student_Profile에 Grade와 Department가 지정되어 있으면, THE Answer_Generator SHALL 해당 Grade와 Department에 맞춰 답변 내용을 구성한다
3. IF 검색된 문서에 질문에 대한 근거가 없으면, THEN THE Answer_Generator SHALL "제공된 지식베이스에는 해당 정보가 없습니다"라는 취지의 메시지를 답변으로 반환한다
4. WHEN Answer_Generator가 답변을 반환하면, THE Answer_Generator SHALL 답변에 사용된 각 문서의 문서명과 원본 내용 발췌를 포함한 Source_Citation을 반환한다
5. IF Answer_Generator가 답변에 대한 Source_Citation을 생성하지 못하면, THEN THE Campus_Assistant SHALL 답변을 표시하지 않고 출처 확인 불가 메시지를 표시한다
6. IF Answer_Generator가 Claude LLM 호출 중 오류를 수신하면, THEN THE Campus_Assistant SHALL 오류 발생 사실을 알리는 메시지를 Query_Interface에 표시한다

### Requirement 5: 지식베이스 문서 관리 및 인덱싱

**User Story:** 관리자로서, 학사규정·기업 협력사·실무프로젝트·교육과정 문서를 지식베이스에 등록하고 갱신하고 싶다. 그래야 학생에게 최신 정보를 제공할 수 있다.

#### Acceptance Criteria

1. WHEN 관리자가 문서를 Document_Category와 함께 업로드하면, THE Campus_Assistant SHALL 해당 문서를 지식 문서 저장소에 저장한다
2. WHEN 관리자가 인덱싱을 실행하면, THE Indexer SHALL 저장소의 각 문서를 청크로 분할하고 Document_Category와 문서명을 메타데이터로 부여하여 Knowledge_Base를 갱신한다
3. WHEN 문서가 업로드되면, THE Campus_Assistant SHALL 해당 문서를 S3 버킷에 백업 업로드한다
4. IF S3 백업 업로드가 실패하면, THEN THE Campus_Assistant SHALL 백업 실패를 알리는 메시지를 표시하고, 관리자가 메시지를 무시하더라도 로컬 저장·인덱싱 및 이후 문서 관리 작업을 계속 진행한다
5. WHEN 인덱싱이 완료되면, THE Campus_Assistant SHALL 처리된 문서 수와 생성된 청크 수를 표시하며, 처리된 문서가 없는 경우 0으로 표시한다
6. THE Query_Interface SHALL 현재 등록된 문서 목록을 Document_Category별로 표시한다

### Requirement 6: 인증 및 AWS 접근

**User Story:** 시스템 운영자로서, 애플리케이션이 자격 증명 노출 없이 AWS 서비스에 접근하기를 원한다. 그래야 배포 환경의 보안을 유지할 수 있다.

#### Acceptance Criteria

1. THE Campus_Assistant SHALL EC2 인스턴스에 부여된 IAM Role을 사용하여 Amazon Bedrock 및 S3에 접근한다
2. IF IAM Role의 권한 부족으로 특정 서비스 호출이 실패하면, THEN THE Campus_Assistant SHALL 해당 기능에 대한 오류 메시지를 표시하고 영향을 받지 않는 나머지 기능은 계속 제공한다
3. IF AWS 자격 증명 오류와 권한 부족이 동시에 발생하면, THEN THE Campus_Assistant SHALL 두 유형을 포괄하는 단일 접근 오류 메시지를 표시한다
