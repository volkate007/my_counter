import streamlit as st
import pandas as pd
from datetime import date
from streamlit_gsheets import GSheetsConnection

# ---------- Список «правильных» категорий ----------
DESIRED_CATEGORIES = [
    ("Продукты",        "expense", "пятёрочка,пятерочка,магнит,перекресток,лента,ашан,дикси,магнолия,кб,пяторочка,ароматный мир"),
    ("Маркетплейс",     "expense", "вб,wb,вайлдберриз,wildberries,озон,ozon,яндекс маркет,зя,золотое яблоко"),
    ("Еда",             "expense", "мак,унифуд,столовая,теремок,кфс,бургеркинг"),
    ("Транспорт",       "expense", "проездной,тройка,стрелка,метро,автобус"),
    ("Спорт",           "expense", "соревнования,семинар,аттестация"),
    ("Зарплата",        "income",  "100б,судейство,зарплата,аванс,зп"),
    ("Переводы",        "income",  "подарок,от мамы,от папы,от бабушки,от дедушки,от кирилла,от бабушки л."),
    ("Другое (расход)", "expense", ""),
    ("Другое (доход)",  "income",  ""),
]
DESIRED_NAMES = {c[0] for c in DESIRED_CATEGORIES}

# TTL кэша чтения из Google Sheets (в секундах).
# Меньше — свежее данные, но больше запросов к API.
# 60 секунд — баланс между свежестью и лимитами.
CACHE_TTL = 60


# ============================================================
# ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS
# ============================================================
@st.cache_resource
def get_conn():
    return st.connection("gsheets", type=GSheetsConnection)


def _invalidate_cache():
    """Сбрасывает кэш чтения, чтобы следующий read пошёл в Google."""
    get_conn().clear()


def _read_sheet(worksheet, columns):
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
    return _read_sheet("categories", ["name", "type", "keywords"])


def _load_transactions_df():
    return _read_sheet("transactions", ["date", "type", "amount", "category", "description", "comment"])


def _save_categories_df(df):
    conn = get_conn()
    conn.update(worksheet="categories", data=df)
    _invalidate_cache()


def _append_transaction(d, amount, category_name, cat_type, description, comment):
    conn = get_conn()
    existing = _load_transactions_df()
    new_row = pd.DataFrame([{
        "date": d.isoformat(),
        "type": cat_type,
        "amount": int(amount),
        "category": category_name,
        "description": description,
        "comment": comment,
    }])
    combined = pd.concat([existing, new_row], ignore_index=True)
    conn.update(worksheet="transactions", data=combined)
    _invalidate_cache()


# ---------- Настройки ----------
def get_setting(key, default=None):
    df = _read_sheet("settings", ["key", "value"])
    if df.empty:
        return default
    row = df[df["key"].astype(str) == str(key)]
    return row.iloc[0]["value"] if not row.empty else default


def set_setting(key, value):
    conn = get_conn()
    df = _read_sheet("settings", ["key", "value"])

    df["key"] = df["key"].astype(str)
    df["value"] = df["value"].astype(str)

    mask = df["key"] == str(key)
    if mask.any():
        df.loc[mask, "value"] = str(value)
    else:
        df = pd.concat(
            [df, pd.DataFrame([{"key": str(key), "value": str(value)}])],
            ignore_index=True
        )

    conn.update(worksheet="settings", data=df)
    _invalidate_cache()


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


# ---------- Синхронизация категорий ----------
def _find_category_by_text(text, categories):
    """categories — список (name, keywords). Ищет по ключам."""
    text_lower = (text or "").lower()
    all_kw = []
    for cname, kws in categories:
        if cname.startswith("Другое"):
            continue
        for kw in str(kws).split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, cname))
    all_kw.sort(reverse=True)
    for _, kw, cname in all_kw:
        if kw in text_lower:
            return cname
    return None


def _get_type_for(name, cats_df):
    row = cats_df[cats_df["name"] == name]
    return row.iloc[0]["type"] if not row.empty else None


def match_category(text, cats_df, cat_type):
    text_lower = text.lower()
    all_kw = []
    for _, row in cats_df.iterrows():
        if row["name"].startswith("Другое") or row["type"] != cat_type:
            continue
        for kw in str(row["keywords"]).split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, row["name"]))
    all_kw.sort(reverse=True)
    for _, kw, cname in all_kw:
        if kw in text_lower:
            return cname, kw
    return None, None


def sync_categories():
    """Синхронизирует категории и пересчитывает все операции по ключам.
    Запускается один раз за сессию."""
    conn = get_conn()

    cats_df = _load_categories_df()
    for col in ["name", "type", "keywords"]:
        if col not in cats_df.columns:
            cats_df[col] = ""

    existing = {str(row["name"]) for _, row in cats_df.iterrows()}

    for name, t, kws in DESIRED_CATEGORIES:
        if name in existing:
            cats_df.loc[cats_df["name"] == name, "type"] = t
            cats_df.loc[cats_df["name"] == name, "keywords"] = kws
        else:
            cats_df = pd.concat([
                cats_df,
                pd.DataFrame([{"name": name, "type": t, "keywords": kws}])
            ], ignore_index=True)

    cats_df = cats_df[cats_df["name"].isin(DESIRED_NAMES)].reset_index(drop=True)
    _save_categories_df(cats_df)

    ops_df = _load_transactions_df()
    if not ops_df.empty and "description" in ops_df.columns:
        cat_list = [(row["name"], row["keywords"]) for _, row in cats_df.iterrows()]
        other_exp = "Другое (расход)"
        other_inc = "Другое (доход)"

        def recategorize(row):
            candidates = []
            for n, k in cat_list:
                if n.startswith("Другое"):
                    continue
                if _get_type_for(n, cats_df) == row["type"]:
                    candidates.append((n, k))
            found = _find_category_by_text(row.get("description", ""), candidates)
            if found:
                return found
            return other_exp if row["type"] == "expense" else other_inc

        ops_df["category"] = ops_df.apply(recategorize, axis=1)
        conn.update(worksheet="transactions", data=ops_df)
        _invalidate_cache()


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


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")

