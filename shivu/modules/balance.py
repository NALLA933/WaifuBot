from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from shivu import application, user_collection


async def get_user(uid):
    return await user_collection.find_one({'id': uid})


async def init_user(uid):
    await user_collection.insert_one({'id': uid, 'balance': 0})


async def balance_cmd(update: Update, context: CallbackContext):
    if not update.effective_user:
        return

    uid = update.effective_user.id
    user = await get_user(uid)
    if not user:
        await init_user(uid)
        user = await get_user(uid)

    balance = int(user.get('balance', 0))
    await update.message.reply_text(f"💸 ʙᴀʟᴀɴᴄᴇ: <code>{balance}</code>")


application.add_handler(CommandHandler("bal", balance_cmd, block=False))
