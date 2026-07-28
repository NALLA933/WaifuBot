import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler
from shivu import application, SUPPORT_CHAT, BOT_USERNAME, LOGGER, user_collection
from shivu.modules.chatlog import track_bot_start
from shivu.modules.database.sudo import fetch_sudo_users
import asyncio

VIDEOS = [
    "https://graph.org/file/fe64e239291abea3641fc-d6e78366c4d534a7c3.mp4"
]

START_VIDEO = "https://graph.org/file/fe64e239291abea3641fc-d6e78366c4d534a7c3.mp4"

OWNERS = [{"name": "Thorfinn", "username": "ll_Thorfinn_ll"}]
SUDO_USERS = [{"name": "Shadwoo", "username": "I_shadwoo"}]

HELP_PAGE_SIZE = 3

HELP_CATEGORIES = {
    "basic": {
        "title": "Basic Commands",
        "commands": [
            ("/start", "Start the bot"),
            ("/grab", "Guess the character"),
            ("/fav", "Add a character to your favourite"),
            ("/harem", "View your collection"),
            ("/bal", "Check your wallet"),
            ("/pay", "Send gold to other users"),
        ],
    },
    "interactive": {
        "title": "Interactive Commands",
        "commands": [
            ("/trade", "Trade characters with others"),
            ("/gift", "Gift a character to someone"),
            ("/claim", "Claim your daily reward"),
            ("/roll", "Gamble your gold"),
            ("/refer", "Invite friends and earn rewards"),
        ],
    },
    "sudo": {
        "title": "Sudo Commands",
        "commands": [
            ("/broadcast", "Broadcast a message to all users"),
            ("/addsudo", "Add a sudo user"),
            ("/removesudo", "Remove a sudo user"),
            ("/ban", "Ban a user from the bot"),
            ("/unban", "Unban a user"),
            ("/stats", "View bot statistics"),
        ],
    },
}


def build_help_menu_view():
    text = "<b>Help Menu</b>\n\nSelect a category to view commands:"
    keyboard = [
        [
            InlineKeyboardButton("Basic", callback_data='help_cat_basic'),
            InlineKeyboardButton("Interactive", callback_data='help_cat_interactive')
        ],
        [InlineKeyboardButton("🌿 Sudo", callback_data='help_cat_sudo')],
        [InlineKeyboardButton("Main Menu", callback_data='back')]
    ]
    return text, InlineKeyboardMarkup(keyboard)


def build_help_category_view(cat_key: str, page: int = 1):
    category = HELP_CATEGORIES[cat_key]
    commands = category["commands"]
    total_pages = max(1, -(-len(commands) // HELP_PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * HELP_PAGE_SIZE
    page_commands = commands[start_idx:start_idx + HELP_PAGE_SIZE]

    lines = [f"<b>{category['title']} {page}/{total_pages}</b>", ""]
    for cmd, desc in page_commands:
        lines.append(f"• <code>{cmd}</code> - {desc}")
    text = "\n".join(lines)

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("Previous", callback_data=f'help_page_{cat_key}_{page - 1}'))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next", callback_data=f'help_page_{cat_key}_{page + 1}'))

    keyboard = []
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("Back to Help Menu", callback_data='help_menu')])

    return text, InlineKeyboardMarkup(keyboard)


