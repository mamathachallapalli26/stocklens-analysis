# StockLens v4 - Intelligent Stock Market Analytics
# Run:  python -m streamlit run app.py
# Data: put one CSV per company in ./data with columns
#       Date, Open, High, Low, Close, Volume.
#       With no CSVs, demo data is generated.
import glob
import os
import sqlite3
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config("StockLens", "📈", layout="wide")
BLUE, GREEN, RED = "#7DD3FC", "#86EFAC", "#FCA5A5"
PURPLE, ORANGE, CYAN = "#C4B5FD", "#FCD34D", "#67E8F9"
PINK = "#F9A8D4"
PASTEL_RDYG = [[0, "#FCA5A5"], [0.5, "#FEF3C7"], [1, "#86EFAC"]]
PASTEL_BLUE = [[0, "#E0F2FE"], [1, "#7DD3FC"]]
INK = "#0B1220"
CARD = "#101F33"
TINT = {BLUE: "#0e2f52", GREEN: "#0d3a2a", RED: "#40212b",
        PURPLE: "#2c2459", ORANGE: "#40301a", CYAN: "#0d3a44"}

CSS = """<style>
.stApp{background:linear-gradient(160deg,#0B1830 0%,TINT 100%);color:#fff}
p,li{font-size:20px!important}
.stApp label,.stApp label p,[data-testid=stWidgetLabel] *{
  color:#fff!important;font-size:19px!important}
.stApp h1{font-size:52px!important;font-weight:900!important;
  color:#fff!important;-webkit-text-fill-color:#fff!important;
  text-shadow:0 0 12px rgba(255,255,255,.25)}
.stApp h2{font-size:34px!important;font-weight:800!important}
.stApp h3{font-size:26px!important;font-weight:700!important}
.stApp h2,.stApp h3,.stApp h4{color:#fff!important;
  -webkit-text-fill-color:#fff!important}
.kpi{background:rgba(255,255,255,.07);border-radius:16px;padding:18px;
  margin-bottom:12px;border-top:5px solid var(--c)}
.kpi b{font-size:34px;display:block;color:#fff;white-space:nowrap}
.kpi span{font-size:18px;color:#e2ecf7}
.box{background:rgba(255,255,255,.07);border-left:8px solid var(--c);
  border-radius:12px;padding:16px 22px;margin:14px 0;font-size:20px}
.box b{font-size:22px}
section[data-testid=stSidebar]{background:#0F2038}
section[data-testid=stSidebar] *{color:#fff!important;
  -webkit-text-fill-color:#fff!important;opacity:1!important}
section[data-testid=stSidebar] [data-testid=stRadio] label *{
  font-size:18px!important;font-weight:600!important;line-height:1.4!important}
section[data-testid=stSidebar] h1{font-size:34px!important}
</style>"""


def theme(acc):
    css = CSS.replace("TINT", TINT[acc]).replace("ACC", acc)
    st.markdown(css.replace("CARD", CARD), unsafe_allow_html=True)
    # ---------------- SQL layer ----------------
SETUP_SQL = """
-- MERGE happens in Python (all CSVs -> raw_prices)
-- CLEAN + DEDUPLICATE + FILTER
CREATE TABLE prices AS
SELECT company, date, open, high, low, close, volume
FROM raw_prices
WHERE date IS NOT NULL AND close IS NOT NULL AND close > 0
GROUP BY company, date;

-- AGGREGATE: returns, moving averages, signals
CREATE VIEW metrics AS
WITH b AS (
  SELECT company, date, open, high, low, close, volume,
    close*1.0/LAG(close) OVER w - 1 AS ret,
    AVG(close) OVER (PARTITION BY company ORDER BY date
        ROWS 19 PRECEDING) AS ma20,
    AVG(close) OVER (PARTITION BY company ORDER BY date
        ROWS 49 PRECEDING) AS ma50,
    ROW_NUMBER() OVER w AS rn
  FROM prices
  WINDOW w AS (PARTITION BY company ORDER BY date))
SELECT *, CASE
  WHEN rn < 50 THEN 'HOLD'
  WHEN close > ma20 AND ma20 > ma50 THEN 'BUY'
  WHEN close < ma20 AND ma20 < ma50 THEN 'SELL'
  ELSE 'HOLD' END AS signal
FROM b;
"""


def demo_data():
    rng = np.random.default_rng(7)
    names = ["Bajaj Auto", "Eicher Motors", "Hero Motocorp",
             "TVS Motors", "TCS", "Infosys"]
    dates = pd.bdate_range("2015-01-01", "2018-12-31")
    out = []
    for i, n in enumerate(names):
        r = rng.normal(0.0006 + i * 1e-4, 0.011 + i * 0.002, len(dates))
        c = 1000 * np.exp(np.cumsum(r))
        out.append(pd.DataFrame({
            "company": n, "date": dates, "open": c, "high": c * 1.01,
            "low": c * 0.99, "close": c,
            "volume": rng.integers(200000, 2000000, len(dates))}))
    d = pd.concat(out)
    return pd.concat([d, d.sample(15, random_state=1)])


