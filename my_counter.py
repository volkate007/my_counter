import streamlit as st
import sqlite3
import pandas as pd
import os
from datetime import date

# ---------- Путь к БД ----------
if os.path.isdir("/mount/src"):
    DB_PATH = "/tmp/finance.db"
else:
    DB_PATH = "finance.db"

MONTHS_RU = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
]

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


# ============================================================
# РАБОТА С БД
# ============================================================
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                category_id INTEGER,
                description TEXT,
                comment TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        if "comment" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN comment TEXT")


# ---------- Синхронизация категорий ----------
def sync_categories():
    """Приводит категории к DESIRED_CATEGORIES + восстанавливает операции с NULL."""
    with get_conn() as conn:
        # 1) Добавляем или обновляем нужные категории
        for name, t, kws in DESIRED_CATEGORIES:
            row = conn.execute(
                "SELECT id FROM categories WHERE name = ?", (name,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE categories SET type = ?, keywords = ? WHERE name = ?",
                    (t, kws, name)
                )
            else:
                try:
                    conn.execute(
                        "INSERT INTO categories (name, type, keywords) VALUES (?, ?, ?)",
                        (name, t, kws)
                    )
                except sqlite3.IntegrityError:
                    pass

        # 2) id «Другое»-категорий (они точно уже есть после шага 1)
        def get_id(name):
            row = conn.execute(
                "SELECT id FROM categories WHERE name = ?", (name,)
            ).fetchone()
            return row[0] if row else None

        other_expense_id = get_id("Другое (расход)")
        other_income_id = get_id("Другое (доход)")

        # 3) Сначала переназначаем операции ЛИШНИХ категорий на «Другое»,
        #    потом удаляем сами категории.
        all_rows = conn.execute("SELECT id, name, type FROM categories").fetchall()
        for cid, cname, ctype in all_rows:
            if cname in DESIRED_NAMES:
                continue
            target = other_expense_id if ctype == "expense" else other_income_id
            if target is not None:
                conn.execute(
                    "UPDATE transactions SET category_id = ? WHERE category_id = ?",
                    (target, cid)
                )
            conn.execute("DELETE FROM categories WHERE id = ?", (cid,))

        # 4) Восстанавливаем операции с потерянной категорией (category_id IS NULL)
        if other_expense_id is not None:
            conn.execute(
                "UPDATE transactions SET category_id = ? "
                "WHERE category_id IS NULL AND type = 'expense'",
                (other_expense_id,)
            )
        if other_income_id is not None:
            conn.execute(
                "UPDATE transactions SET category_id = ? "
                "WHERE category_id IS NULL AND type = 'income'",
                (other_income_id,)
            )


# ---------- Настройки ----------
def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value))
        )

def get_initial_balance():
    val = get_setting("initial_balance")
    return int(val) if val is not None else None

def set_initial_balance(amount):
    set_setting("initial_balance", int(amount))


# ---------- Категории ----------
def load_categories():
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM categories ORDER BY type, name", conn)

def add_category(name, type_, keywords=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO categories (name, type, keywords) VALUES (?, ?, ?)",
            (name.strip(), type_, keywords.strip().lower())
        )

def delete_category(cat_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))

def get_keywords(cat_id):
    with get_conn() as conn:
        row = conn.execute("SELECT keywords FROM categories WHERE id = ?", (cat_id,)).fetchone()
    if not row or not row[0]:
        return []
    return [kw.strip() for kw in row[0].split(",") if kw.strip()]

def save_keywords(cat_id, keywords_list):
    joined = ",".join(k.strip().lower() for k in keywords_list if k.strip())
    with get_conn() as conn:
        conn.execute("UPDATE categories SET keywords = ? WHERE id = ?", (joined, cat_id))

def add_keyword(cat_id, kw):
    kws = get_keywords(cat_id)
    kw = kw.strip().lower()
    if kw and kw not in kws:
        kws.append(kw)
        save_keywords(cat_id, kws)

def remove_keyword(cat_id, kw):
    kws = get_keywords(cat_id)
    if kw in kws:
        kws.remove(kw)
        save_keywords(cat_id, kws)


