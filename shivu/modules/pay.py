from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
from shivu import application, user_collection


async def pay_cmd(update: Update, context: CallbackContext):
    sender = update.effective_user
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to the user you want to pay.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /pay <amount> (as reply)")

    amount = int(context.args[0])
    receiver = update.message.reply_to_message.from_user
    if amount <= 0 or receiver.id == sender.id:
        return await update.message.reply_text("Invalid transaction.")

    s = await user_collection.find_one({'id': sender.id})
    if not s or int(s.get('balance', 0)) < amount:
        return await update.message.reply_text("Insufficient balance.")

    kb = [[
        InlineKeyboardButton("Confirm", callback_data=f"pay_yes_{sender.id}_{receiver.id}_{amount}"),
        InlineKeyboardButton("Cancel", callback_data=f"pay_no_{sender.id}")
    ]]
    await update.message.reply_text(
        f"Send {amount} to {receiver.mention_html()}?",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )


async def pay_callback(update: Update, context: CallbackContext):
    q = update.callback_query
    _, action, sender_id, *rest = q.data.split("_")
    sender_id = int(sender_id)

    if q.from_user.id != sender_id:
        return await q.answer("Not your transaction.", show_alert=True)

    if action == "no":
        await q.edit_message_text("Payment cancelled.")
        return await q.answer()

    receiver_id, amount = int(rest[0]), int(rest[1])

    res = await user_collection.find_one_and_update(
        {'id': sender_id, 'balance': {'$gte': amount}},
        {'$inc': {'balance': -amount}}
    )
    if not res:
        await q.edit_message_text("Insufficient balance.")
        return await q.answer()

    await user_collection.update_one({'id': receiver_id}, {'$inc': {'balance': amount}}, upsert=True)
    await q.edit_message_text(f"Paid {amount} successfully.")
    await q.answer()


application.add_handler(CommandHandler("pay", pay_cmd, block=False))
application.add_handler(CallbackQueryHandler(pay_callback, pattern="^pay_", block=False))