@st.cache_resource
def build_db():
    con = sqlite3.connect(":memory:", check_same_thread=False)
    frames = []
    for f in glob.glob("data/*.csv"):
        d = pd.read_csv(f)
        d.columns = [c.strip().lower() for c in d.columns]
        name = os.path.splitext(os.path.basename(f))[0]
        d["company"] = name.replace("_", " ").title()
        cols = ["company", "date", "open", "high", "low", "close", "volume"]
        frames.append(d[cols])
    raw = pd.concat(frames) if frames else demo_data()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["date"] = raw["date"].dt.strftime("%Y-%m-%d")
    raw.to_sql("raw_prices", con, index=False)
    con.executescript(SETUP_SQL)
    return con


con = build_db()
df = pd.read_sql("SELECT * FROM metrics", con, parse_dates=["date"])
companies = sorted(df.company.unique())
raw_rows = int(pd.read_sql("SELECT COUNT(*) n FROM raw_prices", con).n[0])
bajaj = next((c for c in companies if "bajaj" in c.lower()), companies[0])
# ---------------- metrics ----------------
def drawdown(g):
    return g.close / g.close.cummax() - 1


rows = []
for c, g in df.groupby("company"):
    r = g.ret.dropna()
    rows.append(dict(
        Company=c, Latest=g.close.iloc[-1],
        Return=(g.close.iloc[-1] / g.close.iloc[0] - 1) * 100,
        AvgDaily=r.mean() * 100, Volatility=r.std() * 100,
        MaxDD=drawdown(g).min() * 100, DownDays=int((r < 0).sum()),
        Signal=g.signal.iloc[-1]))
S = pd.DataFrame(rows).set_index("Company")
rank = S.Volatility.rank(method="first")
S["Risk"] = pd.qcut(rank, 3, labels=["Low", "Medium", "High"]).astype(str)
LAST = df.groupby("company").tail(1).set_index("company")
STD = df.groupby("company").ret.transform("std")
anom = df[df.ret.abs() > 3 * STD]


# ---------------- helpers ----------------
def kpis(items):
    for col, (label, value, color) in zip(st.columns(len(items)), items):
        col.markdown(
            f'<div class="kpi" style="--c:{color}"><span>{label}</span>'
            f"<b>{value}</b></div>", unsafe_allow_html=True)


def box(text, color=BLUE, title="📌 PAGE INSIGHT"):
    st.markdown(
        f'<div class="box" style="--c:{color}"><b>{title}</b><br>{text}'
        "</div>", unsafe_allow_html=True)


def bullets(title, color, points):
    items = "".join(f"<li>{p}</li>" for p in points)
    box(f"<ul>{items}</ul>", color, title)


def show(fig, h=430):
    grid = "rgba(255,255,255,0.14)"
    if not fig.layout.title.text:
        fig.update_layout(title_text="")
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", height=h,
        font=dict(size=17, color="#FFFFFF"),
        title_font=dict(size=24, color="#FFFFFF"),
        legend=dict(font=dict(size=16, color="#FFFFFF")),
        colorway=[BLUE, GREEN, ORANGE, PURPLE, PINK, CYAN])
    fig.update_xaxes(color="#FFFFFF", gridcolor=grid,
                     title_font=dict(size=18, color="#FFFFFF"),
                     tickfont=dict(size=16, color="#FFFFFF"))
    fig.update_yaxes(color="#FFFFFF", gridcolor=grid,
                     title_font=dict(size=18, color="#FFFFFF"),
                     tickfont=dict(size=16, color="#FFFFFF"))
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def table(data):
    try:
        st.dataframe(data, width="stretch")
    except Exception:
        st.dataframe(data)


def pick(key, default=None):
    i = companies.index(default) if default in companies else 0
    return st.selectbox("Company", companies, index=i, key=key)


def heat(z, x, y, title, scale=None, zmid=0, fmt="%{text}"):
    fig = go.Figure(go.Heatmap(
        z=z.values, x=x, y=y, text=z.round(1).values,
        texttemplate=fmt, textfont=dict(size=17, color=INK),
        colorscale=scale or PASTEL_RDYG, zmid=zmid))
    fig.update_layout(title=title)
    show(fig)
    # ================= PAGES =================
