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

def match_category(text, cats_df):
    """Ищет категорию по ключевым словам. Возвращает (category_id, name, type, matched_kw) или None."""
    text_lower = text.lower()
    all_kw = []
    for _, row in cats_df.iterrows():
        for kw in row["keywords"].split(","):
            kw = kw.strip()
            if kw:
                all_kw.append((len(kw), kw, row["id"], row["name"], row["type"]))
    all_kw.sort(reverse=True)

    for _, kw, cid, cname, ctype in all_kw:
        if kw in text_lower:
            return cid, cname, ctype, kw
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

page = st.sidebar.radio("Раздел", ["💰 Операции", "🏷️ Категории"])
st.sidebar.divider()

cats_df = load_categories()


# ============================================================
# ЭКРАН: ОПЕРАЦИИ
# ============================================================
if page == "💰 Операции":
    st.title("💰 Учёт доходов и расходов")

    with st.sidebar:
        st.header("➕ Добавить операцию")

        op_date = st.date_input("Дата", value=date.today())
        amount = st.number_input("Сумма (₽)", min_value=1, step=10, format="%d")
        description = st.text_input(
            "На что потрачено / как заработано",
            placeholder="например: вб кроссовки, пятёрочка, зарплата"
        )

        matched = None
        if description:
            matched = match_category(description, cats_df)

        if matched:
            cid, cname, ctype, kw = matched
            emoji = "💸" if ctype == "expense" else "💵"
            st.success(f"{emoji} Категория: **{cname}** (по слову «{kw}»)")
        elif description:
            st.warning("⚠️ Категория не распознана — выбери вручную")

        with st.expander("Выбрать категорию вручную", expanded=not matched):
            cat_options = cats_df.copy()
            cat_options["label"] = cat_options.apply(
                lambda r: f"{'💸' if r['type']=='expense' else '💵'} {r['name']}",
                axis=1
            )
            manual = st.selectbox(
                "Категория",
                options=cat_options["id"].tolist(),
                format_func=lambda i: cat_options.loc[
                    cat_options["id"] == i, "label"
                ].values[0],
                key="manual_cat"
            )

        if st.button("Добавить", type="primary", use_container_width=True):
            if not description.strip():
                st.error("Введи описание")
            else:
                if matched:
                    cid, cname, ctype, _ = matched
                else:
                    row = cats_df[cats_df["id"] == manual].iloc[0]
                    cid, cname, ctype = row["id"], row["name"], row["type"]

                add_transaction(op_date, amount, cid, ctype, description)
                st.success(f"Добавлено: {amount} ₽ — {cname}")
                st.rerun()

    df = load_transactions()

    if df.empty:
        st.info("Пока нет ни одной операции. Добавь первую через панель слева 👈")
    else:
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
            "description": "Описание"
        })
        st.dataframe(view, use_container_width=True, hide_index=True)


# ============================================================
# ЭКРАН: КАТЕГОРИИ
# ============================================================
elif page == "🏷️ Категории":
    st.title("🏷️ Категории и ключевые слова")
    st.caption("Через запятую. Если пользователь введёт одно из этих слов — операция попадёт в эту категорию.")

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
