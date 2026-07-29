from html import escape
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from cachetools import TTLCache

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import TelegramError

from shivu import application, collection, user_collection

char_cache = TTLCache(maxsize=2000, ttl=600)
anime_cache = TTLCache(maxsize=1000, ttl=900)
user_cache = TTLCache(maxsize=500, ttl=300)

USERS_PER_PAGE, CHARS_PER_PAGE = 10, 15


@dataclass
class Char:
    id: str; name: str; anime: str; rarity: str; img_url: str
    is_video: bool = False; price: int = 0

    @classmethod
    def from_dict(cls, d: Dict) -> 'Char':
        return cls(d.get('id', '??'), d.get('name', 'Unknown'), d.get('anime', 'Unknown'),
                    d.get('rarity', '🟢 Common'), d.get('img_url', ''), d.get('is_video', False),
                    d.get('price', 0))


def rarity_parts(rarity) -> Tuple[str, str]:
    if isinstance(rarity, str):
        p = rarity.split(' ', 1)
        return (p[0], p[1] if len(p) > 1 else 'Common')
    return '🟢', 'Common'


async def get_char(cid: str) -> Optional[Char]:
    if cid in char_cache:
        return char_cache[cid]
    d = await collection.find_one({'id': cid})
    if d:
        char_cache[cid] = Char.from_dict(d)
        return char_cache[cid]
    return None


async def find_by_name(name: str) -> List[Dict]:
    key = f"n_{name.lower()}"
    if key in char_cache:
        return char_cache[key]
    res = await collection.find({'name': {'$regex': name, '$options': 'i'}}).to_list(length=None)
    if res:
        char_cache[key] = res
    return res


async def find_by_anime(anime: str) -> List[Dict]:
    key = anime.lower()
    if key in anime_cache:
        return anime_cache[key]
    res = await collection.find({'anime': {'$regex': anime, '$options': 'i'}}).to_list(length=None)
    if res:
        anime_cache[key] = res
    return res


async def global_count(cid: str) -> int:
    key = f"c_{cid}"
    if key in user_cache:
        return user_cache[key]
    try:
        n = await user_collection.count_documents({'characters.id': cid})
    except Exception:
        n = 0
    user_cache[key] = n
    return n


async def get_owners(cid: str) -> List[Dict]:
    key = f"o_{cid}"
    if key in user_cache:
        return user_cache[key]
    users = await user_collection.find(
        {'characters.id': cid}, {'_id': 0, 'id': 1, 'first_name': 1, 'username': 1, 'characters': 1}
    ).to_list(length=None)
    owners = []
    for u in users:
        cnt = sum(1 for c in u.get('characters', []) if c.get('id') == cid)
        if cnt:
            owners.append({'id': u['id'], 'first_name': u.get('first_name', 'Unknown'),
                            'username': u.get('username'), 'count': cnt})
    owners.sort(key=lambda x: x['count'], reverse=True)
    user_cache[key] = owners
    return owners


def process_search(chars: List[Dict]) -> Dict:
    names, data, rarities = {}, {}, {}
    for c in chars:
        n = c.get('name', 'Unknown')
        if n not in names:
            names[n] = 0
            data[n] = c
        names[n] += 1
        e, _ = rarity_parts(c.get('rarity', '🟢 Common'))
        rarities[e] = rarities.get(e, 0) + 1
    return {'names': names, 'data': data, 'rarities': rarities, 'unique': len(names), 'total': len(chars)}


def card_caption(char: Char, gcount: int) -> str:
    emoji, text = rarity_parts(char.rarity)
    return (
        "💠 𝗖𝗛𝗔𝗥𝗔𝗖𝗧𝗘𝗥 𝗜𝗡𝗙𝗢:\n"
        "┏━━━━━━━━━━━━━⧫\n"
        f"◈𝗡𝗔𝗠𝗘: {escape(char.name)}\n"
        f"◈𝗥𝗔𝗥𝗜𝗧𝗬: {emoji} {text}\n"
        f"◈𝗔𝗡𝗜𝗠𝗘: {escape(char.anime)}\n"
        f"◈𝗣𝗥𝗜𝗖𝗘: {char.price:,}\n\n"
        f"🌍 ɢʟᴏʙᴀʟʟʏ ɢʀᴀʙʙᴇᴅ {gcount}x\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "ᴀ ᴘʀᴇᴄɪᴏᴜs ᴄʜᴀʀᴀᴄᴛᴇʀ ᴡᴀɪᴛɪɴɢ ᴛᴏ ᴊᴏɪɴ ʏᴏᴜʀ ᴄᴏʟʟᴇᴄᴛɪᴏɴ"
    )


