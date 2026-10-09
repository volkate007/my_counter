import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

# ---------- Настройки ----------
DB_PATH = "finance.db"

EXPENSE_CATEGORIES = [
    "Еда", "Транспорт", "Жильё", "Развлечения",
    "Здоровье", "Одежда", "Подписки", "Прочее"
]

INCOME_CATEGORIES = [
    "Зарплата", "Фриланс", "Подарки", "Проценты", "Прочее"
]

# ---------- Работа с БД ----------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                description TEXT
            )
        """)

def add_transaction(d, t, amount, category, description):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO transactions (date, type, amount, category, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (d.isoformat(), t, amount, category, description)
        )

def load_transactions():
    with get_conn() as conn:
        return pd.read_sql_query(
            "SELECT * FROM transactions ORDER BY date DESC, id DESC",
            conn
        )

# ---------- Инициализация ----------
init_db()

st.set_page_config(page_title="Мои финансы", page_icon="💰", layout="wide")
st.title("💰 Учёт доходов и расходов")

# ---------- Форма добавления ----------
with st.sidebar:
    st.header("➕ Добавить операцию")

    op_type = st.radio("Тип", ["Расход", "Доход"], horizontal=True)
    is_expense = op_type == "Расход"

    categories = EXPENSE_CATEGORIES if is_expense else INCOME_CATEGORIES

    with st.form("add_form", clear_on_submit=True):
        op_date = st.date_input("Дата", value=date.today())
        amount = st.number_input("Сумма", min_value=0.0, step=10.0, format="%.2f")
        category = st.selectbox("Категория", categories)
        description = st.text_input("Описание (необязательно)")
        submitted = st.form_submit_button("Добавить")

        if submitted:
            if amount <= 0:
                st.error("Сумма должна быть больше нуля")
            else:
                add_transaction(
                    op_date,
                    "expense" if is_expense else "income",
                    amount, category, description
                )
                st.success(f"Добавлено: {op_type} {amount:.2f} ₽ — {category}")
                st.rerun()

# ---------- Данные ----------
df = load_transactions()

if df.empty:
    st.info("Пока нет ни одной операции. Добавь первую через панель слева 👈")
else:
    # ---------- Метрики ----------
    total_income = df.loc[df["type"] == "income", "amount"].sum()
    total_expense = df.loc[df["type"] == "expense", "amount"].sum()
    balance = total_income - total_expense

    col1, col2, col3 = st.columns(3)
    col1.metric("💵 Доходы", f"{total_income:,.2f} ₽")
    col2.metric("💸 Расходы", f"{total_expense:,.2f} ₽")
    col3.metric("📊 Баланс", f"{balance:,.2f} ₽",
                delta=f"{balance:,.2f}", delta_color="normal")

    st.divider()

    # ---------- Таблица ----------
    st.subheader("Все операции")

    view = df.copy()
    view["type"] = view["type"].map({"income": "Доход", "expense": "Расход"})
    view = view.rename(columns={
        "id": "ID", "date": "Дата", "type": "Тип",
        "amount": "Сумма", "category": "Категория",
        "description": "Описание"
    })
    st.dataframe(view, use_container_width=True, hide_index=True)
