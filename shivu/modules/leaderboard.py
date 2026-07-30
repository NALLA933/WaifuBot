import os
from datetime import datetime
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import mention_html
from telegram.ext import CommandHandler, CallbackContext, CallbackQueryHandler

from shivu import application, OWNER_ID, user_collection, top_global_groups_collection, group_user_totals_collection
from shivu import sudo_users as SUDO_USERS


def sc(t):
    return t.translate(str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ))


def is_sudo(user_id):
    return user_id == OWNER_ID or str(user_id) in SUDO_USERS


def format_list(title, rows):
    """rows: list of already-formatted line strings"""
    header = f"🏆 {sc('top')} {len(rows)} {sc(title)} 🏆\n\n"
    return header + "\n".join(rows)


async def send_or_edit(update, context, text, kb, edit):
    if edit:
        q = update.callback_query
        await q.answer()
        await q.message.edit_text(text, parse_mode='HTML', reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=kb)


def back_close_buttons(refresh_cb, extra_row=None):
    rows = [[InlineKeyboardButton("🔄", callback_data=refresh_cb), InlineKeyboardButton("🔙", callback_data="lb_menu")]]
    if extra_row:
        rows.append(extra_row)
    rows.append([InlineKeyboardButton("❌", callback_data="lb_close")])
    return InlineKeyboardMarkup(rows)


# ---------- /tops menu ----------

async def tops_menu(update: Update, context: CallbackContext, edit=False):
    text = f"🏆 {sc('select the top list')} 🏆"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 ʙᴀʟᴀɴᴄᴇ", callback_data="lb_bal")],
        [InlineKeyboardButton("🎴 ᴄʜᴀʀᴀᴄᴛᴇʀꜱ", callback_data="lb_chars")],
        [InlineKeyboardButton("🌱 ɢᴛᴏᴘ", callback_data="lb_gtop")],
        [InlineKeyboardButton("👤 sᴘʀᴏꜰɪʟᴇ", callback_data="lb_profile")],
    ])
    await send_or_edit(update, context, text, kb, edit)


# ---------- Top by balance ----------

async def top_balance(update: Update, context: CallbackContext, edit=False):
    data = await user_collection.find({}, {'id': 1, 'first_name': 1, 'balance': 1}) \
        .sort('balance', -1).limit(10).to_list(10)

    if not data:
        return await send_or_edit(update, context, sc("no data."), None, edit)

    rows = [f"{i}. {escape(u.get('first_name', 'Unknown'))} - Ŧ{u.get('balance', 0):,}"
            for i, u in enumerate(data, 1)]
    text = format_list("users by coins", rows)
    await send_or_edit(update, context, text, back_close_buttons("lb_bal"), edit)


# ---------- Top by characters ----------

async def top_characters(update: Update, context: CallbackContext, edit=False):
    data = await user_collection.aggregate([
        {"$match": {"characters": {"$exists": True, "$type": "array"}}},
        {"$project": {"user_id": "$id", "first_name": 1, "count": {"$size": "$characters"}}},
        {"$sort": {"count": -1}}, {"$limit": 10}
    ]).to_list(10)

    if not data:
        return await send_or_edit(update, context, sc("no data."), None, edit)

    rows = []
    for i, u in enumerate(data, 1):
        name = u.get('first_name', 'Unknown')
        link = mention_html(u['user_id'], name)
        rows.append(f"{i}. {link} - {u['count']:,} ᴄʜᴀʀꜱ")

    text = format_list("users by characters", rows)
    await send_or_edit(update, context, text, back_close_buttons("lb_chars"), edit)


# ---------- Top groups ----------

async def top_groups(update: Update, context: CallbackContext, edit=False):
    data = await top_global_groups_collection.find({}).sort('count', -1).limit(10).to_list(10)

    if not data:
        return await send_or_edit(update, context, sc("no data."), None, edit)

    rows = [f"{i}. {escape(g.get('group_name', 'Unknown'))} - {g.get('count', 0):,} ᴄʜᴀʀꜱ"
            for i, g in enumerate(data, 1)]
    text = format_list("groups", rows)
    await send_or_edit(update, context, text, back_close_buttons("lb_gtop"), edit)


# ---------- My profile ----------

async def my_profile(update: Update, context: CallbackContext, edit=False):
    user_id = update.effective_user.id
    user = await user_collection.find_one({'id': user_id})

    if not user:
        text = f"🏆 {sc('no profile yet')} 🏆\n\n{sc('start collecting!')}"
        return await send_or_edit(update, context, text, back_close_buttons("lb_profile"), edit)

    char_count = len(user.get('characters', []))
    balance = user.get('balance', 0)
    better_than = await user_collection.count_documents({
        "characters": {"$exists": True, "$type": "array"},
        "$expr": {"$lt": [{"$size": "$characters"}, char_count]}
    })
    total = await user_collection.count_documents({"characters": {"$exists": True, "$type": "array"}})
    rank = total - better_than

    link = update.effective_user.mention_html()

    text = (
        f"👤 {sc('profile')} 👤\n\n"
        f"{link}\n\n"
        f"{sc('rank')}: <b>#{rank:,}</b>/{total:,}\n"
        f"{sc('characters')}: <b>{char_count:,}</b>\n"
        f"{sc('balance')}: <b>Ŧ{balance:,}</b>"
    )
    await send_or_edit(update, context, text, back_close_buttons("lb_profile"), edit)


