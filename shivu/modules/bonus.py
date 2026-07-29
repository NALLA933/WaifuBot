import pytz
from dataclasses import dataclass
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext
from telegram.error import TelegramError

from shivu import application, user_collection

IST = pytz.timezone('Asia/Kolkata')


@dataclass(frozen=True)
class BonusConfig:
    daily_base: int = 10000
    daily_cooldown_hours: int = 24
    streak_reset_hours: int = 48
    streak_bonus_per_day: float = 0.05
    max_streak_bonus_days: int = 30
    weekly_cooldown_hours: int = 168
    weekly_days_worth: int = 7
    weekly_bonus_rate: float = 0.20


CONFIG = BonusConfig()
COOLDOWNS = {'daily': CONFIG.daily_cooldown_hours, 'weekly': CONFIG.weekly_cooldown_hours}


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    return pytz.UTC.localize(dt).astimezone(IST) if dt.tzinfo is None else dt.astimezone(IST)


def daily_reward(streak: int) -> int:
    bonus_days = min(max(streak - 1, 0), CONFIG.max_streak_bonus_days)
    return int(CONFIG.daily_base * (1 + bonus_days * CONFIG.streak_bonus_per_day))


def weekly_reward(streak: int) -> int:
    return int(daily_reward(streak) * CONFIG.weekly_days_worth * (1 + CONFIG.weekly_bonus_rate))


def next_streak(last_claim, current_streak: int, now: datetime) -> int:
    if not last_claim or now - to_ist(last_claim) > timedelta(hours=CONFIG.streak_reset_hours):
        return 1
    return current_streak + 1


def format_countdown(remaining: timedelta) -> str:
    total = int(remaining.total_seconds())
    if total <= 0:
        return "Ready"
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m}m" if h else (f"{m}m" if m else f"{s}s")


class UserDB:
    @staticmethod
    async def get(user_id: int) -> dict | None:
        return await user_collection.find_one({'id': user_id})

    @staticmethod
    async def ensure(user_id: int, first_name: str = None, username: str = None) -> dict:
        return await UserDB.get(user_id) or await UserDB._create(user_id, first_name, username)

    @staticmethod
    async def _create(user_id: int, first_name: str, username: str) -> dict:
        doc = {'id': user_id, 'first_name': first_name or 'Unknown', 'username': username,
               'balance': 0, 'bonus_streak': 0, 'bonus_highest_streak': 0}
        await user_collection.insert_one(doc)
        return doc

    @staticmethod
    async def update(user_id: int, inc: dict = None, set_: dict = None):
        ops = {k: v for k, v in {'$inc': inc, '$set': set_}.items() if v}
        if ops:
            await user_collection.update_one({'id': user_id}, ops, upsert=True)


def build_bonus_text(user: dict, first_name: str) -> str:
    return (
        "「 <b>SLAVE X CATCHER</b> 」\n\n"
        "🎮 <b>Bonus System (IST)</b>\n\n"
        f"👤 <b>User:</b> {first_name}\n"
        f"📅 <b>Date:</b> {now_ist().strftime('%Y-%m-%d %H:%M')} IST\n\n"
        f"🔥 <b>Current Streak:</b> {user.get('bonus_streak', 0)} days\n"
        f"🏆 <b>Highest Streak:</b> {user.get('bonus_highest_streak', 0)} days\n\n"
        "Select an option below:"
    )


def build_bonus_keyboard(user: dict, now: datetime) -> InlineKeyboardMarkup:
    rows = []
    for kind in ('daily', 'weekly'):
        label = f"{kind.title()} 🎁"
        if last := user.get(f'last_{kind}_claim'):
            remaining = timedelta(hours=COOLDOWNS[kind]) - (now - to_ist(last))
            if remaining.total_seconds() > 0:
                label = f"{kind.title()} ⏳ {format_countdown(remaining)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bonus:{kind}")])
    rows.append([InlineKeyboardButton("📊 Stats", callback_data="bonus:stats"),
                 InlineKeyboardButton("❌ Close", callback_data="bonus:close")])
    return InlineKeyboardMarkup(rows)