# sync_categories — один раз за сессию (иначе много запросов к Google)
if "synced" not in st.session_state:
    sync_categories()
    st.session_state.synced = True

st.markdown("""
<style>
    details > summary { font-size: 20px !important; }
    details > summary p { font-size: 20px !important; }
    .metrics-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px; }
    .metric-cell { padding: 0; margin: 0; line-height: 1.15; }
    .mini-metric-label { font-size: 14px; color: #666; margin: 0; padding: 0; }
    .mini-metric-value { font-size: 20px; font-weight: 600; color: #111; margin: 0; padding: 0; }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ЭКРАН ПЕРВОГО ЗАПУСКА
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
# СТРАНИЦА: ОПЕРАЦИИ
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
                    st.info(f"Категория: **{matched_name}**")
            else:
                other = "Другое (расход)" if is_expense else "Другое (доход)"
                st.info(f"Категория: **{other}** (слово не распознано)")

        if st.button("Добавить", type="primary", use_container_width=True):
            if amount is None:
                st.error("Введи сумму")
            elif not description.strip():
                st.error("Введи категорию")
            else:
                if not matched_name:
                    matched_name = "Другое (расход)" if is_expense else "Другое (доход)"
                _append_transaction(op_date, amount, matched_name, cat_type, description, comment)
                st.session_state.form_key += 1
                st.success(f"Добавлено: {amount} ₽ — {matched_name}")
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

            view = df_m.copy()
            view["date"] = view["date"].apply(fmt_date)

            def signed(row):
                val = int(row["amount"])
                sign = "+" if row["type"] == "income" else "−"
                return f"{sign}{val:,}".replace(",", " ")

            view["amount_str"] = view.apply(signed, axis=1)
            view = view[["date", "amount_str", "category", "description", "comment"]]
            view = view.rename(columns={
                "date": "Дата", "amount_str": "Сумма", "category": "Категория",
                "description": "Описание", "comment": "Комментарий"
            })

            types = df_m["type"].tolist()
            sum_col_idx = view.columns.get_loc("Сумма")

            def style_row(row):
                styles = [""] * len(row)
                idx2 = view.index.get_loc(row.name)
                t = types[idx2]
                color = "#1a8f3a" if t == "income" else "#c0392b"
                styles[sum_col_idx] = f"color: {color}; font-weight: 600;"
                return styles

            st.dataframe(view.style.apply(style_row, axis=1), use_container_width=True, hide_index=True)


# ============================================================
# СТРАНИЦА: КАТЕГОРИИ
# ============================================================
def page_categories():
    st.title("🏷️ Категории и ключевые слова")
    st.caption("Если в операции встретится одно из ключевых слов — она попадёт в эту категорию.")

    cats_df = _load_categories_df()

    with st.expander("➕ Добавить категорию"):
        with st.form("add_cat", clear_on_submit=True):
            new_name = st.text_input("Название")
            new_type = st.radio("Тип", ["Расход", "Доход"], horizontal=True)
            if st.form_submit_button("Создать"):
                if not new_name.strip():
                    st.error("Введи название")
                else:
                    cats_df = pd.concat([cats_df, pd.DataFrame([{
                        "name": new_name.strip(),
                        "type": "expense" if new_type == "Расход" else "income",
                        "keywords": ""
                    }])], ignore_index=True)
                    _save_categories_df(cats_df)
                    st.success(f"Категория «{new_name}» добавлена")
                    st.rerun()

    st.subheader("Существующие категории")

    for _, row in cats_df.iterrows():
        emoji = "💸" if row["type"] == "expense" else "💵"
        kws = [kw.strip() for kw in str(row["keywords"]).split(",") if kw.strip()]

        with st.expander(f"{emoji} {row['name']}  ·  {len(kws)} слов"):
            st.markdown("**Ключевые слова**")
            if not kws:
                st.caption("Пока нет ключевых слов — добавь ниже.")
            else:
                for kw in kws:
                    c1, c2 = st.columns([10, 1])
                    c1.markdown(
                        f"<div style='padding:4px 10px; background:#f0f2f6; "
                        f"border-radius:8px; display:inline-block'>{kw}</div>",
                        unsafe_allow_html=True
                    )
                    if c2.button("🗑️", key=f"delkw_{row['name']}_{kw}"):
                        new_kws = [k for k in kws if k != kw]
                        cats_df.loc[cats_df["name"] == row["name"], "keywords"] = ",".join(new_kws)
                        _save_categories_df(cats_df)
                        st.rerun()

            with st.form(f"addkw_{row['name']}", clear_on_submit=True):
                c1, c2 = st.columns([4, 1])
                new_kw = c1.text_input("Новое ключевое слово", label_visibility="collapsed")
                if c2.form_submit_button("➕ Добавить", use_container_width=True):
                    if new_kw.strip() and new_kw.strip().lower() not in kws:
                        kws.append(new_kw.strip().lower())
                        cats_df.loc[cats_df["name"] == row["name"], "keywords"] = ",".join(kws)
                        _save_categories_df(cats_df)
                        st.rerun()

            st.divider()
            if st.button("🗑️ Удалить категорию", key=f"delcat_{row['name']}"):
                cats_df = cats_df[cats_df["name"] != row["name"]].reset_index(drop=True)
                _save_categories_df(cats_df)
                st.rerun()


# ============================================================
# НАВИГАЦИЯ (МЕНЮ)
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
