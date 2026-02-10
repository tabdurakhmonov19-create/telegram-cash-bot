from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
import psycopg2
import os
import matplotlib.pyplot as plt
import logging
logging.basicConfig(level=logging.INFO)
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

    # reconnect agar DB yopilgan bo‘lsa
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    user = str(update.effective_user.id)

    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    row = cur.fetchone()

    if row:
        bal = row[0]
    else:
        bal = 0

    await update.message.reply_text(f"Balans: {bal}")



async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        text += f"{amount} — {comment}\n"

    await update.message.reply_text(text)


async def ai_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "user", "content": "Salom AI"}
            ],
            model="llama-3.1-8b-instant"

        )

        await update.message.reply_text(
            chat_completion.choices[0].message.content
        )

    except Exception as e:
        await update.message.reply_text(f"Xato: {e}")

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
You are a professional financial advisor.

Analyze these financial transactions:
{history_text}

Give short and clear advice:
1. Where most money is spent
2. How to save money
3. Budget recommendations
4. Warn unnecessary expenses
"""

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )

        await update.message.reply_text(
            chat_completion.choices[0].message.content
        )

    except Exception as e:
        await update.message.reply_text(f"Xato: {e}")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)

    cur.execute("""
        SELECT comment, SUM(ABS(amount))
        FROM history
        WHERE user_id=%s
        GROUP BY comment
    """, (user,))

    rows = cur.fetchall()

    if not rows:
        await update.message.reply_text("Report uchun data yo‘q.")
        return

    categories = {row[0]: row[1] for row in rows}

    plt.figure()
    plt.bar(categories.keys(), categories.values())
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("report.png")
    plt.close()

    with open("report.png", "rb") as f:
        await update.message.reply_photo(photo=f)











async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global conn, cur

    text = update.message.text
    user = str(update.effective_user.id)

    # DB reconnect
    if conn.closed:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()

    # AI parsing
    try:
        prompt = f"""
Extract financial transaction from this text.

Text: "{text}"

Rules:
- Income positive number
- Expense negative number
- Short comment (1-2 words)

Return ONLY JSON:
{{"amount": number, "comment": "text"}}
"""

        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )

        import json
        result = json.loads(chat.choices[0].message.content)

        amount = int(result["amount"])
        comment = result["comment"]

    except Exception as e:
        await update.message.reply_text("Tushunmadim 🤔")
        return

    # user create
    cur.execute("""
    INSERT INTO users (user_id, balance)
    VALUES (%s, 0)
    ON CONFLICT (user_id) DO NOTHING
    """, (user,))

    # balance update
    cur.execute("""
    UPDATE users
    SET balance = balance + %s
    WHERE user_id=%s
    """, (amount, user))

    # history insert
    cur.execute("""
    INSERT INTO history (user_id, amount, comment)
    VALUES (%s, %s, %s)
    """, (user, amount, comment))

    conn.commit()

    cur.execute("SELECT balance FROM users WHERE user_id=%s", (user,))
    bal = cur.fetchone()[0]

    await update.message.reply_text(
        f"Qo‘shildi: {amount}\n"
        f"Izoh: {comment}\n"
        f"Balans: {bal}"
    )








app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("report", report))
app.add_handler(CommandHandler("analyze", analyze))
app.add_handler(CommandHandler("ai", ai_test))
app.add_handler(MessageHandler(filters.TEXT, handle))

app.run_polling()   