async def bonus_command(update: Update, context: CallbackContext):
    user = await UserDB.ensure(update.effective_user.id, update.effective_user.first_name, update.effective_user.username)
    await update.message.reply_text(
        build_bonus_text(user, update.effective_user.first_name),
        reply_markup=build_bonus_keyboard(user, now_ist()),
        parse_mode='HTML'
    )


async def refresh_menu(query, user_id: int, now: datetime):
    user = await UserDB.get(user_id)
    await query.edit_message_text(
        build_bonus_text(user, query.from_user.first_name),
        reply_markup=build_bonus_keyboard(user, now),
        parse_mode='HTML'
    )


async def claim(update: Update, context: CallbackContext, kind: str):
    query = update.callback_query
    user_id = query.from_user.id
    user = await UserDB.ensure(user_id, query.from_user.first_name, query.from_user.username)
    now = now_ist()

    if last := user.get(f'last_{kind}_claim'):
        remaining = timedelta(hours=COOLDOWNS[kind]) - (now - to_ist(last))
        if remaining.total_seconds() > 0:
            await query.answer(f"⏳ Come back in {format_countdown(remaining)}", show_alert=True)
            return

    set_fields = {f'last_{kind}_claim': now}
    streak = user.get('bonus_streak', 0)

    if kind == 'daily':
        streak = next_streak(user.get('last_daily_claim'), streak, now)
        set_fields['bonus_streak'] = streak
        set_fields['bonus_highest_streak'] = max(streak, user.get('bonus_highest_streak', 0))
        reward = daily_reward(streak)
        alert = f"🎁 +{reward:,} coins! Streak: {streak}d"
    else:
        reward = weekly_reward(streak)
        alert = f"🎁 +{reward:,} coins!"

    await UserDB.update(user_id, inc={'balance': reward}, set_=set_fields)
    await query.answer(alert, show_alert=True)
    await refresh_menu(query, user_id, now)


async def show_stats(update: Update, context: CallbackContext):
    query = update.callback_query
    user = await UserDB.ensure(query.from_user.id, query.from_user.first_name, query.from_user.username)
    streak = user.get('bonus_streak', 0)

    text = (
        "📊 <b>Bonus Stats</b>\n\n"
        f"💰 <b>Balance:</b> {user.get('balance', 0):,} coins\n"
        f"🔥 <b>Current Streak:</b> {streak} days\n"
        f"🏆 <b>Highest Streak:</b> {user.get('bonus_highest_streak', 0)} days\n\n"
        f"🎁 <b>Next Daily Reward:</b> {daily_reward(streak):,} coins\n"
        f"🎁 <b>Next Weekly Reward:</b> {weekly_reward(streak):,} coins"
    )
    await query.answer()
    await query.edit_message_text(
        text, parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bonus:menu")]])
    )


async def back_to_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await refresh_menu(query, query.from_user.id, now_ist())


async def close_menu(update: Update, context: CallbackContext):
    await update.callback_query.answer()
    await update.callback_query.message.delete()


HANDLERS = {
    'daily': lambda u, c: claim(u, c, 'daily'),
    'weekly': lambda u, c: claim(u, c, 'weekly'),
    'stats': show_stats,
    'menu': back_to_menu,
    'close': close_menu,
}


async def bonus_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    handler = HANDLERS.get(query.data.split(':', 1)[1])
    if not handler:
        await query.answer("❌ Unknown action", show_alert=True)
        return
    try:
        await handler(update, context)
    except TelegramError as e:
        await query.answer(f"❌ Error: {type(e).__name__}", show_alert=True)


application.add_handler(CommandHandler("bonus", bonus_command, block=False))
application.add_handler(CallbackQueryHandler(bonus_callback, pattern=r'^bonus:', block=False))
