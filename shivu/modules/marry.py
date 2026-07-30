import asyncio
import random
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext
from shivu import application, user_collection, collection, LOGGER

# NOTE: adjust this import to match wherever RARITIES/rarity_display actually live
# (e.g. shivu.modules.harem). Centralizing here stops rarity strings from
# silently drifting out of sync with what's stored in the DB.
from shivu.modules.hstyle import RARITIES, rarity_display

# ---------------- CONFIG ----------------
OWNER_ID = 7657218453
SUDO_USERS = {8949956998}

PROPOSAL_COST = 2000
DICE_COOLDOWN = 1800
PROPOSE_COOLDOWN = 300
PROPOSE_SUCCESS_RATE = 0.5  # 1/6 win chance (half of dice's 2/6)

UPDATE_CHANNEL = "@Anime_Group_hai"
UPDATE_CHANNEL_URL = "https://t.me/Anime_Group_hai"  # must be SAME channel as above
LOG_GROUP_ID = -1003139865857

PROPOSE_IMAGES = ["https://files.catbox.moe/nvx2um.jpg", "https://files.catbox.moe/vaz41p.jpg", "https://files.catbox.moe/a0ybe8.jpg", "https://files.catbox.moe/5z3vgb.jpg"]
REJECT_IMAGES = ["https://files.catbox.moe/b9l3ot.jpg", "https://files.catbox.moe/yjygaj.jpg", "https://files.catbox.moe/8ezqu8.jpg"]

DICE_RARITIES = [rarity_display(k) for k in ("common", "rare", "legendary")]
PROPOSE_RARITIES = [rarity_display(k) for k in ("celestial", "exclusive")]

cooldowns = {"dice": {}, "propose": {}}


# ---------------- HELPERS ----------------
def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in SUDO_USERS


def check_cooldown(user_id: int, cmd: str, seconds: int) -> tuple[bool, int]:
    last = cooldowns[cmd].get(user_id, 0)
    left = int(seconds - (time.time() - last))
    if left > 0:
        return False, left
    cooldowns[cmd][user_id] = time.time()
    return True, 0