def page_home():
    st.title("STOCKLENS")
    st.subheader("Intelligent Stock Market Analytics")
    st.write("Analyze performance, identify market signals, detect "
             "anomalies and turn historical stock data into business insights.")
    kpis([("📁 Companies", len(companies), BLUE),
          ("📅 Period", f"{df.date.dt.year.min()}–{df.date.dt.year.max()}", CYAN),
          ("📊 Records", f"{len(df):,}", BLUE),
          ("📈 Positive", int((S.Return > 0).sum()), GREEN),
          ("📉 Negative", int((S.Return <= 0).sum()), RED),
          ("⚠️ Anomalies", len(anom), ORANGE)])
    up = int((LAST.close > LAST.ma50).sum())
    mood = up / len(LAST) * 100
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=mood,
        title={"text": "Market Mood: % of stocks above 50-day average"},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": BLUE},
               "steps": [{"range": [0, 33], "color": "#7a3b45"},
                         {"range": [33, 66], "color": "#7a6a2e"},
                         {"range": [66, 100], "color": "#2f6b4c"}]}))
    show(fig, 330)
    cols = ["Return", "Volatility", "MaxDD", "AvgDaily"]
    z = (S[cols] - S[cols].min()) / (S[cols].max() - S[cols].min() + 1e-9)
    fig = go.Figure(go.Heatmap(
        z=z.values, x=["Return %", "Volatility %", "Drawdown %", "Avg Daily %"],
        y=S.index, text=S[cols].round(2).values, texttemplate="%{text}",
        textfont=dict(size=17, color=INK), colorscale=PASTEL_BLUE))
    fig.update_layout(title="Market Performance Heatmap")
    show(fig)
    box("Performance is not the same as stability. A higher return often "
        "comes with higher volatility, so read return, risk and drawdown "
        "together.", BLUE)


def page_perf():
    st.title("Performance Lab")
    st.subheader("How did each company perform?")
    d = df.assign(cum=df.groupby("company").close.transform(
        lambda s: (s / s.iloc[0] - 1) * 100))
    show(px.line(d, x="date", y="cum", color="company",
                 title="Cumulative Return (%)"))
    yr = df.assign(year=df.date.dt.year).groupby(["company", "year"])
    yr = yr.close.agg(["first", "last"])
    pv = ((yr["last"] / yr["first"] - 1) * 100).unstack()
    heat(pv, [str(c) for c in pv.columns], pv.index,
         "Year-by-Year Return (%)", fmt="%{text}%")
    a, b = st.columns(2)
    with a:
        show(px.bar(S, y="AvgDaily", title="Average Daily Return (%)",
                    color_discrete_sequence=[CYAN]), 350)
    with b:
        show(px.bar(S, y="MaxDD", title="Maximum Drawdown (%)",
                    color_discrete_sequence=[RED]), 350)
    bestyr = pv.max().idxmax()
    box(f"Returns change a lot from year to year (best year in the data: "
        f"{bestyr}). Compare cumulative return with volatility to separate "
        "steady growth from unstable performance.", CYAN)


def page_bajaj():
    g = df[df.company == bajaj]
    s = S.loc[bajaj]
    st.title(bajaj.upper())
    st.subheader("Single Stock Intelligence")
    kpis([("Latest Price", f"₹{s.Latest:,.0f}", GREEN),
          ("Total Return", f"{s.Return:.1f}%", GREEN if s.Return > 0 else RED),
          ("Avg Daily Return", f"{s.AvgDaily:.2f}%", BLUE),
          ("Volatility", f"{s.Volatility:.2f}%", ORANGE),
          ("Max Drawdown", f"{s.MaxDD:.1f}%", RED),
          ("Latest Signal", s.Signal, PURPLE)])
    fig = go.Figure([
        go.Scatter(x=g.date, y=g.close, name="Price", line_color=GREEN),
        go.Scatter(x=g.date, y=g.ma20, name="20-day MA", line_color=BLUE),
        go.Scatter(x=g.date, y=g.ma50, name="50-day MA", line_color=ORANGE)])
    fig.update_layout(title="Price Journey + Moving Averages")
    show(fig, 480)
    show(px.bar(g, x="date", y="volume", title="Volume Analysis",
                color_discrete_sequence=[BLUE]), 320)
    ch = g[g.signal != g.signal.shift()]
    st.write("**Signal Timeline:** " + " → ".join(ch.signal.tolist()[:15]))
    box("The page tracks price movement, trend strength, volatility and "
        "signal changes to show how Bajaj Auto behaved over the period.",
        GREEN, "What does the data tell us?")


def page_compare():
    st.title("Company Comparison")
    d = df.assign(inv=df.groupby("company").close.transform(
        lambda s: s / s.iloc[0] * 100))
    show(px.line(d, x="date", y="inv", color="company",
                 title="If ₹100 was invested…"), 480)
    a, b = st.columns(2)
    with a:
        show(px.bar(S, y="Return", title="Return (%)",
                    color_discrete_sequence=[GREEN]), 350)
    with b:
        show(px.bar(S, y="Volatility", title="Volatility (%)",
                    color_discrete_sequence=[ORANGE]), 350)
    sc = S.reset_index()
    show(px.scatter(sc, x="Volatility", y="Return", text="Company",
                    color="Risk", title="Risk vs Return"))
    rd = S[["Return", "Volatility", "AvgDaily", "MaxDD"]].abs()
    rd = rd / rd.max()
    fig = go.Figure([go.Scatterpolar(r=rd.loc[c], theta=rd.columns,
                                     fill="toself", name=c) for c in rd.index])
    fig.update_layout(title="Performance Radar")
    show(fig, 480)
    box("The growth of ₹100 shows what each company delivered per rupee. "
        "Check the risk-return scatter before calling any winner.", BLUE)


