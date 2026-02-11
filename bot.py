from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
import psycopg2
import os
import matplotlib.pyplot as plt
import logging

logging.basicConfig(level=logging.INFO)

def money(x):
    return f"{x:,} so'm"



TOKEN = os.getenv("TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER DEFAULT 0
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id SERIAL PRIMARY KEY,
    user_id TEXT,
    amount INTEGER,
    comment TEXT
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS budgets (
    user_id TEXT,
    category TEXT,
    amount INTEGER,
    PRIMARY KEY (user_id, category)
)
""")

cur.execute("""
ALTER TABLE history
ADD COLUMN IF NOT EXISTS category TEXT
""")

cur.execute("""
ALTER TABLE history
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
""")

conn.commit()

client = Groq(api_key=GROQ_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cash bot tayyor 💰\n"
        "+100000 ish\n"
        "-25000 ovqat\n"
        "/balance yozing"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    user = str(update.effective_user.id)

    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    row = cur.fetchone()

    bal = row[0] if row else 0
    await update.message.reply_text(f"Balans: {money(bal)}"
)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    user = str(update.effective_user.id)

    cur.execute("""
        SELECT amount, comment
        FROM history
        WHERE user_id=%s
        ORDER BY id DESC
        LIMIT 10
    """, (user,))

    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("History yo‘q")
        return

    text = "Oxirgi harajatlar:\n"
    for amount, comment in rows:
        text += f"{money(amount)} — {comment}\n"



    await update.message.reply_text(text)


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    user = str(update.effective_user.id)

    cur.execute("""
        SELECT amount, comment
        FROM history
        WHERE user_id=%s
    """, (user,))

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
            model="llama-3.1-8b-instant"
        )

        await update.message.reply_text(chat.choices[0].message.content)

    except Exception as e:
        await update.message.reply_text(f"AI error: {e}")


async def setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur

    try:
        category = context.args[0].lower()
        amount = int(context.args[1])
    except:
        await update.message.reply_text("Format:\n/setbudget food 1000000")
        return

    user = str(update.effective_user.id)

    cur.execute("""
        INSERT INTO budgets (user_id, category, amount)
        VALUES (%s,%s,%s)
        ON CONFLICT (user_id, category)
        DO UPDATE SET amount=%s
    """, (user, category, amount, amount))

    conn.commit()

    await update.message.reply_text(
    f"✅ Budget set:\n{category} → {money(amount)}"
)



async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur

    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    text = update.message.text
    user = str(update.effective_user.id)
    lines = text.split("\n")

    total = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        try:
            prompt = f"""
Extract money transaction from Uzbek text.

Text: "{line}"

Return JSON:
{{"amount": number, "comment": "short", "category":"oneword"}}
"""

            chat = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant"
            )

            import json, re
            ai_text = chat.choices[0].message.content.strip()
            match = re.search(r"\{[\s\S]*?\}", ai_text)

            if not match:
                raise Exception()

            result = json.loads(match.group().replace("'", '"'))

            amount = int(result["amount"])
            comment = result["comment"]
            category = result.get("category", "other").lower().strip()

        except:
            import re
            nums = re.findall(r"\d+", line)
            if not nums:
                continue

            amount = int(nums[0])

            if any(x in line.lower() for x in ["oldim", "maosh", "keldi"]):
                amount = abs(amount)
            else:
                amount = -abs(amount)

            comment = " ".join(line.split()[:2])

            category = "other"

        # USER
        cur.execute("""
        INSERT INTO users (user_id, balance)
        VALUES (%s, 0)
        ON CONFLICT (user_id) DO NOTHING
        """, (user,))

        # BALANCE
        cur.execute("""
        UPDATE users
        SET balance = balance + %s
        WHERE user_id=%s
        """, (amount, user))

        # HISTORY
        cur.execute("""
        INSERT INTO history (user_id, amount, comment, category)
        VALUES (%s,%s,%s,%s)
        """, (user, amount, comment, category))

        # ⭐ BUDGET ALERT FIXED
        cur.execute("""
        SELECT amount FROM budgets
        WHERE user_id=%s AND LOWER(category)=LOWER(%s)
        """, (user, category))

        row = cur.fetchone()

        if row:
            limit_amount = row[0]

            cur.execute("""
            SELECT SUM(ABS(amount))
            FROM history
            WHERE user_id=%s AND LOWER(category)=LOWER(%s)
            """, (user, category))

            spent = cur.fetchone()[0] or 0

            if spent > limit_amount:
                await update.message.reply_text(
                    f"⚠️ {category} budget oshdi!\n"
                    f"Limit: {limit_amount:,} so'm\n"
                    f"Sarflandi: {spent:,} so'm"

                )

        total += amount

    conn.commit()

    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    bal = cur.fetchone()[0]

    await update.message.reply_text(
    f"Jami qo‘shildi: {money(total)}\n"
    f"Balans: {money(bal)}"
)




app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("analyze", analyze))
app.add_handler(CommandHandler("setbudget", setbudget))
app.add_handler(MessageHandler(filters.TEXT, handle))

app.run_polling()