async def safe_track_bot_start(user_id: int, first_name: str, username: str, is_new_user: bool):
    try:
        from shivu.modules.chatlog import track_bot_start
        await asyncio.wait_for(
            track_bot_start(user_id, first_name, username, is_new_user),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        LOGGER.warning(f"track_bot_start timed out for user {user_id}")
    except ImportError:
        LOGGER.warning("chatlog module not available, skipping bot start tracking")
    except Exception as e:
        LOGGER.error(f"Error in safe_track_bot_start: {e}")

async def start(update: Update, context: CallbackContext):
    try:
        if not update or not update.effective_user:
            LOGGER.error("No update or effective_user in start command")
            return

        user_id = update.effective_user.id
        first_name = update.effective_user.first_name or "User"
        username = update.effective_user.username or ""

        LOGGER.info(f"Start command from user {user_id} (@{username})")

        user_data = await user_collection.find_one({"id": user_id})
        is_new_user = user_data is None

        if is_new_user:
            LOGGER.info(f"Creating new user {user_id}")

            new_user = {
                "id": user_id,
                "first_name": first_name,
                "username": username,
                "balance": 500,
                "characters": [],
                "pass_data": {
                    "tier": "free",
                    "weekly_claims": 0,
                    "last_weekly_claim": None,
                    "streak_count": 0,
                    "last_streak_claim": None,
                    "tasks": {"weekly_claims": 0, "grabs": 0},
                    "mythic_unlocked": False,
                    "premium_expires": None,
                    "elite_expires": None,
                    "pending_elite_payment": None
                }
            }

            await user_collection.insert_one(new_user)
            user_data = new_user

            context.application.create_task(
                safe_track_bot_start(user_id, first_name, username, True)
            )

        else:
            LOGGER.info(f"Existing user {user_id} started bot")

            await user_collection.update_one(
                {"id": user_id},
                {"$set": {"first_name": first_name, "username": username}}
            )

            context.application.create_task(
                safe_track_bot_start(user_id, first_name, username, False)
            )

        caption = f"✨ ʜᴇʏ ᴛʜᴇʀᴇ! ɪ'ᴍ {BOT_USERNAME}, ʏᴏᴜʀ ᴜʟᴛɪᴍᴀᴛᴇ ᴀɴɪᴍᴇ ᴀᴅᴠᴇɴᴛᴜʀᴇ ᴄᴏᴍᴘᴀɴɪᴏɴ. ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴀɴᴅ ʟᴇᴛ ᴛʜᴇ ғᴜɴ ʙᴇɢɪɴ!"

        keyboard = [
            [
                InlineKeyboardButton("sᴜᴘᴘᴏʀᴛ", url=f'https://t.me/{SUPPORT_CHAT}'),
                InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url='https://t.me/PICK_X_UPDATE')
            ],
            [InlineKeyboardButton("sᴛᴀʀᴛ ɢᴜᴇssɪɴɢ💫", url=f'https://t.me/{BOT_USERNAME}?startgroup=new')],
            [
                InlineKeyboardButton("ʜᴇʟᴘ", callback_data='help'),
                InlineKeyboardButton("ᴄʀᴇᴅɪᴛs", callback_data='credits')
            ]
        ]

        await update.message.reply_video(
            video=START_VIDEO,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
            supports_streaming=True
        )

        LOGGER.info(f"Start command completed for user {user_id}")

    except Exception as e:
        LOGGER.error(f"Critical error in start command: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ An error occurred. Please try again later.")
        except:
            pass


