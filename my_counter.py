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
    ("Спорт",       "expense", "соревнования,семинар,аттестация,членский взнос,тренировки"),
    ("Зарплата",    "income",  "100б,судейство,зарплата,аванс,зп"),
    ("Переводы",    "income",  "подарок,от мамы,от папы,от бабушки,от дедушки,от кирилла,от бабушки л."),
    ("Другое",      "both",    ""),
]

DEFAULT_ACCOUNTS = ["Основной", "Спорт", "Зарплата"]

CACHE_TTL = 30
TX_COLUMNS = ["date", "type", "amount", "account", "category", "description", "comment"]
ACC_COLUMNS = ["name", "initial_balance"]


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


# ---------- Категории ----------
def _load_categories_df():
    df = _cached_read("categories", ["name", "type", "keywords"])
    if df.empty:
        return pd.DataFrame(
            [{"name": n, "type": t, "keywords": k} for n, t, k in DESIRED_CATEGORIES]
        )
    df["name"] = df["name"].apply(_normalize_category)
    df = df.drop_duplicates(subset=["name"], keep="first").reset_index(drop=True)
    return df


# ---------- Счета ----------
def _load_accounts_df():
    df = _cached_read("accounts", ACC_COLUMNS)
    if df.empty:
        return pd.DataFrame([
            {"name": a, "initial_balance": 0} for a in DEFAULT_ACCOUNTS
        ])
    df["name"] = df["name"].astype(str).str.strip()
    df = df[df["name"] != ""].reset_index(drop=True)
    df["name"] = df["name"].apply(lambda x: x[:1].upper() + x[1:] if x else x)
    df = df.drop_duplicates(subset=["name"], keep="first").reset_index(drop=True)
    df["initial_balance"] = pd.to_numeric(df["initial_balance"], errors="coerce").fillna(0).astype(int)
    return df


def _save_accounts_df(df):
    conn = get_conn()
    df = df[ACC_COLUMNS].copy().fillna("")
    conn.update(worksheet="accounts", data=df)
    conn.clear()


# ---------- Транзакции ----------
def _load_transactions_df():
    df = _cached_read("transactions", TX_COLUMNS)
    if not df.empty:
        df["category"] = df["category"].apply(_normalize_category)
        df["account"] = df["account"].fillna("").astype(str).str.strip()
        df["account"] = df["account"].apply(lambda x: x[:1].upper() + x[1:] if x else x)

        acc_df = _load_accounts_df()
        default_account = (
            str(acc_df.iloc[0]["name"]) if not acc_df.empty else "Основной"
        )

        df.loc[df["account"] == "", "account"] = default_account

        existing = set(acc_df["name"].astype(str))
        df.loc[~df["account"].isin(existing), "account"] = default_account
    return df


def _append_transaction(d, amount, category_name, cat_type, description, comment, account):
    df = _fresh_read("transactions", TX_COLUMNS)
    new_row = pd.DataFrame([{
        "date": d.isoformat(),
        "type": cat_type,
        "amount": int(amount),
        "account": account,
        "category": category_name,
        "description": description,
        "comment": comment,
    }])
    combined = pd.concat([df, new_row], ignore_index=True)
    conn = get_conn()
    conn.update(worksheet="transactions", data=combined.fillna(""))
    conn.clear()


