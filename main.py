"""
유튜브 댓글 분석 앱 - 1단계 + 2단계
=================================
1단계: 유튜브 영상 링크를 입력받아, 댓글을 '좋아요 많은 순'으로
       최대 100개까지 가져와 표로 보여줍니다.
2단계: 가져온 댓글 전체를 단어로 쪼개서, 자주 나온 단어 상위 20개를
       세어 가로 막대그래프로 보여줍니다.

전체 흐름(초보자용 설명):
1) 사용자가 링크를 입력창에 붙여넣습니다. (예시 버튼으로 자동 입력도 가능)
2) 링크에서 '영상 ID'만 뽑아냅니다. (유튜브는 영상마다 고유 ID가 있습니다)
3) 유튜브 공식 API(YouTube Data API v3)에 그 영상 ID로 댓글을 요청합니다.
4) 받아온 댓글을 좋아요 수 기준으로 정렬해서 표로 보여줍니다.
5) 댓글 전체를 단어로 나눠 상위 20개 단어를 그래프로 보여줍니다.
"""

import re  # 정규표현식: 링크에서 영상 ID를 뽑거나, 문장에서 단어를 뽑을 때 사용합니다.
import requests  # 유튜브 API 서버에 요청(request)을 보낼 때 사용하는 라이브러리입니다.
import pandas as pd  # 댓글 목록을 표(DataFrame) 형태로 다루기 위해 사용합니다.
import streamlit as st  # 웹 화면(UI)을 만들어주는 라이브러리입니다.
import plotly.express as px  # 막대그래프 같은 그래프를 쉽게 그려주는 라이브러리입니다.
from collections import Counter  # 단어 개수를 세는 데 편리한 파이썬 기본 도구입니다.


# -----------------------------
# 기본 설정값
# -----------------------------
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"  # 예시 1: 딥마인드 다큐(영어 댓글)
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"  # 예시 2: 2002 월드컵 추억(한국어 댓글)

st.set_page_config(page_title="유튜브 댓글 분석 (1~2단계)", page_icon="💬", layout="wide")


def extract_video_id(url: str):
    """
    유튜브 링크 문자열에서 '영상 ID'만 뽑아내는 함수.

    유튜브 링크는 보통 아래 두 가지 형태 중 하나입니다.
    - 짧은 링크: https://youtu.be/영상ID?si=아무값
    - 일반 링크: https://www.youtube.com/watch?v=영상ID&기타값...

    영상 ID는 보통 영어 대소문자, 숫자, '-', '_' 로 이루어진 11자리 문자열입니다.
    si= 같은 뒷부분 값은 영상 ID가 아니므로 무시해야 합니다.
    """
    if not url:
        return None

    url = url.strip()

    # 패턴 1: youtu.be/영상ID  (짧은 링크)
    match = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    # 패턴 2: youtube.com/watch?v=영상ID (일반 링크, v= 뒤에 영상ID)
    match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    # 패턴 3: youtube.com/shorts/영상ID (쇼츠 링크도 혹시 몰라 함께 처리)
    match = re.search(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})", url)
    if match:
        return match.group(1)

    return None  # 위 패턴에 하나도 안 맞으면 영상 ID를 못 찾은 것입니다.


