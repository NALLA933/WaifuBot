import re, time, hashlib
from html import escape
from typing import List, Dict, Optional
from dataclasses import dataclass
from cachetools import TTLCache, LRUCache
from pymongo import ASCENDING, TEXT
from functools import lru_cache

from telegram import Update, InlineQueryResultPhoto, InlineQueryResultVideo, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, InlineQueryResultCachedPhoto, SwitchInlineQueryChosenChat
from telegram.ext import InlineQueryHandler, CallbackQueryHandler, ChosenInlineResultHandler
from telegram.constants import ParseMode

from shivu import application, db

collection = db['anime_characters_lol']
user_collection = db['user_collection_lmaoooo']

@dataclass
class Rarity:
    emoji: str
    name: str
    value: int

RARITY_MAP = {
    "mythic": ("🔮", 1), "cosmic": ("🌌", 2), "celestial": ("🪽", 3),
    "exclusive": ("🥴", 4), "legendary": ("🟠", 5), "premium": ("💎", 6),
    "neon": ("⚡", 7), "pearl": ("🐚", 8), "sweet": ("🍭", 9),
    "special": ("🟡", 10), "valentine": ("💋", 11), "winter": ("❄️", 12),
    "erotic": ("🥵", 13), "rare": ("🔵", 14), "common": ("🟢", 15)
}

try:
    collection.create_index([('id', ASCENDING)], unique=True, background=True)
    collection.create_index([('rarity', ASCENDING), ('anime', ASCENDING)], background=True)
    collection.create_index([('name', TEXT), ('anime', TEXT)], background=True)
    user_collection.create_index([('id', ASCENDING)], unique=True, background=True)
    user_collection.create_index([('characters.id', ASCENDING)], background=True, sparse=True)
except: pass

char_cache = TTLCache(maxsize=80000, ttl=2400)
user_cache = TTLCache(maxsize=50000, ttl=1200)
query_cache = LRUCache(maxsize=15000)
count_cache = TTLCache(maxsize=30000, ttl=1800)
feedback_cache = TTLCache(maxsize=10000, ttl=3600)
view_cache = TTLCache(maxsize=5000, ttl=600)
wishlist_cache = TTLCache(maxsize=5000, ttl=1800)

CAPS = str.maketrans('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ', 'ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ')

@lru_cache(maxsize=65536)
def sc(t: str) -> str: return t.translate(CAPS)

@lru_cache(maxsize=32768)
def parse_rar(r: str) -> Rarity:
    if not r or not isinstance(r, str): return Rarity("🟢", "Common", 15)
    rl = r.lower()
    for k, (e, v) in RARITY_MAP.items():
        if k in rl:
            n = r.split(' ', 1)[-1] if ' ' in r else k.title()
            return Rarity(e, n, v)
    p = r.split(' ', 1)
    return Rarity(p[0] if p else "🟢", p[1] if len(p) > 1 else "Common", 15)

def trunc(t: str, l: int = 22) -> str: return t[:l-2] + '..' if len(t) > l else t
def cache_key(*args) -> str: return hashlib.md5(str(args).encode()).hexdigest()

async def get_user(uid: int) -> Optional[Dict]:
    k = f"u{uid}"
    if k in user_cache: return user_cache[k]
    u = await user_collection.find_one({'id': uid}, {'_id': 0})
    if u: user_cache[k] = u
    return u

async def bulk_count(ids: List[str]) -> Dict[str, int]:
    if not ids: return {}
    k = cache_key('bulk', tuple(sorted(ids[:150])))
    if k in count_cache: return count_cache[k]
    pipe = [
        {'$match': {'characters.id': {'$in': ids}}},
        {'$project': {'characters.id': 1}},
        {'$unwind': '$characters'},
        {'$match': {'characters.id': {'$in': ids}}},
        {'$group': {'_id': '$characters.id', 'count': {'$sum': 1}}}
    ]
    results = await user_collection.aggregate(pipe).to_list(None)
    counts = {r['_id']: r['count'] for r in results}
    count_cache[k] = counts
    return counts

