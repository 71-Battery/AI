import os
import glob
import boto3
from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==========================================================
# 교내 공지·학사정보 통합 AI 도우미 - 지식베이스 인덱서
# knowledge_base/ 아래 4개 카테고리 폴더의 문서를 읽어
# 각 청크에 카테고리와 출처(문서명) 메타데이터를 부여한 뒤
# FAISS 인덱스로 저장한다.
# ==========================================================

# 지식베이스 루트 폴더
KB_DIR = "knowledge_base"

# 카테고리(표시명) → 하위 폴더명 매핑
CATEGORY_DIRS = {
    "학사규정": "academic_rules",
    "기업 협력사": "partner_companies",
    "실무프로젝트 목록": "field_projects",
    "교육과정": "curriculum",
}

# S3 백업 버킷 (TODO: 실습 시 본인 팀의 버킷명으로 변경)
BUCKET_NAME = "gsm-instructor-bucket-tbit-498307943987"


def load_category_documents():
    """카테고리별 폴더에서 .md/.txt 문서를 읽어
    (본문, 카테고리, 문서명) 튜플 목록을 반환한다."""
    loaded = []
    for category, subdir in CATEGORY_DIRS.items():
        dir_path = os.path.join(KB_DIR, subdir)
        if not os.path.isdir(dir_path):
            continue
        file_paths = sorted(
            glob.glob(os.path.join(dir_path, "*.md"))
            + glob.glob(os.path.join(dir_path, "*.txt"))
        )
        for path in file_paths:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            loaded.append((text, category, os.path.basename(path)))
    return loaded


def build_local_vector_db():
    print(f"1. Loading campus documents from './{KB_DIR}' by category...")
    documents = load_category_documents()
    if not documents:
        print(f"   Error: '{KB_DIR}' 아래 카테고리 폴더에 문서가 없습니다. 인덱싱을 중단합니다.")
        return 0, 0
    print(f"   Loaded {len(documents)} source document(s) across {len(CATEGORY_DIRS)} categories.")

    print("2. Splitting documents into chunks with category/source metadata...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    all_docs = []
    for text, category, source_name in documents:
        chunks = text_splitter.create_documents(
            [text], metadatas=[{"category": category, "source": source_name}]
        )
        all_docs.extend(chunks)
    print(f"   Created {len(all_docs)} text chunks.")

    print("3. Initializing Bedrock Titan Text Embeddings...")
    bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
    embeddings = BedrockEmbeddings(
        client=bedrock_client,
        model_id="amazon.titan-embed-text-v2:0",
    )

    print("4. Generating vectors and saving to local FAISS index...")
    db = FAISS.from_documents(all_docs, embeddings)
    db.save_local("faiss_index")
    print("   Success! Vector DB saved locally as folder './faiss_index'\n")
    return len(documents), len(all_docs)


if __name__ == "__main__":
    build_local_vector_db()