def page_tech():
    st.title("SIGNAL ENGINE")
    c = pick("tech", bajaj)
    g = df[df.company == c]
    a, b = st.columns(2)
    a.markdown("### 🟢 Bullish\n- Price above moving average\n"
               "- Golden cross: MA20 above MA50\n- Positive momentum\n\n"
               f"**{(g.signal == 'BUY').sum()} BUY days**")
    b.markdown("### 🔴 Bearish\n- Price below moving average\n"
               "- Death cross: MA20 below MA50\n- Negative momentum\n\n"
               f"**{(g.signal == 'SELL').sum()} SELL days**")
    fig = go.Figure([
        go.Scatter(x=g.date, y=g.close, name="Price", line_color=BLUE),
        go.Scatter(x=g.date, y=g.ma20, name="MA20", line_color=GREEN),
        go.Scatter(x=g.date, y=g.ma50, name="MA50", line_color=ORANGE)])
    show(fig, 450)
    cmap = {"BUY": GREEN, "HOLD": ORANGE, "SELL": RED}
    show(px.scatter(g, x="date", y="signal", color="signal",
                    category_orders={"signal": ["BUY", "HOLD", "SELL"]},
                    color_discrete_map=cmap, title="Signal Timeline"), 280)
    box("Moving-average signals follow trends. They confirm a direction "
        "after it starts and can lag at turning points.", PURPLE)


def page_crash():
    st.title("MARKET STRESS LAB")
    c = pick("crash", bajaj)
    g = df[df.company == c].reset_index(drop=True)
    dd = drawdown(g)
    bot = dd.idxmin()
    peak = g.close[:bot + 1].idxmax()
    after = g.index[(g.index > bot) & (g.close >= g.close[peak])]
    rec = after[0] if len(after) else None
    days = (g.date[bot] - g.date[peak]).days
    rtxt = f"{(g.date[rec] - g.date[bot]).days} days" if rec else "Not yet"
    kpis([("Largest Fall", f"{dd.min() * 100:.1f}%", RED),
          ("Fall Duration", f"{days} days", ORANGE),
          ("Recovery Period", rtxt, BLUE),
          ("Gain from Bottom",
           f"{(g.close.iloc[-1] / g.close[bot] - 1) * 100:.1f}%", GREEN)])
    fig = go.Figure(go.Scatter(x=g.date, y=g.close, fill="tozeroy",
                               line_color=BLUE, name="Price"))
    marks = [(peak, "Peak", GREEN), (bot, "Bottom", RED)]
    if rec is not None:
        marks.append((rec, "Recovery", CYAN))
    for i, lab, col in marks:
        fig.add_trace(go.Scatter(
            x=[g.date[i]], y=[g.close[i]], mode="markers+text", text=[lab],
            textposition="top center", marker=dict(size=15, color=col),
            name=lab))
    fig.update_layout(title="Peak → Crash → Bottom → Recovery")
    show(fig, 480)
    t = S.MaxDD.sort_values()
    box(f"Deepest fall in the group: <b>{t.index[0]}</b> ({t.iloc[0]:.1f}%). "
        "Severity is the size of the drawdown; speed is the days from the "
        "bottom back to the old peak.", RED, "What happened?")


def page_risk():
    st.title("Risk Radar")
    c = pick("risk", bajaj)
    s = S.loc[c]
    g = df[df.company == c]
    kpis([("Volatility Level", s.Risk, ORANGE),
          ("Max Drawdown", f"{s.MaxDD:.1f}%", RED),
          ("Downside Days", s.DownDays, RED),
          ("Daily Volatility", f"{s.Volatility:.2f}%", ORANGE)])
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=s.Volatility,
        title={"text": "Daily Volatility %"},
        gauge={"axis": {"range": [0, S.Volatility.max() * 1.3]},
               "bar": {"color": ORANGE}}))
    show(fig, 330)
    st.subheader("Risk Matrix")
    table(S[["Return", "Volatility", "MaxDD", "Risk"]].round(2))
    st.subheader(f"5 Worst Days: {c}")
    worst = g.nsmallest(5, "ret")[["date", "close", "ret"]].copy()
    worst["ret"] = (worst.ret * 100).round(2)
    table(worst.rename(columns={"ret": "return %"}))
    box("Risk is ranked within this peer group (volatility terciles), "
        "not against the whole market.", ORANGE)


def page_ai():
    st.title("AI MARKET INTERPRETATION")
    c = pick("ai", bajaj)
    s = S.loc[c]
    g = df[df.company == c]
    up = g.close.iloc[-1] > g.ma50.iloc[-1]
    word = "above" if up else "below"
    trend = "an improving" if up else "a weakening"
    flagged = int((anom.company == c).sum())
    box(f"{c} is {word} its 50-day average, latest signal "
        f"<b>{s.Signal}</b>, suggesting {trend} trend.", PURPLE, "🧠 Trend")
    box(f"Total return {s.Return:.1f}% with average daily return "
        f"{s.AvgDaily:.3f}%.", BLUE, "📊 Performance")
    box(f"Volatility {s.Volatility:.2f}% ({s.Risk} in the group) and max "
        f"drawdown {s.MaxDD:.1f}%. Bigger swings come with return potential.",
        ORANGE, "⚠️ Risk")
    box(f"{raw_rows - len(df):,} duplicate or invalid rows were removed; "
        f"{flagged} extreme-return days flagged for {c}.", CYAN,
        "🔍 Data Quality")
    box("Read return together with volatility and drawdown, not alone.",
        GREEN, "💼 Business")
    st.caption("Insights are rule-based text built from the calculated metrics.")


