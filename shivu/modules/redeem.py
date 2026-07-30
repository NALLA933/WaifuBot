import random
import string
import html
import time
import asyncio
from datetime import datetime, UTC
from typing import Any, Dict
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CommandHandler, ContextTypes
from pymongo.errors import DuplicateKeyError, PyMongoError

from shivu import collection, user_collection, application, db
from shivu.modules.database.sudo import is_user_sudo

LOG_GROUP_ID = -1003110990230
OWNER_ID = 7657218453
CODE_TTL_DAYS = 30

codes_collection = db['redeem_codes']

_rate_cache: Dict[int, float] = {}
_auth_cache: Dict[int, tuple] = {}
AUTH_TTL = 300

CHAR_CAPTION = (
    "🎉 ᴄʜᴀʀᴀᴄᴛᴇʀ ᴜɴʟᴏᴄᴋᴇᴅ!\n\n"
    "👤 𝙉𝙖𝙢𝙚: {name}\n"
    "💮 𝙍𝙖𝙧𝙞𝙩𝙮: {rarity}\n"
    "🎞 𝘼𝙣𝙞𝙢𝙚: {anime}"
)


async def setup_redeem_code_indexes():
    await codes_collection.create_index([("code", 1)], unique=True)
    await codes_collection.create_index(
        [("created_at", 1)], expireAfterSeconds=CODE_TTL_DAYS * 86400, name="code_expiry_index"
    )
    await codes_collection.create_index([("code", 1), ("claimed_by", 1)], name="claim_validation_index")


async def generate_unique_code(attempts: int = 10) -> str:
    for _ in range(attempts):
        p1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        p2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f"SIYA-{p1}-{p2}"
        if not await codes_collection.find_one({'code': code}):
            return code
    p1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"SIYA-{p1}-{int(time.time()) % 10000:04d}"


async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    try:
        await context.bot.send_message(LOG_GROUP_ID, text, parse_mode=ParseMode.HTML)
    except TelegramError as e:
        print(f"Log error: {e}")


