import json
import boto3
from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import FAISS

# ==========================================================
# 교내 공지·학사정보 통합 AI 도우미 - CLI 챗봇
# 로컬 FAISS 지식베이스를 검색해 답변하고, 문서 출처를 표시한다.
# ==========================================================

SCORE_THRESHOLD = 1.5


def run_campus_chatbot():
    bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
    embeddings = BedrockEmbeddings(client=bedrock_client, model_id="amazon.titan-embed-text-v2:0")

    print("Loading local FAISS knowledge base...")
    try:
        db = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    except Exception as e:
        print(f"Error loading local FAISS index: {e}")
        print("Please run bedrock_faiss_indexer.py first to create the index.")
        return

    print("==================================================")
    print(" 교내 학사정보 AI 도우미 (CLI) - 'exit' 입력 시 종료")
    print("==================================================")

    while True:
        query = input("\nQ: ")
        if query.strip().lower() == "exit":
            print("Chatbot shutdown.")
            break

        results = db.similarity_search_with_score(query, k=4)
        relevant = [(doc, score) for doc, score in results if float(score) <= SCORE_THRESHOLD]

        if not relevant:
            print("\nA: 제공된 지식베이스에는 해당 정보가 없습니다.")
            continue

        context_blocks = []
        for doc, _score in relevant:
            category = doc.metadata.get("category", "미분류")
            source = doc.metadata.get("source", "알 수 없는 문서")
            context_blocks.append(f"[카테고리: {category} | 출처: {source}]\n{doc.page_content}")
        context_text = "\n---\n".join(context_blocks)

        augmented_prompt = f"""
당신은 우리 학교 학생을 돕는 교내 학사정보 안내 도우미입니다.
아래 [참고문서]만을 근거로 질문에 정확하고 친절하게 답하세요.
참고문서에 근거가 없으면 "제공된 지식베이스에는 해당 정보가 없습니다"라고 답하세요.

[참고문서]
{context_text}

질문: {query}
답변:
"""

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": augmented_prompt}],
        })

        try:
            response = bedrock_client.invoke_model(modelId="us.anthropic.claude-sonnet-5", body=body)
            response_body = json.loads(response.get("body").read())
            parts = [c.get("text", "") for c in response_body.get("content", []) if isinstance(c, dict)]
            answer = "\n".join(p for p in parts if p)
            print(f"\nA: {answer}")

            print("\n--- 답변 출처 ---")
            seen = set()
            for doc, _score in relevant:
                source = doc.metadata.get("source", "알 수 없는 문서")
                category = doc.metadata.get("category", "미분류")
                if source in seen:
                    continue
                seen.add(source)
                snippet = doc.page_content.strip().replace("\n", " ")[:120]
                print(f"  • [{category}] {source}: {snippet}...")
        except Exception as e:
            print(f"Error calling Bedrock: {e}")


if __name__ == "__main__":
    run_campus_chatbot()