def page_anom():
    st.title("Anomaly Detector")
    c = pick("anom", bajaj)
    g = df[df.company == c].copy()
    g["z"] = g.ret.abs() / g.ret.std()
    g["Type"] = np.where(g.z > 3, "Abnormal return", "Normal")
    vz = (g.volume - g.volume.mean()) / g.volume.std()
    gaps = int((g.date.diff().dt.days > 5).sum())
    kpis([("Abnormal Returns", int((g.z > 3).sum()), ORANGE),
          ("Unusual Volume", int((vz > 3).sum()), ORANGE),
          ("Date Gaps (>5d)", gaps, RED),
          ("Duplicates Removed", f"{raw_rows - len(df):,}", BLUE)])
    show(px.scatter(g, x="date", y="close", color="Type",
                    color_discrete_map={"Normal": BLUE,
                                        "Abnormal return": ORANGE},
                    title="Normal vs Unusual Observations"), 450)
    bullets("Why anomaly detection matters", ORANGE, [
        "Prevents incorrect analysis", "Finds unusual market behaviour",
        "Improves data quality", "Helps validate datasets",
        "Reduces misleading conclusions",
        "Large jumps may be splits or bonuses (corporate actions)"])


def page_strategy():
    st.title("Strategy Simulator")
    a, b, c3 = st.columns(3)
    c = a.selectbox("Company", companies, index=companies.index(bajaj))
    amt = b.number_input("Investment (₹)", 1000, 10000000, 10000, 1000)
    strat = c3.selectbox("Strategy",
                         ["Buy & Hold", "Moving Average", "Signal Based"])
    g = df[df.company == c].reset_index(drop=True)
    if strat == "Buy & Hold":
        pos = pd.Series(1.0, index=g.index)
    elif strat == "Moving Average":
        pos = (g.close > g.ma20).astype(float)
    else:
        state, p = 0.0, []
        for sig in g.signal:
            if sig == "BUY":
                state = 1.0
            elif sig == "SELL":
                state = 0.0
            p.append(state)
        pos = pd.Series(p)
    pos = pos.shift(1).fillna(0)
    eq = amt * (1 + g.ret.fillna(0) * pos).cumprod()
    trades = int(pos.diff().abs().fillna(pos.iloc[0]).sum())
    end = eq.iloc[-1]
    kpis([("Initial", f"₹{amt:,.0f}", BLUE),
          ("Ending Value", f"₹{end:,.0f}", GREEN if end >= amt else RED),
          ("Return", f"{(end / amt - 1) * 100:.1f}%", GREEN),
          ("Trades", trades, PURPLE),
          ("Max Drawdown", f"{(eq / eq.cummax() - 1).min() * 100:.1f}%", RED)])
    bh = amt * g.close / g.close.iloc[0]
    fig = go.Figure([
        go.Scatter(x=g.date, y=eq, name=strat, line_color=GREEN),
        go.Scatter(x=g.date, y=bh, name="Buy & Hold", line_color=BLUE,
                   line_dash="dot")])
    fig.update_layout(title="Portfolio Value")
    show(fig, 450)
    box("Historical backtest only: no fees, taxes or slippage. Past results "
        "do not predict future returns.", GREEN)


def page_score():
    st.title("Stock Scorecard")

    def n(s):
        return (s - s.min()) / (s.max() - s.min() + 1e-9) * 100

    sig = S.Signal.map({"BUY": 100, "HOLD": 50, "SELL": 0})
    cnt = df.groupby("company").size()
    dq = 100 - (anom.groupby("company").size() / cnt * 1000)
    sc = pd.DataFrame({
        "Return": n(S.Return), "Stability": 100 - n(S.Volatility),
        "Momentum": n(S.AvgDaily), "Low Drawdown": 100 - n(-S.MaxDD),
        "Signal Strength": sig,
        "Data Quality": dq.reindex(S.index).fillna(100).clip(0, 100)})
    c = pick("score", bajaj)
    fig = go.Figure(go.Scatterpolar(r=sc.loc[c], theta=sc.columns,
                                    fill="toself", line_color=CYAN))
    fig.update_layout(title=f"{c} Scorecard")
    a, b = st.columns(2)
    with a:
        show(fig, 450)
    with b:
        table(sc.round(0))
    box("Dimensions are scored 0–100 relative to peers and are NOT merged "
        "into one 'best stock' rank. Pick the criterion that fits your "
        "decision.", CYAN)