async def is_authorized(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    cached = _auth_cache.get(user_id)
    if cached and time.time() - cached[1] < AUTH_TTL:
        return cached[0]
    is_sudo = await is_user_sudo(user_id)
    _auth_cache[user_id] = (is_sudo, time.time())
    return is_sudo


def fmt_amount(amount: float) -> str:
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"


def norm_id(char_id: Any) -> str:
    return str(char_id).strip() if char_id is not None else "unknown"


def safe_waifu(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': norm_id(w.get('id', 'unknown')),
        'name': w.get('name', 'Unknown Character'),
        'img_url': w.get('img_url', ''),
        'rarity': w.get('rarity', 'Common'),
        'anime': w.get('anime', 'Unknown Anime'),
    }


def rate_ok(user_id: int, cooldown: float = 2.0) -> bool:
    now = time.time()
    if now - _rate_cache.get(user_id, 0) < cooldown:
        return False
    _rate_cache[user_id] = now
    return True


async def require_auth(update: Update) -> bool:
    if await is_authorized(update.effective_user.id):
        return True
    await update.message.reply_text("⛔ <b>Access Denied</b>", parse_mode=ParseMode.HTML)
    return False


async def save_code(msg, data: dict) -> bool:
    try:
        await codes_collection.insert_one(data)
        return True
    except DuplicateKeyError:
        await msg.reply_text("⚠️ Code already exists, try again.", parse_mode=ParseMode.HTML)
    except PyMongoError as e:
        await msg.reply_text("❌ Failed to save code.", parse_mode=ParseMode.HTML)
        print(f"DB error: {e}")
    return False


async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not await require_auth(update):
        return
    if len(context.args) < 2:
        await msg.reply_text("Usage: <code>/gen [Amount] [Quantity]</code>", parse_mode=ParseMode.HTML)
        return
    try:
        amount, quantity = float(context.args[0]), int(context.args[1])
        if amount <= 0 or quantity <= 0:
            raise ValueError
    except ValueError:
        await msg.reply_text("❌ Invalid amount/quantity.", parse_mode=ParseMode.HTML)
        return

    code = await generate_unique_code()
    data = {
        'code': code, 'type': 'currency', 'amount': amount, 'quantity': quantity,
        'claimed_by': [], 'created_at': datetime.now(UTC), 'created_by': msg.from_user.id,
    }
    if not await save_code(msg, data):
        return

    fa = fmt_amount(amount)
    await msg.reply_text(
        f"✅ <b>Currency Code Created!</b>\n\n"
        f"🎫 <b>Code:</b> <code>{code}</code>\n💰 <b>Value:</b> {fa}\n"
        f"👥 <b>Claims:</b> {quantity}\n⏰ <b>Expires:</b> {CODE_TTL_DAYS}d",
        parse_mode=ParseMode.HTML
    )
    await send_log(
        context,
        f"📢 <b>#CURRENCY_GEN</b>\nAdmin: {html.escape(msg.from_user.first_name)} (<code>{msg.from_user.id}</code>)\n"
        f"Amount: {fa} | Qty: {quantity}\nCode: <code>{code}</code>"
    )


async def waifu_gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not await require_auth(update):
        return
    if len(context.args) < 2:
        await msg.reply_text("Usage: <code>/sgen [Character_ID] [Quantity]</code>", parse_mode=ParseMode.HTML)
        return
    char_id = norm_id(context.args[0])
    try:
        quantity = int(context.args[1])
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await msg.reply_text("❌ Quantity must be a positive number.", parse_mode=ParseMode.HTML)
        return

    waifu = await collection.find_one({'id': char_id})
    if not waifu:
        await msg.reply_text(f"❌ Character ID <code>{html.escape(char_id)}</code> not found.", parse_mode=ParseMode.HTML)
        return
    waifu_data = safe_waifu(waifu)

    code = await generate_unique_code()
    data = {
        'code': code, 'type': 'character', 'character_id': char_id, 'waifu_data': waifu_data,
        'quantity': quantity, 'claimed_by': [], 'created_at': datetime.now(UTC), 'created_by': msg.from_user.id,
    }
    if not await save_code(msg, data):
        return

    name = html.escape(waifu_data['name'])
    await msg.reply_text(
        f"✅ <b>Character Code Created!</b>\n\n"
        f"🎫 <b>Code:</b> <code>{code}</code>\n👤 <b>Character:</b> {name}\n"
        f"🏷️ <b>ID:</b> <code>{char_id}</code>\n👥 <b>Claims:</b> {quantity}\n⏰ <b>Expires:</b> {CODE_TTL_DAYS}d",
        parse_mode=ParseMode.HTML
    )
    await send_log(
        context,
        f"📢 <b>#CHARACTER_GEN</b>\nAdmin: {html.escape(msg.from_user.first_name)} (<code>{msg.from_user.id}</code>)\n"
        f"Character: {name} (<code>{char_id}</code>)\nCode: <code>{code}</code>"
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user_id = msg.from_user.id

    if not rate_ok(user_id):
        await msg.reply_text("⏳ <b>Wait 2 seconds between redeems.</b>", parse_mode=ParseMode.HTML)
        return
    if not context.args:
        await msg.reply_text("Usage: <code>/redeem SIYA-XXXX-XXXX</code>", parse_mode=ParseMode.HTML)
        return

    code = context.args[0].strip().upper()
    if not code.startswith("SIYA-") or len(code) != 14:
        await msg.reply_text("❌ <b>Invalid code format.</b>", parse_mode=ParseMode.HTML)
        return

    code_info = await codes_collection.find_one({'code': code})
    if not code_info:
        await msg.reply_text("❌ Invalid code. Not found.", parse_mode=ParseMode.HTML)
        return

    result = await codes_collection.update_one(
        {'code': code, 'claimed_by': {'$ne': user_id}, '$expr': {'$lt': [{'$size': '$claimed_by'}, '$quantity']}},
        {'$push': {'claimed_by': user_id}, '$set': {'last_claimed_at': datetime.now(UTC)}}
    )

    if result.modified_count == 0:
        current = await codes_collection.find_one({'code': code})
        if not current:
            await msg.reply_text("❌ Code no longer exists.", parse_mode=ParseMode.HTML)
        elif user_id in current.get('claimed_by', []):
            await msg.reply_text("⚠️ <b>Already Claimed.</b>", parse_mode=ParseMode.HTML)
        elif len(current.get('claimed_by', [])) >= current.get('quantity', 0):
            await msg.reply_text(f"❌ <b>Fully Claimed</b> (limit {current.get('quantity', 0)}).", parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text("❌ Unable to process claim.", parse_mode=ParseMode.HTML)
        return

    try:
        if code_info['type'] == 'currency':
            amount = float(code_info['amount'])
            await user_collection.update_one({'id': user_id}, {'$inc': {'balance': amount}}, upsert=True)
            fa = fmt_amount(amount)
            await msg.reply_text(
                f"🎉 <b>Successfully Redeemed!</b>\n\n💰 <b>Received:</b> {fa} tokens\n"
                f"🔗 <b>Powered by:</b> <a href='https://t.me/AlisaWaifusBot'>AlisaWaifusBot</a>",
                parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
            log_detail = f"Amount: {fa}"

        elif code_info['type'] == 'character':
            w = code_info['waifu_data']
            await user_collection.update_one({'id': user_id}, {'$addToSet': {'characters': w}}, upsert=True)
            caption = CHAR_CAPTION.format(
                name=html.escape(w['name']),
                rarity=w.get('rarity', 'Common'),
                anime=html.escape(w.get('anime', 'Unknown'))
            )
            try:
                if w.get('img_url'):
                    await msg.reply_photo(photo=w['img_url'], caption=caption, parse_mode=ParseMode.HTML)
                else:
                    await msg.reply_text(caption, parse_mode=ParseMode.HTML)
            except TelegramError as e:
                await msg.reply_text(caption, parse_mode=ParseMode.HTML)
                print(f"Photo send error: {e}")
            log_detail = f"Character: {html.escape(w['name'])}"

        else:
            await codes_collection.update_one({'code': code}, {'$pull': {'claimed_by': user_id}})
            await msg.reply_text("❌ Unknown reward type. Reset.", parse_mode=ParseMode.HTML)
            return

    except (PyMongoError, TelegramError, KeyError) as e:
        await codes_collection.update_one({'code': code}, {'$pull': {'claimed_by': user_id}})
        await msg.reply_text("❌ <b>Failed to process reward.</b> Rolled back, try again.", parse_mode=ParseMode.HTML)
        print(f"Reward error: {e}")
        return

    total = len(code_info.get('claimed_by', [])) + 1
    await send_log(
        context,
        f"📢 <b>#REDEEM_LOG</b>\nUser: {html.escape(msg.from_user.first_name)} (<code>{user_id}</code>)\n"
        f"Code: <code>{code}</code>\nReward: {log_detail}\nClaims: {total}/{code_info['quantity']}"
    )


async def revoke_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not await require_auth(update):
        return
    if not context.args:
        await msg.reply_text("Usage: <code>/revoke [Code]</code>", parse_mode=ParseMode.HTML)
        return

    code = context.args[0].strip().upper()
    result = await codes_collection.delete_one({'code': code})
    if result.deleted_count > 0:
        await msg.reply_text(f"🗑️ <b>Code Revoked:</b> <code>{code}</code>", parse_mode=ParseMode.HTML)
        await send_log(
            context,
            f"🗑️ <b>#CODE_REVOKED</b>\nCode: <code>{code}</code>\n"
            f"By: {html.escape(msg.from_user.first_name)} (<code>{msg.from_user.id}</code>)"
        )
    else:
        await msg.reply_text(f"❌ <b>Code Not Found:</b> <code>{code}</code>", parse_mode=ParseMode.HTML)


async def list_codes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not await require_auth(update):
        return
    try:
        codes = await codes_collection.find().sort('created_at', -1).limit(20).to_list(length=20)
    except PyMongoError as e:
        await msg.reply_text("❌ Failed to fetch codes.", parse_mode=ParseMode.HTML)
        print(f"List error: {e}")
        return

    if not codes:
        await msg.reply_text("📭 No active redeem codes.", parse_mode=ParseMode.HTML)
        return

    lines = ["📋 <b>ACTIVE REDEEM CODES</b> (Last 20)", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for i, c in enumerate(codes, 1):
        ctype = c.get('type', 'unknown')
        claimed, total = len(c.get('claimed_by', [])), c.get('quantity', 0)
        if ctype == 'currency':
            reward = f"💰 {fmt_amount(c.get('amount', 0))} tokens"
        elif ctype == 'character':
            reward = f"👤 {html.escape(c.get('waifu_data', {}).get('name', 'Unknown'))}"
        else:
            reward = "❓ Unknown"
        lines += [
            f"<b>#{i}:</b> <code>{c['code']}</code>",
            f"   ┣ <b>Type:</b> {ctype.title()}",
            f"   ┣ <b>Reward:</b> {reward}",
            f"   ┣ <b>Claims:</b> {claimed}/{total}",
            f"   ┗ <b>Created:</b> {c['created_at'].strftime('%Y-%m-%d')}",
            ""
        ]
    lines.append(f"⏰ <i>Codes expire after {CODE_TTL_DAYS} days</i>")
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cleanup_caches():
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        global _rate_cache, _auth_cache
        _rate_cache = {k: v for k, v in _rate_cache.items() if now - v < 7200}
        _auth_cache = {k: v for k, v in _auth_cache.items() if now - v[1] < AUTH_TTL}


application.add_handler(CommandHandler("gen", gen_command, block=False))
application.add_handler(CommandHandler("sgen", waifu_gen_command, block=False))
application.add_handler(CommandHandler("redeem", redeem_command, block=False))
application.add_handler(CommandHandler("sredeem", redeem_command, block=False))
application.add_handler(CommandHandler("revoke", revoke_code_command, block=False))
application.add_handler(CommandHandler("codelist", list_codes_command, block=False))
