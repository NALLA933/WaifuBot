from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, CallbackContext
from shivu import application, sudo_users_collection

AUTHORIZED_USERS = [5147822244]


async def is_sudo(user_id: int) -> bool:
    return await sudo_users_collection.find_one({"id": user_id}) is not None


async def addsudo_cmd(update: Update, context: CallbackContext):
    msg, user = update.effective_message, update.effective_user
    if user.id not in AUTHORIZED_USERS:
        return await msg.reply_text("You are not authorized to add sudo users.")
    if not msg.reply_to_message:
        return await msg.reply_text("Reply to a user's message to add them as sudo.")

    target = msg.reply_to_message.from_user
    await sudo_users_collection.update_one(
        {"id": target.id},
        {"$set": {
            "id": target.id,
            "username": target.username or "unknown",
            "first_name": target.first_name or "unknown",
            "added_on": datetime.utcnow()
        }},
        upsert=True
    )
    await msg.reply_html(f"Added <a href='tg://user?id={target.id}'>{target.first_name}</a> as sudo user.")


async def removesudo_cmd(update: Update, context: CallbackContext):
    msg, user = update.effective_message, update.effective_user
    if user.id not in AUTHORIZED_USERS:
        return await msg.reply_text("You are not authorized to remove sudo users.")
    if not msg.reply_to_message:
        return await msg.reply_text("Reply to a sudo user's message to remove them.")

    target = msg.reply_to_message.from_user
    if not await is_sudo(target.id):
        return await msg.reply_text("This user is not in sudo list.")

    await sudo_users_collection.delete_one({"id": target.id})
    await msg.reply_html(f"Removed <a href='tg://user?id={target.id}'>{target.first_name}</a> from sudo list.")


async def sudolist_cmd(update: Update, context: CallbackContext):
    msg, user = update.effective_message, update.effective_user
    if user.id not in AUTHORIZED_USERS and not await is_sudo(user.id):
        return await msg.reply_text("You are not authorized to view sudo list.")

    users = await sudo_users_collection.find().to_list(length=None)
    if not users:
        return await msg.reply_text("No sudo users found.")

    text = "\n".join(
        f"{i}. <a href='tg://user?id={u['id']}'>{u.get('first_name', 'unknown')}</a>"
        for i, u in enumerate(users, 1)
    )
    await msg.reply_html(f"<b>Sudo Users:</b>\n{text}")


application.add_handler(CommandHandler("addsudo", addsudo_cmd))
application.add_handler(CommandHandler("sudoremove", removesudo_cmd))
application.add_handler(CommandHandler("sudolist", sudolist_cmd))