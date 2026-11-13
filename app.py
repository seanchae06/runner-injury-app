"""러너 부상 예측 & 방지 어시스턴트 - UI 뼈대
실행: streamlit run app.py
"""
import datetime

import pandas as pd
import streamlit as st

# ── 페이지 설정: 반드시 다른 st 명령보다 먼저 호출 ──────────────────────
st.set_page_config(
    page_title="러너 부상 예측 & 방지 어시스턴트",
    page_icon="🏃",
    layout="centered",  # 본문 폭을 좁혀 글이 좌우로 늘어지지 않게
    initial_sidebar_state="expanded",  # 메뉴(사이드바)를 처음부터 펼쳐 둠
)

# ── 상수 ────────────────────────────────────────────────────────────────
HOME = "home"
MENU = ["1. 운동 기록 저장", "2. 부상 위험도 예측", "3. 웹 소개 및 알고리즘"]
COLUMNS = ["날짜", "거리(km)", "총 시간", "통증 점수"]  # 총 시간은 "시:분:초" 형식
PAIN_AREAS = ["무릎 앞쪽", "장경인대", "발바닥", "아킬레스건"]

# ── session_state 초기화 ───────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = HOME  # 첫 접속 시 항상 시작 화면
if "records" not in st.session_state:
    st.session_state.records = pd.DataFrame(columns=COLUMNS)
if "loaded_file" not in st.session_state:
    st.session_state.loaded_file = None  # 같은 CSV를 rerun마다 다시 읽지 않기 위한 표시


# ── 화면 전환 콜백 ─────────────────────────────────────────────────────
def go_to(page):
    st.session_state.page = page


def on_menu_change():
    st.session_state.page = st.session_state.nav_radio


def wide_button(label, **kwargs):
    """컨테이너 폭에 맞춘 버튼 (Streamlit 버전에 따라 인자 이름이 달라서 분기)."""
    try:
        return st.button(label, width="stretch", **kwargs)
    except TypeError:
        return st.button(label, use_container_width=True, **kwargs)