async def get_owners(cid: str, lim: int = 100) -> List[Dict]:
    k = f"o{cid}{lim}"
    if k in count_cache: return count_cache[k]
    pipe = [
        {'$match': {'characters.id': cid}},
        {'$project': {'id': 1, 'first_name': 1, 'username': 1, 'characters': {'$filter': {'input': '$characters', 'as': 'c', 'cond': {'$eq': ['$$c.id', cid]}}}}},
        {'$addFields': {'count': {'$size': '$characters'}}},
        {'$sort': {'count': -1}},
        {'$limit': lim},
        {'$project': {'characters': 0}}
    ]
    owners = await user_collection.aggregate(pipe).to_list(lim)
    count_cache[k] = owners
    return owners

async def search_chars(q: str, lim: int = 1000) -> List[Dict]:
    k = cache_key('search', q, lim)
    if k in query_cache: return query_cache[k]
    if q:
        chars = await collection.find({'$text': {'$search': q}}, {'_id': 0, 'score': {'$meta': 'textScore'}}).sort([('score', {'$meta': 'textScore'})]).limit(lim).to_list(lim)
        if not chars:
            rx = re.compile(f'^{re.escape(q)}', re.IGNORECASE)
            chars = await collection.find({'$or': [{'name': rx}, {'anime': rx}, {'id': q}]}, {'_id': 0}).limit(lim).to_list(lim)
    else:
        chars = await collection.find({}, {'_id': 0}).limit(lim).to_list(lim)
    query_cache[k] = chars
    return chars

async def filter_chars(chars: List[Dict], mode: str, uid: int = None) -> List[Dict]:
    if mode == 'rare': return [c for c in chars if parse_rar(c.get('rarity', '')).value <= 9]
    elif mode == 'video': return [c for c in chars if c.get('is_video', False)]
    elif mode == 'new': return sorted(chars, key=lambda x: str(x.get('_id', '')), reverse=True)
    elif mode == 'popular':
        ids = [c.get('id') for c in chars if c.get('id')]
        if ids:
            counts = await bulk_count(ids)
            return sorted(chars, key=lambda x: counts.get(x.get('id'), 0), reverse=True)
    elif mode == 'trending':
        ids = [c.get('id') for c in chars if c.get('id')]
        if ids:
            picks = {cid: feedback_cache.get(f'pick_{cid}', 0) for cid in ids if feedback_cache.get(f'pick_{cid}', 0) > 0}
            return sorted(chars, key=lambda x: picks.get(x.get('id'), 0), reverse=True)
    elif mode == 'owned' and uid:
        usr = await get_user(uid)
        if usr:
            owned = {c.get('id') for c in usr.get('characters', []) if isinstance(c, dict) and c.get('id')}
            return [c for c in chars if c.get('id') in owned]
    elif mode == 'notowned' and uid:
        usr = await get_user(uid)
        if usr:
            owned = {c.get('id') for c in usr.get('characters', []) if isinstance(c, dict) and c.get('id')}
            return [c for c in chars if c.get('id') not in owned]
    elif mode == 'wishlist' and uid:
        wl = wishlist_cache.get(f'wl_{uid}', set())
        return [c for c in chars if c.get('id') in wl]
    return chars

def dedupe(chars: List[Dict]) -> List[Dict]:
    seen, result = set(), []
    for c in chars:
        cid = c.get('id')
        if cid and cid not in seen:
            seen.add(cid)
            result.append(c)
    return result

def minimal_caption(ch: Dict, fav: bool = False, stats: Dict = None, uid: int = None) -> str:
    cid, nm, an = ch.get('id', '??'), ch.get('name', 'Unknown'), ch.get('anime', 'Unknown')
    r = parse_rar(ch.get('rarity', ''))
    wl = wishlist_cache.get(f'wl_{uid}', set()) if uid else set()
    is_wl = cid in wl
    
    cap = f"""{'💖 ' if fav else ''}{'⭐ ' if is_wl else ''}<b>{escape(nm)}</b>

{r.emoji} <code>{sc(r.name)}</code> • 🆔 <code>{cid}</code>
📺 <i>{escape(trunc(an, 38))}</i>"""
    
    if stats:
        cap += f"\n\n👥 <code>{stats.get('owners', 0)}</code> • 🎯 <code>{stats.get('total', 0)}×</code>"
    return cap

