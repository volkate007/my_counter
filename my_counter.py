import streamlit as st
import pandas as pd
from datetime import date
from streamlit_gsheets import GSheetsConnection

# ============================================================
# КАТЕГОРИИ — ИСТОЧНИК ПРАВДЫ
# ============================================================
DESIRED_CATEGORIES = [
    ("Продукты",    "expense", "пятёрочка,пятерочка,магнит,перекресток,лента,ашан,дикси,магнолия,кб,пяторочка,ароматный мир"),
    ("Маркетплейс", "expense", "вб,wb,вайлдберриз,wildberries,озон,ozon,яндекс маркет,зя,золотое яблоко"),
    ("Еда",         "expense", "мак,унифуд,столовая,теремок,кфс,бургеркинг"),
    ("Транспорт",   "expense", "проездной,тройка,стрелка,метро,автобус"),
    ("Спорт",       "expense", "соревнования,семинар,аттестация"),
    ("Зарплата",    "income",  "100б,судейство,зарплата,аванс,зп"),
    ("Переводы",    "income",  "подарок,от мамы,от папы,от бабушки,от дедушки,от кирилла,от бабушки л."),
    ("Другое",      "both",    ""),
]

CACHE_TTL = 30
TX_COLUMNS = ["date", "type", "amount", "category", "description", "comment"]


# ============================================================
# ПОДКЛЮЧЕНИЕ
# ============================================================
@st.cache_resource
def get_conn():
    return st.connection("gsheets", type=GSheetsConnection)


def _normalize_category(cat):
    if cat is None:
        return ""
    cat = str(cat).strip()
    if cat.lower().startswith("другое"):
        return "Другое"
    return cat


def _fresh_read(worksheet, columns):
    conn = get_conn()
    df = conn.read(worksheet=worksheet, ttl=0)
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.dropna(how="all").reset_index(drop=True)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df


def _cached_read(worksheet, columns):
    conn = get_conn()
    df = conn.read(worksheet=worksheet, ttl=CACHE_TTL)
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.dropna(how="all").reset_index(drop=True)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df


def _load_categories_df():
    df = _cached_read("categories", ["name", "type", "keywords"])
    if df.empty:
        return pd.DataFrame(
            [{"name": n, "type": t, "keywords": k} for n, t, k in DESIRED_CATEGORIES]
        )
    df["name"] = df["name"].apply(_normalize_category)
    df = df.drop_duplicates(subset=["name"], keep="first").reset_index(drop=True)
    return df


def _load_transactions_df():
    df = _cached_read("transactions", TX_COLUMNS)
    if not df.empty:
        df["category"] = df["category"].apply(_normalize_category)
    return df


def _append_transaction(d, amount, category_name, cat_type, description, comment):
    df = _fresh_read("transactions", TX_COLUMNS)
    new_row = pd.DataFrame([{
        "date": d.isoformat(),
        "type": cat_type,
        "amount": int(amount),
        "category": category_name,
        "description": description,
        "comment": comment,
    }])
    combined = pd.concat([df, new_row], ignore_index=True)
    conn = get_conn()
    conn.update(worksheet="transactions", data=combined.fillna(""))
    conn.clear()


# ---------- Настройки ----------
def get_setting(key, default=None):
    df = _cached_read("settings", ["key", "value"])
    if df.empty:
        return default
    row = df[df["key"].astype(str) == str(key)]
    return row.iloc[0]["value"] if not row.empty else default


def set_setting(key, value):
    conn = get_conn()
    df = _fresh_read("settings", ["key", "value"])
    df["key"] = df["key"].astype(str)
    df["value"] = df["value"].astype(str)
    mask = df["key"] == str(key)
    if mask.any():
        df.loc[mask, "value"] = str(value)
    else:
        df = pd.concat([df, pd.DataFrame([{"key": str(key), "value": str(value)}])], ignore_index=True)
    conn.update(worksheet="settings", data=df)
    conn.clear()


def get_initial_balance():
    val = get_setting("initial_balance")
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def set_initial_balance(amount):
    set_setting("initial_balance", str(int(amount)))


# ---------- Распознавание ----------
def match_category(text, cats_df, cat_type):
    text_lower = (text or "").lower()
    all_kw = []
    for _, row in cats_df.iterrows():
        name = str(row["name"])
        row_type = str(row["type"])

        if name == "Другое":
            continue
        if row_type != cat_type and row_type != "both":
            continue

        for kw in str(row["keywords"]).split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, name))

    all_kw.sort(reverse=True)
    for _, kw, cname in all_kw:
        if kw in text_lower:
            return cname, kw

    return "Другое", None