def read_csv(file):
    """엑셀에서 저장한 한글 CSV(cp949)도 읽을 수 있게 인코딩을 차례로 시도."""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            file.seek(0)
            return pd.read_csv(file, encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일 인코딩을 읽을 수 없습니다.")


# ── 사이드바 (시작 화면에서는 아예 만들지 않고, 그 뒤로는 항상 펼쳐짐) ──
if st.session_state.page != HOME:
    with st.sidebar:
        st.header("🏃 메뉴")
        # 라디오 선택값을 현재 화면과 동기화한 뒤 렌더링
        st.session_state.nav_radio = st.session_state.page
        st.radio("이동할 화면", MENU, key="nav_radio", on_change=on_menu_change)
        st.divider()
        st.button("🏠 시작 화면으로", on_click=go_to, args=(HOME,))


# ── 화면 0: 시작 화면 ──────────────────────────────────────────────────
def render_home():
    st.write("")
    st.write("")
    st.markdown(
        "<h1 style='text-align:center;'>러너 부상 예측 &amp; 방지 어시스턴트</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<h3 style='text-align:center; font-weight:400;'>"
        "안전한 마라톤 완주를 위한 페이스메이커</h3>",
        unsafe_allow_html=True,
    )
    st.write("")
    _, center, _ = st.columns([1, 2, 1])
    with center:
        wide_button(
            "👉 시작하기",
            type="primary",
            on_click=go_to,
            args=(MENU[0],),
        )


# ── 화면 1: 운동 기록 저장 ─────────────────────────────────────────────
def render_records():
    st.title("📝 운동 기록 저장")

    # 1) 기존 기록 불러오기
    uploaded = st.file_uploader("기존 기록(CSV) 불러오기", type=["csv"])
    if uploaded is not None:
        file_id = (uploaded.name, uploaded.size)
        if st.session_state.loaded_file != file_id:
            try:
                df = read_csv(uploaded)
                missing = [c for c in COLUMNS if c not in df.columns]
                if missing:
                    st.error(f"CSV에 필요한 열이 없습니다: {', '.join(missing)}")
                else:
                    df = df[COLUMNS].astype({"날짜": str, "총 시간": str})
                    st.session_state.records = pd.concat(
                        [st.session_state.records, df], ignore_index=True
                    ).drop_duplicates(ignore_index=True)
                    st.session_state.loaded_file = file_id
                    st.success(f"기록 {len(df)}건을 불러왔습니다.")
            except Exception as e:  # 빈 파일, 깨진 파일 등
                st.error(f"CSV를 읽는 중 오류가 발생했습니다: {e}")

    # 2) 입력 폼
    with st.form("record_form", clear_on_submit=True):
        st.subheader("새 기록 입력")
        col1, col2 = st.columns(2)
        with col1:
            date = st.date_input("날짜", value=datetime.date.today())
        with col2:
            distance = st.number_input(
                "달린 거리(km)", min_value=0.0, max_value=200.0, step=0.1, format="%.1f"
            )

        st.markdown("**총 시간** (달리는 데 걸린 전체 시간)")
        t1, t2, t3 = st.columns(3)
        with t1:
            hours = st.number_input("시간", min_value=0, max_value=23, step=1)
        with t2:
            minutes = st.number_input("분", min_value=0, max_value=59, step=1)
        with t3:
            seconds = st.number_input("초", min_value=0, max_value=59, step=1)

        pain = st.slider("현재 통증 점수", min_value=0, max_value=10, value=0)
        st.caption(
            "이날 달리는 중이나 달린 직후에 느낀 가장 심한 통증을 기준으로 골라 주세요.\n\n"
            # 물결표(~)는 마크다운에서 취소선으로 해석되므로 \\~ 로 적는다
            "- **0**: 통증 없음\n"
            "- **1\\~3**: 약한 통증 (달리기에 지장 없음)\n"
            "- **4\\~6**: 중간 통증 (달리는 내내 신경 쓰임)\n"
            "- **7\\~10**: 심한 통증 (달리기 어렵거나 불가능)"
        )
        submitted = st.form_submit_button("기록 추가")

    if submitted:
        if distance <= 0:
            st.warning("달린 거리를 0보다 크게 입력해 주세요.")
        elif hours == 0 and minutes == 0 and seconds == 0:
            st.warning("총 시간을 입력해 주세요.")
        else:
            total_time = f"{hours}:{minutes:02d}:{seconds:02d}"  # 예: 0:48:59
            new_row = pd.DataFrame(
                [[date.isoformat(), distance, total_time, pain]], columns=COLUMNS
            )
            st.session_state.records = pd.concat(
                [st.session_state.records, new_row], ignore_index=True
            )
            st.success("기록이 추가되었습니다.")

    # 3) 누적 기록 표 + 다운로드
    st.subheader("누적 기록")
    records = st.session_state.records
    if records.empty:
        st.info("아직 저장된 기록이 없습니다. CSV를 불러오거나 새 기록을 추가해 주세요.")
    else:
        st.dataframe(records, hide_index=True)

    st.download_button(
        "내 기록 다운로드(CSV)",
        data=records.to_csv(index=False).encode("utf-8-sig"),  # 엑셀 한글 깨짐 방지
        file_name="running_records.csv",
        mime="text/csv",
        disabled=records.empty,
    )


# ── 화면 2: 부상 위험도 예측 ───────────────────────────────────────────
def render_predict():
    st.title("🩺 부상 위험도 예측")

    st.subheader("현재 통증 부위")
    for area in PAIN_AREAS:
        st.checkbox(area, key=f"pain_{area}")

    st.write("")
    if st.button("🚨 부상 위험도 분석하기", type="primary"):
        # TODO: st.session_state.records 와 체크된 통증 부위로 분석 로직 연결
        st.info("분석 결과가 여기에 표시됩니다")


# ── 화면 3: 웹 소개 및 알고리즘 ────────────────────────────────────────
def render_about():
    st.title("📖 웹 소개 및 알고리즘")

    st.subheader("프로젝트 기획 의도")
    st.write("장거리 러너의 과훈련 방지 및 근골격계 부상 예방")

    st.subheader("예측 알고리즘 분석 근거")
    st.markdown(
        "- **10% 룰**: 급격한 부하 증가 방지\n"
        "- **통증 부위별 스포츠 의학적 가중치**"
    )

    st.divider()
    st.markdown(
        ":red[**⚠️ 본 프로그램은 교육용 예방 프로토타입이며, "
        "실제 의학적 진단 및 처방을 대체할 수 없습니다.**]"
    )


# ── 라우팅 ─────────────────────────────────────────────────────────────
PAGES = {
    HOME: render_home,
    MENU[0]: render_records,
    MENU[1]: render_predict,
    MENU[2]: render_about,
}
PAGES[st.session_state.page]()