def get_other_category(cat_type):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name FROM categories WHERE type = ? AND name LIKE 'Другое%' LIMIT 1",
            (cat_type,)
        ).fetchone()
    return row if row else (None, "Другое")


def match_category(text, cats_df, cat_type):
    text_lower = text.lower()
    all_kw = []
    for _, row in cats_df[cats_df["type"] == cat_type].iterrows():
        if row["name"].startswith("Другое"):
            continue
        for kw in str(row["keywords"]).split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, row["id"], row["name"]))
    all_kw.sort(reverse=True)

    for _, kw, cid, cname in all_kw:
        if kw in text_lower:
            return cid, cname, kw

    other_id, other_name = get_other_category(cat_type)
    return other_id, other_name, None


# ---------- Транзакции ----------
def add_transaction(d, amount, category_id, cat_type, description, comment):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (date, type, amount, category_id, description, comment) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (d.isoformat(), cat_type, int(amount), category_id, description, comment)
        )

def load_transactions():
    with get_conn() as conn:
        return pd.read_sql_query("""
            SELECT t.date, t.type, t.amount,
                   c.name AS category, t.description, t.comment
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            ORDER BY t.date DESC, t.id DESC
        """, conn)


# ---------- Вспомогательные ----------
def month_label(year, month):
    return f"{MONTHS_RU[month - 1].capitalize()} {year}"

def available_months(df):
    if df.empty:
        return []
    dates = pd.to_datetime(df["date"])
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


