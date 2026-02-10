from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
import json
import os
import matplotlib.pyplot as plt
import psycopg2
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




def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cash bot tayyor 💰\n"
        "+100000 ish\n"
        "-25000 ovqat\n"
        "/balance yozing"
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    data = load_data()

    bal = data.get(user, {}).get("balance", 0)
    await update.message.reply_text(f"Balans: {bal}")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    data = load_data()

    if user not in data or "history" not in data[user]:
        await update.message.reply_text("History yo‘q")
        return

    text = "Oxirgi harajatlar:\n"

    for item in data[user]["history"][-10:]:
        text += f"{item['amount']} — {item['comment']}\n"

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
    data = load_data()

    if user not in data or "history" not in data[user]:
        await update.message.reply_text("Analiz uchun data yo‘q.")
        return

    history_text = ""
    for item in data[user]["history"]:
        history_text += f"{item['amount']} — {item['comment']}\n"

    prompt = f"""
You are a professional financial advisor.

Analyze these financial transactions:
{history_text}

Give short and clear advice:

1. Where most money is spent
2. How to save money
3. Budget recommendations
4. Warn if there are unnecessary expenses

Write simple, practical advice.
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
    data = load_data()

    if user not in data or "history" not in data[user]:
        await update.message.reply_text("Report uchun data yo‘q.")
        return

    categories = {}
    for item in data[user]["history"]:
        cat = item["comment"]
        amount = abs(item["amount"])

        if cat in categories:
            categories[cat] += amount
        else:
            categories[cat] = amount

    plt.figure()
    plt.bar(categories.keys(), categories.values())
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("report.png")
    plt.close()

    await update.message.reply_photo(photo=open("report.png", "rb"))







async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = str(update.effective_user.id)

    data = load_data()

    if user not in data:
        data[user] = {"balance": 0, "history": []}

    if text.startswith("+") or text.startswith("-"):
        parts = text.split(" ", 1)
        amount = int(parts[0])
        comment = parts[1] if len(parts) > 1 else "izoh yo‘q"

        data[user]["balance"] += amount
        data[user]["history"].append({
            "amount": amount,
            "comment": comment
        })

        save_data(data)

        await update.message.reply_text(
            f"Qo‘shildi: {amount}\n"
            f"Izoh: {comment}\n"
            f"Balans: {data[user]['balance']}"
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
