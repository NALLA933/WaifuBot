from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from shivu import application, user_collection


async def get_user(uid):
    return await user_collection.find_one({"id": uid})


async def init_user(uid):
    user = {"id": uid, "balance": 0}
    await user_collection.insert_one(user)
    return user


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    uid = update.effective_user.id

    user = await get_user(uid)
    if user is None:
        user = await init_user(uid)

    balance = user.get("balance", 0)

    await update.message.reply_text(
        f"💸 **Balance:** `{balance}`",
        parse_mode="Markdown",
    )


application.add_handler(CommandHandler("bal", balance_cmd, block=False))