def owners_caption(ch: Dict, owners: List[Dict]) -> str:
    nm = ch.get('name', 'Unknown')
    total = sum(o.get('count', 0) for o in owners)
    cap = f"<b>{escape(nm)}</b>\n\n👥 <b>{len(owners)}</b> ᴏᴡɴᴇʀs • <b>{total}×</b> ɢʀᴀʙʙᴇᴅ\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, o in enumerate(owners[:30], 1):
        medal = medals.get(i, f"{i}.")
        fn = escape(trunc(o.get('first_name', 'User'), 18))
        cap += f"{medal} {fn} • <code>×{o.get('count', 0)}</code>\n"
    return cap

def stats_caption(ch: Dict, owners: List[Dict]) -> str:
    nm = ch.get('name', 'Unknown')
    total = sum(o.get('count', 0) for o in owners)
    avg = round(total / len(owners), 1) if owners else 0
    cap = f"<b>{escape(nm)}</b>\n\n📊 <b>sᴛᴀᴛɪsᴛɪᴄs</b>\n🎯 <code>{total}×</code> ɢʀᴀʙʙᴇᴅ\n👥 <code>{len(owners)}</code> ᴏᴡɴᴇʀs\n📈 <code>{avg}×</code> ᴀᴠɢ\n"
    if owners:
        cap += f"\n🏆 <b>ᴛᴏᴘ ᴄᴏʟʟᴇᴄᴛᴏʀs</b>\n"
        for i, o in enumerate(owners[:10], 1):
            fn = escape(trunc(o.get('first_name', 'User'), 18))
            cap += f"{i}. {fn} • <code>×{o.get('count', 0)}</code>\n"
    return cap

def create_kbd(cid: str, uid: int = None) -> InlineKeyboardMarkup:
    wl = wishlist_cache.get(f'wl_{uid}', set()) if uid else set()
    is_wl = cid in wl
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ᴏᴡɴᴇʀs", callback_data=f"o.{cid}"), InlineKeyboardButton("📊 sᴛᴀᴛs", callback_data=f"s.{cid}")],
        [InlineKeyboardButton("📋 ᴄᴏᴘʏ ɪᴅ", callback_data=f"c.{cid}"), InlineKeyboardButton(f"{'⭐ ʀᴇᴍᴏᴠᴇ' if is_wl else '⭐ ᴡɪsʜʟɪsᴛ'}", callback_data=f"w.{cid}")],
        [InlineKeyboardButton("📤 sʜᴀʀᴇ", switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(query=cid, allow_user_chats=True, allow_group_chats=True, allow_channel_chats=False))]
    ])

