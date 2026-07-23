import json
import boto3


def test_bedrock():
    # 1. Bedrock Runtime Client (EC2 IAM Instance Profile 자동 사용)
    bedrock_runtime = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")

    # 2. Claude 추론 프로필 ID
    model_id = "us.anthropic.claude-sonnet-5"

    # 3. Payload
    prompt = "교내 학사정보 AI 도우미 프로젝트의 Bedrock 연동에 성공했습니다. 축하 메시지 한 줄 출력해줘."
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    })

    print("Sending prompt to Bedrock Claude...")
    try:
        response = bedrock_runtime.invoke_model(modelId=model_id, body=body)
        # 4. Response Parsing (text 타입 블록만 안전 추출)
        response_body = json.loads(response.get("body").read())
        parts = [c.get("text", "") for c in response_body.get("content", []) if isinstance(c, dict)]
        answer = "\n".join(p for p in parts if p)
        print("\n--- Claude Response ---")
        print(answer)
        print("-----------------------")
    except Exception as e:
        print(f"Error calling Bedrock: {e}")


if __name__ == "__main__":
    test_bedrock()
