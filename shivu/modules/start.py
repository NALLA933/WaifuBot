import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler
from shivu import application, SUPPORT_CHAT, UPDATE_CHAT, BOT_USERNAME, LOGGER, user_collection

START_VIDEO = "https://graph.org/file/e668451eba24048fe880c-8cefbbe834e0f673d8.mp4"
FORCE_SUB_CHAT = "anime_group_hai"

MAIN_CAPTION = (
    f"✨ ʜᴇʏ ᴛʜᴇʀᴇ! ɪ'ᴍ {BOT_USERNAME}, ʏᴏᴜʀ ᴜʟᴛɪᴍᴀᴛᴇ ᴀɴɪᴍᴇ ᴀᴅᴠᴇɴᴛᴜʀᴇ ᴄᴏᴍᴘᴀɴɪᴏɴ. "
    f"ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴀɴᴅ ʟᴇᴛ ᴛʜᴇ ғᴜɴ ʙᴇɢɪɴ!"
)
MAIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("sᴜᴘᴘᴏʀᴛ", url=f'https://t.me/{SUPPORT_CHAT}'),
     InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url=f'https://t.me/{UPDATE_CHAT}')],
    [InlineKeyboardButton("sᴛᴀʀᴛ ɢᴜᴇssɪɴɢ💫", url=f'https://t.me/{BOT_USERNAME}?startgroup=new')],
    [InlineKeyboardButton("ʜᴇʟᴘ", callback_data='sxc_help'),
     InlineKeyboardButton("ᴄʀᴇᴅɪᴛs", callback_data='sxc_credits')]
])

FORCE_SUB_TEXT = "🔒 <b>Join our updates channel to use this bot!</b>"
FORCE_SUB_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("Join Channel", url=f'https://t.me/{FORCE_SUB_CHAT}')],
    [InlineKeyboardButton("Try Again", callback_data='sxc_checksub')]
])

PAGE_SIZE = 6
CATEGORIES = {
    "basic": ("Basic Commands", [
        ("/start", "Start the bot"),
        ("/grab", "Grab the character"),
        ("/fav", "Add a character to your favourite"),
        ("/swaifu", "claim your daily waifu"),
        ("/pay", "Give cash💸 to other users"),
        ("/bal", "See your balence"),
        ("/harem", "See your character's collection"),
        ("/gift", "Gift your waifu to someone 🎀"),
        ("/trade", "Trade characters between users"),
        ("/tops", "View the leaderboard"),
        ("/sprofile", "View your profile"),
        ("/changetime", "Change the spawn time of characters [Owner/Admins]"),
    ]),
    "interactive": ("Interactive Commands", [
        ("/claim", "Claim your daily reward"),
        ("/roll", "Gamble your gold"),
        ("/refer", "Invite friends and earn rewards"),
    ]),
    "sudo": ("Sudo Commands", [
        ("/broadcast", "Broadcast a message to all users"),
        ("/addsudo", "Add a sudo user"),
        ("/removesudo", "Remove a sudo user"),
        ("/ban", "Ban a user from the bot"),
        ("/unban", "Unban a user"),
        ("/stats", "View bot statistics"),
    ]),
}




async def is_force_sub_member(user_id, context: CallbackContext):
    try:
        member = await context.bot.get_chat_member(f"@{FORCE_SUB_CHAT}", user_id)
        return member.status not in ('left', 'kicked')
    except Exception as e:
        LOGGER.warning(f"Force-sub check failed for {user_id}: {e}")
        return True


def menu_view():
    kb = [
        [InlineKeyboardButton("Basic", callback_data='sxc_cat_basic'),
         InlineKeyboardButton("Interactive", callback_data='sxc_cat_interactive')],
        [InlineKeyboardButton("🌿 Sudo", callback_data='sxc_cat_sudo')],
        [InlineKeyboardButton("Main Menu", callback_data='sxc_back')]
    ]
    return "<b>Help Menu</b>\n\nSelect a category to view commands:", InlineKeyboardMarkup(kb)