async def inlinequery(update: Update, context) -> None:
    q, off, uid, qid = update.inline_query.query, int(update.inline_query.offset) if update.inline_query.offset else 0, update.inline_query.from_user.id, update.inline_query.id
    try:
        is_coll, usr, sq, fm = False, None, q, None
        
        if q.startswith('collection.'):
            is_coll = True
            parts = q.split(' ', 1)
            tid = parts[0].split('.')[1]
            sq = parts[1].strip() if len(parts) > 1 else ''
            for m in ['rare', 'video', 'new', 'popular', 'trending', 'owned', 'notowned', 'wishlist']:
                if sq.startswith(f'-{m}'):
                    fm = m
                    sq = sq.replace(f'-{m}', '').strip()
                    break
            if not tid.isdigit():
                await update.inline_query.answer([], cache_time=5)
                return
            tuid = int(tid)
            usr = await get_user(tuid)
            if not usr:
                await update.inline_query.answer([InlineQueryResultArticle(id="nouser", title="❌ ɴᴏ ᴄᴏʟʟᴇᴄᴛɪᴏɴ", description="sᴛᴀʀᴛ ʏᴏᴜʀ ᴊᴏᴜʀɴᴇʏ", thumbnail_url="https://i.imgur.com/placeholder.png", input_message_content=InputTextMessageContent("<b>🎮 sᴛᴀʀᴛ ᴄᴏʟʟᴇᴄᴛɪɴɢ!</b>", parse_mode=ParseMode.HTML))], cache_time=5)
                return
            cd = {c['id']: c for c in usr.get('characters', []) if isinstance(c, dict) and c.get('id')}
            all_chars = list(cd.values())
            if sq:
                rx = re.compile(re.escape(sq), re.IGNORECASE)
                all_chars = [c for c in all_chars if rx.search(c.get('name', '')) or rx.search(c.get('anime', '')) or rx.search(c.get('id', ''))]
            if fm: all_chars = await filter_chars(all_chars, fm, tuid)
            fc = None
            fav = usr.get('favorites')
            if fav and not sq and not fm:
                fid = fav.get('id') if isinstance(fav, dict) else fav
                fc = next((c for c in all_chars if c.get('id') == fid), None)
                if fc:
                    all_chars = [c for c in all_chars if c.get('id') != fid]
                    all_chars.insert(0, fc)
            if not fm or fm not in ['new', 'popular', 'trending']:
                all_chars.sort(key=lambda x: parse_rar(x.get('rarity', '')).value)
        else:
            for m in ['rare', 'video', 'new', 'popular', 'trending', 'owned', 'notowned', 'wishlist']:
                if sq.startswith(f'-{m}'):
                    fm = m
                    sq = sq.replace(f'-{m}', '').strip()
                    break
            am = re.search(r'-anime:(\S+)', sq)
            if am:
                anime_filter = am.group(1)
                sq = sq.replace(am.group(0), '').strip()
                all_chars = await search_chars(sq)
                rx = re.compile(re.escape(anime_filter), re.IGNORECASE)
                all_chars = [c for c in all_chars if rx.search(c.get('anime', ''))]
            else:
                all_chars = await search_chars(sq)
            if fm: all_chars = await filter_chars(all_chars, fm, uid)
            if not fm or fm not in ['new', 'popular', 'trending']:
                all_chars.sort(key=lambda x: parse_rar(x.get('rarity', '')).value)
        
        all_chars = dedupe(all_chars)
        chars = all_chars[off:off+50]
        has_more = len(all_chars) > off + 50
        noff = str(off + 50) if has_more else ""
        
        cids = [c.get('id') for c in chars if c.get('id')]
        bs = {}
        if cids and not is_coll:
            od = await bulk_count(cids)
            for cid in cids:
                ol = await get_owners(cid, 10)
                bs[cid] = {'owners': len(ol), 'total': od.get(cid, 0)}
        
        view_cache[f'rv_{uid}'] = cids[:10]
        
        results = []
        for ch in chars:
            cid = ch.get('id')
            if not cid: continue
            nm, an, img, vid = ch.get('name', '?'), ch.get('anime', '?'), ch.get('img_url', ''), ch.get('is_video', False)
            r = parse_rar(ch.get('rarity', ''))
            fav = False
            if is_coll and usr:
                fv = usr.get('favorites')
                fid = fv.get('id') if isinstance(fv, dict) else fv
                fav = (fid == cid)
            st = bs.get(cid)
            cap = minimal_caption(ch, fav, stats=st, uid=uid)
            kbd = create_kbd(cid, uid)
            rid = f"{cid}{off}{qid[:8]}"
            title = f"{'💖 ' if fav else ''}{r.emoji} {trunc(nm, 28)}"
            pop = ""
            if st and st.get('owners', 0) > 10: pop = f"🔥 {st['owners']} ᴏᴡɴᴇʀs"
            elif st and st.get('total', 0) > 5: pop = f"⭐ {st['total']}× ɢʀᴀʙs"
            desc = f"{r.name} • {trunc(an, 20)}"
            if pop: desc = f"{pop} • {desc}"
            
            if vid:
                results.append(InlineQueryResultVideo(id=rid, video_url=img, mime_type="video/mp4", thumbnail_url=img, title=title, description=desc, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd))
            else:
                results.append(InlineQueryResultPhoto(id=rid, photo_url=img, thumbnail_url=img, title=title, description=desc, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd))
        
        await update.inline_query.answer(results, next_offset=noff, cache_time=90, is_personal=is_coll)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await update.inline_query.answer([], cache_time=5)

async def chosen_inline_result(update: Update, context) -> None:
    result = update.chosen_inline_result
    cid = result.result_id
    cp = cid.split('][')
    cidc = cp[0][:20] if cp else cid[:20]
    cidc = ''.join(filter(str.isalnum, cidc))
    fk = f'pick_{cidc}'
    feedback_cache[fk] = feedback_cache.get(fk, 0) + 1
    qk = f'query_{result.from_user.id}'
    feedback_cache[qk] = result.query