async def is_user_joined(context: CallbackContext, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(UPDATE_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        LOGGER.error(f"is_user_joined failed for {user_id}: {e}")
        return False


async def get_unique_char(user_id: int, rarities: list[str]):
    """Return one random character not already owned by the user, or None."""
    try:
        user = await user_collection.find_one({"id": user_id}) or {}
        owned = [c.get("id") for c in user.get("characters", [])]
        pipeline = [
            {"$match": {"rarity": {"$in": rarities}, "id": {"$nin": owned}}},
            {"$sample": {"size": 1}},
        ]
        result = await collection.aggregate(pipeline).to_list(length=1)
        return result[0] if result else None
    except Exception as e:
        LOGGER.error(f"get_unique_char failed for {user_id}: {e}")
        return None


async def add_char_to_user(user_id: int, username: str, first_name: str, char: dict) -> bool:
    try:
        await user_collection.update_one(
            {"id": user_id},
            {"$push": {"characters": char}, "$set": {"username": username, "first_name": first_name}},
            upsert=True,
        )
        return True
    except Exception as e:
        LOGGER.error(f"add_char_to_user failed for {user_id}: {e}")
        return False


async def send_win_log(context: CallbackContext, user, char: dict, method: str):
    text = (
        "<b>🏆 ɴᴇᴡ ᴄʜᴀʀᴀᴄᴛᴇʀ ᴄʟᴀɪᴍᴇᴅ!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>👤 ᴜsᴇʀ:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"<b>🕹️ ᴍᴇᴛʜᴏᴅ:</b> <code>/{method}</code>\n"
        f"<b>🌸 ɴᴀᴍᴇ:</b> {char['name']}\n"
        f"<b>💎 ʀᴀʀɪᴛʏ:</b> <code>{char['rarity']}</code>\n━━━━━━━━━━━━━━━━━━━━"
    )
    try:
        await context.bot.send_photo(LOG_GROUP_ID, char["img_url"], caption=text, parse_mode="HTML")
    except Exception as e:
        LOGGER.error(f"send_win_log failed: {e}")


# ---------------- /dice, /marry ----------------
async def dice_marry(update: Update, context: CallbackContext):
    user = update.effective_user
    ok, rem = check_cooldown(user.id, "dice", DICE_COOLDOWN)
    if not ok:
        return await update.message.reply_text(f"⏳ ᴡᴀɪᴛ <b>{rem // 60}ᴍ {rem % 60}s</b>", parse_mode="HTML")

    val = (await context.bot.send_dice(update.effective_chat.id, emoji="🎲")).dice.value
    await asyncio.sleep(3.5)

    if val not in (1, 6):
        return await update.message.reply_text(f"🎲 ᴅɪᴄᴇ: <b>{val}</b>\nʏᴏᴜʀ ᴍᴀʀʀɪᴀɢᴇ ᴘʀᴏᴘᴏꜱᴀʟ ᴡᴀꜱ ʀᴇᴊᴇᴄᴛᴇᴅ ᴀɴᴅ ꜱʜᴇ ʀᴀɴ ᴀᴡᴀʏ!", parse_mode="HTML")

    char = await get_unique_char(user.id, DICE_RARITIES)
    if not char:
        return await update.message.reply_text("🎲 ʏᴏᴜ ᴡᴏɴ, ʙᴜᴛ ɴᴏ ɴᴇᴡ ᴄʜᴀʀᴀᴄᴛᴇʀs ʟᴇғᴛ ᴛᴏ ᴄʟᴀɪᴍ!")

    await add_char_to_user(user.id, user.username, user.first_name, char)
    caption = (
        f"<b>🎲 ᴅɪᴄᴇ ʀᴇsᴜʟᴛ: {val}</b>\nᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴs <a href='tg://user?id={user.id}'>{user.first_name}</a>!\n"
        f"ɴᴀᴍᴇ: <b>{char['name']}</b>\nʀᴀʀɪᴛʏ: <b>{char['rarity']}</b>"
    )
    await update.message.reply_photo(char["img_url"], caption=caption, parse_mode="HTML")
    await send_win_log(context, user, char, "dice")


# ---------------- /propose ----------------
async def propose(update: Update, context: CallbackContext):
    user = update.effective_user

    if not await is_user_joined(context, user.id):
        btn = [[InlineKeyboardButton("📢 ᴊᴏɪɴ ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ", url=UPDATE_CHANNEL_URL)]]
        return await update.message.reply_text(
            "<b>⚠️ ᴀᴄᴄᴇss ʟᴏᴄᴋᴇᴅ!</b>\n\nᴊᴏɪɴ ᴏᴜʀ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.",
            reply_markup=InlineKeyboardMarkup(btn), parse_mode="HTML",
        )

    user_data = await user_collection.find_one({"id": user.id})
    if not user_data or user_data.get("balance", 0) < PROPOSAL_COST:
        return await update.message.reply_text("ʏᴏᴜ ɴᴇᴇᴅ ᴀᴛ ʟᴇᴀꜱᴛ 2000 ᴛᴏᴋᴇɴꜱ ᴛᴏ ᴘʀᴏᴘᴏꜱᴇ.", parse_mode="HTML")

    ok, rem = check_cooldown(user.id, "propose", PROPOSE_COOLDOWN)
    if not ok:
        return await update.message.reply_text(f"⏳ ᴄᴏᴏʟᴅᴏᴡɴ: <code>{rem // 60}ᴍ {rem % 60}s</code>", parse_mode="HTML")

    await user_collection.update_one({"id": user.id}, {"$inc": {"balance": -PROPOSAL_COST}})

    msg = await update.message.reply_photo(
        random.choice(PROPOSE_IMAGES), caption="<b>✨ ꜰɪɴᴀʟʟʏ ᴛʜᴇ ᴛɪᴍᴇ ʜᴀꜱ ᴄᴏᴍᴇ ✨</b>", parse_mode="HTML"
    )
    await asyncio.sleep(3)

    if random.random() > PROPOSE_SUCCESS_RATE:
        await msg.delete()
        return await update.message.reply_photo(
            random.choice(REJECT_IMAGES),
            caption=f"<b>ʏᴏᴜ'ᴠᴇ ʙᴇᴇɴ ꜰʀɪᴇɴᴅ-ᴢᴏɴᴇᴅ ꜱᴏ ʜᴀʀᴅ, ʏᴏᴜ'ʀᴇ ɴᴏᴡ ᴛʜᴇ ᴍᴀʏᴏʀ ᴏꜰ ꜰʀɪᴇɴᴅ ᴢᴏɴᴇ ᴄɪᴛʏ! 🏙️!</b>",
            parse_mode="HTML",
        )

    char = await get_unique_char(user.id, PROPOSE_RARITIES)
    if not char:
        await user_collection.update_one({"id": user.id}, {"$inc": {"balance": PROPOSAL_COST}})
        return await msg.edit_caption(caption="ʀᴇғᴜɴᴅᴇᴅ! ɴᴏ ʀᴀʀᴇ ᴄʜᴀʀs ʟᴇғᴛ.")

    await add_char_to_user(user.id, user.username, user.first_name, char)
    await msg.delete()
    caption = (
        f"<b>{char['name']} ʜᴀꜱ ᴀᴄᴄᴇᴘᴛᴇᴅ ʏᴏᴜʀ ᴘʀᴏᴘᴏꜱᴀʟ! 😇</b>\n"
        f"☘️ 𝙉𝙖𝙢𝙚: {char['name']}\n"
        f"🵿 𝙍𝙖𝙧𝙞𝙩𝙮: {char['rarity']}\n"
        f"💠 𝘼𝙣𝙞𝙢𝙚: {char.get('anime', 'Unknown')}\n"
        f"🆔 ɪᴅ: <code>{char['id']}</code>"
    )
    await update.message.reply_photo(char["img_url"], caption=caption, parse_mode="HTML")
    await send_win_log(context, user, char, "propose")


# ---------------- /cdm (owner/sudo) ----------------
async def cdm_cmd(update: Update, context: CallbackContext):
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_text("🚫 You are not authorized to use this command.")

    reply = update.message.reply_to_message
    target_id = reply.from_user.id if reply and reply.from_user else None
    if target_id is None and context.args:
        target_id = int(context.args[0]) if context.args[0].isdigit() else None

    if target_id is None:
        return await update.message.reply_text("Usage: /cdm <user_id> (or reply to the user's message)")

    cooldowns["dice"].pop(target_id, None)
    cooldowns["propose"].pop(target_id, None)
    await update.message.reply_text(f"COOLDOWN RESET FOR USER {target_id} (MARRY & PROPOSE).")


# ---------------- HANDLERS ----------------
application.add_handler(CommandHandler(["dice", "marry"], dice_marry, block=False))
application.add_handler(CommandHandler(["propose"], propose, block=False))
application.add_handler(CommandHandler(["cdm"], cdm_cmd, block=False))
