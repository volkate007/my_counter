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
                keywords TEXT NOT NULL DEFAULT '',
                is_default INTEGER NOT NULL DEFAULT 0
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

        # Миграция: если таблица transactions уже была без колонки comment — добавляем её
        cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
        if "comment" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN comment TEXT")

        cur = conn.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            default_categories = [
                ("Продукты",    "expense", "пятёрочка,пятерочка,магнит,перекресток,лента,ашан,продукты,еда", 1),
                ("Маркетплейс", "expense", "вб,wb,вайлдберриз,wildberries,озон,ozon,яндекс маркет,маркет", 1),
                ("Транспорт",   "expense", "метро,автобус,такси,яндекс такси,бензин,заправка,каршеринг", 1),
                ("Жильё",       "expense", "квартира,аренда,жкх,коммуналка,электричество,газ,вода", 1),
                ("Развлечения", "expense", "кино,театр,концерт,игры,steam,netflix", 1),
                ("Здоровье",    "expense", "аптека,врач,клиника,стоматолог,лекарства", 1),
                ("Одежда",      "expense", "одежда,обувь,h&m,zara,uniqlo", 1),
                ("Подписки",    "expense", "подписка,spotify,яндекс плюс,подписки", 1),
                ("Зарплата",    "income",  "зарплата,аванс,зп", 1),
                ("Фриланс",     "income",  "фриланс,заказ,проект,гонорар", 1),
                ("Подарки",     "income",  "подарок,подарили", 1),
            ]
            conn.executemany(
                "INSERT INTO categories (name, type, keywords, is_default) VALUES (?, ?, ?, ?)",
                default_categories
            )


# ---------- Категории ----------
def load_categories():
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM categories ORDER BY type, name", conn)

def add_category(name, type_, keywords):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO categories (name, type, keywords) VALUES (?, ?, ?)",
            (name.strip(), type_, keywords.strip().lower())
        )

def update_category_keywords(cat_id, keywords):
    with get_conn() as conn:
        conn.execute(
            "UPDATE categories SET keywords = ? WHERE id = ?",
            (keywords.strip().lower(), cat_id)
        )

def delete_category(cat_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM categories WHERE id = ? AND is_default = 0", (cat_id,))

def match_category(text, cats_df, cat_type):
    """Ищет категорию нужного типа по ключевым словам.
    Возвращает (category_id, name, matched_kw) или None."""
    text_lower = text.lower()
    all_kw = []
    for _, row in cats_df[cats_df["type"] == cat_type].iterrows():
        for kw in row["keywords"].split(","):
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


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
init_db()

st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")


# ============================================================
# СТРАНИЦА: ОПЕРАЦИИ
# ============================================================
def page_operations():
    st.title("💰 Учёт доходов и расходов")

    cats_df = load_categories()

    with st.sidebar:
        op_type = st.radio("Тип операции", ["Расход", "Доход"], horizontal=True)
        is_expense = op_type == "Расход"
        cat_type = "expense" if is_expense else "income"

        st.header(f"➕ Добавить {'расход' if is_expense else 'доход'}")

        op_date = st.date_input("Дата", value=date.today())
        amount = st.number_input("Сумма (₽)", min_value=1, step=10, format="%d")
        description = st.text_input(
            "Описание (для распознавания)",
            placeholder="например: вб кроссовки, пятёрочка"
            if is_expense else "например: зарплата, фриланс"
        )
        comment = st.text_input(
            "Комментарий (необязательно)",
            placeholder="например: подарок сестре"
        )

        matched = None
        if description:
            matched = match_category(description, cats_df, cat_type)

        if matched:
            cid, cname, kw = matched
            st.success(f"Категория: **{cname}** (по слову «{kw}»)")
        elif description:
            st.warning("⚠️ Категория не распознана")

        if st.button("Добавить", type="primary", use_container_width=True):
            if not description.strip():
                st.error("Введи описание")
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

    df = load_transactions()

    if df.empty:
        st.info("Пока нет ни одной операции. Добавь первую через панель слева 👈")
        return

    total_income = df.loc[df["type"] == "income", "amount"].sum()
    total_expense = df.loc[df["type"] == "expense", "amount"].sum()
    balance = total_income - total_expense

    col1, col2, col3 = st.columns(3)
    col1.metric("💵 Доходы", f"{total_income:,} ₽".replace(",", " "))
    col2.metric("💸 Расходы", f"{total_expense:,} ₽".replace(",", " "))
    col3.metric("📊 Баланс", f"{balance:,} ₽".replace(",", " "))

    st.divider()
    st.subheader("Все операции")

    view = df.copy()
    view["type"] = view["type"].map({"income": "Доход", "expense": "Расход"})
    view = view.rename(columns={
        "id": "ID", "date": "Дата", "type": "Тип",
        "amount": "Сумма", "category": "Категория",
        "description": "Описание", "comment": "Комментарий"
    })
    st.dataframe(view, use_container_width=True, hide_index=True)


# ============================================================
# СТРАНИЦА: КАТЕГОРИИ
# ============================================================
def page_categories():
    st.title("🏷️ Категории и ключевые слова")
    st.caption("Через запятую. Если пользователь введёт одно из этих слов — операция попадёт в эту категорию.")

    cats_df = load_categories()

    with st.expander("➕ Добавить категорию"):
        with st.form("add_cat", clear_on_submit=True):
            new_name = st.text_input("Название", placeholder="например: Маркетплейс")
            new_type = st.radio("Тип", ["Расход", "Доход"], horizontal=True)
            new_keywords = st.text_input(
                "Ключевые слова (через запятую)",
                placeholder="вб, озон, wildberries, ozon"
            )
            if st.form_submit_button("Создать"):
                if not new_name.strip():
                    st.error("Введи название")
                else:
                    try:
                        add_category(
                            new_name,
                            "expense" if new_type == "Расход" else "income",
                            new_keywords
                        )
                        st.success(f"Категория «{new_name}» добавлена")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Такая категория уже есть")

    st.subheader("Существующие категории")

    for _, row in cats_df.iterrows():
        emoji = "💸" if row["type"] == "expense" else "💵"
        default_badge = " 🔒" if row["is_default"] else ""

        with st.expander(f"{emoji} {row['name']}{default_badge}"):
            new_kw = st.text_area(
                "Ключевые слова (через запятую)",
                value=row["keywords"],
                key=f"kw_{row['id']}"
            )
            c1, c2 = st.columns([1, 1])
            if c1.button("💾 Сохранить", key=f"save_{row['id']}"):
                update_category_keywords(row["id"], new_kw)
                st.success("Сохранено")
                st.rerun()
            if not row["is_default"]:
                if c2.button("🗑️ Удалить", key=f"del_{row['id']}"):
                    delete_category(row["id"])
                    st.rerun()
            else:
                c2.caption("Системная — нельзя удалить")


# ============================================================
# НАВИГАЦИЯ (МЕНЮ)
# ============================================================
pages = [
    st.Page(page_operations, title="Операции", icon="💰", default=True),
    st.Page(page_categories, title="Категории", icon="🏷️"),
]

nav = st.navigation(pages, position="sidebar")
nav.run()