def owners_caption(char: Char, owners: List[Dict], page: int, gcount: int) -> str:
    emoji, text = rarity_parts(char.rarity)
    start, end = page * USERS_PER_PAGE, page * USERS_PER_PAGE + USERS_PER_PAGE
    total_pages = (len(owners) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    lines = [
        "🏆 𝗖𝗛𝗔𝗥𝗔𝗖𝗧𝗘𝗥 𝗢𝗪𝗡𝗘𝗥𝗦:",
        f"◈𝗡𝗔𝗠𝗘: {escape(char.name)}  {emoji} {text}",
        f"◈𝗔𝗡𝗜𝗠𝗘: {escape(char.anime)}",
        "━━━━━━━━━━━━━━━━━",
    ]
    for i, o in enumerate(owners[start:end], start + 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        link = f"<a href='tg://user?id={o['id']}'>{escape(o['first_name'])}</a>"
        if o['username']:
            link += f" (@{escape(o['username'])})"
        lines.append(f"{medal} {link} x{o['count']}")
    lines.append(f"\n📄 ᴘᴀɢᴇ {page+1}/{total_pages} • 🌍 {gcount}x ᴛᴏᴛᴀʟ")
    return "\n".join(lines)


def find_caption(query: str, r: Dict, page: int, show_all: bool) -> Tuple[str, int]:
    total_pages = 1 if show_all else max(1, (r['unique'] + CHARS_PER_PAGE - 1) // CHARS_PER_PAGE)
    lines = [
        "🔍 𝗦𝗘𝗔𝗥𝗖𝗛 𝗥𝗘𝗦𝗨𝗟𝗧𝗦:",
        f"◈ǫᴜᴇʀʏ: {escape(query)}  |  ᴛᴏᴛᴀʟ: {r['total']}  |  ᴜɴɪǫᴜᴇ: {r['unique']}",
        "━━━━━━━━━━━━━━━━━",
    ]
    items = sorted(r['names'].items())
    s, e = (0, len(items)) if show_all else (page * CHARS_PER_PAGE, page * CHARS_PER_PAGE + CHARS_PER_PAGE)
    for i, (name, cnt) in enumerate(items[s:e], s + 1):
        c = r['data'][name]
        emoji, text = rarity_parts(c.get('rarity', '🟢 Common'))
        lines.append(f"{i}. {escape(name)} [{c.get('id','??')}] {emoji} {text}"
                      + (f" x{cnt}" if cnt > 1 else ""))
    if not show_all and total_pages > 1:
        lines.append(f"\n📄 ᴘᴀɢᴇ {page+1}/{total_pages}")
    return "\n".join(lines), total_pages


def pagination_kb(cid: str, page: int, total: int, back=False) -> InlineKeyboardMarkup:
    kb = []
    if total > 1:
        row = []
        if page > 0: row.append(InlineKeyboardButton("⬅️", callback_data=f"owners_{cid}_{page-1}"))
        if page < total - 1: row.append(InlineKeyboardButton("➡️", callback_data=f"owners_{cid}_{page+1}"))
        if row: kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data=f"back_{cid}")] if back
              else [InlineKeyboardButton("🏆 ᴏᴡɴᴇʀs", callback_data=f"owners_{cid}_0")])
    return InlineKeyboardMarkup(kb)


def find_kb(query: str, page: int, total: int) -> Optional[InlineKeyboardMarkup]:
    if total <= 1:
        return None
    row = []
    if page > 0: row.append(InlineKeyboardButton("⬅️", callback_data=f"find_{query}_{page-1}"))
    row.append(InlineKeyboardButton(f"{page+1}/{total}", callback_data="noop"))
    if page < total - 1: row.append(InlineKeyboardButton("➡️", callback_data=f"find_{query}_{page+1}"))
    return InlineKeyboardMarkup([row])


