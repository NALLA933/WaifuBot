import os
import asyncio
import random
from datetime import datetime
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext, CallbackQueryHandler

from shivu import application, OWNER_ID, user_collection, top_global_groups_collection, group_user_totals_collection
from shivu import sudo_users as SUDO_USERS

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
VIDEOS = [
    "https://files.catbox.moe/csqqb2.mp4",
    "https://files.catbox.moe/dpeatb.mp4", 
    "https://files.catbox.moe/38b2an.mp4", 
    "https://files.catbox.moe/x3k8vj.mp4"
]

def sc(t): return t.translate(str.maketrans("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢABCDEFGHIJKLMNOPQRSTUVWXYZ"))
def badge(r): return "1sᴛ" if r==1 else "2ɴᴅ" if r==2 else "3ʀᴅ" if r==3 else f"ᴛᴏᴘ{r}" if r<=10 else f"#{r}"
def bar(c, m, l=10): f=int((c/m)*l) if m>0 else 0; return "▰"*f+"▱"*(l-f)
def get_video(): return random.choice(VIDEOS)

async def anim(msg, txt):
    try:
        for i in range(8): await msg.edit_text(f"{SPINNER[i%len(SPINNER)]} {sc(txt)}"); await asyncio.sleep(0.2)
    except: pass

