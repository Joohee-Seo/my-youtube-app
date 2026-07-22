"""
유튜브 댓글 분석 앱 - 1단계 + 2단계 + 3단계
========================================
1단계: 유튜브 영상 링크를 입력받아, 댓글을 '좋아요 많은 순'으로
       최대 100개까지 가져와 표로 보여줍니다.
2단계: 가져온 댓글 전체를 단어로 쪼개서, 자주 나온 단어 상위 20개를
       세어 가로 막대그래프로 보여줍니다.
3단계: 댓글 전체로 워드클라우드(단어 구름) 그림을 만들어 화면에 띄웁니다.

전체 흐름(초보자용 설명):
1) 사용자가 링크를 입력창에 붙여넣습니다. (예시 버튼으로 자동 입력도 가능)
2) 링크에서 '영상 ID'만 뽑아냅니다. (유튜브는 영상마다 고유 ID가 있습니다)
3) 유튜브 공식 API(YouTube Data API v3)에 그 영상 ID로 댓글을 요청합니다.
4) 받아온 댓글을 좋아요 수 기준으로 정렬해서 표로 보여줍니다.
5) 댓글 전체를 단어로 나눠 상위 20개 단어를 그래프로 보여줍니다.
6) 댓글 전체로 워드클라우드 그림을 그려서 보여줍니다.
"""

import os  # 파일 경로(폰트 파일 위치 등)를 다룰 때 사용합니다.
import re  # 정규표현식: 링크에서 영상 ID를 뽑거나, 문장에서 단어를 뽑을 때 사용합니다.
import requests  # 유튜브 API 서버 요청 + 폰트 파일 내려받기에 사용하는 라이브러리입니다.
import pandas as pd  # 댓글 목록을 표(DataFrame) 형태로 다루기 위해 사용합니다.
import streamlit as st  # 웹 화면(UI)을 만들어주는 라이브러리입니다.
import plotly.express as px  # 막대그래프 같은 그래프를 쉽게 그려주는 라이브러리입니다.
from collections import Counter  # 단어 개수를 세는 데 편리한 파이썬 기본 도구입니다.
from wordcloud import WordCloud  # 단어 구름(워드클라우드) 그림을 만들어주는 라이브러리입니다.


# -----------------------------
# 기본 설정값
# -----------------------------
EXAMPLE_1_URL = "https://youtu.be/d95J8yzvjbQ?si=LfL5DLwCL8Pk077r"  # 예시 1: 딥마인드 다큐(영어 댓글)
EXAMPLE_2_URL = "https://youtu.be/I9vK5EVTt0U?si=NEZ8L7MRuNvrzINa"  # 예시 2: 2002 월드컵 추억(한국어 댓글)

# 한글이 깨지지 않도록 사용할 나눔고딕 폰트 파일 주소와, 내려받아 저장할 위치
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
FONT_PATH = "NanumGothic-Regular.ttf"  # 앱 폴더 안에 이 이름으로 저장합니다.

st.set_page_config(page_title="유튜브 댓글 분석 (1~3단계)", page_icon="💬", layout="wide")


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


def get_words(comments, min_len=2):
    """
    댓글 리스트에서 '단어'만 뽑아 리스트로 돌려주는 함수.

    - 한글/영어/숫자 덩어리만 단어로 인정합니다. (문장부호·이모지는 제외)
    - 영어는 소문자로 통일합니다. (Dog, dog → dog)
    - min_len(기본 2)글자 미만인 단어는 제외합니다. → 한 글자 단어 빼기
    """
    all_text = " ".join(c["댓글"] for c in comments)
    words = re.findall(r"[가-힣A-Za-z0-9]+", all_text)
    return [w.lower() for w in words if len(w) >= min_len]


def count_top_words(comments, top_n=20):
    """
    [2단계] 댓글 전체를 단어로 쪼개서, 자주 나온 단어 상위 top_n개를 세는 함수.

    반환값: [("단어", 횟수), ...] 형태의 리스트 (많이 나온 순서)
    """
    cleaned = get_words(comments, min_len=2)  # 한 글자 단어 제외
    return Counter(cleaned).most_common(top_n)