def page_season():
    st.title("Seasonality Lab")
    st.subheader("Which months were strong or weak?")
    m = df.assign(month=df.date.dt.month).groupby(["company", "month"])
    pv = (m.ret.mean() * 100).unstack()
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    heat(pv, names[:pv.shape[1]], pv.index,
         "Average Daily Return by Month (%)")
    c = pick("season", bajaj)
    row = pv.loc[c]
    best, worst = names[int(row.idxmax()) - 1], names[int(row.idxmin()) - 1]
    kpis([("Strongest Month", best, GREEN), ("Weakest Month", worst, RED)])
    box("Only a few years of data sit behind each month, so treat "
        "patterns as questions to investigate, not rules to trade on.", ORANGE)


def page_corr():
    st.title("Correlation Map")
    st.subheader("Do these stocks move together?")
    wide = df.pivot_table(index="date", columns="company", values="ret")
    cm = wide.corr()
    heat(cm * 100, cm.columns, cm.index, "Return Correlation (x100)",
         scale=PASTEL_BLUE, zmid=None)
    pairs = cm.where(np.triu(np.ones(cm.shape), 1).astype(bool)).stack()
    hi, lo = pairs.idxmax(), pairs.idxmin()
    kpis([("Most Similar Pair", f"{hi[0]} & {hi[1]}", BLUE),
          ("Most Different Pair", f"{lo[0]} & {lo[1]}", PURPLE)])
    box("Stocks with lower correlation spread risk better. Two stocks that "
        "move almost together add less protection when the market falls.",
        BLUE)


def page_time():
    st.title("Time Machine")
    st.subheader("What if you had invested earlier?")
    a, b = st.columns(2)
    amt = a.number_input("Amount (₹)", 1000, 10000000, 10000, 1000)
    first, last = df.date.min().date(), df.date.max().date()
    start = b.date_input("Invest on", first, min_value=first, max_value=last)
    res = []
    for c in companies:
        g = df[(df.company == c) & (df.date >= pd.Timestamp(start))]
        if len(g) > 1:
            res.append((c, amt * g.close.iloc[-1] / g.close.iloc[0]))
    r = pd.DataFrame(res, columns=["Company", "Value"])
    r = r.sort_values("Value", ascending=False)
    r["Gain %"] = ((r.Value / amt - 1) * 100).round(1)
    r["Value"] = r.Value.round(0)
    if len(r):
        kpis([("Best Outcome", r.Company.iloc[0], GREEN),
              ("Its Value", f"₹{r.Value.iloc[0]:,.0f}", GREEN),
              ("Weakest Outcome", r.Company.iloc[-1], RED)])
        show(px.bar(r, x="Company", y="Value",
                    title="Value today of your investment",
                    color_discrete_sequence=[CYAN]), 380)
        table(r)
    box("A backtest shows what happened, not what will happen. Start date "
        "changes the answer a lot.", CYAN)


def page_sql():
    st.title("SQL Analytics")
    st.subheader("The pipeline is SQL-driven")
    ops = ["MERGE", "CLEAN", "DEDUPLICATE", "FILTER", "JOIN", "AGGREGATE"]
    for col, o in zip(st.columns(6), ops):
        col.markdown(f'<div class="kpi" style="--c:{BLUE}"><b>{o}</b></div>',
                     unsafe_allow_html=True)
    st.code(SETUP_SQL, language="sql")
    box("MERGE loads every company file into one table. CLEAN, FILTER and "
        "DEDUPLICATE build <code>prices</code>. Window-function AGGREGATEs "
        "create returns, moving averages and signals.", BLUE)


QUERIES = {
    "Average Price": (
        "SELECT company, ROUND(AVG(close),2) AS avg_price "
        "FROM prices GROUP BY company",
        "Average close shows a typical price level, not performance."),
    "Highest Price": (
        "SELECT company, MAX(high) AS highest FROM prices GROUP BY company",
        "Peak prices mark the top of each stock's range."),
    "Lowest Price": (
        "SELECT company, MIN(low) AS lowest FROM prices GROUP BY company",
        "Lowest prices show the floor reached in the period."),
    "Total Records": (
        "SELECT company, COUNT(*) AS records FROM prices GROUP BY company",
        "Uneven counts can signal missing dates."),
    "Positive Returns": (
        "SELECT company, COUNT(*) AS positive_days FROM metrics "
        "WHERE ret > 0 GROUP BY company",
        "More up-days suggest consistency, not bigger gains."),
    "Negative Returns": (
        "SELECT company, COUNT(*) AS negative_days FROM metrics "
        "WHERE ret < 0 GROUP BY company",
        "Down-day counts feed the downside-risk view."),
    "Stock Comparison": (
        "SELECT company, ROUND(AVG(ret)*100,3) AS avg_daily_pct, "
        "ROUND(SQRT(AVG(ret*ret)-AVG(ret)*AVG(ret))*100,3) AS volatility_pct "
        "FROM metrics GROUP BY company",
        "Average return versus volatility compares reward and risk."),
    "Monthly Performance": (
        "SELECT company, SUBSTR(date,1,7) AS month, "
        "ROUND(AVG(ret)*100,3) AS avg_daily_pct FROM metrics "
        "WHERE company = 'BAJAJ' GROUP BY company, month LIMIT 24",
        "Monthly averages reveal strong or weak stretches."),
    "Signal Analysis": (
        "SELECT company, signal, COUNT(*) AS days FROM metrics "
        "GROUP BY company, signal ORDER BY company",
        "Shows how often each stock was bullish, neutral or bearish."),
    "Data Quality": (
        "SELECT (SELECT COUNT(*) FROM raw_prices) AS raw_rows, "
        "(SELECT COUNT(*) FROM prices) AS clean_rows, "
        "(SELECT COUNT(*) FROM raw_prices)-(SELECT COUNT(*) FROM prices) "
        "AS removed",
        "Removed rows are duplicates or invalid records."),
}
def page_play():
    st.title("SQL Playground")
    q = st.selectbox("Choose Query", list(QUERIES))
    sql = QUERIES[q][0].replace("BAJAJ", bajaj)
    st.code(sql, language="sql")
    table(pd.read_sql(sql, con))
    box(QUERIES[q][1], BLUE, "💬 Business Interpretation")
    with st.expander("Write your own SELECT"):
        own = st.text_area("SQL", "SELECT * FROM metrics LIMIT 10")
        if st.button("Run") and own.strip().lower().startswith("select"):
            try:
                table(pd.read_sql(own, con))
            except Exception as e:
                st.error(e)