async def global_leaderboard(update: Update, context: CallbackContext, edit=False):
    q = update.callback_query if edit else None
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    if edit: await q.answer(sc("refreshing..."))

    task = asyncio.create_task(anim(msg, "fetching rankings"))
    try:
        data = await top_global_groups_collection.aggregate([
            {"$project": {"group_name": 1, "count": 1}}, {"$sort": {"count": -1}}, {"$limit": 10}
        ]).to_list(10)
        task.cancel()
        if not data: return await msg.edit_text(sc("no data available."))

        vid = get_video()
        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('top groups')}⸻</b>\n\n"
        for i, g in enumerate(data, 1):
            n = escape(g.get('group_name', 'Unknown'))[:20]; c = g.get("count", 0)
            cap += f"<b>{badge(i)}</b> {sc(n)}\n{bar(c, data[0]['count'], 10)} {c:,}\n"
        cap += f"\n<i>{sc('updated')}: {datetime.now().strftime('%H:%M')}</i>"

        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="lb_tg"), InlineKeyboardButton("📊", callback_data="lb_more")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def ctop(update: Update, context: CallbackContext, edit=False, cid=None):
    q = update.callback_query if edit else None
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    cid = cid or update.effective_chat.id
    if edit: await q.answer(sc("refreshing..."))

    task = asyncio.create_task(anim(msg, "analyzing chat"))
    try:
        try: chat = await context.bot.get_chat(cid); title = escape(chat.title)[:25]
        except: title = "This Chat"

        data = await group_user_totals_collection.aggregate([
            {"$match": {"group_id": cid}}, {"$project": {"user_id": "$_id", "first_name": 1, "character_count": "$count"}},
            {"$sort": {"character_count": -1}}, {"$limit": 10}
        ]).to_list(10)
        task.cancel()
        if not data: return await msg.edit_text(sc("no data."))

        uids = [u.get('user_id', u.get('_id')) for u in data]
        bal_docs = await user_collection.find({'id': {'$in': uids}}, {'id': 1, 'balance': 1}).to_list(len(uids))
        bal_map = {b['id']: b.get('balance', 0) for b in bal_docs}

        tot = sum(u['character_count'] for u in data)
        vid = get_video()
        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('chat top')}⸻</b>\n{sc(title)}\n\n"
        for i, u in enumerate(data, 1):
            uid = u.get('user_id', u.get('_id')); n = escape(u.get('first_name', 'Unknown'))[:15]; c = u.get("character_count", 0)
            pct = (c/tot*100) if tot>0 else 0; bal = bal_map.get(uid, 0)
            m = f"<a href='tg://user?id={uid}'>{sc(n)}</a>"
            cap += f"<b>{badge(i)}</b> {m}\n{bar(c, data[0]['character_count'], 10)} {c:,} ᴄʜᴀʀꜱ ({pct:.1f}%) | 💰{bal:,}\n"
        cap += f"\n<i>{sc('total')}: {tot:,}</i>"

        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data=f"lb_ct_{cid}"), InlineKeyboardButton("📊", callback_data=f"lb_cs_{cid}")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def leaderboard(update: Update, context: CallbackContext, edit=False, lim=10):
    q = update.callback_query if edit else None
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    if edit: await q.answer(sc("refreshing..."))

    task = asyncio.create_task(anim(msg, "fetching champions"))
    try:
        data = await user_collection.aggregate([
            {"$match": {"characters": {"$exists": True, "$type": "array"}}},
            {"$project": {"user_id": "$id", "first_name": 1, "character_count": {"$size": "$characters"}, "balance": 1}},
            {"$sort": {"character_count": -1}}, {"$limit": lim}
        ]).to_list(lim)
        task.cancel()
        if not data: return await msg.edit_text(sc("no data."))

        vid = get_video()
        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('hall of fame' if lim==10 else f'top {lim}')}⸻</b>\n\n"
        for i, u in enumerate(data, 1):
            uid = u.get('user_id', u.get('_id')); n = escape(u.get('first_name', 'Unknown'))[:15]
            c = u.get("character_count", 0); bal = u.get('balance', 0)
            m = f"<a href='tg://user?id={uid}'>{sc(n)}</a>"
            cap += f"<b>{badge(i)}</b> {m}\n{bar(c, data[0]['character_count'], 10)} {c:,} ᴄʜᴀʀꜱ | 💰{bal:,}\n"
        cap += f"\n<i>{sc('top')} {lim}</i>"

        if lim==10:
            btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="lb_g"), InlineKeyboardButton("📈20", callback_data="lb_20")], [InlineKeyboardButton("👤", callback_data="lb_mr"), InlineKeyboardButton("🏆", callback_data="lb_tg")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        else:
            btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="lb_20"), InlineKeyboardButton("🔙10", callback_data="lb_g")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def my_rank(update: Update, context: CallbackContext, edit=False):
    q = update.callback_query if edit else None
    uid = update.effective_user.id
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    if edit: await q.answer(sc("loading..."))

    task = asyncio.create_task(anim(msg, "calculating rank"))
    try:
        user = await user_collection.find_one({'id': uid})
        task.cancel()

        vid = get_video()
        if not user or 'characters' not in user:
            cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('no profile')}⸻</b>\n\n{sc('start collecting!')}\n"
            btns = InlineKeyboardMarkup([[InlineKeyboardButton("🏆", callback_data="lb_g")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
            return await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)

        cc = len(user.get('characters', []))
        bal = user.get('balance', 0)
        hi = await user_collection.count_documents({"characters": {"$exists": True, "$type": "array"}, "$expr": {"$gt": [{"$size": "$characters"}, cc]}})
        r = hi+1; tot = await user_collection.count_documents({"characters": {"$exists": True, "$type": "array"}})
        n = escape(user.get('first_name', 'Unknown')); m = f"<a href='tg://user?id={uid}'>{sc(n)}</a>"
        pct = ((tot-r)/tot*100) if tot>0 else 0
        tier = "🌟ʟᴇɢᴇɴᴅ" if r==1 else "💎ᴍᴀꜱᴛᴇʀ" if r<=10 else "💠ᴅɪᴀᴍᴏɴᴅ" if pct>=90 else "🔷ᴘʟᴀᴛɪɴᴜᴍ" if pct>=75 else "🟡ɢᴏʟᴅ" if pct>=50 else "⚪ꜱɪʟᴠᴇʀ" if pct>=25 else "🟤ʙʀᴏɴᴢᴇ"

        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('profile')}⸻</b>\n\n{m} {tier}\n\n{sc('rank')}: <b>#{r:,}</b>/{tot:,}\n{sc('badge')}: <b>{badge(r)}</b>\n{sc('chars')}: <b>{cc:,}</b>\n{sc('balance')}: <b>💰{bal:,}</b>\n{sc('percentile')}: <b>ᴛᴏᴘ{100-pct:.1f}%</b>\n\n{bar(pct, 100, 12)}\n"

        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="lb_mr"), InlineKeyboardButton("🏆", callback_data="lb_g")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def chat_stats(update: Update, context: CallbackContext, edit=False, cid=None):
    q = update.callback_query if edit else None
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    cid = cid or update.effective_chat.id
    if edit: await q.answer(sc("loading..."))

    task = asyncio.create_task(anim(msg, "computing stats"))
    try:
        try: chat = await context.bot.get_chat(cid); title = escape(chat.title)[:30]
        except: title = "This Chat"

        uc = await group_user_totals_collection.count_documents({"group_id": cid})
        task.cancel()
        if uc==0: return await msg.edit_text(sc("no activity."))

        res = await group_user_totals_collection.aggregate([{"$match": {"group_id": cid}}, {"$group": {"_id": None, "total": {"$sum": "$count"}}}]).to_list(1)
        tot = res[0]['total'] if res else 0
        top = await group_user_totals_collection.find_one({"group_id": cid}, sort=[("count", -1)])

        vid = get_video()
        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('chat stats')}⸻</b>\n\n{sc(title)}\n\n{sc('users')}: <b>{uc:,}</b>\n{sc('chars')}: <b>{tot:,}</b>\n{sc('avg')}: <b>{tot/uc:.1f}</b>"
        if top: cap += f"\n\n{sc('top')}: {sc(escape(top.get('first_name', 'Unknown'))[:18])}\n{sc('count')}: <b>{top.get('count', 0):,}</b>"

        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data=f"lb_cs_{cid}"), InlineKeyboardButton("👥", callback_data=f"lb_ct_{cid}")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def stats(update: Update, context: CallbackContext, edit=False):
    # FIXED: Check both command and callback
    uid = update.effective_user.id
    if uid != OWNER_ID and str(uid) not in SUDO_USERS:
        return await (update.callback_query.answer(sc("unauthorized."), show_alert=True) if edit else update.message.reply_text(sc("unauthorized.")))

    q = update.callback_query if edit else None
    msg = q.message if edit else await update.message.reply_text(sc("loading..."))
    if edit: await q.answer(sc("refreshing..."))

    task = asyncio.create_task(anim(msg, "computing"))
    try:
        u = await user_collection.count_documents({})
        g = len(await group_user_totals_collection.distinct('group_id'))
        c = await user_collection.count_documents({"characters": {"$exists": True, "$type": "array"}})
        res = await user_collection.aggregate([{"$match": {"characters": {"$exists": True, "$type": "array"}}}, {"$project": {"cc": {"$size": "$characters"}}}, {"$group": {"_id": None, "tot": {"$sum": "$cc"}}}]).to_list(1)
        tc = res[0]['tot'] if res else 0
        task.cancel()

        vid = get_video()
        cap = f"<a href='{vid}'>&#8205;</a><b>⸻{sc('system stats')}⸻</b>\n\n{sc('users')}: <b>{u:,}</b>\n{sc('collectors')}: <b>{c:,}</b>\n{sc('groups')}: <b>{g:,}</b>\n{sc('chars')}: <b>{tc:,}</b>\n\n{sc('avg')}: <b>{tc/c:.1f}</b>\n{sc('rate')}: <b>{(c/u*100):.1f}%</b>\n\n<i>{datetime.now().strftime('%H:%M:%S')}</i>"

        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="lb_st")], [InlineKeyboardButton("❌", callback_data="lb_close")]])
        await msg.edit_text(cap, parse_mode='HTML', reply_markup=btns)
    except: pass

