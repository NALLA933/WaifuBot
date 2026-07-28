import importlib
import asyncio
import random
import traceback
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackContext, MessageHandler, filters
from telegram.error import BadRequest

from shivu import db, shivuu, application, LOGGER
from shivu.modules import ALL_MODULES


collection = db['anime_characters_lol']
user_collection = db['user_collection_lmaoooo']
group_user_totals_collection = db['group_user_totalsssssss']
top_global_groups_collection = db['top_global_groups']

MESSAGE_FREQUENCY = 70
DESPAWN_TIME = 180
AMV_ALLOWED_GROUP_ID = -1003100468240

locks = {}
message_counts = {}
sent_characters = {}
last_characters = {}
first_correct_guesses = {}
spawn_messages = {}
spawn_message_links = {}
currently_spawning = {}

for module_name in ALL_MODULES:
    try:
        importlib.import_module("shivu.modules." + module_name)
    except Exception:
        pass


async def is_character_allowed(character, chat_id=None):
    try:
        if character.get('removed', False):
            return False

        char_rarity = character.get('rarity', '🟢 Common')
        rarity_emoji = char_rarity.split(' ')[0] if isinstance(char_rarity, str) and ' ' in char_rarity else char_rarity
        is_video = character.get('is_video', False)

        if is_video and rarity_emoji == '🎥':
            return chat_id == AMV_ALLOWED_GROUP_ID

        return True

    except Exception:
        return True


async def despawn_character(chat_id, message_id, character, context):
    try:
        await asyncio.sleep(DESPAWN_TIME)

        if chat_id in first_correct_guesses:
            last_characters.pop(chat_id, None)
            spawn_messages.pop(chat_id, None)
            spawn_message_links.pop(chat_id, None)
            currently_spawning.pop(chat_id, None)
            return

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass

        rarity = character.get('rarity', '🟢 Common')
        rarity_emoji = rarity.split(' ')[0] if isinstance(rarity, str) and ' ' in rarity else '🟢'

        is_video = character.get('is_video', False)
        media_url = character.get('img_url')

        char_name = escape(character.get('name', 'Unknown'))
        char_anime = escape(character.get('anime', 'Unknown'))
        char_rarity = escape(rarity)

        missed_caption = f"""⏰ ᴛɪᴍᴇ's ᴜᴘ! ʏᴏᴜ ᴀʟʟ ᴍɪssᴇᴅ ᴛʜɪs ᴡᴀɪғᴜ!

{rarity_emoji} ɴᴀᴍᴇ: <b>{char_name}</b>
⚡ ᴀɴɪᴍᴇ: <b>{char_anime}</b>
🎯 ʀᴀʀɪᴛʏ: <b>{char_rarity}</b>

💔 ʙᴇᴛᴛᴇʀ ʟᴜᴄᴋ ɴᴇxᴛ ᴛɪᴍᴇ!"""

        if is_video:
            missed_msg = await context.bot.send_video(
                chat_id=chat_id,
                video=media_url,
                caption=missed_caption,
                parse_mode='HTML',
                supports_streaming=True
            )
        else:
            missed_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=media_url,
                caption=missed_caption,
                parse_mode='HTML'
            )

        await asyncio.sleep(10)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=missed_msg.message_id)
        except BadRequest:
            pass

        last_characters.pop(chat_id, None)
        spawn_messages.pop(chat_id, None)
        spawn_message_links.pop(chat_id, None)
        currently_spawning.pop(chat_id, None)

    except Exception:
        pass


async def message_counter(update: Update, context: CallbackContext) -> None:
    try:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return

        if not update.message and not update.edited_message:
            return

        chat_id = update.effective_chat.id
        chat_id_str = str(chat_id)

        if chat_id_str not in locks:
            locks[chat_id_str] = asyncio.Lock()
        lock = locks[chat_id_str]

        async with lock:
            if chat_id_str not in message_counts:
                message_counts[chat_id_str] = 0

            message_counts[chat_id_str] += 1

            if message_counts[chat_id_str] >= MESSAGE_FREQUENCY:
                if chat_id_str not in currently_spawning or not currently_spawning[chat_id_str]:
                    currently_spawning[chat_id_str] = True
                    message_counts[chat_id_str] = 0
                    asyncio.create_task(send_image(update, context))

    except Exception:
        pass