def category_view(cat_key: str, page: int = 1):
    title, commands = CATEGORIES[cat_key]
    total_pages = max(1, -(-len(commands) // PAGE_SIZE))
    page = max(1, min(page, total_pages))
    chunk = commands[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    text = f"<b>{title} {page}/{total_pages}</b>\n\n" + "\n".join(
        f"• <code>{cmd}</code> - {desc}" for cmd, desc in chunk
    )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("Previous", callback_data=f'sxc_pg_{cat_key}_{page - 1}'))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next", callback_data=f'sxc_pg_{cat_key}_{page + 1}'))

    kb = ([nav] if nav else []) + [[InlineKeyboardButton("Back to Help Menu", callback_data='sxc_menu')]]
    return text, InlineKeyboardMarkup(kb)

CREDITS_USERS = [
    ("ＩＭ 𖣘 ＵＣＨＩＨＡ", "iMSASUKESi", 7657218453),  # replace with real numeric id
]

async def credits_view(context: CallbackContext):
    kb = []
    for name, username, user_id in CREDITS_USERS:
        url = f'tg://user?id={user_id}'
        kb.append([InlineKeyboardButton(f"{name}", url=url)])
    kb.append([InlineKeyboardButton("BACK", callback_data='sxc_back')])
    return "𝗦𝘂𝗱𝗼:", InlineKeyboardMarkup(kb)
def _new_user_doc(user_id, first_name, username):
    return {
        "id": user_id, "first_name": first_name, "username": username,
        "balance": 500, "characters": [],
        "pass_data": {
            "tier": "free", "weekly_claims": 0, "last_weekly_claim": None,
            "streak_count": 0, "last_streak_claim": None,
            "tasks": {"weekly_claims": 0, "grabs": 0},
            "mythic_unlocked": False, "premium_expires": None,
            "elite_expires": None, "pending_elite_payment": None
        }
    }


async def _ensure_user(user_id, first_name, username):
    """Returns True if this is a newly created user."""
    user_data = await user_collection.find_one({"id": user_id})
    if user_data:
        await user_collection.update_one(
            {"id": user_id}, {"$set": {"first_name": first_name, "username": username}}
        )
        return False
    await user_collection.insert_one(_new_user_doc(user_id, first_name, username))
    return True


async def safe_track_bot_start(user_id, first_name, username, is_new_user):
    try:
        from shivu.modules.chatlog import track_bot_start
        await asyncio.wait_for(track_bot_start(user_id, first_name, username, is_new_user), timeout=5.0)
    except asyncio.TimeoutError:
        LOGGER.warning(f"track_bot_start timed out for user {user_id}")
    except ImportError:
        LOGGER.warning("chatlog module not available, skipping bot start tracking")
    except Exception as e:
        LOGGER.error(f"Error in safe_track_bot_start: {e}")


async def start(update: Update, context: CallbackContext):
    try:
        if not update or not update.effective_user:
            return

        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "User"
        username = update.effective_user.username or ""

        if not await is_force_sub_member(user_id, context):
            await update.message.reply_text(FORCE_SUB_TEXT, parse_mode='HTML', reply_markup=FORCE_SUB_KEYBOARD)
            return

        is_new = await _ensure_user(user_id, first_name, username)
        context.application.create_task(safe_track_bot_start(user_id, first_name, username, is_new))

        await update.message.reply_video(
            video=START_VIDEO, caption=MAIN_CAPTION, reply_markup=MAIN_KEYBOARD,
            parse_mode='HTML', supports_streaming=True
        )

    except Exception as e:
        LOGGER.error(f"Critical error in start command: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ An error occurred. Please try again later.")
        except Exception:
            pass


async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Error answering callback query: {e}")
        return

    try:
        data = query.data
        user_id = query.from_user.id

        if data == 'sxc_checksub':
            if not await is_force_sub_member(user_id, context):
                await query.answer("⚠️ You haven't joined yet!", show_alert=True)
                return
            first_name = query.from_user.first_name or "User"
            username = query.from_user.username or ""
            await _ensure_user(user_id, first_name, username)
            await query.message.delete()
            await context.bot.send_video(
                chat_id=user_id, video=START_VIDEO, caption=MAIN_CAPTION,
                reply_markup=MAIN_KEYBOARD, parse_mode='HTML', supports_streaming=True
            )
            return

        if not await is_force_sub_member(user_id, context):
            await query.answer("⚠️ Join our channel first!", show_alert=True)
            return

        if not await user_collection.find_one({"id": user_id}):
            await query.answer("⚠️ sᴛᴀʀᴛ ʙᴏᴛ ғɪʀsᴛ", show_alert=True)
            return

        if data == 'sxc_credits':
            text, markup = await credits_view(context)
        elif data in ('sxc_help', 'sxc_menu'):
            text, markup = menu_view()
        elif data.startswith('sxc_cat_'):
            cat_key = data[len('sxc_cat_'):]
            if cat_key not in CATEGORIES:
                await query.answer("⚠️ Unknown category", show_alert=True)
                return
            text, markup = category_view(cat_key)
        elif data.startswith('sxc_pg_'):
            cat_key, _, page_str = data[len('sxc_pg_'):].rpartition('_')
            if cat_key not in CATEGORIES or not page_str.isdigit():
                await query.answer("⚠️ Unknown page", show_alert=True)
                return
            text, markup = category_view(cat_key, int(page_str))
        elif data == 'sxc_back':
            text, markup = MAIN_CAPTION, MAIN_KEYBOARD
        else:
            return

        await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=markup)

    except Exception as e:
        LOGGER.error(f"Error in button callback: {e}", exc_info=True)
        try:
            await query.answer("⚠️ An error occurred. Please try again.", show_alert=True)
        except Exception:
            pass


application.add_handler(CommandHandler('start', start, block=False))
application.add_handler(CallbackQueryHandler(button_callback, pattern=r'^sxc_', block=False))

LOGGER.info("✓ Start module loaded successfully")
