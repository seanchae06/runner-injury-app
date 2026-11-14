"""러너 부상 예측 & 방지 어시스턴트
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

# ── 판정 기준 (숫자를 바꾸려면 여기만 고치면 됨) ───────────────────────
DISTANCE_SITES = {"무릎 앞쪽", "장경인대"}  # 거리 부하와 관련이 크다고 보는 부위
PACE_SITES = {"발바닥", "아킬레스건"}  # 강도(속도) 부하와 관련이 크다고 보는 부위

SPIKE_LIMITS = (1.1, 1.3)  # 단일 러닝 급증: 그 전 30일 최장 거리 대비 배수 (주의, 위험)
WEEKLY_LIMITS = (1.1, 1.3)  # 주간 증가율: 최근 7일 / 그 전 7일
ACWR_LIMITS = (1.3, 1.5)  # 부하 비율: 최근 7일 / 최근 28일의 주 평균
PACE_LIMITS = (0.05, 0.10)  # 강도 변화: 페이스가 빨라진 비율 (팀 설정 기준)
MIN_DAYS_LOAD = 14  # 기록 기간이 이보다 짧으면 부하 축은 판정 보류
MIN_DAYS_CHRONIC = 28  # 기록 기간이 이보다 짧으면 부하 비율·강도 변화는 계산 제외

SCORE_LABELS = {0: "정상", 1: "주의", 2: "위험", None: "계산 불가"}
LOAD_STAGES = ["낮음", "보통", "높음"]
PAIN_STAGES = ["없음", "주의", "위험"]
GRADES = ["낮음", "주의", "높음", "매우 높음"]
# 결합 표: GRADE_MATRIX[부하 단계][통증 단계] -> 최종 등급 번호
GRADE_MATRIX = [
    [0, 1, 2],  # 부하 낮음
    [1, 2, 3],  # 부하 보통
    [2, 3, 3],  # 부하 높음
]
ADVICE = {
    0: "현재 훈련 패턴을 유지해도 좋습니다. 거리나 강도를 늘릴 때는 조금씩 늘려 주세요.",
    1: "이번 주에는 거리와 강도를 더 늘리지 말고, 통증이나 피로가 가라앉는지 지켜보세요.",
    2: "거리와 강도를 줄이고 쉬는 날을 늘려 주세요. 통증이 있다면 가라앉을 때까지 무리하지 마세요.",
    3: "달리기를 쉬거나 크게 줄여 주세요. 통증이 계속되면 의료진의 진료를 받아 보세요.",
}

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


# ── 분석 로직 ──────────────────────────────────────────────────────────
def parse_time_to_seconds(text):
    """'시:분:초' 또는 '분:초' 문자열을 초로 바꾼다. 형식이 다르면 None."""
    try:
        nums = [float(part) for part in str(text).strip().split(":")]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return None


def prepare_daily(records):
    """기록 표를 날짜별 한 줄(거리 합, 시간 합, 최고 통증)로 정리한다."""
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(records["날짜"], errors="coerce").dt.normalize(),
            "km": pd.to_numeric(records["거리(km)"], errors="coerce"),
            "sec": pd.to_numeric(records["총 시간"].map(parse_time_to_seconds), errors="coerce"),
            "pain": pd.to_numeric(records["통증 점수"], errors="coerce"),
        }
    )
    valid = df["date"].notna() & (df["km"] > 0)
    daily = (
        df[valid]
        .groupby("date")
        .agg(
            km=("km", "sum"),
            sec=("sec", lambda x: x.sum(min_count=1)),
            pain=("pain", "max"),
        )
        .sort_index()
    )
    return daily, int((~valid).sum())  # (날짜별 표, 읽지 못해 제외한 행 수)


def score(value, limits):
    """값이 주의 기준을 넘으면 1점, 위험 기준을 넘으면 2점."""
    caution, danger = limits
    value = round(value, 4)
    return 2 if value > danger else 1 if value > caution else 0


def analyze(records, sites, prior_injury, novice):
    """부하 축과 통증 축을 각각 판정하고, 결합 표와 보정으로 최종 등급을 낸다."""
    daily, skipped = prepare_daily(records)
    if daily.empty:
        return None

    day = pd.Timedelta(days=1)
    ref = daily.index.max()  # 기준일 = 가장 최근 기록 날짜
    span = (ref - daily.index.min()).days + 1  # 기록 기간(일)
    last7 = daily.loc[ref - 6 * day : ref]
    prev7 = daily.loc[ref - 13 * day : ref - 7 * day]
    last28 = daily.loc[ref - 27 * day : ref]
    prev28 = daily.loc[ref - 34 * day : ref - 7 * day]
    rows = []  # 화면에 보여 줄 지표별 결과

    # ── 부하 축 ──
    # (1) 단일 러닝 급증: 최근 7일의 각 러닝을 그 전 30일 최장 거리와 비교
    spike, spike_text = None, "비교할 이전 기록 없음"
    for date, km in last7["km"].items():
        before = daily.loc[date - 30 * day : date - day, "km"]
        if not before.empty and (spike is None or km / before.max() > spike):
            spike = km / before.max()
            spike_text = f"{km:.1f}km, 그 전 30일 최장 {before.max():.1f}km의 {spike:.2f}배"
    spike_score = None if spike is None else score(spike, SPIKE_LIMITS)
    rows.append(("부하", "단일 러닝 급증", spike_text, spike_score))

    # (2) 주간 부하 변화: 주간 증가율(지난주 대비)과 부하 비율(4주 평균 대비)
    #     주간 증가율은 달리는 요일 패턴만으로도 흔들리므로(예: 격일로 달리면 주 3회와 4회가 번갈아 나옴)
    #     두 값이 모두 기준을 넘을 때만 인정하고, 주간 증가율만 계산될 때는 1점까지만 준다.
    week_km, parts = last7["km"].sum(), []
    week_score = acwr_score = None
    if prev7["km"].sum() > 0:
        ratio = week_km / prev7["km"].sum()
        week_score = score(ratio, WEEKLY_LIMITS)
        parts.append(f"지난주 대비 {ratio:.2f}배")
    if span >= MIN_DAYS_CHRONIC:
        acwr = week_km / (last28["km"].sum() / 4)
        acwr_score = score(acwr, ACWR_LIMITS)
        parts.append(f"4주 평균 대비 {acwr:.2f}배")
    if week_score is not None and acwr_score is not None:
        weekly_score = min(week_score, acwr_score)
    elif acwr_score is not None:
        weekly_score = acwr_score
    elif week_score is not None:
        weekly_score = min(week_score, 1)
    else:
        weekly_score = None
    weekly_text = f"최근 7일 {week_km:.1f}km" + (f" ({', '.join(parts)})" if parts else "")
    rows.append(("부하", "주간 부하 변화", weekly_text, weekly_score))

    # (3) 강도 변화: 최근 7일 평균 페이스가 그 전 4주보다 얼마나 빨라졌는지
    pace_score, pace_text = None, "기록 기간 4주 미만 또는 시간 기록 없음"
    recent, earlier = last7.dropna(subset=["sec"]), prev28.dropna(subset=["sec"])
    if span >= MIN_DAYS_CHRONIC and not recent.empty and not earlier.empty:
        recent_pace = recent["sec"].sum() / recent["km"].sum()  # 1km당 초
        earlier_pace = earlier["sec"].sum() / earlier["km"].sum()
        faster = (earlier_pace - recent_pace) / earlier_pace
        pace_score = score(faster, PACE_LIMITS)
        if abs(faster) < 0.005:
            pace_text = "이전 4주와 비슷함"
        else:
            pace_text = f"이전 4주보다 {abs(faster) * 100:.1f}% {'빨라짐' if faster > 0 else '느려짐'}"
    rows.append(("부하", "강도 변화", pace_text, pace_score))

    # (4) 휴식 부족: 최근 7일 중 달리지 않은 날 수
    rest_days = 7 - len(last7)
    rest_score = 0 if rest_days >= 2 else 1 if rest_days == 1 else 2
    rows.append(("부하", "휴식", f"최근 7일 중 쉰 날 {rest_days}일", rest_score))

    load_total = sum(s for s in (spike_score, weekly_score, pace_score, rest_score) if s is not None)
    if span < MIN_DAYS_LOAD:
        load_stage = None  # 기록이 부족하면 판정 보류
    else:
        load_stage = 0 if load_total <= 1 else 1 if load_total <= 3 else 2

    # ── 통증 축 ──
    pains = daily["pain"].dropna()
    level = int(last7["pain"].max()) if last7["pain"].notna().any() else 0
    last3, before3 = pains.tail(3), pains.iloc[-6:-3]
    rising = len(pains) >= 6 and last3.mean() - before3.mean() >= 1
    persistent = len(last3) == 3 and bool((last3 >= 3).all())
    level_score = 2 if level >= 6 else 1 if level >= 3 else 0
    rows.append(("통증", "통증 수준", f"최근 7일 최고 {level}점", level_score))
    trend_text = "상승" if rising else "지속" if persistent else "뚜렷한 변화 없음"
    rows.append(("통증", "통증 추세", trend_text, 1 if rising or persistent else 0))
    rows.append(("통증", "통증 부위", ", ".join(sites) if sites else "없음", 1 if sites else 0))

    if level >= 6 or (level >= 3 and (rising or persistent)):
        pain_stage = 2
    elif level >= 3 or sites or rising:
        pain_stage = 1
    else:
        pain_stage = 0

    # ── 결합 표 ── (부하가 판정 보류이면 '부하 낮음' 줄을 최소 등급으로 사용)
    grade = GRADE_MATRIX[load_stage or 0][pain_stage]

    # ── 보정 ── (해당 항목이 여러 개여도 한 단계만 올림)
    reasons = []
    distance_up = (spike_score or 0) >= 1 or (weekly_score or 0) >= 1
    if load_stage is not None and distance_up and DISTANCE_SITES & set(sites):
        reasons.append("무릎 앞쪽·장경인대 통증이 있는 상태에서 거리 부하가 늘었습니다.")
    if load_stage is not None and (pace_score or 0) >= 1 and PACE_SITES & set(sites):
        reasons.append("발바닥·아킬레스건 통증이 있는 상태에서 달리는 속도가 빨라졌습니다.")
    if prior_injury and grade >= 1:
        reasons.append("최근 12개월 안에 부상 이력이 있습니다.")
    if novice and load_stage is not None and load_stage >= 1:
        reasons.append("러닝 경력이 6개월 미만인데 부하가 보통 이상입니다.")
    if reasons:
        grade = min(grade + 1, len(GRADES) - 1)

    return {
        "ref": ref, "span": span, "run_days": len(daily), "skipped": skipped,
        "rows": rows, "load_total": load_total, "load_stage": load_stage,
        "pain_stage": pain_stage, "grade": grade, "reasons": reasons,
    }


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
            "- **0\\~2**: 통증이 없거나 거의 느껴지지 않음\n"
            "- **3\\~5**: 통증이 느껴지지만 달릴 수는 있음\n"
            "- **6\\~10**: 통증 때문에 달리기에 지장이 있음"
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
def render_result(result):
    grade, load_stage = result["grade"], result["load_stage"]
    st.caption(
        f"기준일 {result['ref']:%Y-%m-%d} (가장 최근 기록) · "
        f"기록 기간 {result['span']}일 · 달린 날 {result['run_days']}일"
    )
    if result["skipped"]:
        st.warning(f"날짜나 거리를 읽을 수 없는 기록 {result['skipped']}건은 분석에서 제외했습니다.")

    # 최종 등급
    if load_stage is None and grade == 0:
        st.info(
            f"**판정 보류**: 기록 기간이 {MIN_DAYS_LOAD}일 미만이라 훈련 부하를 판정할 수 없습니다. "
            "기록이 더 쌓이면 다시 분석해 주세요."
        )
    else:
        label = f"부상 위험 신호: **{GRADES[grade]}**"
        if load_stage is None and grade < len(GRADES) - 1:
            label += f" 이상 (기록 기간이 {MIN_DAYS_LOAD}일 미만이라 통증만 반영한 최소 등급)"
        box = st.success if grade == 0 else st.warning if grade == 1 else st.error
        box(label)
        st.write(ADVICE[grade])

    # 두 축의 단계
    col1, col2 = st.columns(2)
    load_label = "판정 보류" if load_stage is None else f"{LOAD_STAGES[load_stage]} ({result['load_total']}점)"
    col1.metric("부하 단계", load_label)
    col2.metric("통증 단계", PAIN_STAGES[result["pain_stage"]])

    # 지표별 근거
    st.subheader("판정 이유")
    table = pd.DataFrame(
        [(group, name, text, SCORE_LABELS[s]) for group, name, text, s in result["rows"]],
        columns=["구분", "지표", "내 기록", "판정"],
    )
    st.dataframe(table, hide_index=True)
    if result["reasons"]:
        st.markdown("**한 단계 상향된 이유**")
        for reason in result["reasons"]:
            st.markdown(f"- {reason}")

    st.caption(
        "이 결과는 부상과 관련 있다고 알려진 신호를 점검한 것이며, 부상 확률이나 의학적 진단이 아닙니다. "
        "수면, 신발, 주로 상태, 달리는 자세처럼 입력하지 않은 요인은 반영되지 않습니다."
    )


def render_predict():
    st.title("🩺 부상 위험도 예측")

    st.subheader("현재 통증 부위")
    for area in PAIN_AREAS:
        st.checkbox(area, key=f"pain_{area}")

    st.subheader("배경 정보")
    prior_injury = st.checkbox("최근 12개월 안에 달리기로 인한 부상을 겪은 적이 있다")
    novice = st.checkbox("달리기를 시작한 지 6개월이 안 됐다")

    st.write("")
    if st.button("🚨 부상 위험도 분석하기", type="primary"):
        sites = [area for area in PAIN_AREAS if st.session_state.get(f"pain_{area}")]
        result = analyze(st.session_state.records, sites, prior_injury, novice)
        if result is None:
            st.warning("분석할 기록이 없습니다. 먼저 '1. 운동 기록 저장'에서 기록을 추가해 주세요.")
        else:
            render_result(result)


# ── 화면 3: 웹 소개 및 알고리즘 ────────────────────────────────────────
def render_about():
    st.title("📖 웹 소개 및 알고리즘")

    st.subheader("프로젝트 기획 의도")
    st.write("장거리 러너의 과훈련 방지 및 근골격계 부상 예방")

    st.subheader("판정 방식")
    st.markdown(
        "운동 기록에서 **부하 축**(훈련량이 얼마나 급하게 늘었는지)과 "
        "**통증 축**(몸이 이미 신호를 보내고 있는지)을 따로 판정한 뒤, "
        "두 결과를 표로 결합해 네 단계 등급(낮음, 주의, 높음, 매우 높음)을 냅니다."
    )

    st.markdown("**1. 부하 축**: 지표마다 0점(정상), 1점(주의), 2점(위험)을 매겨 더합니다.")
    st.dataframe(
        pd.DataFrame(
            [
                ("단일 러닝 급증", "최근 7일의 러닝 거리 ÷ 그 전 30일 최장 거리", "1.1배 초과", "1.3배 초과"),
                ("주간 부하 변화", "최근 7일 ÷ 그 전 7일, 최근 7일 ÷ 4주 평균 (둘 다 넘을 때)", "1.1배 / 1.3배 초과", "1.3배 / 1.5배 초과"),
                ("강도 변화", "최근 7일 평균 페이스가 이전 4주보다 빨라진 정도", "5% 이상", "10% 초과"),
                ("휴식", "최근 7일 중 쉰 날 수", "1일", "0일"),
            ],
            columns=["지표", "계산", "주의(1점)", "위험(2점)"],
        ),
        hide_index=True,
    )
    st.markdown(
        "합계 0\\~1점은 부하 낮음, 2\\~3점은 보통, 4점 이상은 높음입니다. "
        "주간 부하 변화는 달리는 요일에 따라 흔들릴 수 있어서 두 비율이 모두 기준을 넘을 때만 인정하고, "
        "기록이 4주 미만이라 지난주 대비 비율만 계산될 때는 1점까지만 줍니다."
    )

    st.markdown(
        "**2. 통증 축**\n"
        "- 수준: 최근 7일 최고 통증 점수 (0\\~2 안전, 3\\~5 주의, 6 이상 위험)\n"
        "- 추세: 최근 3회 평균이 그 전 3회보다 1점 이상 높으면 상승, 최근 3회 모두 3점 이상이면 지속\n"
        "- 부위: 체크한 통증 부위가 있는지"
    )

    st.markdown("**3. 결합 표**")
    st.dataframe(
        pd.DataFrame(
            [[GRADES[g] for g in row] for row in GRADE_MATRIX],
            index=[f"부하 {stage}" for stage in LOAD_STAGES],
            columns=[f"통증 {stage}" for stage in PAIN_STAGES],
        )
    )

    st.markdown(
        "**4. 보정** (해당하면 한 단계 상향, 여러 개여도 한 단계만)\n"
        "- 무릎 앞쪽·장경인대 통증이 있는데 거리 부하가 늘어난 경우\n"
        "- 발바닥·아킬레스건 통증이 있는데 달리는 속도가 빨라진 경우\n"
        "- 최근 12개월 안에 부상 이력이 있고 등급이 주의 이상인 경우\n"
        "- 러닝 경력 6개월 미만이고 부하가 보통 이상인 경우"
    )

    st.subheader("한계")
    st.markdown(
        "- 지표별 기준은 스포츠 의학 문헌을 참고했지만, 점수를 더하고 결합하는 방식은 "
        "이 프로젝트에서 설계한 것으로 실제 부상 자료로 검증되지 않았습니다.\n"
        f"- 기록 기간이 {MIN_DAYS_LOAD}일 미만이면 부하 축은 판정하지 않습니다.\n"
        "- 수면, 신발, 주로 상태, 달리는 자세처럼 입력하지 않은 요인은 반영하지 못합니다."
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