def render_transactions_table(df_m):
    view = df_m.copy()
    view["date"] = view["date"].apply(fmt_date)

    def signed(row):
        val = int(row["amount"])
        sign = "+" if row["type"] == "income" else "−"
        return f"{sign}{val:,}".replace(",", " ")

    view["amount_str"] = view.apply(signed, axis=1)

    view = view[["date", "amount_str", "category", "description", "comment"]].copy()
    view = view.rename(columns={
        "date": "Дата", "amount_str": "Сумма",
        "category": "Категория", "description": "Описание",
        "comment": "Комментарий"
    })

    types = df_m["type"].tolist()
    sum_col_idx = view.columns.get_loc("Сумма")

    def style_row(row):
        styles = [""] * len(row)
        idx = view.index.get_loc(row.name)
        t = types[idx]
        color = "#1a8f3a" if t == "income" else "#c0392b"
        styles[sum_col_idx] = f"color: {color}; font-weight: 600;"
        return styles

    styled = view.style.apply(style_row, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
init_db()
sync_categories()

st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")

st.markdown("""
<style>
    details > summary {
        font-size: 20px !important;
    }
    details > summary p {
        font-size: 20px !important;
    }
    .metrics-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
        margin-bottom: 4px;
    }
    .metric-cell {
        padding: 0;
        margin: 0;
        line-height: 1.15;
    }
    .mini-metric-label {
        font-size: 14px;
        color: #666;
        margin: 0;
        padding: 0;
    }
    .mini-metric-value {
        font-size: 20px;
        font-weight: 600;
        color: #111;
        margin: 0;
        padding: 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ЭКРАН ПЕРВОГО ЗАПУСКА
# ============================================================
def page_onboarding():
    st.title("👋 Добро пожаловать в учёт финансов")

    st.markdown(
        "Чтобы правильно считать баланс, скажи: **сколько денег у тебя сейчас?**\n\n"
        "Это будет точкой отсчёта. Дальше приложение будет прибавлять доходы "
        "и вычитать расходы от этой суммы."
    )

    with st.form("onboarding"):
        initial = st.number_input(
            "Начальная сумма (₽)",
            min_value=1,
            step=1000,
            format="%d",
            value=None
        )
        submitted = st.form_submit_button("Начать учёт", type="primary")

        if submitted:
            if initial is None:
                st.error("Введи начальную сумму")
            else:
                set_initial_balance(initial)
                st.rerun()


# ============================================================
# СТРАНИЦА: ОПЕРАЦИИ
# ============================================================
def page_operations():
    st.markdown("### 💰 Учёт доходов и расходов")

    cats_df = load_categories()

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
            min_value=1,
            step=10,
            format="%d",
            value=None,
            key=f"amount_{st.session_state.form_key}"
        )
        description = st.text_input(
            "Категория",
            key=f"desc_{st.session_state.form_key}"
        )
        comment = st.text_input(
            "Комментарий",
            key=f"comment_{st.session_state.form_key}"
        )

        matched = None
        if description:
            matched = match_category(description, cats_df, cat_type)
            if matched:
                cid, cname, kw = matched
                if kw:
                    st.success(f"Категория: **{cname}** (по слову «{kw}»)")
                else:
                    st.info(f"Категория: **{cname}** (слово не распознано)")

        if st.button("Добавить", type="primary", use_container_width=True):
            if amount is None:
                st.error("Введи сумму")
            elif not description.strip():
                st.error("Введи категорию")
            else:
                if matched:
                    cid, cname, _ = matched
                else:
                    cid, cname = get_other_category(cat_type)

                add_transaction(op_date, amount, cid, cat_type, description, comment)
                st.session_state.form_key += 1
                st.success(f"Добавлено: {amount} ₽ — {cname}")
                st.rerun()

        st.divider()
        with st.expander("⚙️ Начальный баланс"):
            current_initial = get_initial_balance() or 0
            new_initial = st.number_input(
                "Начальная сумма (₽)",
                min_value=0,
                step=1000,
                format="%d",
                value=int(current_initial),
                key="edit_initial"
            )
            if st.button("Сохранить", use_container_width=True):
                set_initial_balance(new_initial)
                st.success("Сохранено")
                st.rerun()

    df = load_transactions()

    if df.empty:
        st.info("Пока нет ни одной операции. Добавь первую через панель слева 👈")
        return

    initial = get_initial_balance() or 0
    total_income_all = df.loc[df["type"] == "income", "amount"].sum()
    total_expense_all = df.loc[df["type"] == "expense", "amount"].sum()
    current_balance = initial + total_income_all - total_expense_all

    st.metric("💼 Текущий баланс", f"{fmt_money(current_balance)} ₽")

    st.divider()

    months = available_months(df)
    dates = pd.to_datetime(df["date"])

    for idx, (y, m) in enumerate(months):
        mask = (dates.dt.year == y) & (dates.dt.month == m)
        df_m = df[mask]
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
            render_transactions_table(df_m)


# ============================================================
# СТРАНИЦА: КАТЕГОРИИ
# ============================================================
def page_categories():
    st.title("🏷️ Категории и ключевые слова")
    st.caption("Если в операции встретится одно из ключевых слов — она попадёт в эту категорию.")

    cats_df = load_categories()

    with st.expander("➕ Добавить категорию"):
        with st.form("add_cat", clear_on_submit=True):
            new_name = st.text_input("Название")
            new_type = st.radio("Тип", ["Расход", "Доход"], horizontal=True)
            if st.form_submit_button("Создать"):
                if not new_name.strip():
                    st.error("Введи название")
                else:
                    try:
                        add_category(
                            new_name,
                            "expense" if new_type == "Расход" else "income",
                            ""
                        )
                        st.success(f"Категория «{new_name}» добавлена")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Такая категория уже есть")

    st.subheader("Существующие категории")

    for _, row in cats_df.iterrows():
        emoji = "💸" if row["type"] == "expense" else "💵"
        cat_id = row["id"]
        kws = get_keywords(cat_id)

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
                    if c2.button("🗑️", key=f"delkw_{cat_id}_{kw}", help="Удалить слово"):
                        remove_keyword(cat_id, kw)
                        st.rerun()

            with st.form(f"addkw_{cat_id}", clear_on_submit=True):
                c1, c2 = st.columns([4, 1])
                new_kw = c1.text_input(
                    "Новое ключевое слово",
                    label_visibility="collapsed",
                    key=f"newkw_{cat_id}"
                )
                if c2.form_submit_button("➕ Добавить", use_container_width=True):
                    if new_kw.strip():
                        add_keyword(cat_id, new_kw)
                        st.rerun()

            st.divider()

            if st.button("🗑️ Удалить категорию", key=f"delcat_{cat_id}"):
                delete_category(cat_id)
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