# ---------- Вспомогательные ----------
def month_label(year, month):
    months = ["январь", "февраль", "март", "апрель", "май", "июнь",
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    return f"{months[month - 1].capitalize()} {year}"


def available_months(df):
    if df.empty:
        return []
    dates = pd.to_datetime(df["date"], errors="coerce")
    periods = dates.dt.to_period("M").dropna().unique()
    periods = sorted(periods, reverse=True)
    return [(p.year, p.month) for p in periods]


def fmt_money(x):
    return f"{int(x):,}".replace(",", " ")


def fmt_date(iso_date):
    try:
        d = pd.to_datetime(iso_date)
        return d.strftime("%d.%m.%Y")
    except Exception:
        return iso_date


def render_day_table(day_df):
    """Таблица операций за день. Колонка «Категория» НЕ отображается,
    но остаётся в данных (и в Google Sheets)."""
    view = day_df.copy().reset_index(drop=True)

    view["date_str"] = view["date"].apply(fmt_date)

    def signed(row):
        val = int(row["amount"])
        sign = "+" if row["type"] == "income" else "−"
        return f"{sign}{val:,}".replace(",", " ")

    view["amount_str"] = view.apply(signed, axis=1)

    # Пустые значения — пустая строка
    for col in ["description", "comment"]:
        view[col] = view[col].fillna("").astype(str)

    # Колонки для отображения: без category
    view = view[["date_str", "amount_str", "description", "comment"]]
    view = view.rename(columns={
        "date_str": "Дата",
        "amount_str": "Сумма",
        "description": "Описание",
        "comment": "Комментарий",
    })

    types = day_df.reset_index(drop=True)["type"].tolist()
    sum_col_idx = view.columns.get_loc("Сумма")

    def style_row(row):
        styles = [""] * len(row)
        i = view.index.get_loc(row.name)
        t = types[i]
        color = "#1a8f3a" if t == "income" else "#c0392b"
        styles[sum_col_idx] = f"color: {color}; font-weight: 600;"
        return styles

    styled = view.style.apply(style_row, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")

st.markdown("""
<style>
    details > summary { font-size: 20px !important; }
    details > summary p { font-size: 20px !important; }
    .metrics-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
    .metric-cell { padding: 0; margin: 0; line-height: 1.15; }
    .mini-metric-label { font-size: 14px; color: #666; margin: 0; padding: 0; }
    .mini-metric-value { font-size: 20px; font-weight: 600; color: #111; margin: 0; padding: 0; }
    .day-header {
        font-size: 16px;
        font-weight: 600;
        color: #333;
        margin: 12px 0 6px 0;
        padding: 4px 0;
        border-bottom: 1px solid #e5e7eb;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ОНБОРДИНГ
# ============================================================
def page_onboarding():
    st.title("👋 Добро пожаловать в учёт финансов")
    st.markdown("Скажи: **сколько денег у тебя сейчас?** Это будет точкой отсчёта.")

    with st.form("onboarding"):
        initial = st.number_input(
            "Начальная сумма (₽)",
            min_value=1, step=1000, format="%d", value=None
        )
        submitted = st.form_submit_button("Начать учёт", type="primary")

        if submitted:
            if initial is None:
                st.error("Введи начальную сумму")
            else:
                set_initial_balance(int(initial))
                st.rerun()


# ============================================================
# ОПЕРАЦИИ
# ============================================================
def page_operations():
    st.markdown("### 💰 Учёт доходов и расходов")

    cats_df = _load_categories_df()

    with st.sidebar:
        op_type = st.radio("Тип операции", ["Расход", "Доход"], horizontal=True)
        is_expense = op_type == "Расход"
        cat_type = "expense" if is_expense else "income"

        st.header(f"➕ Добавить {'расход' if is_expense else 'доход'}")
        op_date = st.date_input("Дата", value=date.today())

        if "form_key" not in st.session_state:
            st.session_state.form_key = 0

        amount = st.number_input(
            "Сумма (₽)",
            min_value=1, step=10, format="%d", value=None,
            key=f"amount_{st.session_state.form_key}"
        )
        description = st.text_input("Категория", key=f"desc_{st.session_state.form_key}")
        comment = st.text_input("Комментарий", key=f"comment_{st.session_state.form_key}")

        matched_name, matched_kw = None, None
        if description:
            matched_name, matched_kw = match_category(description, cats_df, cat_type)
            if matched_name:
                if matched_kw:
                    st.success(f"Категория: **{matched_name}** (по слову «{matched_kw}»)")
                else:
                    st.info(f"Категория: **{matched_name}** (слово не распознано)")

        if st.button("Добавить", type="primary", use_container_width=True):
            if amount is None:
                st.error("Введи сумму")
            elif not description.strip():
                st.error("Введи категорию")
            else:
                description_clean = description.strip().lower()
                comment_clean = comment.strip().lower()

                matched_name_final, _ = match_category(description_clean, cats_df, cat_type)
                if not matched_name_final:
                    matched_name_final = "Другое"

                _append_transaction(
                    op_date, amount, matched_name_final, cat_type,
                    description_clean, comment_clean
                )
                st.session_state.form_key += 1
                st.success(f"Добавлено: {amount} ₽ — {matched_name_final}")
                st.rerun()

        st.divider()
        with st.expander("⚙️ Начальный баланс"):
            current_initial = get_initial_balance() or 0
            new_initial = st.number_input(
                "Начальная сумма (₽)",
                min_value=0, step=1000, format="%d",
                value=int(current_initial),
                key="edit_initial"
            )
            if st.button("Сохранить", use_container_width=True):
                set_initial_balance(int(new_initial))
                st.success("Сохранено")
                st.rerun()

    df = _load_transactions_df()

    if df.empty:
        st.info("Пока нет ни одной операции. Добавь первую через панель слева 👈")
        return

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)

    initial = get_initial_balance() or 0
    total_income_all = df.loc[df["type"] == "income", "amount"].sum()
    total_expense_all = df.loc[df["type"] == "expense", "amount"].sum()
    current_balance = initial + total_income_all - total_expense_all

    st.metric("💼 Текущий баланс", f"{fmt_money(current_balance)} ₽")
    st.divider()

    months = available_months(df)
    dates = pd.to_datetime(df["date"], errors="coerce")

    for idx, (y, m) in enumerate(months):
        mask = (dates.dt.year == y) & (dates.dt.month == m)
        df_m = df[mask].copy()
        m_income = df_m.loc[df_m["type"] == "income", "amount"].sum()
        m_expense = df_m.loc[df_m["type"] == "expense", "amount"].sum()

        label = f"📅 {month_label(y, m)}"
        is_first = (idx == 0)
        with st.expander(label, expanded=is_first):
            st.markdown(
                f"""
                <div class="metrics-row">
                    <div class="metric-cell">
                        <div class="mini-metric-label">💵 Доходы</div>
                        <div class="mini-metric-value">+{fmt_money(m_income)} ₽</div>
                    </div>
                    <div class="metric-cell">
                        <div class="mini-metric-label">💸 Расходы</div>
                        <div class="mini-metric-value">−{fmt_money(m_expense)} ₽</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            st.divider()

            df_m["_date_obj"] = pd.to_datetime(df_m["date"], errors="coerce")
            unique_dates = sorted(df_m["_date_obj"].dropna().unique(), reverse=True)

            for d in unique_dates:
                day_df = df_m[df_m["_date_obj"] == d].copy()

                st.markdown(
                    f"<div class='day-header'>📆 {pd.Timestamp(d).strftime('%d.%m.%Y')}</div>",
                    unsafe_allow_html=True
                )
                render_day_table(day_df)


# ============================================================
# КАТЕГОРИИ (только просмотр)
# ============================================================
def page_categories():
    st.title("🏷️ Категории и ключевые слова")
    st.caption(
        "Категории заданы в коде (переменная `DESIRED_CATEGORIES`). "
        "Чтобы что-то изменить — отредактируй код и перезапусти приложение."
    )

    cats_df = _load_categories_df()

    if cats_df.empty:
        st.warning("Категории не найдены.")
        return

    for _, row in cats_df.iterrows():
        name = str(row["name"])
        row_type = str(row["type"])

        if row_type == "expense":
            emoji = "💸"
        elif row_type == "income":
            emoji = "💵"
        else:
            emoji = "🔹"

        kws = [kw.strip() for kw in str(row["keywords"]).split(",") if kw.strip()]

        with st.expander(f"{emoji} {name}  ·  {len(kws)} слов"):
            if not kws:
                st.caption("Нет ключевых слов.")
            else:
                for kw in kws:
                    st.markdown(
                        f"<div style='padding:4px 10px; background:#f0f2f6; "
                        f"border-radius:8px; display:inline-block; margin:2px 0'>{kw}</div>",
                        unsafe_allow_html=True
                    )


# ============================================================
# НАВИГАЦИЯ
# ============================================================
if get_initial_balance() is None:
    page_onboarding()
else:
    pages = [
        st.Page(page_operations, title="Операции", icon="💰", default=True),
        st.Page(page_categories, title="Категории", icon="🏷️"),
    ]
    nav = st.navigation(pages, position="sidebar")
    nav.run()