# ---------- Owner/sudo stats ----------

async def stats(update: Update, context: CallbackContext, edit=False):
    user_id = update.effective_user.id
    if not is_sudo(user_id):
        msg = sc("unauthorized.")
        if edit:
            return await update.callback_query.answer(msg, show_alert=True)
        return await update.message.reply_text(msg)

    users = await user_collection.count_documents({})
    groups = len(await group_user_totals_collection.distinct('group_id'))
    collectors = await user_collection.count_documents({"characters": {"$exists": True, "$type": "array"}})

    total_chars_result = await user_collection.aggregate([
        {"$match": {"characters": {"$exists": True, "$type": "array"}}},
        {"$project": {"count": {"$size": "$characters"}}},
        {"$group": {"_id": None, "total": {"$sum": "$count"}}}
    ]).to_list(1)
    total_chars = total_chars_result[0]['total'] if total_chars_result else 0

    text = (
        f"📊 {sc('system stats')} 📊\n\n"
        f"{sc('users')}: <b>{users:,}</b>\n"
        f"{sc('collectors')}: <b>{collectors:,}</b>\n"
        f"{sc('groups')}: <b>{groups:,}</b>\n"
        f"{sc('total characters')}: <b>{total_chars:,}</b>\n\n"
        f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄", callback_data="lb_stats")],
        [InlineKeyboardButton("❌", callback_data="lb_close")]
    ])
    await send_or_edit(update, context, text, kb, edit)


# ---------- Export commands (sudo only) ----------

async def export_users(update: Update, context: CallbackContext):
    if not is_sudo(update.effective_user.id):
        return await update.message.reply_text(sc('unauthorized.'))

    users = await user_collection.find({}).to_list(None)
    lines = [f"[{u.get('id')}] {u.get('first_name')} | @{u.get('username')} | {len(u.get('characters', []))} chars"
              for u in users]
    content = f"USER EXPORT — {datetime.now()}\nTotal: {len(users):,}\n{'='*50}\n\n" + "\n".join(lines)

    with open('users.txt', 'w', encoding='utf-8') as f:
        f.write(content)
    with open('users.txt', 'rb') as f:
        await context.bot.send_document(update.effective_chat.id, f, caption=f"<b>{sc('users')}</b>: {len(users):,}", parse_mode='HTML')
    os.remove('users.txt')


async def export_groups(update: Update, context: CallbackContext):
    if not is_sudo(update.effective_user.id):
        return await update.message.reply_text(sc('unauthorized.'))

    groups = await top_global_groups_collection.find({}).sort('count', -1).to_list(None)
    lines = [f"[{i}] {g.get('group_name')} | {g.get('count', 0):,}" for i, g in enumerate(groups, 1)]
    content = f"GROUP EXPORT — {datetime.now()}\nTotal: {len(groups):,}\n{'='*50}\n\n" + "\n".join(lines)

    with open('groups.txt', 'w', encoding='utf-8') as f:
        f.write(content)
    with open('groups.txt', 'rb') as f:
        await context.bot.send_document(update.effective_chat.id, f, caption=f"<b>{sc('groups')}</b>: {len(groups):,}", parse_mode='HTML')
    os.remove('groups.txt')


# ---------- Callback router ----------

CALLBACKS = {
    "lb_menu": tops_menu,
    "lb_bal": top_balance,
    "lb_chars": top_characters,
    "lb_gtop": top_groups,
    "lb_profile": my_profile,
    "lb_stats": stats,
}


async def cb(update: Update, context: CallbackContext):
    data = update.callback_query.data
    if data == "lb_close":
        return await update.callback_query.message.delete()
    handler = CALLBACKS.get(data)
    if handler:
        await handler(update, context, edit=True)


# ---------- Handlers ----------

application.add_handler(CommandHandler('tops', tops_menu, block=False))
application.add_handler(CommandHandler('balancetop', top_balance, block=False))
application.add_handler(CommandHandler(['chartop', 'top'], top_characters, block=False))
application.add_handler(CommandHandler(['gtop', 'topgroups'], top_groups, block=False))
application.add_handler(CommandHandler(['sprofile', 'rank'], my_profile, block=False))
application.add_handler(CommandHandler('stats', stats, block=False))
application.add_handler(CommandHandler('list', export_users, block=False))
application.add_handler(CommandHandler('groups', export_groups, block=False))
application.add_handler(CallbackQueryHandler(cb, pattern="^lb_"))
