import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import importlib
import random
import traceback
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackContext, MessageHandler, filters
from telegram.error import BadRequest

from shivu import db, shivuu, application, LOGGER
from shivu.modules import ALL_MODULES

OWNER_ID = 7657218453
SUDO_USERS = [8949956998]

collection = db['anime_characters_lol']
user_collection = db['user_collection_lmaoooo']
group_user_totals_collection = db['group_user_totalsssssss']
top_global_groups_collection = db['top_global_groups']
rarity_status_collection = db['rarity_status_settings']

MESSAGE_FREQUENCY = 70
DESPAWN_TIME = 180
AMV_ALLOWED_GROUP_ID = -1003100468240

RARITIES = {
    "common": ("🟢", "Common"), "rare": ("🔵", "Rare"), "legendary": ("🟠", "Legendary"),
    "special": ("🟡", "Special Edition"), "celestial": ("🪽", "Celestial"), "erotic": ("🥵", "Erotic"),
    "exclusive": ("🥴", "Exclusive"), "premium": ("💎", "Premium Edition"), "mythic": ("🔮", "Mythic"),
    "sweet": ("🍭", "Sweet"), "valentine": ("💋", "Valentine"), "winter": ("❄️", "Winter"),
    "neon": ("⚡", "Neon"), "pearl": ("🐚", "Pearl"), "cosmic": ("🌌", "Cosmic"),
}

rarity_status_cache = {}
locks, message_counts = {}, {}
sent_characters, last_characters = {}, {}
first_correct_guesses, spawn_messages, spawn_message_links = {}, {}, {}
currently_spawning = {}

for module_name in ALL_MODULES:
    try:
        importlib.import_module("shivu.modules." + module_name)
    except Exception:
        LOGGER.exception(f"Failed loading module {module_name}")


def get_rarity_key(rarity_str):
    if not isinstance(rarity_str, str):
        return None
    rarity_str = rarity_str.strip()
    emoji, name = (rarity_str.split(' ', 1) + [''])[:2] if ' ' in rarity_str else (rarity_str, '')
    name = name.strip().lower()
    for key, (r_emoji, r_name) in RARITIES.items():
        if rarity_str == key or emoji == r_emoji or name == r_name.lower():
            return key
    return None


async def load_rarity_status():
    try:
        doc = await rarity_status_collection.find_one({'_id': 'settings'})
        saved = doc.get('status', {}) if doc else {}
    except Exception:
        saved = {}
    for key in RARITIES:
        rarity_status_cache[key] = saved.get(key, True)
    LOGGER.info(f"Rarity status loaded: {rarity_status_cache}")


async def set_rarity_status(key, enabled):
    rarity_status_cache[key] = enabled
    await rarity_status_collection.update_one(
        {'_id': 'settings'}, {'$set': {f'status.{key}': enabled}}, upsert=True
    )


def is_authorized(user_id):
    return user_id == OWNER_ID or user_id in SUDO_USERS


async def is_character_allowed(character, chat_id=None):
    if character.get('removed', False):
        return False
    rarity = character.get('rarity', '🟢 Common')
    emoji = rarity.split(' ')[0] if isinstance(rarity, str) and ' ' in rarity else rarity
    key = get_rarity_key(rarity)
    if key is not None and not rarity_status_cache.get(key, True):
        return False
    if character.get('is_video', False) and emoji == '🎥':
        return chat_id == AMV_ALLOWED_GROUP_ID
    return True


async def _send_media(context, chat_id, character, caption, **timeouts):
    if character.get('is_video', False):
        return await context.bot.send_video(chat_id=chat_id, video=character.get('img_url'),
                                              caption=caption, parse_mode='HTML',
                                              supports_streaming=True, **timeouts)
    return await context.bot.send_photo(chat_id=chat_id, photo=character.get('img_url'),
                                         caption=caption, parse_mode='HTML', **timeouts)