def page_reco():
    st.title("Business Recommendations")
    best, calm = S.Return.idxmax(), S.Volatility.idxmin()
    wild, deep = S.Volatility.idxmax(), S.MaxDD.idxmin()
    nb = int((S.Signal == "BUY").sum())
    bullets("📈 Growth", GREEN, [
        f"<b>{best}</b> had the highest return ({S.Return.max():.1f}%); "
        "study what drove it.",
        f"{int((S.Return > 0).sum())} of {len(S)} companies ended positive.",
        "Compare growth year by year, not just the full period."])
    bullets("⚠️ Risk Management", RED, [
        f"<b>{wild}</b> is most volatile; <b>{calm}</b> is steadiest.",
        f"Deepest fall: <b>{deep}</b> at {S.MaxDD.min():.1f}%.",
        "Review drawdown and recovery time next to return."])
    bullets("🧹 Data Management", CYAN, [
        f"{raw_rows - len(df):,} duplicate or invalid rows were removed.",
        f"{len(anom):,} extreme-return days flagged: check corporate actions.",
        "Keep a raw table and build clean tables from it."])
    bullets("📊 Analytics", BLUE, [
        f"{nb} of {len(S)} companies show BUY now; signals are not forecasts.",
        "Read moving averages with volatility and drawdown.",
        "Test signals against Buy & Hold in the simulator."])
    bullets("🤖 Automation", PURPLE, [
        "Schedule the SQL cleaning and metrics build.",
        "Refresh the dashboard when new CSV files arrive.",
        "Add automatic data-quality checks."])
    bullets("🎯 Decision Support", ORANGE, [
        "Use several metrics, not one signal.",
        "Use the Scorecard to see strengths by dimension.",
        "Results are historical and exclude fees and taxes."])


def page_story():
    st.title("Project Story")
    st.subheader("From raw files to business decisions")
    steps = [("raw_prices", raw_rows), ("clean prices", len(df)),
             ("daily returns", int(df.ret.notna().sum())),
             ("BUY / SELL signals", int((df.signal != "HOLD").sum()))]
    fig = go.Figure(go.Funnel(y=[s[0] for s in steps],
                              x=[s[1] for s in steps],
                              marker={"color": [BLUE, CYAN, PURPLE, GREEN]}))
    fig.update_layout(title="Rows at each stage of the pipeline")
    show(fig, 400)
    story = [
        ("1 · Collect", BLUE, "Daily Open, High, Low, Close, Volume for "
         f"{len(companies)} companies."),
        ("2 · Merge", CYAN, "All company files are loaded into one SQLite "
         "table."),
        ("3 · Clean", GREEN, "SQL removes duplicates and invalid rows."),
        ("4 · Calculate", PURPLE, "Window functions create returns, "
         "moving averages and signals."),
        ("5 · Analyse", ORANGE, "Python measures return, volatility, "
         "drawdown, anomalies and scores."),
        ("6 · Decide", RED, "Dashboards turn the numbers into insights "
         "managers can act on.")]
    for t, col, txt in story:
        box(txt, col, t)


def page_about():
    st.title("About Project")
    st.subheader("Created by: Challapalli Mamatha")
    box("Build an interactive stock-market analytics system that combines "
        "SQL data preparation, Python analytics and Streamlit visualization "
        "to turn historical stock data into understandable business "
        "insights.", PURPLE, "Project Objective")
    st.subheader("Dataset")
    st.write(f"**{len(companies)} companies:** " + ", ".join(companies))
    st.subheader("Technology")
    st.write("🐍 Python · 🗃️ SQL / SQLite · 📊 Pandas · 📈 Plotly · "
             "🎨 Streamlit · 📓 Jupyter Notebook · 💻 VS Code")
    bullets("What this project shows", GREEN, [
        "SQL skills: merge, clean, deduplicate, window functions.",
        "Analytics skills: returns, risk, drawdown, anomalies.",
        "Communication skills: an insight under every page."])
    bullets("Limitations", ORANGE, [
        "Historical data only; no fees, taxes or slippage.",
        "Signals are simple moving-average rules.",
        "Not financial advice."])


