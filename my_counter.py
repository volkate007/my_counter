import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

DB_PATH = "finance.db"

# ---------- Работа с БД ----------
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
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)
        # Засеять категории по умолчанию, если таблица пустая
        cur = conn.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            default_categories = [
                # name,             type,      keywords,                                    is_default
                ("Продукты",        "expense", "пятёрочка,пятерочка,магнит,перекресток,лента,ашан,продукты,еда", 1),
                ("Маркетплейс",     "expense", "вб,wb,вайлдберриз,wildberries,озон,ozon,яндекс маркет,маркет", 1),
                ("Транспорт",       "expense", "метро,автобус,такси,яндекс такси,бензин,заправка,каршеринг", 1),
                ("Жильё",           "expense", "квартира,аренда,жкх,коммуналка,электричество,газ,вода", 1),
                ("Развлечения",     "expense", "кино,театр,концерт,игры,steam,netflix", 1),
                ("Здоровье",        "expense", "аптека,врач,клиника,стоматолог,лекарства", 1),
                ("Одежда",          "expense", "одежда,обувь,h&m,zara,uniqlo", 1),
                ("Подписки",        "expense", "подписка,spotify,яндекс плюс,подписки", 1),
                ("Зарплата",        "income",  "зарплата,аванс,зп", 1),
                ("Фриланс",         "income",  "фриланс,заказ,проект,гонорар", 1),
                ("Подарки",         "income",  "подарок,подарили", 1),
            ]
            conn.executemany(
                "INSERT INTO categories (name, type, keywords, is_default) VALUES (?, ?, ?, ?)",
                default_categories
            )

# ---------- Категории ----------
def load_categories():
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM categories ORDER BY type, name", conn
        )

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

def match_category(text, cats_df):
    """Ищет категорию по ключевым словам. Возвращает (category_id, name, type) или None."""
    text_lower = text.lower()
    # Сначала проверяем более длинные ключи (точнее совпадение)
    all_kw = []
    for _, row in cats_df.iterrows():
        for kw in row["keywords"].split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, row["id"], row["name"], row["type"]))
    all_kw.sort(reverse=True)  # длинные вперёд

    for _, kw, cid, cname, ctype in all_kw:
        if kw in text_lower:
            return cid, cname, ctype
    return None

# ---------- Транзакции ----------
def add_transaction(d, amount, category_id, cat_type, description):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (date, type, amount, category_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (d.isoformat(), cat_type, int(amount), category_id, description)
        )

def load_transactions():
    with get_conn() as conn:
        return pd.read_sql_query("""
            SELECT t.id, t.date, t.type, t.amount,
                   c.name AS category, t.description
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            ORDER BY t.date DESC, t.id DESC
        """, conn)

# ---------- Инициализация ----------
init_db()

st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")

# ---------- Меню ----------
page = st.sidebar.radio("Раздел", ["💰 Операции", "🏷️ Категории"])
st.sidebar.divider()

cats_df = load_categories()
