#siya method v3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext, CallbackQueryHandler
from telegram.error import TelegramError
from html import escape
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import random
import math
from shivu import db, application, LOGGER
from shivu.modules.hstyle import get_user_style_template, get_user_display_options

RARITIES = {
    "common": ("🟢", "Common"),
    "rare": ("🔵", "Rare"),
    "legendary": ("🟠", "Legendary"),
    "special": ("🟡", "Special Edition"),
    "celestial": ("🪽", "Celestial"),
    "erotic": ("🥵", "Erotic"),
    "exclusive": ("🥴", "Exclusive"),
    "premium": ("💎", "Premium Edition"),
    "mythic": ("🔮", "Mythic"),
    "sweet": ("🍭", "Sweet"),
    "valentine": ("💋", "Valentine"),
    "winter": ("❄️", "Winter"),
    "neon": ("⚡", "Neon"),
    "pearl": ("🐚", "Pearl"),
    "cosmic": ("🌌", "Cosmic"),
}


def rarity_display(key: str) -> str:
    emoji, name = RARITIES.get(key, RARITIES["common"])
    return f"{emoji} {name}"


def rarity_emoji(display: str) -> str:
    return display.split(' ', 1)[0] if display else "🟢"


def chunk(items: list, size: int) -> list:
    return [items[i:i + size] for i in range(0, len(items), size)]


@dataclass
class Character:
    id: str
    name: str
    anime: str
    rarity: str
    img_url: Optional[str] = None
    is_video: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional['Character']:
        if not isinstance(data, dict):
            return None
        return cls(
            id=data.get('id', ''),
            name=data.get('name', 'Unknown'),
            anime=data.get('anime', 'Unknown'),
            rarity=data.get('rarity', rarity_display('common')),
            img_url=data.get('img_url'),
            is_video=data.get('is_video', False)
        )


@dataclass
class DisplayOptions:
    show_url: bool = False
    video_support: bool = True
    preview_image: bool = True
    show_rarity_full: bool = False
    compact_mode: bool = False
    show_id_bottom: bool = False