def _append_transfer(d, amount, from_account, to_account, comment):
    df = _fresh_read("transactions", TX_COLUMNS)
    new_row = pd.DataFrame([{
        "date": d.isoformat(),
        "type": "transfer",
        "amount": int(amount),
        "account": from_account,
        "category": to_account,
        "description": f"перевод на {to_account}",
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


# ---------- Распознавание категорий ----------
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


# ---------- Подсчёт балансов ----------
def compute_account_balances(accounts_df, tx_df):
    balances = {}
    for _, row in accounts_df.iterrows():
        balances[str(row["name"])] = int(row["initial_balance"])

    if tx_df.empty:
        return balances

    for _, tx in tx_df.iterrows():
        t = str(tx["type"])
        amt = int(tx["amount"])
        acc = str(tx.get("account", "") or "")
        if acc not in balances:
            continue

        if t == "income":
            balances[acc] += amt
        elif t == "expense":
            balances[acc] -= amt
        elif t == "transfer":
            balances[acc] -= amt
            target = str(tx.get("category", "") or "")
            if target in balances:
                balances[target] += amt

    return balances


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
    view = day_df.copy().reset_index(drop=True)

    def signed(row):
        val = int(row["amount"])
        t = str(row["type"])
        if t == "income":
            return f"+{val:,}".replace(",", " ")
        else:
            return f"−{val:,}".replace(",", " ")

    view["amount_str"] = view.apply(signed, axis=1)

    for col in ["description", "comment"]:
        view[col] = view[col].fillna("").astype(str)

    view = view[["amount_str", "description", "comment"]]
    view = view.rename(columns={
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


def render_month_blocks(df):
    """Для главной страницы: по месяцам → по дням."""
    if df.empty:
        st.info("Нет операций.")
        return

    df = df[df["type"].isin(["income", "expense"])].copy()
    if df.empty:
        st.info("Нет операций для отображения.")
        return

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)

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


def render_account_operations_table(df):
    """Для страницы «Счета»: единая таблица с колонкой «Дата».
    Без разбиения по месяцам и без метрик."""
    if df.empty:
        st.info("Нет операций по этому счёту.")
        return

    df = df[df["type"].isin(["income", "expense"])].copy()
    if df.empty:
        st.info("Нет операций для отображения.")
        return

    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0).astype(int)
    df["_date_obj"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_date_obj"]).sort_values("_date_obj", ascending=False).reset_index(drop=True)

    def signed(row):
        val = int(row["amount"])
        t = str(row["type"])
        return f"+{val:,}".replace(",", " ") if t == "income" else f"−{val:,}".replace(",", " ")

    df["amount_str"] = df.apply(signed, axis=1)
    df["date_str"] = df["_date_obj"].apply(lambda d: d.strftime("%d.%m.%Y"))

    for col in ["description", "comment"]:
        df[col] = df[col].fillna("").astype(str)

    view = df[["date_str", "amount_str", "description", "comment"]].rename(columns={
        "date_str": "Дата",
        "amount_str": "Сумма",
        "description": "Описание",
        "comment": "Комментарий",
    })

    types = df["type"].tolist()
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
    .acc-tile {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 12px 16px;
        margin: 4px 0;
    }
    .acc-name { font-size: 14px; color: #666; }
    .acc-balance { font-size: 22px; font-weight: 700; color: #111; }
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
                acc_df = _load_accounts_df()
                if "Основной" not in acc_df["name"].tolist():
                    acc_df = pd.concat([
                        acc_df,
                        pd.DataFrame([{"name": "Основной", "initial_balance": initial}])
                    ], ignore_index=True)
                else:
                    acc_df.loc[acc_df["name"] == "Основной", "initial_balance"] = initial
                _save_accounts_df(acc_df)
                set_setting("onboarded", "1")
                st.rerun()


# ============================================================
# СТРАНИЦА: ОПЕРАЦИИ
# ============================================================
def page_operations():
    st.markdown("### 💰 Учёт доходов и расходов")

    cats_df = _load_categories_df()
    acc_df = _load_accounts_df()
    account_names = acc_df["name"].astype(str).tolist()

    df = _load_transactions_df()
    balances = compute_account_balances(acc_df, df)
    total = sum(balances.values())

    st.markdown("#### 💼 Балансы по счетам")

    n_cols = len(account_names) + 1
    cols = st.columns(n_cols)

    for i, acc in enumerate(account_names):
        with cols[i]:
            st.markdown(
                f"""
                <div class="acc-tile">
                    <div class="acc-name">{acc}</div>
                    <div class="acc-balance">{fmt_money(balances.get(acc, 0))} ₽</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    with cols[-1]:
        st.markdown(
            f"""
            <div class="acc-tile" style="background:#eef2ff; border-color:#c7d2fe">
                <div class="acc-name">Итого</div>
                <div class="acc-balance">{fmt_money(total)} ₽</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.divider()

    with st.sidebar:
        st.header("➕ Добавить операцию")

        account = st.selectbox("Счёт", account_names, key="form_account")

        op_kind = st.radio(
            "Действие",
            ["Расход", "Доход", "Перевод"],
            horizontal=True,
            key="form_kind"
        )

        op_date = st.date_input("Дата", value=date.today(), key="form_date")

        if "form_key" not in st.session_state:
            st.session_state.form_key = 0

        amount = st.number_input(
            "Сумма (₽)",
            min_value=1, step=10, format="%d", value=None,
            key=f"amount_{st.session_state.form_key}"
        )

        if op_kind == "Перевод":
            target_options = [a for a in account_names if a != account]
            if not target_options:
                st.warning("Нужно минимум два счёта для перевода")
                target_account = None
            else:
                target_account = st.selectbox(
                    "На счёт", target_options, key="form_target"
                )
            description = ""
            comment = st.text_input(
                "Комментарий", key=f"comment_{st.session_state.form_key}"
            )

            if st.button("Перевести", type="primary", use_container_width=True):
                if amount is None:
                    st.error("Введи сумму")
                elif target_account is None:
                    st.error("Выбери счёт-назначение")
                elif account == target_account:
                    st.error("Счёт-источник и счёт-назначение совпадают")
                else:
                    _append_transfer(
                        op_date, amount, account, target_account,
                        comment.strip().lower()
                    )
                    st.session_state.form_key += 1
                    st.success(f"Переведено: {amount} ₽ → {target_account}")
                    st.rerun()
        else:
            cat_type = "expense" if op_kind == "Расход" else "income"

            description = st.text_input(
                "Категория", key=f"desc_{st.session_state.form_key}"
            )
            comment = st.text_input(
                "Комментарий", key=f"comment_{st.session_state.form_key}"
            )

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

                    matched_name_final, _ = match_category(
                        description_clean, cats_df, cat_type
                    )
                    if not matched_name_final:
                        matched_name_final = "Другое"

                    _append_transaction(
                        op_date, amount, matched_name_final, cat_type,
                        description_clean, comment_clean, account
                    )
                    st.session_state.form_key += 1
                    st.success(f"Добавлено: {amount} ₽ — {matched_name_final}")
                    st.rerun()

    render_month_blocks(df)


# ============================================================
# СТРАНИЦА: КАТЕГОРИИ
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
# СТРАНИЦА: СЧЕТА
# ============================================================
def page_accounts():
    st.title("⚙️ Счета")
    st.caption("Выбери счёт — увидишь только его операции.")

    acc_df = _load_accounts_df()
    tx_df = _load_transactions_df()

    if acc_df.empty:
        st.warning("Нет ни одного счёта.")
        return

    balances = compute_account_balances(acc_df, tx_df)

    account_names = acc_df["name"].astype(str).tolist()

    if "selected_account" not in st.session_state:
        st.session_state.selected_account = account_names[0]

    if st.session_state.selected_account not in account_names:
        st.session_state.selected_account = account_names[0]

    cols = st.columns(len(account_names))
    for i, acc in enumerate(account_names):
        is_selected = (acc == st.session_state.selected_account)
        with cols[i]:
            label = f"{acc}\n\n{fmt_money(balances.get(acc, 0))} ₽"
            btn_type = "primary" if is_selected else "secondary"
            if st.button(label, key=f"acc_btn_{acc}", use_container_width=True, type=btn_type):
                st.session_state.selected_account = acc
                st.rerun()

    st.divider()

    selected = st.session_state.selected_account
    st.markdown(f"#### 📋 Операции по счёту «{selected}»")

    df_acc = tx_df[tx_df["account"] == selected].copy()

    if df_acc.empty:
        st.info(f"По счёту «{selected}» пока нет операций.")
        return

    # Единая таблица — без разбиения по месяцам, без метрик, с колонкой «Дата»
    render_account_operations_table(df_acc)


# ============================================================
# НАВИГАЦИЯ
# ============================================================
if get_setting("onboarded") is None and _load_accounts_df()["initial_balance"].sum() == 0:
    page_onboarding()
else:
    pages = [
        st.Page(page_operations, title="Операции", icon="💰", default=True),
        st.Page(page_accounts, title="Счета", icon="⚙️"),
        st.Page(page_categories, title="Категории", icon="🏷️"),
    ]
    nav = st.navigation(pages, position="sidebar")
    nav.run()
