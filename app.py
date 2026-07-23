import os
import re
import glob
import json
from dataclasses import dataclass

import boto3
import streamlit as st
from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==========================================================
# 교내 공지·학사정보 통합 AI 도우미
# 학교의 모든 정보(학사규정, 기업 협력사, 실무프로젝트 목록,
# 교육과정)를 지식베이스로 담고, 학생의 질문을 받아
#   1) 학년/학과 파악  2) 관련 정보 검색(RAG)  3) 맞춤 설명
# 을 수행하는 RAG 챗봇. 답변에는 문서 출처를 함께 표시한다.
# ==========================================================

st.set_page_config(
    page_title="Campus AI · 교내 학사정보 도우미",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------
# 설정: 지식베이스 카테고리 / 학과·학년 / S3
# ----------------------------------------------------------
KB_DIR = "knowledge_base"
CATEGORY_DIRS = {
    "학사규정": "academic_rules",
    "기업 협력사": "partner_companies",
    "실무프로젝트 목록": "field_projects",
    "교육과정": "curriculum",
}
CATEGORY_ICON = {
    "학사규정": "📘",
    "기업 협력사": "🤝",
    "실무프로젝트 목록": "🛠️",
    "교육과정": "📚",
}
GRADES = ["미지정", "1학년", "2학년", "3학년"]
DEPARTMENTS = ["미지정", "소프트웨어개발과", "스마트IoT과"]

# 질문 텍스트에서 학과를 추론하기 위한 별칭 사전
DEPARTMENT_ALIASES = {
    "소프트웨어개발과": ["소프트웨어개발과", "소프트웨어과", "소프트웨어", "sw과", "sw", "소개과"],
    "스마트IoT과": ["스마트iot과", "스마트 iot", "iot과", "iot", "사물인터넷", "스마트아이오티"],
}

BUCKET_NAME = "gsm-instructor-bucket-tbit-498307943987"

# 검색 결과 관련성 임계값 (FAISS L2 거리 기반, 작을수록 유사)
SCORE_THRESHOLD = 1.5


# ----------------------------------------------------------
# 데이터 모델
# ----------------------------------------------------------
@dataclass
class StudentProfile:
    grade: str = "미지정"
    department: str = "미지정"

    @property
    def is_complete(self) -> bool:
        return self.grade != "미지정" and self.department != "미지정"


@dataclass
class RetrievedChunk:
    content: str
    category: str
    source: str
    score: float


# ----------------------------------------------------------
# Custom Theme / CSS
# ----------------------------------------------------------
def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }
        .stApp {
            background:
                radial-gradient(1200px 600px at 100% -10%, rgba(56,189,248,0.12), transparent 60%),
                radial-gradient(900px 500px at -10% 110%, rgba(52,211,153,0.10), transparent 55%),
                #0d1117;
            color: #e6e8ef;
        }
        .hero {
            border-radius: 20px; padding: 28px 32px;
            background: linear-gradient(120deg, #0ea5e9 0%, #2563eb 50%, #14b8a6 100%);
            box-shadow: 0 12px 40px rgba(37,99,235,0.35); margin-bottom: 6px;
        }
        .hero h1 { color:#fff; font-weight:800; font-size:1.9rem; margin:0 0 6px 0; letter-spacing:-0.02em; }
        .hero p { color:rgba(255,255,255,0.92); font-size:0.98rem; margin:0; line-height:1.55; }
        .hero .badge {
            display:inline-block; background:rgba(255,255,255,0.18); border:1px solid rgba(255,255,255,0.3);
            color:#fff; padding:3px 12px; border-radius:999px; font-size:0.72rem; font-weight:600;
            margin-bottom:12px; letter-spacing:0.03em;
        }
        .chip-row { display:flex; gap:10px; flex-wrap:wrap; margin:14px 0 4px; }
        .chip {
            background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.09); border-radius:12px;
            padding:10px 14px; font-size:0.82rem; color:#c7cbd9; flex:1; min-width:150px;
        }
        .chip b { color:#fff; display:block; font-size:0.9rem; margin-bottom:2px; }
        section[data-testid="stSidebar"] { background:#11151c; border-right:1px solid rgba(255,255,255,0.06); }
        section[data-testid="stSidebar"] .sidebar-brand { font-weight:800; font-size:1.15rem; color:#fff; display:flex; align-items:center; gap:8px; }
        section[data-testid="stSidebar"] .sidebar-sub { color:#8b91a7; font-size:0.8rem; margin-bottom:14px; }
        div[data-testid="stChatMessage"] { background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); border-radius:16px; padding:6px 12px; }
        .src-card {
            background:rgba(14,165,233,0.08); border:1px solid rgba(14,165,233,0.28);
            border-left:3px solid #0ea5e9; border-radius:10px; padding:10px 14px; margin:8px 0;
        }
        .src-title { font-family:'JetBrains Mono', monospace; font-size:0.8rem; color:#7dd3fc; font-weight:600; margin-bottom:4px; }
        .src-snippet { color:#aeb4c6; font-size:0.8rem; line-height:1.5; }
        .cat-badge { display:inline-block; background:rgba(20,184,166,0.15); border:1px solid rgba(20,184,166,0.4);
            color:#5eead4; padding:1px 8px; border-radius:999px; font-size:0.7rem; margin-left:6px; }
        .stButton > button {
            border-radius:10px; border:1px solid rgba(37,99,235,0.5);
            background:linear-gradient(120deg, #0ea5e9, #2563eb); color:#fff; font-weight:600; padding:8px 18px;
            transition: transform .08s ease, box-shadow .2s ease;
        }
        .stButton > button:hover { transform:translateY(-1px); box-shadow:0 8px 20px rgba(37,99,235,0.4); }
        .doc-item {
            background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:10px;
            padding:9px 14px; margin:6px 0; font-family:'JetBrains Mono', monospace; font-size:0.82rem;
            color:#d7dbe8; display:flex; align-items:center; gap:10px;
        }
        .doc-item .dot { width:8px; height:8px; border-radius:50%; background:#34d399; }
        .sec-head { font-weight:700; font-size:1.05rem; color:#fff; margin:6px 0 2px; }
        #MainMenu, footer, header {visibility:hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------
# AWS 클라이언트
# ----------------------------------------------------------
@st.cache_resource
def get_aws_clients():
    s3_client = boto3.client("s3")
    bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
    return s3_client, bedrock_client


s3_client, bedrock_client = get_aws_clients()


def get_embeddings():
    return BedrockEmbeddings(client=bedrock_client, model_id="amazon.titan-embed-text-v2:0")


def load_vector_db():
    try:
        return FAISS.load_local("faiss_index", get_embeddings(), allow_dangerous_deserialization=True)
    except Exception:
        return None


# ----------------------------------------------------------
# Indexer: 카테고리 폴더 전체 재인덱싱
# ----------------------------------------------------------
def rebuild_index():
    all_docs = []
    n_files = 0
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    for category, subdir in CATEGORY_DIRS.items():
        dir_path = os.path.join(KB_DIR, subdir)
        if not os.path.isdir(dir_path):
            continue
        for path in sorted(glob.glob(os.path.join(dir_path, "*.md")) + glob.glob(os.path.join(dir_path, "*.txt"))):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            chunks = text_splitter.create_documents(
                [text], metadatas=[{"category": category, "source": os.path.basename(path)}]
            )
            all_docs.extend(chunks)
            n_files += 1
    if not all_docs:
        return 0, 0
    db = FAISS.from_documents(all_docs, get_embeddings())
    db.save_local("faiss_index")
    return n_files, len(all_docs)


# ----------------------------------------------------------
# Profile_Identifier: 학년/학과 식별
# ----------------------------------------------------------
def identify_profile(query: str, explicit_grade: str, explicit_dept: str) -> StudentProfile:
    grade = explicit_grade if explicit_grade != "미지정" else "미지정"
    dept = explicit_dept if explicit_dept != "미지정" else "미지정"

    q = query.lower()
    # 학년 추론 (명시 선택이 없을 때만)
    if grade == "미지정":
        m = re.search(r"([1-3])\s*학년", query)
        if m:
            grade = f"{m.group(1)}학년"

    # 학과 추론 (명시 선택이 없을 때만)
    if dept == "미지정":
        for dept_name, aliases in DEPARTMENT_ALIASES.items():
            if any(alias in q for alias in aliases):
                dept = dept_name
                break

    return StudentProfile(grade=grade, department=dept)


# ----------------------------------------------------------
# Retriever: 점수 기반 유사도 검색 + 임계값 필터
# ----------------------------------------------------------
def retrieve(db, query: str, k: int = 4, threshold: float = SCORE_THRESHOLD):
    results = db.similarity_search_with_score(query, k=k)
    chunks = []
    for doc, score in results:
        chunks.append(
            RetrievedChunk(
                content=doc.page_content,
                category=doc.metadata.get("category", "미분류"),
                source=doc.metadata.get("source", "알 수 없는 문서"),
                score=float(score),
            )
        )
    relevant = [c for c in chunks if c.score <= threshold]
    return chunks, relevant


# ----------------------------------------------------------
# Answer_Generator: 프로파일 반영 프롬프트 + Claude 스트리밍
# ----------------------------------------------------------
def build_prompt(profile: StudentProfile, chunks, query: str) -> str:
    context_blocks = [
        f"[카테고리: {c.category} | 출처: {c.source}]\n{c.content}" for c in chunks
    ]
    context_text = "\n---\n".join(context_blocks)
    return f"""
당신은 우리 학교 학생을 돕는 교내 학사정보 안내 도우미입니다.
아래 [참고문서]만을 근거로 학생의 질문에 정확하고 친절하게 답하세요.
참고문서에 근거가 없는 내용은 지어내지 말고 "제공된 지식베이스에는 해당 정보가 없습니다"라고 답하세요.
가능하면 어떤 문서를 근거로 삼았는지 자연스럽게 언급하세요.

[학생 정보]
- 학년: {profile.grade}
- 학과: {profile.department}
학년/학과에 해당하는 규정·교육과정·실무프로젝트·협력사 정보가 있으면 그에 맞춰 설명하세요.
학년 또는 학과가 '미지정'이면 일반 정보로 답하되, 더 정확한 안내를 위해 학년/학과 확인을 정중히 요청하세요.

[참고문서]
{context_text}

질문: {query}
답변:
"""


def stream_bedrock(prompt_text: str):
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt_text}],
    })
    try:
        response = bedrock_client.invoke_model_with_response_stream(
            modelId="us.anthropic.claude-sonnet-5", body=body
        )
        for event in response.get("body"):
            chunk = json.loads(event.get("chunk").get("bytes").decode("utf-8"))
            if chunk.get("type") == "content_block_delta":
                yield chunk.get("delta", {}).get("text", "")
    except Exception as e:
        yield f"\n\n⚠️ AWS 접근 오류로 답변을 생성하지 못했습니다: {e}"


def render_sources(sources):
    with st.expander("📎 답변 출처 보기", expanded=False):
        for i, src in enumerate(sources, 1):
            icon = CATEGORY_ICON.get(src["category"], "📄")
            st.markdown(
                f"""
                <div class="src-card">
                    <div class="src-title">{icon} {i}. {src['source']}
                        <span class="cat-badge">{src['category']}</span></div>
                    <div class="src-snippet">{src['snippet']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


inject_css()

# ----------------------------------------------------------
# Sidebar
# ----------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-brand">🎓 Campus AI</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-sub">교내 공지·학사정보 통합 도우미</div>', unsafe_allow_html=True)

    page = st.radio("메뉴", ["💬 학사정보 Q&A", "📁 지식베이스 관리"], label_visibility="collapsed")

    st.divider()
    st.markdown('<div class="sec-head">🧑‍🎓 내 정보</div>', unsafe_allow_html=True)
    st.caption("선택하면 학년·학과에 맞춰 답변합니다.")
    sel_grade = st.selectbox("학년", GRADES, index=0)
    sel_dept = st.selectbox("학과", DEPARTMENTS, index=0)

    st.divider()
    _total = 0
    for _cat, _sub in CATEGORY_DIRS.items():
        _p = os.path.join(KB_DIR, _sub)
        if os.path.isdir(_p):
            _total += len(glob.glob(os.path.join(_p, "*.md")) + glob.glob(os.path.join(_p, "*.txt")))
    st.markdown(
        f'<div class="sidebar-sub">📚 등록 문서 <b style="color:#7dd3fc">{_total}</b>개 · 카테고리 {len(CATEGORY_DIRS)}종</div>',
        unsafe_allow_html=True,
    )
    st.caption("Powered by Amazon Bedrock · FAISS · LangChain")


# ==========================================
# PAGE 1: 학사정보 Q&A
# ==========================================
if page == "💬 학사정보 Q&A":
    st.markdown(
        """
        <div class="hero">
            <span class="badge">CAMPUS INFO ASSISTANT</span>
            <h1>🎓 교내 학사정보 Q&A</h1>
            <p>학사규정 · 기업 협력사 · 실무프로젝트 · 교육과정에 대해 물어보세요.<br>
            AI가 <b>학년/학과를 파악</b>하고 <b>관련 정보를 찾아</b> <b>학교 특성에 맞춰</b> 설명합니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="chip-row">
            <div class="chip"><b>📘 학사규정</b>출결·성적·진급·졸업</div>
            <div class="chip"><b>🤝 기업 협력사</b>현장실습·채용연계</div>
            <div class="chip"><b>🛠️ 실무프로젝트</b>학년별 프로젝트</div>
            <div class="chip"><b>📚 교육과정</b>학과·학년별 커리큘럼</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    db = load_vector_db()
    if db is None:
        st.warning("지식베이스를 불러올 수 없습니다. '📁 지식베이스 관리'에서 인덱스를 먼저 빌드해 주세요.", icon="⚠️")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        avatar = "🎓" if message["role"] == "assistant" else "🧑‍🎓"
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])
            if message.get("sources"):
                render_sources(message["sources"])

    if db is not None:
        if query := st.chat_input("궁금한 점을 입력하세요… 예) 3학년 현장실습은 어떻게 신청해?"):
            # 1) 학년/학과 파악
            profile = identify_profile(query, sel_grade, sel_dept)

            with st.chat_message("user", avatar="🧑‍🎓"):
                st.markdown(query)
            st.session_state.messages.append({"role": "user", "content": query})

            # 2) 관련 정보 검색
            all_chunks, relevant = retrieve(db, query, k=4)

            with st.chat_message("assistant", avatar="🎓"):
                if not relevant:
                    answer = (
                        "제공된 지식베이스에는 해당 정보가 없습니다. "
                        "학사규정·기업 협력사·실무프로젝트·교육과정에 관한 질문을 해주세요."
                    )
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": []})
                else:
                    # 3) 학교 특성 맞춤 설명 (스트리밍)
                    prompt = build_prompt(profile, relevant, query)
                    placeholder = st.empty()
                    full = ""
                    for piece in stream_bedrock(prompt):
                        full += piece
                        placeholder.markdown(full + "▌")
                    placeholder.markdown(full)

                    sources = [
                        {
                            "source": c.source,
                            "category": c.category,
                            "snippet": c.content.strip().replace("\n", " ")[:200] + "...",
                        }
                        for c in relevant
                    ]
                    render_sources(sources)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": full, "sources": sources}
                    )

# ==========================================
# PAGE 2: 지식베이스 관리
# ==========================================
elif page == "📁 지식베이스 관리":
    st.markdown(
        """
        <div class="hero">
            <span class="badge">KNOWLEDGE BASE MANAGER</span>
            <h1>📁 지식베이스 관리 &amp; 인덱싱</h1>
            <p>학사규정 · 기업 협력사 · 실무프로젝트 · 교육과정 문서를 카테고리별로 등록하고 벡터 인덱스를 갱신합니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for _cat, _sub in CATEGORY_DIRS.items():
        os.makedirs(os.path.join(KB_DIR, _sub), exist_ok=True)

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.markdown('<div class="sec-head">📄 카테고리별 등록 문서</div>', unsafe_allow_html=True)
        for cat, sub in CATEGORY_DIRS.items():
            icon = CATEGORY_ICON.get(cat, "📄")
            files = sorted(
                glob.glob(os.path.join(KB_DIR, sub, "*.md"))
                + glob.glob(os.path.join(KB_DIR, sub, "*.txt"))
            )
            st.markdown(f"**{icon} {cat}** ({len(files)}개)")
            if files:
                for p in files:
                    st.markdown(
                        f'<div class="doc-item"><span class="dot"></span>{os.path.basename(p)}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("등록된 문서 없음")

        st.markdown('<div class="sec-head" style="margin-top:18px;">🔄 전체 재인덱싱</div>', unsafe_allow_html=True)
        if st.button("지식베이스 전체 재인덱싱 실행", use_container_width=True):
            with st.spinner("인덱스를 재빌드하는 중…"):
                n_files, n_chunks = rebuild_index()
            if n_files == 0:
                st.error("등록된 문서가 없습니다. 먼저 문서를 업로드하세요.")
            else:
                st.success(f"완료! 총 {n_files}개 문서, {n_chunks}개 청크로 인덱스를 갱신했습니다.", icon="✅")
                st.session_state.messages = []

    with col_right:
        st.markdown('<div class="sec-head">⬆️ 새 문서 추가</div>', unsafe_allow_html=True)
        cat_choice = st.selectbox("카테고리 선택", list(CATEGORY_DIRS.keys()))
        uploaded_file = st.file_uploader("문서(.md 또는 .txt)를 업로드하세요", type=["txt", "md"])

        if uploaded_file is not None:
            st.markdown(
                f'<div class="doc-item"><span class="dot"></span>{uploaded_file.name} · {uploaded_file.size} bytes</div>',
                unsafe_allow_html=True,
            )
            if st.button("문서 저장 및 인덱스 재빌드", use_container_width=True):
                progress = st.progress(0)
                status = st.empty()
                try:
                    status.text("1/3 · 카테고리 폴더에 문서 저장 중…")
                    subdir = CATEGORY_DIRS[cat_choice]
                    save_path = os.path.join(KB_DIR, subdir, uploaded_file.name)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    progress.progress(30)

                    status.text("2/3 · S3 버킷으로 백업 업로드 중…")
                    try:
                        uploaded_file.seek(0)
                        s3_client.upload_fileobj(
                            uploaded_file, BUCKET_NAME, f"{subdir}/{uploaded_file.name}"
                        )
                    except Exception as s3e:
                        st.warning(f"S3 백업은 건너뜁니다(로컬 인덱싱은 계속): {s3e}", icon="☁️")
                    progress.progress(60)

                    status.text("3/3 · 전체 문서로 벡터 인덱스 재빌드 중…")
                    n_files, n_chunks = rebuild_index()
                    progress.progress(100)

                    st.success(
                        f"완료! '{cat_choice}'에 문서를 추가하고 총 {n_files}개 문서, "
                        f"{n_chunks}개 청크로 인덱스를 갱신했습니다.",
                        icon="✅",
                    )
                    st.session_state.messages = []
                except Exception as e:
                    st.error(f"작업 중 오류가 발생했습니다: {e}")