@dataclass
class UserCollection:
    user_id: int
    characters: List[Character] = field(default_factory=list)
    favorite: Optional[Character] = None
    filter_mode: str = "default"

    def get_filtered_characters(self) -> List[Character]:
        if self.filter_mode == "default" or self.filter_mode not in RARITIES:
            return self.characters
        target = rarity_display(self.filter_mode)
        return [c for c in self.characters if c.rarity == target]

    def count_by_id(self, characters: List[Character]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for char in characters:
            counts[char.id] = counts.get(char.id, 0) + 1
        return counts

    def group_by_anime(self, characters: List[Character]) -> Dict[str, List[Character]]:
        grouped: Dict[str, List[Character]] = {}
        for char in characters:
            grouped.setdefault(char.anime, []).append(char)
        return grouped


class MediaHelper:
    VIDEO_EXT = ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v')

    @staticmethod
    def is_video_url(url: Optional[str]) -> bool:
        return bool(url) and url.lower().split('?')[0].endswith(MediaHelper.VIDEO_EXT)

    @staticmethod
    async def send_media_message(message, media_url: Optional[str], caption: str,
                                  reply_markup, is_video: bool = False,
                                  display_options: Optional[DisplayOptions] = None):
        opts = display_options or DisplayOptions()

        if opts.show_url and media_url:
            caption += f"\n\n🔗 <code>{media_url}</code>"

        is_video = opts.video_support and (is_video or MediaHelper.is_video_url(media_url))

        if not opts.preview_image or not media_url:
            return await message.reply_text(caption, reply_markup=reply_markup, parse_mode='HTML')

        try:
            if is_video:
                return await message.reply_video(
                    video=media_url, caption=caption, reply_markup=reply_markup,
                    parse_mode='HTML', supports_streaming=True,
                    read_timeout=120, write_timeout=120
                )
            return await message.reply_photo(
                photo=media_url, caption=caption, reply_markup=reply_markup, parse_mode='HTML'
            )
        except TelegramError as e:
            LOGGER.warning(f"Media send failed, falling back to text: {e}")
            return await message.reply_text(caption, reply_markup=reply_markup, parse_mode='HTML')


class HaremMessageBuilder:
    def __init__(self, collection: UserCollection, page: int, total_pages: int,
                 style: Dict, options: DisplayOptions, user_name: str):
        self.collection = collection
        self.page = page
        self.total_pages = total_pages
        self.style = style
        self.options = options
        self.user_name = user_name

    def build_message(self, characters: List[Character], anime_counts: Dict[str, int]) -> str:
        message = self.style['header'].format(
            user_name=escape(self.user_name), page=self.page + 1, total_pages=self.total_pages
        )

        grouped = self.collection.group_by_anime(characters)
        counts = self.collection.count_by_id(self.collection.characters)
        seen = set()

        for anime, chars in grouped.items():
            user_count = sum(1 for c in self.collection.characters if c.anime == anime)
            message += self.style['anime_header'].format(
                anime=escape(anime), user_count=user_count, total_count=anime_counts.get(anime, 0)
            )
            if not self.options.compact_mode:
                message += self.style['separator']

            for char in chars:
                if char.id in seen:
                    continue
                message += self._format_character(char, counts.get(char.id, 1))
                seen.add(char.id)

            message += self.style['footer'] if not self.options.compact_mode else '\n'

        return message

    def _format_character(self, char: Character, count: int) -> str:
        rarity = char.rarity if self.options.show_rarity_full else rarity_emoji(char.rarity)
        fav = " [🍁]" if self.collection.favorite and char.id == self.collection.favorite.id else ""

        if self.options.show_id_bottom:
            line = self.style['character'].replace('{id}', '').format(
                id='', rarity=rarity, name=escape(char.name), fav=fav, count=count
            )
            return line + f"    └─ ID: <code>{char.id}</code>\n"

        return self.style['character'].format(
            id=char.id, rarity=rarity, name=escape(char.name), fav=fav, count=count
        )


class HaremHandler:
    CHARACTERS_PER_PAGE = 10

    def __init__(self):
        self.collection_db = db['anime_characters_lol']
        self.user_db = db['user_collection_lmaoooo']

    async def load_user_collection(self, user_id: int) -> Optional[UserCollection]:
        user = await self.user_db.find_one({'id': user_id})
        if not user:
            return None

        characters = [c for c in (Character.from_dict(c) for c in user.get('characters', [])) if c]
        favorite = Character.from_dict(user.get('favorites')) if user.get('favorites') else None

        if favorite and not any(c.id == favorite.id for c in characters):
            await self.user_db.update_one({'id': user_id}, {'$unset': {'favorites': ""}})
            favorite = None

        return UserCollection(
            user_id=user_id, characters=characters, favorite=favorite,
            filter_mode=user.get('smode', 'default')
        )

    async def get_anime_counts(self, anime_list: List[str]) -> Dict[str, int]:
        return {anime: await self.collection_db.count_documents({"anime": anime}) for anime in anime_list}

    def _build_keyboard(self, page: int, total_pages: int, total_chars: int, user_id: int) -> InlineKeyboardMarkup:
        keyboard = [[InlineKeyboardButton(
            f"✨ slaves ({total_chars})", switch_inline_query_current_chat=f"collection.{user_id}"
        )]]

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("Previous", callback_data=f"harem_page:{page - 1}:{user_id}"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next", callback_data=f"harem_page:{page + 1}:{user_id}"))
        if nav:
            keyboard.append(nav)

        keyboard.append([InlineKeyboardButton("▶ 5x", callback_data=f"harem_5x:{user_id}")])
        keyboard.append([InlineKeyboardButton("Close", callback_data=f"harem_close:{user_id}")])
        return InlineKeyboardMarkup(keyboard)

    async def show_harem(self, update: Update, context: CallbackContext, page: int = 0, edit: bool = False):
        user_id = update.effective_user.id
        message = update.message or update.callback_query.message

        collection = await self.load_user_collection(user_id)
        if not collection:
            await message.reply_text("⚠️ You need to grab a character first using /grab command!")
            return
        if not collection.characters:
            await message.reply_text("📭 You don't have any characters yet! Use /grab to catch some.")
            return

        filtered = collection.get_filtered_characters()
        if not filtered:
            await message.reply_text(
                f"❌ You don't have any characters with rarity: {rarity_display(collection.filter_mode)}\n"
                f"💡 Change mode using /smode"
            )
            return

        filtered.sort(key=lambda c: (c.anime, c.id))
        total_pages = math.ceil(len(filtered) / self.CHARACTERS_PER_PAGE)
        page = page if 0 <= page < total_pages else 0

        start = page * self.CHARACTERS_PER_PAGE
        current = filtered[start:start + self.CHARACTERS_PER_PAGE]

        style = await get_user_style_template(user_id)
        opts_dict = await get_user_display_options(user_id)
        options = DisplayOptions(**opts_dict) if opts_dict else DisplayOptions()

        anime_counts = await self.get_anime_counts(list({c.anime for c in current}))
        builder = HaremMessageBuilder(collection, page, total_pages, style, options, update.effective_user.first_name)
        text = builder.build_message(current, anime_counts)
        markup = self._build_keyboard(page, total_pages, len(filtered), user_id)

        display_char = collection.favorite if collection.favorite and collection.favorite.img_url else (
            random.choice(filtered) if filtered else None
        )
        media_url = display_char.img_url if display_char else None
        is_video = display_char.is_video if display_char else False

        if media_url and edit:
            try:
                await message.edit_caption(caption=text, reply_markup=markup, parse_mode='HTML')
                return
            except TelegramError as e:
                LOGGER.warning(f"Edit failed, resending: {e}")

        if media_url:
            await MediaHelper.send_media_message(message, media_url, text, markup, is_video, options)
        elif edit:
            await message.edit_text(text=text, reply_markup=markup, parse_mode='HTML')
        else:
            await message.reply_text(text=text, reply_markup=markup, parse_mode='HTML')


class ModeHandler:
    def __init__(self):
        self.user_db = db['user_collection_lmaoooo']

    async def show_mode_menu(self, update: Update):
        keyboard = [[
            InlineKeyboardButton("ᴅᴇғᴀᴜʟᴛ", callback_data="harem_mode_default"),
            InlineKeyboardButton("ʀᴀʀɪᴛʏ ғɪʟᴛᴇʀ", callback_data="harem_mode_rarity"),
        ]]
        text = (
            "╭─────────────────╮\n"
            "│  <b>ᴄᴏʟʟᴇᴄᴛɪᴏɴ ᴍᴏᴅᴇ</b>  │\n"
            "╰─────────────────╯\n\n"
            "◆ <b>ᴅᴇғᴀᴜʟᴛ</b>\n  sʜᴏᴡ ᴀʟʟ ᴄʜᴀʀᴀᴄᴛᴇʀs\n\n"
            "◆ <b>ʀᴀʀɪᴛʏ ғɪʟᴛᴇʀ</b>\n  ғɪʟᴛᴇʀ ʙʏ sᴘᴇᴄɪғɪᴄ ᴛɪᴇʀ\n\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n"
            "💡 <i>Use /hstyle to change visual style</i>"
        )
        markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='HTML')

    async def show_rarity_menu(self, query):
        buttons = [InlineKeyboardButton(emoji, callback_data=f"harem_mode_{key}") for key, (emoji, _) in RARITIES.items()]
        keyboard = chunk(buttons, 3) + [[InlineKeyboardButton("🗑 Close", callback_data="harem_mode_back")]]
        text = (
            "🪄 <b>HAREM RARITY SELECTOR</b>\n\n"
            "🎯 Select a rarity below to filter your harem view.\n"
            "✅ Current selected rarity will be marked.\n\n"
            "Tap a rarity or close this menu anytime."
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    async def set_mode(self, user_id: int, mode: str):
        await self.user_db.update_one({'id': user_id}, {'$set': {'smode': mode}}, upsert=True)

    async def handle_mode_callback(self, update: Update, context: CallbackContext):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        if data == "harem_mode_default":
            await self.set_mode(user_id, 'default')
            await query.answer("✓ ᴍᴏᴅᴇ sᴇᴛ ᴛᴏ ᴅᴇғᴀᴜʟᴛ")
            await query.edit_message_text(
                "╭─────────────────╮\n│   <b>ᴍᴏᴅᴇ ᴜᴘᴅᴀᴛᴇᴅ</b>   │\n╰─────────────────╯\n\n"
                "◆ <b>ᴄᴜʀʀᴇɴᴛ ғɪʟᴛᴇʀ</b>\n  ᴀʟʟ ᴄʜᴀʀᴀᴄᴛᴇʀs\n\n"
                "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n   ✦ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ✦\n\n"
                "sʜᴏᴡɪɴɢ ʏᴏᴜʀ ᴄᴏᴍᴘʟᴇᴛᴇ\nᴄʜᴀʀᴀᴄᴛᴇʀ ᴄᴏʟʟᴇᴄᴛɪᴏɴ",
                parse_mode='HTML'
            )
            return

        if data == "harem_mode_rarity":
            await self.show_rarity_menu(query)
            await query.answer()
            return

        if data == "harem_mode_back":
            await self.show_mode_menu(update)
            await query.answer()
            return

        mode_name = data.replace("harem_mode_", "")
        if mode_name not in RARITIES:
            await query.answer("❌ ɪɴᴠᴀʟɪᴅ ʀᴀʀɪᴛʏ", show_alert=True)
            return

        emoji, name = RARITIES[mode_name]
        await self.set_mode(user_id, mode_name)
        await query.answer(f"✓ {name} ғɪʟᴛᴇʀ ᴀᴄᴛɪᴠᴀᴛᴇᴅ")
        await query.edit_message_text(
            "╭─────────────────╮\n│  <b>ғɪʟᴛᴇʀ ᴀᴘᴘʟɪᴇᴅ</b>  │\n╰─────────────────╯\n\n"
            f"      {emoji}\n\n◆ <b>{name}</b>\n\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n   ✦ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ✦\n\n"
            f"ᴅɪsᴘʟᴀʏɪɴɢ ᴏɴʟʏ\n{name.lower()} ᴄʜᴀʀᴀᴄᴛᴇʀs",
            parse_mode='HTML'
        )


class UnfavHandler:
    def __init__(self):
        self.user_db = db['user_collection_lmaoooo']

    async def show_unfav_prompt(self, update: Update):
        user_id = update.effective_user.id
        user = await self.user_db.find_one({'id': user_id})

        if not user:
            await update.message.reply_text('⚠️ 𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙣𝙤𝙩 𝙂𝙤𝙩 𝘼𝙣𝙮 𝙒𝘼𝙄𝙁𝙐 𝙮𝙚𝙩...')
            return

        fav = Character.from_dict(user.get('favorites'))
        if not fav:
            await update.message.reply_text("💔 You don't have a favorite character set!")
            return

        buttons = [[
            InlineKeyboardButton("✅ ʏᴇs", callback_data=f"harem_unfav_yes:{user_id}"),
            InlineKeyboardButton("❌ ɴᴏ", callback_data=f"harem_unfav_no:{user_id}")
        ]]
        opts_dict = await get_user_display_options(user_id)
        options = DisplayOptions(**opts_dict) if opts_dict else DisplayOptions()

        caption = (
            f"<b>💔 ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴛʜɪs ғᴀᴠᴏʀɪᴛᴇ?</b>\n\n"
            f"✨ <b>ɴᴀᴍᴇ:</b> <code>{escape(fav.name)}</code>\n"
            f"📺 <b>ᴀɴɪᴍᴇ:</b> <code>{escape(fav.anime)}</code>\n"
            f"🆔 <b>ɪᴅ:</b> <code>{fav.id}</code>"
        )
        await MediaHelper.send_media_message(
            update.message, fav.img_url, caption, InlineKeyboardMarkup(buttons), fav.is_video, options
        )

    async def handle_unfav_callback(self, update: Update):
        query = update.callback_query
        action, _, user_id_str = query.data.partition(':')
        user_id = await verify_owner(query, user_id_str)
        if user_id is None:
            return
        await query.answer()

        if action == 'harem_unfav_yes':
            user = await self.user_db.find_one({'id': user_id})
            fav = Character.from_dict(user.get('favorites')) if user else None
            if not fav:
                await query.answer("❌ ɴᴏ ғᴀᴠᴏʀɪᴛᴇ ғᴏᴜɴᴅ!", show_alert=True)
                return

            await self.user_db.update_one({'id': user_id}, {'$unset': {'favorites': ""}})
            await query.edit_message_caption(
                caption=(
                    f"<b>💔 ғᴀᴠᴏʀɪᴛᴇ ʀᴇᴍᴏᴠᴇᴅ!</b>\n\n"
                    f"✨ <b>ɴᴀᴍᴇ:</b> <code>{escape(fav.name)}</code>\n"
                    f"📺 <b>ᴀɴɪᴍᴇ:</b> <code>{escape(fav.anime)}</code>\n\n"
                    f"<i>💖 ʏᴏᴜ ᴄᴀɴ sᴇᴛ ᴀ ɴᴇᴡ ғᴀᴠᴏʀɪᴛᴇ ᴜsɪɴɢ /fav</i>"
                ),
                parse_mode='HTML'
            )
        elif action == 'harem_unfav_no':
            await query.edit_message_caption(caption="❌ ᴀᴄᴛɪᴏɴ ᴄᴀɴᴄᴇʟᴇᴅ. ғᴀᴠᴏʀɪᴛᴇ ᴋᴇᴘᴛ.", parse_mode='HTML')


async def verify_owner(query, user_id_str: str) -> Optional[int]:
    try:
        owner_id = int(user_id_str)
    except ValueError:
        await query.answer("❌ Invalid data!", show_alert=True)
        return None
    if query.from_user.id != owner_id:
        await query.answer("⚠️ This is not your collection!", show_alert=True)
        return None
    return owner_id


harem_handler = HaremHandler()
mode_handler = ModeHandler()
unfav_handler = UnfavHandler()


async def harem_command(update: Update, context: CallbackContext):
    try:
        await harem_handler.show_harem(update, context)
    except TelegramError as e:
        LOGGER.error(f"Error in harem_command: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Error loading harem. Please try again.")


async def harem_page_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        _, page_str, user_id_str = query.data.split(':')
        user_id = await verify_owner(query, user_id_str)
        if user_id is None:
            return
        await query.answer()
        await harem_handler.show_harem(update, context, int(page_str), edit=True)
    except (ValueError, TelegramError) as e:
        LOGGER.error(f"Error in harem_page_callback: {e}", exc_info=True)
        await query.answer("❌ Error loading page", show_alert=True)


async def smode_command(update: Update, context: CallbackContext):
    try:
        await mode_handler.show_mode_menu(update)
    except TelegramError as e:
        LOGGER.error(f"Error in smode_command: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Error loading mode menu.")


async def mode_callback(update: Update, context: CallbackContext):
    try:
        await mode_handler.handle_mode_callback(update, context)
    except TelegramError as e:
        LOGGER.error(f"Error in mode_callback: {e}", exc_info=True)


async def unfav_command(update: Update, context: CallbackContext):
    try:
        await unfav_handler.show_unfav_prompt(update)
    except TelegramError as e:
        LOGGER.error(f"Error in unfav_command: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Error processing unfav command.")


async def unfav_callback(update: Update, context: CallbackContext):
    try:
        await unfav_handler.handle_unfav_callback(update)
    except TelegramError as e:
        LOGGER.error(f"Error in unfav_callback: {e}", exc_info=True)


async def harem_5x_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    _, _, user_id_str = query.data.partition(':')
    if await verify_owner(query, user_id_str) is None:
        return
    await query.answer("🔜 5x view coming soon", show_alert=True)


async def harem_close_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    _, _, user_id_str = query.data.partition(':')
    if await verify_owner(query, user_id_str) is None:
        return
    await query.answer()
    await query.message.delete()


application.add_handler(CommandHandler(["harem", "collection"], harem_command, block=False))
application.add_handler(CommandHandler("smode", smode_command, block=False))
application.add_handler(CommandHandler("unfav", unfav_command, block=False))
application.add_handler(CallbackQueryHandler(harem_page_callback, pattern='^harem_page:', block=False))
application.add_handler(CallbackQueryHandler(mode_callback, pattern='^harem_mode_', block=False))
application.add_handler(CallbackQueryHandler(unfav_callback, pattern="^harem_unfav_", block=False))
application.add_handler(CallbackQueryHandler(harem_5x_callback, pattern='^harem_5x:', block=False))
application.add_handler(CallbackQueryHandler(harem_close_callback, pattern='^harem_close:', block=False))