async def show_owners(update: Update, context) -> None:
    q = update.callback_query
    await q.answer()
    try:
        cid = q.data.split('.', 1)[1]
        ch = await collection.find_one({'id': cid}, {'_id': 0})
        if not ch:
            await q.answer("❌ ɴᴏᴛ ғᴏᴜɴᴅ", show_alert=True)
            return
        owners = await get_owners(cid, 100)
        if not owners:
            await q.answer("ℹ️ ɴᴏ ᴏᴡɴᴇʀs", show_alert=True)
            return
        cap = owners_caption(ch, owners)
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data=f"b.{cid}"), InlineKeyboardButton("📊 sᴛᴀᴛs", callback_data=f"s.{cid}")], [InlineKeyboardButton("📤 sʜᴀʀᴇ", switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(query=cid, allow_user_chats=True, allow_group_chats=True, allow_channel_chats=False))]])
        await q.edit_message_caption(caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)

async def back_card(update: Update, context) -> None:
    q = update.callback_query
    await q.answer()
    try:
        cid = q.data.split('.', 1)[1]
        ch = await collection.find_one({'id': cid}, {'_id': 0})
        if not ch:
            await q.answer("❌ ɴᴏᴛ ғᴏᴜɴᴅ", show_alert=True)
            return
        uid = q.from_user.id
        cap = minimal_caption(ch, uid=uid)
        kbd = create_kbd(cid, uid)
        await q.edit_message_caption(caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)

async def show_stats(update: Update, context) -> None:
    q = update.callback_query
    await q.answer()
    try:
        cid = q.data.split('.', 1)[1]
        ch = await collection.find_one({'id': cid}, {'_id': 0})
        if not ch:
            await q.answer("❌ ɴᴏᴛ ғᴏᴜɴᴅ", show_alert=True)
            return
        owners = await get_owners(cid, 100)
        cap = stats_caption(ch, owners)
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ʙᴀᴄᴋ", callback_data=f"b.{cid}"), InlineKeyboardButton("👥 ᴏᴡɴᴇʀs", callback_data=f"o.{cid}")], [InlineKeyboardButton("📤 sʜᴀʀᴇ", switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(query=cid, allow_user_chats=True, allow_group_chats=True, allow_channel_chats=False))]])
        await q.edit_message_caption(caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)

async def copy_id(update: Update, context) -> None:
    q = update.callback_query
    cid = q.data.split('.', 1)[1]
    await q.answer(f"📋 ɪᴅ ᴄᴏᴘɪᴇᴅ: {cid}", show_alert=False)

async def toggle_wishlist(update: Update, context) -> None:
    q = update.callback_query
    uid = q.from_user.id
    cid = q.data.split('.', 1)[1]
    wk = f'wl_{uid}'
    wl = wishlist_cache.get(wk, set())
    if cid in wl:
        wl.remove(cid)
        await q.answer("⭐ ʀᴇᴍᴏᴠᴇᴅ ғʀᴏᴍ ᴡɪsʜʟɪsᴛ", show_alert=False)
    else:
        wl.add(cid)
        await q.answer("⭐ ᴀᴅᴅᴇᴅ ᴛᴏ ᴡɪsʜʟɪsᴛ", show_alert=False)
    wishlist_cache[wk] = wl
    try:
        ch = await collection.find_one({'id': cid}, {'_id': 0})
        if ch:
            cap = minimal_caption(ch, uid=uid)
            kbd = create_kbd(cid, uid)
            await q.edit_message_caption(caption=cap, parse_mode=ParseMode.HTML, reply_markup=kbd)
    except: pass

application.add_handler(InlineQueryHandler(inlinequery, block=False))
application.add_handler(ChosenInlineResultHandler(chosen_inline_result, block=False))
application.add_handler(CallbackQueryHandler(show_owners, pattern=r'^o\.', block=False))
application.add_handler(CallbackQueryHandler(back_card, pattern=r'^b\.', block=False))
application.add_handler(CallbackQueryHandler(show_stats, pattern=r'^s\.', block=False))
application.add_handler(CallbackQueryHandler(copy_id, pattern=r'^c\.', block=False))
application.add_handler(CallbackQueryHandler(toggle_wishlist, pattern=r'^w\.', block=False))