async def despawn_character(chat_id, message_id, character, context):
    await asyncio.sleep(DESPAWN_TIME)
    try:
        if chat_id in first_correct_guesses:
            return

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass

        rarity = character.get('rarity', '🟢 Common')
        emoji = rarity.split(' ')[0] if isinstance(rarity, str) and ' ' in rarity else '🟢'
        caption = (
            f"⏰ ᴛɪᴍᴇ's ᴜᴘ! ʏᴏᴜ ᴀʟʟ ᴍɪssᴇᴅ ᴛʜɪs ᴡᴀɪғᴜ!\n\n"
            f"{emoji} ɴᴀᴍᴇ: <b>{escape(character.get('name', 'Unknown'))}</b>\n"
            f"⚡ ᴀɴɪᴍᴇ: <b>{escape(character.get('anime', 'Unknown'))}</b>\n"
            f"🎯 ʀᴀʀɪᴛʏ: <b>{escape(rarity)}</b>\n\n"
            f"💔 ʙᴇᴛᴛᴇʀ ʟᴜᴄᴋ ɴᴇxᴛ ᴛɪᴍᴇ!"
        )
        missed_msg = await _send_media(context, chat_id, character, caption)
        await asyncio.sleep(10)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=missed_msg.message_id)
        except BadRequest:
            pass
    except Exception:
        LOGGER.exception(f"despawn_character failed for chat={chat_id}")
    finally:
        last_characters.pop(chat_id, None)
        spawn_messages.pop(chat_id, None)
        spawn_message_links.pop(chat_id, None)
        currently_spawning.pop(str(chat_id), None)


