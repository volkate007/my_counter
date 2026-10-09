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

        cur = conn.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            default_categories = [
                ("Продукты",    "expense", "пятёрочка,пятерочка,магнит,перекресток,лента,ашан,продукты,еда"),
                ("Маркетплейс", "expense", "вб,wb,вайлдберриз,wildberries,озон,ozon,яндекс маркет,маркет"),
                ("Транспорт",   "expense", "метро,автобус,такси,яндекс такси,бензин,заправка,каршеринг"),
                ("Жильё",       "expense", "квартира,аренда,жкх,коммуналка,электричество,газ,вода"),
                ("Развлечения", "expense", "кино,театр,концерт,игры,steam,netflix"),
                ("Здоровье",    "expense", "аптека,врач,клиника,стоматолог,лекарства"),
                ("Одежда",      "expense", "одежда,обувь,h&m,zara,uniqlo"),
                ("Подписки",    "expense", "подписка,spotify,яндекс плюс,подписки"),
                ("Зарплата",    "income",  "зарплата,аванс,зп"),
                ("Фриланс",     "income",  "фриланс,заказ,проект,гонорар"),
                ("Подарки",     "income",  "подарок,подарили"),
            ]
            conn.executemany(
                "INSERT INTO categories (name, type, keywords) VALUES (?, ?, ?)",
                default_categories
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

def match_category(text, cats_df, cat_type):
    text_lower = text.lower()
    all_kw = []
    for _, row in cats_df[cats_df["type"] == cat_type].iterrows():
        for kw in str(row["keywords"]).split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, row["id"], row["name"]))
    all_kw.sort(reverse=True)

    for _, kw, cid, cname in all_kw:
        if kw in text_lower:
            return cid, cname, kw
    return None


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
            SELECT t.id, t.date, t.type, t.amount,
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


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
init_db()

st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")


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
# КОМПОНЕНТ: плашка месяца
# ============================================================
def render_month_block(y, m, df_m):
    """Рисует заголовок месяца с выровненными справа суммами и раскрывающийся список операций."""

    key_open = f"month_open_{y}_{m}"
    if key_open not in st.session_state:
        st.session_state[key_open] = False  # по умолчанию все свёрнуты

    m_income = df_m.loc[df_m["type"] == "income", "amount"].sum()
    m_expense = df_m.loc[df_m["type"] == "expense", "amount"].sum()

    # ---------- Заголовок: 3 колонки ----------
    # [месяц]  [суммы справа]  [кнопка раскрытия]
    c_title, c_sums, c_btn = st.columns([6, 3, 1])

    with c_title:
        st.markdown(
            f"<div style='padding-top:8px; font-size:1.05rem; font-weight:600'>"
            f"📅 {month_label(y, m)}</div>",
            unsafe_allow_html=True
        )

    with c_sums:
        st.markdown(
            f"<div style='padding-top:8px; text-align:right; white-space:nowrap'>"
            f"💵 +{fmt_money(m_income)} ₽&nbsp;&nbsp;&nbsp;"
            f"💸 −{fmt_money(m_expense)} ₽"
            f"</div>",
            unsafe_allow_html=True
        )

    with c_btn:
        icon = "▼" if st.session_state[key_open] else "▶"
        if st.button(icon, key=f"toggle_{y}_{m}", use_container_width=True):
            st.session_state[key_open] = not st.session_state[key_open]
            st.rerun()

    # ---------- Содержимое ----------
    if st.session_state[key_open]:
        with st.container(border=True):
            view = df_m.copy()
            view["type"] = view["type"].map({"income": "Доход", "expense": "Расход"})
            view = view.rename(columns={
                "id": "ID", "date": "Дата", "type": "Тип",
                "amount": "Сумма", "category": "Категория",
                "description": "Описание", "comment": "Комментарий"
            })
            st.dataframe(view, use_container_width=True, hide_index=True)

    # Тонкий разделитель между месяцами
    st.markdown(
        "<hr style='margin:4px 0 12px 0; border:none; border-top:1px solid #e5e7eb'>",
        unsafe_allow_html=True
    )


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
        amount = st.number_input(
            "Сумма (₽)",
            min_value=1,
            step=10,
            format="%d",
            value=None
        )
        description = st.text_input("Категория")
        comment = st.text_input("Комментарий")

        matched = None
        if description:
            matched = match_category(description, cats_df, cat_type)

        if matched:
            cid, cname, kw = matched
            st.success(f"Категория: **{cname}** (по слову «{kw}»)")
        elif description:
            st.warning("⚠️ Категория не распознана")

        if st.button("Добавить", type="primary", use_container_width=True):
            if amount is None:
                st.error("Введи сумму")
            elif not description.strip():
                st.error("Введи категорию")
            elif not matched:
                st.error(
                    "Не удалось определить категорию. "
                    "Добавь нужное слово в разделе «🏷️ Категории»."
                )
            else:
                cid, cname, _ = matched
                add_transaction(op_date, amount, cid, cat_type, description, comment)
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

    # ===== ТЕКУЩИЙ БАЛАНС =====
    initial = get_initial_balance() or 0
    total_income_all = df.loc[df["type"] == "income", "amount"].sum()
    total_expense_all = df.loc[df["type"] == "expense", "amount"].sum()
    current_balance = initial + total_income_all - total_expense_all

    st.metric("💼 Текущий баланс", f"{fmt_money(current_balance)} ₽")

    st.divider()

    # ===== СПИСОК МЕСЯЦЕВ =====
    months = available_months(df)
    dates = pd.to_datetime(df["date"])

    for y, m in months:
        mask = (dates.dt.year == y) & (dates.dt.month == m)
        df_m = df[mask]
        render_month_block(y, m, df_m)


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