async def send_image(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    try:
        all_characters = list(await collection.find({}).to_list(length=None))

        if not all_characters:
            currently_spawning[str(chat_id)] = False
            return

        if chat_id not in sent_characters:
            sent_characters[chat_id] = []

        if len(sent_characters[chat_id]) >= len(all_characters):
            sent_characters[chat_id] = []

        available_characters = [
            c for c in all_characters
            if 'id' in c and c.get('id') not in sent_characters[chat_id]
        ]

        if not available_characters:
            available_characters = all_characters
            sent_characters[chat_id] = []

        allowed_characters = []
        for char in available_characters:
            if await is_character_allowed(char, chat_id):
                allowed_characters.append(char)

        if not allowed_characters:
            currently_spawning[str(chat_id)] = False
            return

        character = random.choice(allowed_characters)

        sent_characters[chat_id].append(character['id'])
        last_characters[chat_id] = character

        if chat_id in first_correct_guesses:
            del first_correct_guesses[chat_id]

        caption = """✨ ʟᴏᴏᴋ! ᴀ ᴡᴀɪꜰᴜ ʜᴀꜱ ᴀᴘᴘᴇᴀʀᴇᴅ ✨
✦ ᴍᴀᴋᴇ ʜᴇʀ ʏᴏᴜʀꜱ — ᴛʏᴘᴇ /ɢʀᴀʙ &lt;ᴡᴀɪꜰᴜ_ɴᴀᴍᴇ&gt;

⏳ ᴛɪᴍᴇ ʟɪᴍɪᴛ: 3 ᴍɪɴᴜᴛᴇꜱ!"""

        is_video = character.get('is_video', False)
        media_url = character.get('img_url')

        if is_video:
            spawn_msg = await context.bot.send_video(
                chat_id=chat_id,
                video=media_url,
                caption=caption,
                parse_mode='HTML',
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300,
                connect_timeout=60,
                pool_timeout=60
            )
        else:
            spawn_msg = await context.bot.send_photo(
                chat_id=chat_id,
                photo=media_url,
                caption=caption,
                parse_mode='HTML',
                read_timeout=180,
                write_timeout=180
            )

        spawn_messages[chat_id] = spawn_msg.message_id

        chat_username = update.effective_chat.username
        if chat_username:
            spawn_message_links[chat_id] = f"https://t.me/{chat_username}/{spawn_msg.message_id}"
        else:
            chat_id_str = str(chat_id).replace('-100', '')
            spawn_message_links[chat_id] = f"https://t.me/c/{chat_id_str}/{spawn_msg.message_id}"

        currently_spawning[str(chat_id)] = False

        asyncio.create_task(despawn_character(chat_id, spawn_msg.message_id, character, context))

    except Exception:
        currently_spawning[str(chat_id)] = False


async def guess(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    try:
        if chat_id not in last_characters:
            await update.message.reply_html('<b>ɴᴏ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ʏᴇᴛ!</b>')
            return

        if chat_id in first_correct_guesses:
            await update.message.reply_html(
                '<b>🚫 ᴡᴀɪғᴜ ᴀʟʀᴇᴀᴅʏ ɢʀᴀʙʙᴇᴅ ʙʏ sᴏᴍᴇᴏɴᴇ ᴇʟsᴇ ⚡. ʙᴇᴛᴛᴇʀ ʟᴜᴄᴋ ɴᴇxᴛ ᴛɪᴍᴇ..!!</b>'
            )
            return

        guess_text = ' '.join(context.args).lower() if context.args else ''

        if not guess_text:
            await update.message.reply_html('<b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ɴᴀᴍᴇ!</b>')
            return

        if "()" in guess_text or "&" in guess_text:
            await update.message.reply_html(
                "<b>ɴᴀʜʜ ʏᴏᴜ ᴄᴀɴ'ᴛ ᴜsᴇ ᴛʜɪs ᴛʏᴘᴇs ᴏғ ᴡᴏʀᴅs...❌</b>"
            )
            return

        character_name = last_characters[chat_id].get('name', '').lower()
        name_parts = character_name.split()

        is_correct = (
            sorted(name_parts) == sorted(guess_text.split()) or
            any(part == guess_text for part in name_parts) or
            guess_text == character_name
        )

        if is_correct:
            first_correct_guesses[chat_id] = user_id

            if chat_id in spawn_messages:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=spawn_messages[chat_id])
                except BadRequest:
                    pass
                spawn_messages.pop(chat_id, None)

            user = await user_collection.find_one({'id': user_id})
            if user:
                update_fields = {}
                if hasattr(update.effective_user, 'username') and update.effective_user.username:
                    if update.effective_user.username != user.get('username'):
                        update_fields['username'] = update.effective_user.username
                if update.effective_user.first_name != user.get('first_name'):
                    update_fields['first_name'] = update.effective_user.first_name

                if update_fields:
                    await user_collection.update_one({'id': user_id}, {'$set': update_fields})

                await user_collection.update_one(
                    {'id': user_id},
                    {'$push': {'characters': last_characters[chat_id]}}
                )
            else:
                await user_collection.insert_one({
                    'id': user_id,
                    'username': getattr(update.effective_user, 'username', None),
                    'first_name': update.effective_user.first_name,
                    'characters': [last_characters[chat_id]],
                })

            group_user_total = await group_user_totals_collection.find_one({
                'user_id': user_id,
                'group_id': chat_id
            })

            if group_user_total:
                update_fields = {}
                if hasattr(update.effective_user, 'username') and update.effective_user.username:
                    if update.effective_user.username != group_user_total.get('username'):
                        update_fields['username'] = update.effective_user.username
                if update.effective_user.first_name != group_user_total.get('first_name'):
                    update_fields['first_name'] = update.effective_user.first_name

                if update_fields:
                    await group_user_totals_collection.update_one(
                        {'user_id': user_id, 'group_id': chat_id},
                        {'$set': update_fields}
                    )

                await group_user_totals_collection.update_one(
                    {'user_id': user_id, 'group_id': chat_id},
                    {'$inc': {'count': 1}}
                )
            else:
                await group_user_totals_collection.insert_one({
                    'user_id': user_id,
                    'group_id': chat_id,
                    'username': getattr(update.effective_user, 'username', None),
                    'first_name': update.effective_user.first_name,
                    'count': 1,
                })

            group_info = await top_global_groups_collection.find_one({'group_id': chat_id})
            if group_info:
                update_fields = {}
                if update.effective_chat.title != group_info.get('group_name'):
                    update_fields['group_name'] = update.effective_chat.title

                if update_fields:
                    await top_global_groups_collection.update_one(
                        {'group_id': chat_id},
                        {'$set': update_fields}
                    )

                await top_global_groups_collection.update_one(
                    {'group_id': chat_id},
                    {'$inc': {'count': 1}}
                )
            else:
                await top_global_groups_collection.insert_one({
                    'group_id': chat_id,
                    'group_name': update.effective_chat.title,
                    'count': 1,
                })

            character = last_characters[chat_id]
            keyboard = [[
                InlineKeyboardButton(
                    "🪼 ʜᴀʀᴇᴍ",
                    switch_inline_query_current_chat=f"collection.{user_id}"
                )
            ]]

            character_name = character.get('name', 'Unknown')
            anime = character.get('anime', 'Unknown')
            rarity = character.get('rarity', '🟢 Common')
            character_id = character.get('id', 'Unknown')
            owner_name = update.effective_user.first_name

            success_message = f"""🎊 ᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴs! ɴᴇᴡ ᴄʜᴀʀᴀᴄᴛᴇʀ ᴜɴʟᴏᴄᴋᴇᴅ 🎊
╭════════•┈┈┈┈•════════╮
┃ ✦ ɴᴀᴍᴇ: 𓂃ࣰࣲ {escape(character_name)}
┃ ✦ ʀᴀʀɪᴛʏ: {escape(rarity)}
┃ ✦ ᴀɴɪᴍᴇ: {escape(anime)}
┃ ✦ ɪᴅ: 🆔 {escape(str(character_id))}
┃ ✦ ꜱᴛᴀᴛᴜꜱ: ᴀᴅᴅᴇᴅ ᴛᴏ ʜᴀʀᴇᴍ ✅
┃ ✦ ᴏᴡɴᴇʀ: ✧ {escape(owner_name)}
╰════════•┈┈┈┈•════════╯

✧ ᴄʜᴀʀᴀᴄᴛᴇʀ ꜱᴜᴄᴄᴇꜱꜰᴜʟʟʏ ᴀᴅᴅᴇᴅ ɪɴ ʏᴏᴜʀ ʜᴀʀᴇᴍ ✅"""

            await update.message.reply_text(
                success_message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            spawn_message_links.pop(chat_id, None)

        else:
            keyboard = []
            if chat_id in spawn_message_links:
                keyboard.append([
                    InlineKeyboardButton(
                        "📍 ᴠɪᴇᴡ sᴘᴀᴡɴ ᴍᴇssᴀɢᴇ",
                        url=spawn_message_links[chat_id]
                    )
                ])

            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await update.message.reply_html(
                '<b>ᴘʟᴇᴀsᴇ ᴡʀɪᴛᴇ ᴀ ᴄᴏʀʀᴇᴄᴛ ɴᴀᴍᴇ..❌</b>',
                reply_markup=reply_markup
            )

    except Exception:
        pass





async def main():
    """Main async entry point"""

    try:
        # Start Pyrogram client
        await shivuu.start()

        # Register handlers
        application.add_handler(
            CommandHandler(["grab", "g"], guess, block=False)
        )
        application.add_handler(
            MessageHandler(filters.ALL, message_counter, block=False)
        )

        # Start Telegram Bot API application
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        LOGGER.info("✅ ʏᴏɪᴄʜɪ ʀᴀɴᴅɪ ʙᴏᴛ sᴛᴀʀᴛᴇᴅ")

        # Keep the bot running
        await asyncio.Event().wait()

    except Exception as e:
        LOGGER.exception("Bot crashed!")
        traceback.print_exc()

    finally:
        LOGGER.info("Stopping bot...")

        try:
            await application.updater.stop()
        except Exception:
            pass

        try:
            await application.stop()
        except Exception:
            pass

        try:
            await application.shutdown()
        except Exception:
            pass

        try:
            await shivuu.stop()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())