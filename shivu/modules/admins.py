from telegram import Update
from telegram.ext import CommandHandler, CallbackContext

from shivu import application, user_collection, db

OWNER_ID = 7657218453
SUDO_USERS = [8949956998]


def is_authorized(user_id):
    return user_id == OWNER_ID or user_id in SUDO_USERS


bot_settings_collection = db['bot_settings']

# NOTE ON CURRENCY FIELD:
# Your propose/marry module deducts PROPOSAL_COST from the 'balance' field
# (see propose.py), even though it's shown to users as "tokens" in the UI.
# So /addt and /removet below operate on that same 'balance' field so they
# actually affect what /propose checks. If your economy actually uses a
# separate 'tokens' field elsewhere, just swap 'balance' for 'tokens' in
# the two functions below.
CURRENCY_FIELD = 'balance'


# --- /destroy <user_id> ---
async def destroy_cmd(update: Update, context: CallbackContext):
    try:
        requester_id = update.effective_user.id
        if not is_authorized(requester_id):
            await update.message.reply_text("🚫 You are not authorized to use this command.")
            return

        if not context.args:
            await update.message.reply_text("Usage: /destroy <user_id>")
            return

        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user id.")
            return

        user = await user_collection.find_one({'id': target_id})
        count = len(user.get('characters', [])) if user else 0

        await user_collection.update_one(
            {'id': target_id},
            {'$set': {'characters': []}},
            upsert=True
        )

        await update.message.reply_text(
            f"Successfully destroyed {count} characters for user {target_id}"
        )
    except Exception:
        pass


# --- /setded <percentage> ---
async def setded_cmd(update: Update, context: CallbackContext):
    try:
        requester_id = update.effective_user.id
        if not is_authorized(requester_id):
            await update.message.reply_text("🚫 You are not authorized to use this command.")
            return

        if not context.args:
            await update.message.reply_text("Usage: /setded <percentage>")
            return

        try:
            percentage = float(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid percentage.")
            return

        await bot_settings_collection.update_one(
            {'_id': 'settings'},
            {'$set': {'deduction_percentage': percentage}},
            upsert=True
        )

        await update.message.reply_text(
            f"✅ DEDUCTION PERCENTAGE SET TO {percentage:.1f}%"
        )
    except Exception:
        pass


async def get_deduction_percentage() -> float:
    """Helper other modules can import to read the current deduction %."""
    try:
        doc = await bot_settings_collection.find_one({'_id': 'settings'})
        return doc.get('deduction_percentage', 0.0) if doc else 0.0
    except Exception:
        return 0.0


# --- /addt <user_id> <amount> ---
async def addt_cmd(update: Update, context: CallbackContext):
    try:
        requester_id = update.effective_user.id
        if not is_authorized(requester_id):
            await update.message.reply_text("🚫 You are not authorized to use this command.")
            return

        if len(context.args) < 2:
            await update.message.reply_text("Usage: /addt <user_id> <amount>")
            return

        try:
            target_id = int(context.args[0])
            amount = int(context.args[1])
        except ValueError:
            await update.message.reply_text("Invalid user id or amount.")
            return

        await user_collection.update_one(
            {'id': target_id},
            {'$inc': {CURRENCY_FIELD: amount}},
            upsert=True
        )

        user = await user_collection.find_one({'id': target_id})
        new_balance = user.get(CURRENCY_FIELD, 0) if user else amount

        await update.message.reply_text(
            f"Success! {amount} Tokens added to user {target_id}. "
            f"Updated balance: {new_balance} Tokens."
        )
    except Exception:
        pass


# --- /removet <amount> <user_id> ---
async def removet_cmd(update: Update, context: CallbackContext):
    try:
        requester_id = update.effective_user.id
        if not is_authorized(requester_id):
            await update.message.reply_text("🚫 You are not authorized to use this command.")
            return

        if len(context.args) < 2:
            await update.message.reply_text("Usage: /removet <amount> <user_id>")
            return

        try:
            amount = int(context.args[0])
            target_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text("Invalid amount or user id.")
            return

        user = await user_collection.find_one({'id': target_id})
        current = user.get(CURRENCY_FIELD, 0) if user else 0
        new_balance = max(0, current - amount)

        await user_collection.update_one(
            {'id': target_id},
            {'$set': {CURRENCY_FIELD: new_balance}},
            upsert=True
        )

        await update.message.reply_text(
            f"Success! {amount} Tokens removed from user {target_id}. "
            f"Updated balance: {new_balance} Tokens."
        )
    except Exception:
        pass


# Handlers registration
application.add_handler(CommandHandler(['destroy'], destroy_cmd, block=False))
application.add_handler(CommandHandler(['setded'], setded_cmd, block=False))
application.add_handler(CommandHandler(['addt'], addt_cmd, block=False))
application.add_handler(CommandHandler(['removet'], removet_cmd, block=False))
