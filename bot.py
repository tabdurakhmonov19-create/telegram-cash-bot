import json
import logging
import os
import re
from collections import defaultdict

import psycopg2
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from groq import Groq
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()


def money(amount: int) -> str:
    return f"{amount:,} so'm"


def ensure_db_connection() -> None:
    global conn, cur
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()


def setup_database() -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            balance INTEGER DEFAULT 0
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            amount INTEGER,
            comment TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS budgets (
            user_id TEXT,
            category TEXT,
            amount INTEGER,
            PRIMARY KEY (user_id, category)
        )
        """
    )

    cur.execute(
        """
        ALTER TABLE history
        ADD COLUMN IF NOT EXISTS category TEXT
        """
    )

    cur.execute(
        """
        ALTER TABLE history
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS history_archive (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            amount INTEGER,
            comment TEXT,
            category TEXT,
            created_at TIMESTAMP
        )
        """
    )

    conn.commit()


setup_database()
client = Groq(api_key=GROQ_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    await update.message.reply_text(
        "Cash bot tayyor 💰\n"
        "+100000 ish\n"
        "-25000 ovqat\n"
        "/balance yozing"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    ensure_db_connection()
    user = str(update.effective_user.id)

    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    row = cur.fetchone()
    bal = row[0] if row else 0

    await update.message.reply_text(f"Balans: {money(bal)}")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    ensure_db_connection()
    user = str(update.effective_user.id)

    cur.execute(
        """
        SELECT amount, comment
        FROM history
        WHERE user_id=%s
        ORDER BY id DESC
        LIMIT 10
        """,
        (user,),
    )
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("History yo‘q")
        return

    text = "Oxirgi harajatlar:\n"
    for amount, comment in rows:
        text += f"{money(amount)} — {comment}\n"

    await update.message.reply_text(text)


async def auto_month_report():
    ensure_db_connection()

    cur.execute(
        """
        SELECT user_id, category, SUM(ABS(amount))
        FROM history
        GROUP BY user_id, category
        """
    )
    rows = cur.fetchall()

    if not rows:
        return

    data = defaultdict(list)
    for user, category, amount in rows:
        data[user].append((category or "other", amount))

    for user, items in data.items():
        text = "📊 Oylik hisobot:\n\n"
        total = 0

        for category, amount in items:
            text += f"{category}: {money(amount)}\n"
            total += amount

        text += f"\n💰 Jami: {money(total)}"

        try:
            await app.bot.send_message(chat_id=user, text=text)
        except Exception:
            logging.exception("Failed to send monthly report to user %s", user)


async def monthly_reset():
    ensure_db_connection()

    cur.execute(
        """
        INSERT INTO history_archive
        SELECT * FROM history
        """
    )
    cur.execute("DELETE FROM history")
    cur.execute("UPDATE users SET balance = 0")

    conn.commit()
    logging.info("Monthly archive + reset done")


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    ensure_db_connection()
    user = str(update.effective_user.id)

    cur.execute(
        """
        SELECT amount, comment
        FROM history
        WHERE user_id=%s
        """,
        (user,),
    )
    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("Analiz uchun data yo‘q.")
        return

    history_text = ""
    for amount, comment in rows:
        history_text += f"{amount} — {comment}\n"

    prompt = f"""
Analyze financial transactions:

{history_text}

Give short financial advice.
"""

    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        await update.message.reply_text(chat.choices[0].message.content)
    except Exception as exc:
        await update.message.reply_text(f"AI error: {exc}")


async def setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_db_connection()

    try:
        category = context.args[0].lower().strip()
        amount = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Format:\n/setbudget food 1000000")
        return

    user = str(update.effective_user.id)

    cur.execute(
        """
        INSERT INTO budgets (user_id, category, amount)
        VALUES (%s,%s,%s)
        ON CONFLICT (user_id, category)
        DO UPDATE SET amount=%s
        """,
        (user, category, amount, amount),
    )
    conn.commit()

    await update.message.reply_text(f"✅ Budget set:\n{category} → {money(amount)}")


def parse_transaction_from_text(line: str) -> tuple[int, str, str] | None:
    prompt = f"""
Extract money transaction from Uzbek text.

Text: "{line}"

Return JSON:
{{"amount": number, "comment": "short", "category":"oneword"}}
"""

    try:
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        ai_text = chat.choices[0].message.content.strip()
        match = re.search(r"\{[\s\S]*?\}", ai_text)
        if not match:
            raise ValueError("No JSON in AI output")

        result = json.loads(match.group().replace("'", '"'))
        amount = int(result["amount"])
        comment = str(result.get("comment", "")).strip() or "transaction"
        category = str(result.get("category", "other")).lower().strip() or "other"
        return amount, comment, category

    except Exception:
        numbers = re.findall(r"[+-]?\d+", line)
        if not numbers:
            return None

        amount = int(numbers[0])
        lower_line = line.lower()

        if amount == 0:
            return None

        if amount > 0 and not numbers[0].startswith("+"):
            income_keywords = ["oldim", "maosh", "keldi", "tushdi"]
            if any(word in lower_line for word in income_keywords):
                amount = abs(amount)
            else:
                amount = -abs(amount)

        comment = " ".join(line.split()[:4]) or "transaction"
        return amount, comment, "other"


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    ensure_db_connection()

    text = update.message.text
    user = str(update.effective_user.id)
    lines = text.split("\n")

    total = 0
    processed_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parsed = parse_transaction_from_text(line)
        if not parsed:
            continue

        amount, comment, category = parsed

        cur.execute(
            """
            INSERT INTO users (user_id, balance)
            VALUES (%s, 0)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user,),
        )

        cur.execute(
            """
            UPDATE users
            SET balance = balance + %s
            WHERE user_id=%s
            """,
            (amount, user),
        )

        cur.execute(
            """
            INSERT INTO history (user_id, amount, comment, category)
            VALUES (%s,%s,%s,%s)
            """,
            (user, amount, comment, category),
        )

        cur.execute(
            """
            SELECT amount FROM budgets
            WHERE user_id=%s AND LOWER(category)=LOWER(%s)
            """,
            (user, category),
        )
        row = cur.fetchone()

        if row:
            limit_amount = row[0]
            cur.execute(
                """
                SELECT SUM(ABS(amount))
                FROM history
                WHERE user_id=%s AND LOWER(category)=LOWER(%s)
                """,
                (user, category),
            )
            spent = cur.fetchone()[0] or 0

            if spent > limit_amount:
                await update.message.reply_text(
                    f"⚠️ {category} budget oshdi!\n"
                    f"Limit: {limit_amount:,} so'm\n"
                    f"Sarflandi: {spent:,} so'm"
                )

        total += amount
        processed_count += 1

    if processed_count == 0:
        await update.message.reply_text("Tranzaksiya aniqlanmadi. Masalan: -25000 ovqat")
        return

    conn.commit()
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    bal = cur.fetchone()[0]

    await update.message.reply_text(
        f"{processed_count} ta yozuv qo‘shildi.\n"
        f"Jami o‘zgarish: {money(total)}\n"
        f"Balans: {money(bal)}"
    )


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("analyze", analyze))
app.add_handler(CommandHandler("setbudget", setbudget))
app.add_handler(MessageHandler(filters.TEXT, handle))

scheduler = AsyncIOScheduler()
scheduler.add_job(auto_month_report, "cron", day=1, hour=9)
scheduler.add_job(monthly_reset, "cron", day=1, hour=0, minute=5)
scheduler.start()

app.run_polling()