async def send_media(update: Update, char: Char, caption: str, kb) -> None:
    try:
        method = update.message.reply_video if char.is_video else update.message.reply_photo
        kwargs = {'caption': caption, 'reply_markup': kb, 'parse_mode': ParseMode.HTML}
        await method(video=char.img_url, **kwargs) if char.is_video else await method(photo=char.img_url, **kwargs)
    except (TelegramError, Exception) as e:
        await update.message.reply_text(f"{caption}\n\n⚠️ media error: {escape(str(e))}",
                                         reply_markup=kb, parse_mode=ParseMode.HTML)


async def check_character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return await update.message.reply_text("Usage: /check <id>")
    char = await get_char(context.args[0])
    if not char:
        return await update.message.reply_text("❌ Character not found.")
    gcount = await global_count(char.id)
    await send_media(update, char, card_caption(char, gcount), pagination_kb(char.id, 0, 1))


async def find_character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return await update.message.reply_text("Usage: /find <name> [--all]")
    args = context.args.copy()
    show_all = '--all' in args
    if show_all: args.remove('--all')
    name = ' '.join(args)
    chars = await find_by_name(name)
    if not chars:
        return await update.message.reply_text(f"❌ No results for {escape(name)}")
    r = process_search(chars)
    text, total = find_caption(name, r, 0, show_all)
    kb = None if show_all else find_kb(name, 0, total)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def find_anime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return await update.message.reply_text("Usage: /anime <name>")
    name = ' '.join(context.args)
    chars = await find_by_anime(name)
    if not chars:
        return await update.message.reply_text(f"❌ No characters found from {escape(name)}")
    r = process_search(chars)
    text, _ = find_caption(name, r, 0, True)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def find_users_with_character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        return await update.message.reply_text("Usage: /pfind <id>")
    cid = context.args[0]
    char = await get_char(cid)
    if not char:
        return await update.message.reply_text("❌ Character not found.")
    owners = await get_owners(cid)
    if not owners:
        return await update.message.reply_text("No users own this character.")
    gcount = await global_count(cid)
    total = (len(owners) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    await send_media(update, char, owners_caption(char, owners, 0, gcount), pagination_kb(cid, 0, total, back=True))


async def handle_owners_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, cid, page = q.data.split('_')
    page = int(page)
    char = await get_char(cid)
    owners = await get_owners(cid)
    if not char or not owners:
        return await q.answer("Not found", show_alert=True)
    gcount = await global_count(cid)
    total = (len(owners) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    await q.edit_message_caption(caption=owners_caption(char, owners, page, gcount),
                                  reply_markup=pagination_kb(cid, page, total, back=True),
                                  parse_mode=ParseMode.HTML)


async def handle_back_to_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    cid = q.data.split('_')[1]
    char = await get_char(cid)
    if not char:
        return await q.answer("Not found", show_alert=True)
    gcount = await global_count(cid)
    await q.edit_message_caption(caption=card_caption(char, gcount),
                                  reply_markup=pagination_kb(cid, 0, 1), parse_mode=ParseMode.HTML)


async def handle_find_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data.replace('find_', '', 1)
    name, page = data.rsplit('_', 1)
    page = int(page)
    chars = await find_by_name(name)
    if not chars:
        return await q.answer("No results", show_alert=True)
    r = process_search(chars)
    text, total = find_caption(name, r, page, False)
    await q.edit_message_text(text, reply_markup=find_kb(name, page, total), parse_mode=ParseMode.HTML)


application.add_handler(CommandHandler("check", check_character, block=False))
application.add_handler(CommandHandler("find", find_character, block=False))
application.add_handler(CommandHandler("anime", find_anime, block=False))
application.add_handler(CommandHandler("hfind", find_users_with_character, block=False))
application.add_handler(CallbackQueryHandler(handle_owners_pagination, pattern=r"^owners_", block=False))
application.add_handler(CallbackQueryHandler(handle_back_to_card, pattern=r"^back_", block=False))
application.add_handler(CallbackQueryHandler(handle_find_pagination, pattern=r"^find_", block=False))