async def message_counter(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type not in ('group', 'supergroup'):
        return
    if not update.message and not update.edited_message:
        return

    chat_id = str(update.effective_chat.id)
    locks.setdefault(chat_id, asyncio.Lock())

    async with locks[chat_id]:
        message_counts[chat_id] = message_counts.get(chat_id, 0) + 1
        LOGGER.info(f"[spawn] chat={chat_id} count={message_counts[chat_id]}/{MESSAGE_FREQUENCY} spawning={currently_spawning.get(chat_id, False)}")

        if message_counts[chat_id] >= MESSAGE_FREQUENCY and not currently_spawning.get(chat_id):
            currently_spawning[chat_id] = True
            message_counts[chat_id] = 0
            asyncio.create_task(send_image(update, context))


async def send_image(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    chat_id_str = str(chat_id)

    try:
        all_characters = await collection.find({}).to_list(length=None)
        if not all_characters:
            LOGGER.warning("[spawn] characters collection is EMPTY - add characters first")
            return

        sent_characters.setdefault(chat_id, [])
        if len(sent_characters[chat_id]) >= len(all_characters):
            sent_characters[chat_id] = []

        available = [c for c in all_characters if c.get('id') not in sent_characters[chat_id]] or all_characters
        allowed = [c for c in available if await is_character_allowed(c, chat_id)]

        if not allowed:
            LOGGER.warning(f"[spawn] no allowed characters for chat={chat_id} — check /rarity_status")
            return

        character = random.choice(allowed)
        sent_characters[chat_id].append(character['id'])
        last_characters[chat_id] = character
        first_correct_guesses.pop(chat_id, None)

        caption = "<b>✨ ᴀ ɴᴇᴡ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀꜱ ᴀᴘᴘᴇᴀʀᴇᴅ!\n✨ᴜꜱᴇ /grab (ɴᴀᴍᴇ) ᴛᴏ ᴀᴅᴅ ɪᴛ ɪɴ ʏᴏᴜʀ ʜᴀʀᴇᴍ."
        timeouts = dict(read_timeout=300, write_timeout=300, connect_timeout=60, pool_timeout=60)
        spawn_msg = await _send_media(context, chat_id, character, caption, **timeouts)

        spawn_messages[chat_id] = spawn_msg.message_id
        username = update.effective_chat.username
        spawn_message_links[chat_id] = (
            f"https://t.me/{username}/{spawn_msg.message_id}" if username
            else f"https://t.me/c/{chat_id_str.replace('-100', '')}/{spawn_msg.message_id}"
        )
        asyncio.create_task(despawn_character(chat_id, spawn_msg.message_id, character, context))
        LOGGER.info(f"[spawn] spawned '{character.get('name')}' in chat={chat_id}")

    except Exception:
        LOGGER.exception(f"[spawn] send_image failed for chat={chat_id}")
    finally:
        currently_spawning[chat_id_str] = False


async def _bump_counter(coll, query, update_fields, inc_field='count', inc_by=1):
    doc = await coll.find_one(query)
    if doc:
        if update_fields:
            await coll.update_one(query, {'$set': update_fields})
        await coll.update_one(query, {'$inc': {inc_field: inc_by}})
    else:
        await coll.insert_one({**query, **update_fields, inc_field: inc_by})


async def guess(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        if chat_id not in last_characters:
            return await update.message.reply_html('<b>ɴᴏ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ʏᴇᴛ!</b>')

        if chat_id in first_correct_guesses:
            return await update.message.reply_html(
                '<b>🚫 ᴡᴀɪғᴜ ᴀʟʀᴇᴀᴅʏ ɢʀᴀʙʙᴇᴅ ʙʏ sᴏᴍᴇᴏɴᴇ ᴇʟsᴇ ⚡. ʙᴇᴛᴛᴇʀ ʟᴜᴄᴋ ɴᴇxᴛ ᴛɪᴍᴇ..!!</b>'
            )

        guess_text = ' '.join(context.args).lower() if context.args else ''
        if not guess_text:
            return await update.message.reply_html('<b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ɴᴀᴍᴇ!</b>')
        if "()" in guess_text or "&" in guess_text:
            return await update.message.reply_html("<b>ɴᴀʜʜ ʏᴏᴜ ᴄᴀɴ'ᴛ ᴜsᴇ ᴛʜɪs ᴛʏᴘᴇs ᴏғ ᴡᴏʀᴅs...❌</b>")

        character = last_characters[chat_id]
        char_name = character.get('name', '').lower()
        name_parts = char_name.split()
        is_correct = (
            sorted(name_parts) == sorted(guess_text.split())
            or guess_text in name_parts
            or guess_text == char_name
        )

        if not is_correct:
            kb = None
            if chat_id in spawn_message_links:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("📍 ᴠɪᴇᴡ sᴘᴀᴡɴ ᴍᴇssᴀɢᴇ", url=spawn_message_links[chat_id])]])
            return await update.message.reply_html('<b>ᴘʟᴇᴀsᴇ ᴡʀɪᴛᴇ ᴀ ᴄᴏʀʀᴇᴄᴛ ɴᴀᴍᴇ..❌</b>', reply_markup=kb)

        first_correct_guesses[chat_id] = user_id
        if chat_id in spawn_messages:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=spawn_messages[chat_id])
            except BadRequest:
                pass
            spawn_messages.pop(chat_id, None)

        eu = update.effective_user
        user_fields = {'first_name': eu.first_name}
        if eu.username:
            user_fields['username'] = eu.username

        user = await user_collection.find_one({'id': user_id})
        if user:
            changed = {k: v for k, v in user_fields.items() if user.get(k) != v}
            if changed:
                await user_collection.update_one({'id': user_id}, {'$set': changed})
            await user_collection.update_one({'id': user_id}, {'$push': {'characters': character}})
        else:
            await user_collection.insert_one({'id': user_id, **user_fields, 'characters': [character]})

        await _bump_counter(group_user_totals_collection, {'user_id': user_id, 'group_id': chat_id}, user_fields)
        await _bump_counter(top_global_groups_collection, {'group_id': chat_id}, {'group_name': update.effective_chat.title})

        rarity = character.get('rarity', '🟢 Common')
        r_emoji, r_name = (rarity.split(' ', 1) + [''])[:2] if isinstance(rarity, str) and ' ' in rarity else (rarity, '')

        success_message = (
            "<b>Congratulation 🎉\n"
            f"{escape(eu.first_name)} 👑 You Got New waifu 🫧\n"
            f"🌸NAME: {escape(character.get('name', 'Unknown'))} [🆔]\n"
            f"🧩ANIME: {escape(character.get('anime', 'Unknown'))}\n"
            f"RAIRTY: {escape(r_emoji)} {escape(r_name)}\n"
            f"IDID: {escape(str(character.get('id', 'Unknown')))}\n\n"
            "⛩ Check your /harem Now</b>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🪼 ʜᴀʀᴇᴍ", switch_inline_query_current_chat=f"collection.{user_id}")]])
        await update.message.reply_text(success_message, parse_mode='HTML', reply_markup=kb)
        spawn_message_links.pop(chat_id, None)

    except Exception:
        LOGGER.exception(f"guess() failed for chat={chat_id}, user={user_id}")