def page_goal():
    st.title("Business Goal & Objectives")
    st.subheader("Why this project exists")
    box("Help managers understand how historical stock data behaved: which "
        "companies grew, how risky the ride was, and what the signals say, "
        "so decisions rest on evidence instead of intuition.",
        BLUE, "🏆 Main Business Goal")
    bullets("🎯 Business Objectives", GREEN, [
        "Merge and clean data for six companies using SQL.",
        "Measure return, volatility and maximum drawdown for each.",
        "Generate trend signals from moving averages.",
        "Detect anomalies and protect data quality.",
        "Compare companies fairly, side by side.",
        "Test simple strategies against Buy & Hold.",
        "Explain every result in plain business language."])
    bullets("❓ Questions the dashboard answers", PURPLE, [
        "Which company grew the most, and at what risk?",
        "How deep were the falls and how fast was the recovery?",
        "Do moving-average signals beat simply holding?",
        "Can the data be trusted?"])
    kpis([("Rows processed", f"{raw_rows:,}", BLUE),
          ("Rows removed", f"{raw_rows - len(df):,}", ORANGE),
          ("Companies", len(companies), GREEN),
          ("Pages built", len(PAGES), PURPLE)])
    box("Success means a manager can open one page, read one insight and "
        "make a better-informed decision.", CYAN, "✅ Success Measure")


def page_challenges():
    st.title("Challenges & Learnings")
    st.subheader("What was hard, and how it was solved")
    dup = raw_rows - len(df)
    items = [
        ("🧹 Messy raw data", ORANGE,
         f"{dup:,} duplicate or invalid rows had to be found.",
         "SQL GROUP BY and filters build a clean table from the raw one."),
        ("📅 Missing and uneven dates", RED,
         "Gaps between trading days can distort returns.",
         "Gap checks were added to the Anomaly Detector."),
        ("⚡ Extreme price jumps", PURPLE,
         f"{len(anom):,} days looked abnormal.",
         "They are flagged for review, not deleted, because they may be "
         "splits or bonuses."),
        ("⚖️ Fair comparison", BLUE,
         "Return alone hides risk; one 'best stock' rank would mislead.",
         "A multi-dimension scorecard shows the metrics separately."),
        ("📈 Designing signals", GREEN,
         "Moving averages need history before they mean anything.",
         "The first 49 days are marked HOLD until both averages exist."),
        ("🎨 Readable dashboard", CYAN,
         "Dark themes can hide text and chart labels.",
         "White text, soft colors and larger fonts were applied page by "
         "page."),
    ]
    for t, col, problem, fix in items:
        box(f"<b>Problem:</b> {problem}<br><b>Solution:</b> {fix}", col, t)
    bullets("📚 Key learnings", GREEN, [
        "Clean data first; every later number depends on it.",
        "Never read return without volatility and drawdown.",
        "A simple insight under each chart beats a complex chart.",
        "Backtests describe the past and do not promise the future."])


PAGES = {
    "🏠 Market Command Center": (BLUE, page_home),
    "🏆 Business Goal & Objectives": (GREEN, page_goal),
    "🧭 Project Story": (PURPLE, page_story),
    "📊 Performance Lab": (CYAN, page_perf),
    "🔎 Bajaj Auto Explorer": (GREEN, page_bajaj),
    "🏢 Company Comparison": (BLUE, page_compare),
    "📈 Technical Signals": (PURPLE, page_tech),
    "💥 Crash & Recovery Lab": (RED, page_crash),
    "⚠️ Risk Radar": (ORANGE, page_risk),
    "🤖 AI Insights": (PURPLE, page_ai),
    "🚨 Anomaly Detector": (ORANGE, page_anom),
    "🎯 Strategy Simulator": (GREEN, page_strategy),
    "🧮 Stock Scorecard": (CYAN, page_score),
    "📅 Seasonality Lab": (ORANGE, page_season),
    "🔗 Correlation Map": (BLUE, page_corr),
    "⏳ Time Machine": (CYAN, page_time),
    "🗃️ SQL Analytics": (BLUE, page_sql),
    "🧪 SQL Playground": (BLUE, page_play),
    "💡 Business Recommendations": (GREEN, page_reco),
    "🧗 Challenges & Learnings": (ORANGE, page_challenges),
    "👩‍💻 About Project": (PURPLE, page_about),
}

st.sidebar.title("📈 STOCKLENS")
choice = st.sidebar.radio("Navigate", list(PAGES))
st.sidebar.markdown("---\n**Created by Challapalli Mamatha**")
st.sidebar.markdown("`VERSION v5`")
accent, render = PAGES[choice]
theme(accent)
render()