def fetch_comments(video_id: str, api_key: str):
    """
    유튜브 Data API v3의 commentThreads 창구에 요청을 보내서
    댓글을 최대 100개까지 받아오는 함수.

    반환값: (댓글 리스트, 에러 메시지)
    - 성공하면 (댓글 리스트, None)
    - 실패하면 (None, "친절한 한국어 에러 메시지")
    """
    endpoint = "https://www.googleapis.com/youtube/v3/commentThreads"

    params = {
        "part": "snippet",       # 댓글의 내용, 좋아요 수 등 기본 정보를 가져오라는 뜻
        "videoId": video_id,     # 어떤 영상의 댓글을 가져올지 지정
        "maxResults": 100,       # 한 번에 최대 100개까지 요청 (API 허용 최대치)
        "order": "relevance",    # 최신순이 아니라 '좋아요 많은 순(인기순)'으로 요청
        "key": api_key,          # 유튜브 API 사용을 위한 인증 키
    }

    try:
        response = requests.get(endpoint, params=params, timeout=10)
    except requests.exceptions.RequestException:
        # 인터넷 연결 문제 등, 요청 자체가 안 보내진 경우
        return None, "⚠️ 유튜브 서버에 연결하지 못했어요. 인터넷 연결 상태를 확인한 뒤 다시 시도해 주세요."

    if response.status_code == 200:
        data = response.json()
        comments = []

        for item in data.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "댓글": snippet.get("textOriginal", ""),
                "좋아요 수": snippet.get("likeCount", 0),
            })

        return comments, None

    # ---- 여기서부터는 실패(에러) 상황을 한국어로 친절하게 안내 ----
    try:
        error_reason = response.json().get("error", {}).get("errors", [{}])[0].get("reason", "")
    except Exception:
        error_reason = ""

    if response.status_code == 404:
        return None, "😥 해당 영상을 찾을 수 없어요. 링크가 정확한지 다시 확인해 주세요."

    if response.status_code == 403 and error_reason == "commentsDisabled":
        return None, "🔒 이 영상은 댓글 기능이 꺼져 있어서 댓글을 가져올 수 없어요."

    if response.status_code == 403 and "quota" in error_reason.lower():
        return None, "⏳ 오늘 유튜브 API 사용량(할당량)을 다 써버렸어요. 내일 다시 시도해 주세요."

    if response.status_code == 403:
        return None, "🔑 API 키에 문제가 있는 것 같아요. 비밀 금고(secrets)에 등록한 YOUTUBE_API_KEY 값을 확인해 주세요."

    return None, f"❌ 댓글을 가져오는 중 알 수 없는 문제가 발생했어요. (오류 코드: {response.status_code})"


def count_top_words(comments, top_n=20):
    """
    [2단계] 댓글 전체를 단어로 쪼개서, 자주 나온 단어 상위 top_n개를 세는 함수.

    - 여러 댓글의 텍스트를 하나로 합칩니다.
    - 정규표현식으로 '단어'만 뽑아냅니다.
      (한글, 영어, 숫자를 단어로 인정하고, 문장부호/이모지 등은 자동으로 제외됩니다.)
    - 한 글자짜리 단어(예: 'a', '의', '1')는 의미가 약하므로 제외합니다.
    - 영어는 대소문자를 구분하지 않도록 모두 소문자로 바꿉니다. (Dog, dog → dog)

    반환값: [("단어", 횟수), ...] 형태의 리스트 (많이 나온 순서)
    """
    # 모든 댓글 텍스트를 하나의 큰 문자열로 합칩니다.
    all_text = " ".join(c["댓글"] for c in comments)

    # 한글/영어/숫자로 이루어진 '단어 덩어리'만 뽑아냅니다.
    # \w 는 밑줄도 포함하지만, 여기서는 한글+영문+숫자 위주로 단어를 인식합니다.
    words = re.findall(r"[가-힣A-Za-z0-9]+", all_text)

    # 영어 단어는 소문자로 통일하고, 한 글자짜리 단어는 걸러냅니다.
    cleaned = [w.lower() for w in words if len(w) >= 2]

    # Counter가 각 단어의 등장 횟수를 세어주고, most_common으로 상위 N개를 뽑습니다.
    return Counter(cleaned).most_common(top_n)


# -----------------------------
# 화면(UI) 구성 시작
# -----------------------------
st.title("💬 유튜브 댓글 분석기 (1~2단계)")
st.caption("영상 링크를 넣으면, 좋아요가 많은 순으로 댓글을 가져와 표로 보여주고 자주 쓰인 단어도 분석해요.")