async def rarity_status_cmd(update: Update, context: CallbackContext) -> None:
    lines = ["<b>🎯 Rarity Spawn Status</b>\n"]
    for key, (emoji, name) in RARITIES.items():
        state = "✅ ON" if rarity_status_cache.get(key, True) else "❌ OFF"
        lines.append(f"{emoji} <b>{escape(name)}</b> (<code>{key}</code>) — {state}")
    lines.append("\nUse /rarity_on <key> or /rarity_off <key> to change.")
    await update.message.reply_html("\n".join(lines))


async def _rarity_toggle_cmd(update: Update, context: CallbackContext, enable: bool) -> None:
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_html('<b>🚫 You are not authorized to use this command.</b>')
    if not context.args:
        cmd = "/rarity_on" if enable else "/rarity_off"
        return await update.message.reply_html(f'<b>Usage:</b> {cmd} &lt;rarity_key&gt;')

    key = context.args[0].lower()
    if key not in RARITIES:
        return await update.message.reply_html(f'<b>❌ Unknown rarity key:</b> <code>{escape(key)}</code>')

    await set_rarity_status(key, enable)
    emoji, name = RARITIES[key]
    state = "ENABLED and can spawn" if enable else "DISABLED and will not spawn"
    icon = "✅" if enable else "🚫"
    await update.message.reply_html(f'<b>{icon} {emoji} {escape(name)} rarity is now {state}.</b>')


async def rarity_on_cmd(update, context):
    await _rarity_toggle_cmd(update, context, True)


async def rarity_off_cmd(update, context):
    await _rarity_toggle_cmd(update, context, False)


async def name_cmd(update: Update, context: CallbackContext) -> None:
    if not is_authorized(update.effective_user.id):
        return await update.message.reply_html('<b>🚫 You are not authorized to use this command.</b>')

    chat_id = update.effective_chat.id
    if chat_id not in last_characters:
        return await update.message.reply_html('<b>ɴᴏ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ʏᴇᴛ!</b>')

    c = last_characters[chat_id]
    text = (
        "<b>🎭 CURRENT SPAWNED CHARACTER:</b>\n\n"
        f"<b>🌸 NAME:</b> {escape(c.get('name', 'Unknown'))}\n"
        f"<b>🧩 ANIME:</b> {escape(c.get('anime', 'Unknown'))}\n"
        f"<b>✨ RARITY:</b> {escape(c.get('rarity', '🟢 Common'))}\n"
        f"<b>🆔 ID:</b> {escape(str(c.get('id', 'Unknown')))}\n\n"
        "<b>💡 USE /grab (NAME) TO ADD IT TO YOUR HAREM!</b>"
    )
    await update.message.reply_html(text)


async def main():
    try:
        await load_rarity_status()
        await shivuu.start()

        application.add_handler(CommandHandler(["grab", "g"], guess, block=False))
        application.add_handler(CommandHandler(["rarity_status"], rarity_status_cmd, block=False))
        application.add_handler(CommandHandler(["rarity_on"], rarity_on_cmd, block=False))
        application.add_handler(CommandHandler(["rarity_off"], rarity_off_cmd, block=False))
        application.add_handler(CommandHandler(["name"], name_cmd, block=False))

        # separate group so it never blocks the commands above
        application.add_handler(MessageHandler(filters.ALL, message_counter, block=False), group=1)

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        LOGGER.info("✅ ʏᴏɪᴄʜɪ ʀᴀɴᴅɪ ʙᴏᴛ sᴛᴀʀᴛᴇᴅ")
        await asyncio.Event().wait()

    except Exception:
        LOGGER.exception("Bot crashed!")
        traceback.print_exc()

    finally:
        LOGGER.info("Stopping bot...")
        for coro in (application.updater.stop, application.stop, application.shutdown, shivuu.stop):
            try:
                await coro()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()