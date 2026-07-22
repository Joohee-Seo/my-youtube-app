import re
from urllib.parse import urlparse, parse_qs

import requests
import pandas as pd
import streamlit as st
from openai import OpenAI

# ────────────────────────────────────────────────────────────
# 기본 설정값
# ────────────────────────────────────────────────────────────
# 페이지 제목, 아이콘 등 기본 화면 설정
st.set_page_config(page_title="유튜브 댓글 분석 (1단계)", page_icon="💬")

# 예시로 쓸 두 개의 유튜브 링크
EXAMPLE_URL_1 = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"  # 딥마인드 다큐 (영어 댓글)
EXAMPLE_URL_2 = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"  # 2002 월드컵 추억 (한국어 댓글)


# ────────────────────────────────────────────────────────────
# 함수 1) 링크에서 영상 ID 뽑아내기
# ────────────────────────────────────────────────────────────
def extract_video_id(url: str):
    """
    유튜브 링크 문자열에서 11자리 영상 ID만 뽑아내는 함수.
    - https://youtu.be/영상ID?si=xxxx  (짧은 링크)
    - https://www.youtube.com/watch?v=영상ID&si=xxxx  (일반 링크)
    - https://www.youtube.com/shorts/영상ID  (쇼츠)
    위 형태를 모두 처리하고, si= 같은 뒤에 붙는 값은 자동으로 무시된다.
    영상 ID를 찾지 못하면 None을 돌려준다.
    """
    if not url:
        return None

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = parsed.netloc.lower()

    # 1) youtu.be 짧은 링크: 경로 첫 부분이 곧 영상 ID
    if "youtu.be" in host:
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id if video_id else None

    # 2) youtube.com 계열 링크
    if "youtube.com" in host:
        # 2-1) /watch?v=영상ID 형태 → 쿼리스트링에서 v 값을 꺼낸다
        if parsed.path == "/watch":
            query = parse_qs(parsed.query)
            video_ids = query.get("v")
            return video_ids[0] if video_ids else None

        # 2-2) /shorts/영상ID, /embed/영상ID 형태
        for prefix in ("/shorts/", "/embed/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].split("/")[0]

    return None


# ────────────────────────────────────────────────────────────
# 함수 2) 유튜브 댓글 가져오기 (YouTube Data API v3)
# ────────────────────────────────────────────────────────────
def fetch_comments(video_id: str, api_key: str, max_results: int = 100):
    """
    commentThreads 창구(endpoint)에 요청을 보내서 댓글을 가져오는 함수.
    - part=snippet : 댓글 내용만 필요하므로 snippet만 요청
    - order=relevance : 최신순이 아니라 '좋아요가 많은 순(관련도순)'으로 정렬해서 받아옴
    성공하면 [{'댓글':..., '좋아요':...}, ...] 형태의 리스트를 돌려준다.
    실패하면 이유가 담긴 RuntimeError를 발생시킨다 (화면에는 친절한 한국어 메시지로 보여줄 것).
    """
    endpoint = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "order": "relevance",   # 좋아요 많은 순(관련도순)
        "maxResults": max_results,  # 유튜브 API가 한 번에 줄 수 있는 최대치(100)
        "key": api_key,
    }

    try:
        response = requests.get(endpoint, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.HTTPError as error:
        # 유튜브가 알려주는 실패 사유를 최대한 읽어서 친절한 메시지로 바꿔준다
        reason = None
        try:
            reason = response.json()["error"]["errors"][0]["reason"]
        except Exception:
            pass

        if reason == "commentsDisabled":
            raise RuntimeError("이 영상은 댓글 기능이 꺼져 있어서 댓글을 가져올 수 없어요.")
        elif reason in ("quotaExceeded", "dailyLimitExceeded"):
            raise RuntimeError("오늘 사용할 수 있는 유튜브 API 할당량을 다 써버렸어요. 내일 다시 시도해주세요.")
        elif response.status_code == 403:
            raise RuntimeError("YouTube API 키가 올바르지 않거나 권한이 없어요. secrets 설정(YOUTUBE_API_KEY)을 확인해주세요.")
        elif response.status_code == 404:
            raise RuntimeError("영상을 찾을 수 없어요. 링크가 정확한지 다시 확인해주세요.")
        else:
            raise RuntimeError(f"댓글을 불러오는 중 오류가 발생했어요. (오류 코드: {response.status_code})")
    except requests.exceptions.RequestException:
        raise RuntimeError("네트워크 문제로 댓글을 불러오지 못했어요. 잠시 후 다시 시도해주세요.")

    data = response.json()
    items = data.get("items", [])

    if not items:
        raise RuntimeError("댓글을 하나도 찾지 못했어요. 댓글이 없는 영상일 수 있어요.")

    comments = []
    for item in items:
        snippet = item["snippet"]["topLevelComment"]["snippet"]
        comments.append({
            "댓글": snippet.get("textOriginal", ""),
            "좋아요": snippet.get("likeCount", 0),
        })

    # 좋아요 많은 순으로 한 번 더 확실히 정렬
    comments.sort(key=lambda c: c["좋아요"], reverse=True)
    return comments


# ────────────────────────────────────────────────────────────
# 함수 3) Solar API로 댓글 세 줄 요약하기
# ────────────────────────────────────────────────────────────
def summarize_comments(comments: list, api_key: str):
    """
    가져온 댓글 전체를 Solar API(solar-open2 모델)에 보내서
    '한국어 세 줄 요약 + 마지막 줄에 긍정/부정 비율 추정'을 받아오는 함수.
    openai 라이브러리를 그대로 쓰되, base_url만 업스테이지 주소로 바꿔서 사용한다.
    """
    # 업스테이지 서버 주소로 openai 클라이언트를 연결
    client = OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")

    # 댓글 목록을 "- 댓글내용 (좋아요 n개)" 형태의 하나의 긴 텍스트로 합침
    comment_lines = [f"- {c['댓글']} (좋아요 {c['좋아요']}개)" for c in comments]
    comment_text = "\n".join(comment_lines)

    prompt = f"""다음은 어느 유튜브 영상에 달린 댓글 목록입니다.
이 댓글들을 참고해서 전체 시청자 반응을 한국어 세 줄로 요약해주세요.
마지막 줄에는 긍정 반응과 부정 반응의 대략적인 비율을 백분율(예: 긍정 70% / 부정 30%)로 추정해서 함께 적어주세요.

[댓글 목록]
{comment_text}
"""

    try:
        response = client.chat.completions.create(
            model="solar-open2",       # 모델 이름은 반드시 이 문자열 그대로 사용
            reasoning_effort="none",   # 추론(생각) 기능 끄기
            messages=[
                {"role": "user", "content": prompt}
            ],
        )
    except Exception:
        raise RuntimeError("AI 요약을 만드는 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.")

    try:
        return response.choices[0].message.content
    except Exception:
        raise RuntimeError("AI가 요약 결과를 돌려주지 않았어요. 잠시 후 다시 시도해주세요.")


# ────────────────────────────────────────────────────────────
# 화면 구성 시작
# ────────────────────────────────────────────────────────────
st.title("💬 유튜브 댓글 분석 (1단계)")
st.write("유튜브 영상 링크를 넣으면 댓글을 좋아요 많은 순으로 가져와서 보여주고, AI로 세 줄 요약도 해줘요.")

# 텍스트 입력창에 쓸 값을 세션 상태에 미리 준비해둔다 (없으면 기본값으로 채움)
if "url_input" not in st.session_state:
    st.session_state.url_input = EXAMPLE_URL_1


# 예시 버튼을 눌렀을 때 실행될 함수들 (버튼 클릭 → 입력창 값을 바꿔줌)
def _use_example_1():
    st.session_state.url_input = EXAMPLE_URL_1


def _use_example_2():
    st.session_state.url_input = EXAMPLE_URL_2


# 예시 버튼 두 개를 나란히 배치 (입력창보다 위쪽)
example_col1, example_col2 = st.columns(2)
with example_col1:
    st.button("예시 1 · 딥마인드 다큐(영어 댓글)", on_click=_use_example_1, use_container_width=True)
with example_col2:
    st.button("예시 2 · 2002 월드컵 추억(한국어 댓글)", on_click=_use_example_2, use_container_width=True)

# 유튜브 링크 입력창 (key로 세션 상태와 연결되어 있어서 버튼을 누르면 자동으로 값이 바뀜)
video_url = st.text_input("유튜브 영상 링크", key="url_input")

# 댓글 가져오기 버튼
fetch_clicked = st.button("댓글 가져오기", type="primary")

# ────────────────────────────────────────────────────────────
# '댓글 가져오기' 버튼 처리
# ────────────────────────────────────────────────────────────
if fetch_clicked:
    video_id = extract_video_id(video_url)

    if not video_id:
        st.error("영상 링크에서 영상 ID를 찾지 못했어요. 링크가 올바른지 확인해주세요.")
    else:
        # secrets 금고에서 유튜브 API 키를 꺼내온다
        youtube_api_key = st.secrets.get("YOUTUBE_API_KEY")

        if not youtube_api_key:
            st.error("YOUTUBE_API_KEY가 secrets에 설정되어 있지 않아요. 스트림릿 클라우드의 Secrets 설정을 확인해주세요.")
        else:
            with st.spinner("댓글을 가져오는 중이에요..."):
                try:
                    comments = fetch_comments(video_id, youtube_api_key, max_results=100)
                    # 다음 요약 버튼 클릭 시에도 쓸 수 있도록 세션에 저장
                    st.session_state.comments = comments
                    st.session_state.summary = None  # 새로 댓글을 가져왔으니 이전 요약은 초기화
                except RuntimeError as error:
                    st.error(str(error))

# ────────────────────────────────────────────────────────────
# 세션에 저장된 댓글이 있으면 지표 카드 + 표로 보여주기
# ────────────────────────────────────────────────────────────
if "comments" in st.session_state and st.session_state.comments:
    comments = st.session_state.comments

    st.metric("가져온 댓글 개수", f"{len(comments)}개")

    df = pd.DataFrame(comments)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # ────────────────────────────────────────────────
    # AI 세 줄 요약 버튼
    # ────────────────────────────────────────────────
    if st.button("✨ AI 세 줄 요약"):
        solar_api_key = st.secrets.get("SOLAR_API_KEY")

        if not solar_api_key:
            st.error("SOLAR_API_KEY가 secrets에 설정되어 있지 않아요. 스트림릿 클라우드의 Secrets 설정을 확인해주세요.")
        else:
            with st.spinner("AI가 댓글을 읽고 요약하는 중이에요..."):
                try:
                    summary = summarize_comments(comments, solar_api_key)
                    st.session_state.summary = summary
                except RuntimeError as error:
                    st.error(str(error))

    # 요약 결과가 세션에 있으면 화면에 보여준다
    if st.session_state.get("summary"):
        st.subheader("📝 AI 세 줄 요약")
        st.write(st.session_state.summary)