async def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query

    try:
        await query.answer()
    except Exception as e:
        LOGGER.error(f"Error answering callback query: {e}")
        return

    try:
        user_id = query.from_user.id
        user_data = await user_collection.find_one({"id": user_id})

        if not user_data:
            await query.answer("⚠️ sᴛᴀʀᴛ ʙᴏᴛ ғɪʀsᴛ", show_alert=True)
            return

        if query.data == 'credits':
            text = f"""<b>🩵 ʙᴏᴛ ᴄʀᴇᴅɪᴛs</b>

sᴘᴇᴄɪᴀʟ ᴛʜᴀɴᴋs ᴛᴏ ᴇᴠᴇʀʏᴏɴᴇ ᴡʜᴏ ᴍᴀᴅᴇ ᴛʜɪs ᴘᴏssɪʙʟᴇ

<b>ᴏᴡɴᴇʀs</b>"""

            buttons = []

            for i in range(0, len(OWNERS), 2):
                owner_row = [
                    InlineKeyboardButton(f" {o['name']}", url=f"https://t.me/{o['username'].replace('@', '')}")
                    for o in OWNERS[i:i+2]
                ]
                if owner_row:
                    buttons.append(owner_row)

            try:
                from shivu.modules.database.sudo import fetch_sudo_users
                sudo_users_db = await fetch_sudo_users()
                if sudo_users_db:
                    text += "\n\n<b>sᴜᴅᴏ ᴜsᴇʀs</b>"
                    for i in range(0, len(sudo_users_db), 2):
                        sudo_row = [
                            InlineKeyboardButton(
                                s.get('sudo_title') or s.get('name') or s.get('first_name', 'Sudo'),
                                url=f"https://t.me/{s['username'].replace('@', '')}"
                            )
                            for s in sudo_users_db[i:i+2] if s.get('username')
                        ]
                        if sudo_row:
                            buttons.append(sudo_row)
            except ImportError:
                LOGGER.warning("sudo module not available")
            except Exception as e:
                LOGGER.error(f"Error fetching sudo users: {e}")

            text += "\n\n<b>🔐 ᴅᴇᴠᴇʟᴏᴘᴇʀ</b>"
            buttons.append([InlineKeyboardButton("ʙᴀᴄᴋ", callback_data='back')])

            await query.edit_message_caption(
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif query.data == 'help':
            text, markup = build_help_menu_view()
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=markup)

        elif query.data == 'help_menu':
            text, markup = build_help_menu_view()
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=markup)

        elif query.data.startswith('help_cat_'):
            cat_key = query.data[len('help_cat_'):]
            if cat_key not in HELP_CATEGORIES:
                await query.answer("⚠️ Unknown category", show_alert=True)
                return
            text, markup = build_help_category_view(cat_key, page=1)
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=markup)

        elif query.data.startswith('help_page_'):
            remainder = query.data[len('help_page_'):]
            cat_key, _, page_str = remainder.rpartition('_')
            if cat_key not in HELP_CATEGORIES or not page_str.isdigit():
                await query.answer("⚠️ Unknown page", show_alert=True)
                return
            text, markup = build_help_category_view(cat_key, page=int(page_str))
            await query.edit_message_caption(caption=text, parse_mode='HTML', reply_markup=markup)

        elif query.data == 'back':
            caption = f"✨ ʜᴇʏ ᴛʜᴇʀᴇ! ɪ'ᴍ {BOT_USERNAME}, ʏᴏᴜʀ ᴜʟᴛɪᴍᴀᴛᴇ ᴀɴɪᴍᴇ ᴀᴅᴠᴇɴᴛᴜʀᴇ ᴄᴏᴍᴘᴀɴɪᴏɴ. ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴀɴᴅ ʟᴇᴛ ᴛʜᴇ ғᴜɴ ʙᴇɢɪɴ!"

            keyboard = [
                [
                    InlineKeyboardButton("sᴜᴘᴘᴏʀᴛ", url=f'https://t.me/{SUPPORT_CHAT}'),
                    InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url='https://t.me/PICK_X_UPDATE')
                ],
                [InlineKeyboardButton("sᴛᴀʀᴛ ɢᴜᴇssɪɴɢ💫", url=f'https://t.me/{BOT_USERNAME}?startgroup=new')],
                [
                    InlineKeyboardButton("ʜᴇʟᴘ", callback_data='help'),
                    InlineKeyboardButton("ᴄʀᴇᴅɪᴛs", callback_data='credits')
                ]
            ]

            await query.edit_message_caption(
                caption=caption,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        LOGGER.error(f"Error in button callback: {e}", exc_info=True)
        try:
            await query.answer("⚠️ An error occurred. Please try again.", show_alert=True)
        except:
            pass


application.add_handler(CommandHandler('start', start, block=False))
application.add_handler(CallbackQueryHandler(
    button_callback,
    pattern='^(help|credits|back|help_menu|help_cat_\\w+|help_page_\\w+_\\d+)$',
    block=False
))

LOGGER.info("✓ Start module loaded successfully")