# 입력창의 값을 기억해두는 저장소(session_state)를 준비합니다.
# 이렇게 해야 예시 버튼을 눌렀을 때 입력창 값을 바꿀 수 있어요.
if "video_url" not in st.session_state:
    st.session_state.video_url = EXAMPLE_1_URL

# 예시 버튼 두 개를 나란히 배치
col1, col2 = st.columns(2)
with col1:
    if st.button("예시 1 · 딥마인드 다큐(영어 댓글)", use_container_width=True):
        st.session_state.video_url = EXAMPLE_1_URL
with col2:
    if st.button("예시 2 · 2002 월드컵 추억(한국어 댓글)", use_container_width=True):
        st.session_state.video_url = EXAMPLE_2_URL

# 유튜브 링크 입력창 (session_state의 값을 그대로 보여줌)
video_url = st.text_input("유튜브 영상 링크를 붙여넣어 주세요", key="video_url")

fetch_button = st.button("📥 댓글 가져오기", type="primary")

# -----------------------------
# 댓글 가져오기 버튼을 눌렀을 때의 동작
# -----------------------------
if fetch_button:
    video_id = extract_video_id(video_url)

    if video_id is None:
        st.error("🙏 링크에서 영상 정보를 찾지 못했어요. 유튜브 영상 링크가 맞는지 확인해 주세요.\n\n"
                 "예: https://youtu.be/영상ID  또는  https://www.youtube.com/watch?v=영상ID")
    else:
        # secrets에서 API 키를 안전하게 불러옵니다.
        api_key = st.secrets.get("YOUTUBE_API_KEY", None)

        if not api_key:
            st.error("🔑 유튜브 API 키가 설정되어 있지 않아요. "
                     "스트림릿 클라우드의 'Secrets' 설정에 YOUTUBE_API_KEY 값을 추가해 주세요.")
        else:
            with st.spinner("댓글을 가져오는 중이에요..."):
                comments, error_message = fetch_comments(video_id, api_key)

            if error_message:
                st.error(error_message)
            elif not comments:
                st.info("😶 이 영상에는 댓글이 하나도 없는 것 같아요.")
            else:
                # 좋아요 수가 많은 순으로 정렬 (내림차순)
                comments_sorted = sorted(comments, key=lambda c: c["좋아요 수"], reverse=True)
                df = pd.DataFrame(comments_sorted)

                # 가져온 댓글 개수를 큰 지표 카드로 표시
                st.metric("가져온 댓글 개수", f"{len(df)} 개")

                # 댓글 목록을 표로 표시 (좋아요 수와 함께)
                st.subheader("📝 댓글 목록 (좋아요 많은 순)")
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "댓글": st.column_config.TextColumn("댓글", width="large"),
                        "좋아요 수": st.column_config.NumberColumn("좋아요 수", format="%d"),
                    },
                )

                # -----------------------------
                # [2단계] 자주 나온 단어 상위 20개 그래프
                # -----------------------------
                st.subheader("🔤 자주 나온 단어 TOP 20")

                top_words = count_top_words(comments_sorted, top_n=20)

                if not top_words:
                    st.info("😶 단어를 셀 만한 내용이 부족해요.")
                else:
                    # 그래프용 표로 변환합니다.
                    word_df = pd.DataFrame(top_words, columns=["단어", "횟수"])

                    # plotly 가로 막대그래프를 그립니다.
                    fig = px.bar(
                        word_df,
                        x="횟수",
                        y="단어",
                        orientation="h",  # h = horizontal(가로 막대)
                        text="횟수",       # 막대 끝에 횟수 숫자를 표시
                    )

                    # 많이 나온 단어가 '위'에 오도록 순서를 뒤집습니다.
                    # (기본값은 큰 값이 아래에 놓이기 때문에 반대로 정렬해줍니다.)
                    fig.update_yaxes(categoryorder="total ascending")
                    fig.update_layout(
                        xaxis_title="등장 횟수",
                        yaxis_title="단어",
                        height=600,
                    )

                    st.plotly_chart(fig, use_container_width=True)