@st.cache_data(show_spinner=False)
def download_font():
    """
    [3단계] 한글이 깨지지 않도록 나눔고딕 폰트 파일을 내려받는 함수.

    - 이미 내려받아 둔 파일이 있으면 다시 받지 않고 그대로 씁니다.
    - @st.cache_data 덕분에, 한 번 성공하면 그 결과를 기억해 매번 다시 받지 않습니다.

    반환값: 성공하면 폰트 파일 경로(문자열), 실패하면 None
    """
    # 이미 파일이 존재하면 그 경로를 그대로 돌려줍니다.
    if os.path.exists(FONT_PATH):
        return FONT_PATH

    try:
        response = requests.get(FONT_URL, timeout=15)
        if response.status_code == 200:
            # 폰트는 글자가 아닌 '바이너리' 파일이므로 'wb'(write binary) 모드로 저장합니다.
            with open(FONT_PATH, "wb") as f:
                f.write(response.content)
            return FONT_PATH
    except requests.exceptions.RequestException:
        return None  # 인터넷 문제 등으로 내려받기 실패

    return None  # 상태코드가 200이 아니면(파일을 못 받으면) 실패 처리


def make_wordcloud_image(comments, font_path):
    """
    [3단계] 댓글 전체로 워드클라우드 그림을 만들어 이미지로 돌려주는 함수.

    - 배경은 흰색으로 설정합니다.
    - 한 글자 단어는 제외합니다. (2단계와 동일 기준)
    - matplotlib 같은 그래프 라이브러리는 쓰지 않고,
      WordCloud가 만들어주는 그림을 바로 이미지(PIL Image)로 변환해 돌려줍니다.

    반환값: 이미지 객체 (없으면 None)
    """
    words = get_words(comments, min_len=2)  # 한 글자 단어 제외한 단어 목록
    if not words:
        return None

    # 단어들을 공백으로 이어 붙여 워드클라우드에 넣을 '한 덩어리 텍스트'를 만듭니다.
    text = " ".join(words)

    wc = WordCloud(
        font_path=font_path,      # 한글 폰트 지정 (이게 없으면 한글이 네모로 깨집니다)
        background_color="white", # 배경 흰색
        width=800,
        height=500,
        collocations=False,       # 같은 단어가 두 단어처럼 중복 집계되는 것을 방지
        min_word_length=2,        # 한 글자 단어 제외 (한 번 더 안전장치)
    ).generate(text)

    # .to_image() 는 matplotlib 없이 곧바로 그림(PIL Image)을 만들어 줍니다.
    return wc.to_image()


# -----------------------------
# 화면(UI) 구성 시작
# -----------------------------
st.title("💬 유튜브 댓글 분석기 (1~3단계)")
st.caption("영상 링크를 넣으면 댓글을 가져와 표·단어 그래프·워드클라우드로 분석해요.")

# 입력창의 값을 기억해두는 저장소(session_state)를 준비합니다.
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
                    word_df = pd.DataFrame(top_words, columns=["단어", "횟수"])

                    fig = px.bar(
                        word_df,
                        x="횟수",
                        y="단어",
                        orientation="h",  # h = horizontal(가로 막대)
                        text="횟수",       # 막대 끝에 횟수 숫자를 표시
                    )
                    # 많이 나온 단어가 '위'에 오도록 정렬
                    fig.update_yaxes(categoryorder="total ascending")
                    fig.update_layout(
                        xaxis_title="등장 횟수",
                        yaxis_title="단어",
                        height=600,
                    )
                    st.plotly_chart(fig, use_container_width=True)

                # -----------------------------
                # [3단계] 워드클라우드 그림
                # -----------------------------
                st.subheader("☁️ 워드클라우드")

                with st.spinner("한글 폰트를 준비하는 중이에요..."):
                    font_path = download_font()

                if font_path is None:
                    # 폰트를 못 받았을 때의 친절한 한국어 안내
                    st.error("😥 한글 폰트를 내려받지 못해서 워드클라우드를 만들 수 없어요.\n\n"
                             "인터넷 연결 상태를 확인한 뒤 잠시 후 다시 시도해 주세요.")
                else:
                    wc_image = make_wordcloud_image(comments_sorted, font_path)

                    if wc_image is None:
                        st.info("😶 워드클라우드를 그릴 만한 단어가 부족해요.")
                    else:
                        # matplotlib 없이 이미지 그대로 화면에 띄웁니다.
                        st.image(wc_image, use_container_width=True)