async def export_users(update: Update, context: CallbackContext):
    if str(update.effective_user.id) not in SUDO_USERS: return await update.message.reply_text(sc('unauthorized.'))
    msg = await update.message.reply_text(sc('exporting...'))
    task = asyncio.create_task(anim(msg, "generating"))
    try:
        users = await user_collection.find({}).to_list(None)
        task.cancel()
        cont = f"⸻USER EXPORT⸻\n{datetime.now()}\nTotal: {len(users):,}\n{'='*50}\n\n"
        for u in users: cont += f"[{u.get('id')}] {u.get('first_name')} | @{u.get('username')} | {len(u.get('characters', []))} chars\n"
        with open('users.txt', 'w', encoding='utf-8') as f: f.write(cont)
        await msg.edit_text(sc("✓ complete!"))
        with open('users.txt', 'rb') as f: await context.bot.send_document(update.effective_chat.id, f, caption=f"<b>{sc('users')}</b>: {len(users):,}", parse_mode='HTML')
        os.remove('users.txt'); await msg.delete()
    except: pass

async def export_groups(update: Update, context: CallbackContext):
    if str(update.effective_user.id) not in SUDO_USERS: return await update.message.reply_text(sc('unauthorized.'))
    msg = await update.message.reply_text(sc('exporting...'))
    task = asyncio.create_task(anim(msg, "generating"))
    try:
        grps = await top_global_groups_collection.find({}).to_list(None)
        grps.sort(key=lambda x: x.get('count', 0), reverse=True)
        task.cancel()
        cont = f"⸻GROUP EXPORT⸻\n{datetime.now()}\nTotal: {len(grps):,}\n{'='*50}\n\n"
        for i, g in enumerate(grps, 1): cont += f"[{i}] {g.get('group_name')} | {g.get('count', 0):,}\n"
        with open('groups.txt', 'w', encoding='utf-8') as f: f.write(cont)
        await msg.edit_text(sc("✓ complete!"))
        with open('groups.txt', 'rb') as f: await context.bot.send_document(update.effective_chat.id, f, caption=f"<b>{sc('groups')}</b>: {len(grps):,}", parse_mode='HTML')
        os.remove('groups.txt'); await msg.delete()
    except: pass

async def cb(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    d = q.data
    try:
        if d=="lb_g": await leaderboard(update, context, True)
        elif d=="lb_20": await leaderboard(update, context, True, 20)
        elif d=="lb_tg": await global_leaderboard(update, context, True)
        elif d=="lb_mr": await my_rank(update, context, True)
        elif d.startswith("lb_ct_"): await ctop(update, context, True, int(d.split("_")[2]))
        elif d.startswith("lb_cs_"): await chat_stats(update, context, True, int(d.split("_")[2]))
        elif d=="lb_st": await stats(update, context, True)  # FIXED: Added this line
        elif d=="lb_close": await q.message.delete()
    except: pass

application.add_handler(CommandHandler('topgroups', global_leaderboard, block=False))
application.add_handler(CommandHandler('topchat', ctop, block=False))
application.add_handler(CommandHandler(['gstop', 'top'], leaderboard, block=False))
application.add_handler(CommandHandler(['sprofile', 'rank'], my_rank, block=False))
application.add_handler(CommandHandler('chatstats', chat_stats, block=False))
application.add_handler(CommandHandler('stats', stats, block=False))
application.add_handler(CommandHandler('list', export_users, block=False))
application.add_handler(CommandHandler('groups', export_groups, block=False))
application.add_handler(CallbackQueryHandler(cb, pattern="^lb_"))
