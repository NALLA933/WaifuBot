"""
Telegram Bot Redeem System
Atomic thread-safe code redemption with MongoDB backend.
Handles currency and character rewards with race condition protection.
"""

import random
import string
import html
import time
from datetime import datetime, UTC
from typing import Dict, Any, Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

# Database imports
from shivu import collection, user_collection, application
from shivu import db 
from shivu.modules.database.sudo import is_user_sudo

# --- CONFIGURATION ---
LOG_GROUP_ID = -1003110990230  # Channel ID for logging activities
OWNER_ID = 7657218453  # Bot owner's Telegram ID
CODE_TTL_DAYS = 30  # Codes auto-delete after 30 days to save space
# ---------------------

# Database collection for redeem codes
codes_collection = db['redeem_codes']

# Rate limiting cache: user_id -> last_redeem_timestamp
# Cleared periodically to prevent memory leaks
_redeem_rate_cache = {}
_auth_cache = {}  # Simple cache for auth checks: user_id -> (is_sudo, timestamp)
_AUTH_CACHE_TTL = 300  # 5 minutes cache for sudo checks

# --- DATABASE INDEX SETUP FUNCTION ---
async def setup_redeem_code_indexes():
    """
    Creates necessary indexes for optimal performance.
    Run this once during bot initialization.
    """
    try:
        # Unique index prevents duplicate codes at database level
        await codes_collection.create_index([("code", 1)], unique=True)
        
        # TTL index auto-deletes old codes after 30 days
        await codes_collection.create_index(
            [("created_at", 1)],
            expireAfterSeconds=CODE_TTL_DAYS * 24 * 60 * 60,
            name="code_expiry_index"
        )
        
        # Compound index for fast claim validation
        await codes_collection.create_index(
            [("code", 1), ("claimed_by", 1)],
            name="claim_validation_index"
        )
        
        print("✅ Redeem system indexes created successfully")
    except Exception as e:
        print(f"❌ Failed to create database indexes: {e}")

# --- HELPER FUNCTIONS ---

async def generate_unique_code(max_attempts: int = 10) -> str:
    """
    Generates a unique code with duplicate prevention.
    Uses database check to ensure no collisions.
    """
    for attempt in range(max_attempts):
        part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        code = f"SIYA-{part1}-{part2}"
        
        # Database check ensures no duplicate codes exist
        existing = await codes_collection.find_one({'code': code})
        if not existing:
            return code
    
    # Fallback: use timestamp if max attempts reached
    timestamp = int(time.time()) % 10000
    part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"SIYA-{part1}-{timestamp:04d}"

async def send_log(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Sends formatted log messages to the configured log channel."""
    try:
        await context.bot.send_message(
            chat_id=LOG_GROUP_ID, 
            text=text, 
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"Logging Error: {e}")

async def check_auth_cached(user_id: int) -> bool:
    """
    Checks if user is owner or sudo with simple time-based caching.
    Returns True if user is authorized, False otherwise.
    """
    # Always allow owner
    if user_id == OWNER_ID:
        return True
    
    # Check cache first
    current_time = time.time()
    cached = _auth_cache.get(user_id)
    if cached:
        is_sudo, timestamp = cached
        if current_time - timestamp < _AUTH_CACHE_TTL:
            return is_sudo
    
    # Cache miss or expired - query database
    is_sudo = await is_user_sudo(user_id)
    _auth_cache[user_id] = (is_sudo, current_time)
    return is_sudo

async def check_auth(update: Update) -> bool:
    """Wrapper for auth check using cached version."""
    user_id = update.effective_user.id
    return await check_auth_cached(user_id)

def format_currency_amount(amount: float) -> str:
    """Formats currency amount with proper comma separators."""
    if isinstance(amount, int) or amount.is_integer():
        return f"{amount:,.0f}"
    return f"{amount:,.2f}"

def normalize_character_id(char_id: Any) -> str:
    """
    Normalizes character ID to string format.
    Ensures consistent type matching with main collection.
    """
    # Convert to string, strip whitespace, handle None/empty values
    if char_id is None:
        return "unknown"
    return str(char_id).strip()

def safe_character_data(waifu: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures character data has all required fields with safe defaults."""
    return {
        'id': normalize_character_id(waifu.get('id', 'unknown')),
        'name': waifu.get('name', 'Unknown Character'),
        'img_url': waifu.get('img_url', ''),
        'rarity': waifu.get('rarity', 'Common'),
        'anime': waifu.get('anime', 'Unknown Anime')
    }

def check_rate_limit(user_id: int, cooldown_seconds: float = 2.0) -> bool:
    """
    Basic rate limiting to prevent command spam.
    Returns True if allowed, False if rate limited.
    """
    current_time = time.time()
    last_time = _redeem_rate_cache.get(user_id, 0)
    
    if current_time - last_time < cooldown_seconds:
        return False
    
    _redeem_rate_cache[user_id] = current_time
    return True

# --- CURRENCY GENERATION COMMAND ---

async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to generate currency redeem codes.
    Creates codes that can be redeemed for in-game currency.
    """
    msg = update.message
    user_id = msg.from_user.id

    # Authorization check
    if not await check_auth(update):
        await msg.reply_text("⛔ <b>Access Denied</b>", parse_mode=ParseMode.HTML)
        return

    # Validate command arguments
    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: <code>/gen [Amount] [Quantity]</code>\n"
            "Example: <code>/gen 5000 10</code>",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        # Parse and validate input values
        amount = float(context.args[0])
        quantity = int(context.args[1])
        
        if amount <= 0 or quantity <= 0:
            await msg.reply_text("❌ Amount and quantity must be positive numbers.", parse_mode=ParseMode.HTML)
            return
            
    except ValueError:
        await msg.reply_text("❌ Invalid format. Use numbers for amount and quantity.", parse_mode=ParseMode.HTML)
        return

    # Generate unique code with duplicate prevention
    try:
        code_str = await generate_unique_code()
    except Exception as e:
        await msg.reply_text("❌ Failed to generate unique code. Please try again.", parse_mode=ParseMode.HTML)
        print(f"Code generation error: {e}")
        return

    # Prepare code document for database
    code_data = {
        'code': code_str,
        'type': 'currency',
        'amount': amount,
        'quantity': quantity,
        'claimed_by': [],
        'created_at': datetime.now(UTC),
        'created_by': user_id
    }
    
    # Save to database with error handling
    try:
        await codes_collection.insert_one(code_data)
    except Exception as e:
        # Handle duplicate key error (should not happen with generate_unique_code)
        if "duplicate key error" in str(e).lower():
            await msg.reply_text("⚠️ Generated code already exists. Please try the command again.", parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text("❌ Failed to save code to database.", parse_mode=ParseMode.HTML)
        print(f"Database Error: {e}")
        return

    # Send success response to admin
    formatted_amount = format_currency_amount(amount)
    await msg.reply_text(
        f"✅ <b>Currency Code Created!</b>\n\n"
        f"🎫 <b>Code:</b> <code>{code_str}</code>\n"
        f"💰 <b>Value:</b> {formatted_amount}\n"
        f"👥 <b>Total Claims:</b> {quantity}\n"
        f"⏰ <b>Expires:</b> After {CODE_TTL_DAYS} days\n\n"
        f"<i>Code will remain valid even after bot restart.</i>",
        parse_mode=ParseMode.HTML
    )

    # Log the code generation
    executor_name = html.escape(msg.from_user.first_name)
    log_text = (
        f"📢 <b>#CURRENCY_GEN</b>\n"
        f"Admin: {executor_name} (<code>{user_id}</code>)\n"
        f"Amount: {formatted_amount} | Qty: {quantity}\n"
        f"Code: <code>{code_str}</code>"
    )
    await send_log(context, log_text)

# --- CHARACTER GENERATION COMMAND ---

async def waifu_gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to generate character redeem codes.
    Creates codes that can be redeemed for specific characters.
    """
    msg = update.message
    user_id = msg.from_user.id

    # Authorization check
    if not await check_auth(update):
        await msg.reply_text("⛔ <b>Access Denied</b>", parse_mode=ParseMode.HTML)
        return

    # Validate command arguments
    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: <code>/sgen [Character_ID] [Quantity]</code>\n"
            "Example: <code>/sgen abc123 5</code>",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        # Normalize character ID to ensure consistent format
        char_id = normalize_character_id(context.args[0])
        quantity = int(context.args[1])
        
        if quantity <= 0:
            await msg.reply_text("❌ Quantity must be a positive number.", parse_mode=ParseMode.HTML)
            return
            
    except ValueError:
        await msg.reply_text("❌ Quantity must be a valid number.", parse_mode=ParseMode.HTML)
        return

    # Fetch character data from main collection
    try:
        waifu = await collection.find_one({'id': char_id})
        if not waifu:
            await msg.reply_text(
                f"❌ Character ID <code>{html.escape(char_id)}</code> not found.",
                parse_mode=ParseMode.HTML
            )
            return
            
        # Sanitize and standardize character data
        waifu_data = safe_character_data(waifu)
        
    except Exception as e:
        await msg.reply_text("❌ Error fetching character data.", parse_mode=ParseMode.HTML)
        print(f"Character fetch error: {e}")
        return

    # Generate unique code with duplicate prevention
    try:
        code_str = await generate_unique_code()
    except Exception as e:
        await msg.reply_text("❌ Failed to generate unique code. Please try again.", parse_mode=ParseMode.HTML)
        print(f"Code generation error: {e}")
        return

    # Prepare code document for database
    code_data = {
        'code': code_str,
        'type': 'character',
        'character_id': char_id,  # Store normalized ID for reference
        'waifu_data': waifu_data,
        'quantity': quantity,
        'claimed_by': [],
        'created_at': datetime.now(UTC),
        'created_by': user_id
    }
    
    # Save to database with error handling
    try:
        await codes_collection.insert_one(code_data)
    except Exception as e:
        if "duplicate key error" in str(e).lower():
            await msg.reply_text("⚠️ Generated code already exists. Please try the command again.", parse_mode=ParseMode.HTML)
        else:
            await msg.reply_text("❌ Failed to save code to database.", parse_mode=ParseMode.HTML)
        print(f"Database Error: {e}")
        return

    # Send success response to admin
    await msg.reply_text(
        f"✅ <b>Character Code Created!</b>\n\n"
        f"🎫 <b>Code:</b> <code>{code_str}</code>\n"
        f"👤 <b>Character:</b> {html.escape(waifu_data['name'])}\n"
        f"🏷️ <b>ID:</b> <code>{char_id}</code>\n"
        f"👥 <b>Total Claims:</b> {quantity}\n"
        f"⏰ <b>Expires:</b> After {CODE_TTL_DAYS} days",
        parse_mode=ParseMode.HTML
    )

    # Log the code generation
    executor_name = html.escape(msg.from_user.first_name)
    log_text = (
        f"📢 <b>#CHARACTER_GEN</b>\n"
        f"Admin: {executor_name} (<code>{user_id}</code>)\n"
        f"Character: {html.escape(waifu_data['name'])} (<code>{char_id}</code>)\n"
        f"Code: <code>{code_str}</code>"
    )
    await send_log(context, log_text)

# --- UNIVERSAL REDEEM COMMAND ---

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main redeem command with atomic operations to prevent race conditions.
    Handles both currency and character rewards with thread safety.
    """
    msg = update.message
    user_id = msg.from_user.id

    # Rate limiting to prevent spam
    if not check_rate_limit(user_id, cooldown_seconds=2.0):
        await msg.reply_text(
            "⏳ <b>Please wait 2 seconds between redeem attempts.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    # Validate command has code argument
    if not context.args:
        await msg.reply_text(
            "Usage: <code>/redeem SIYA-XXXX-XXXX</code>\n"
            "Example: <code>/redeem SIYA-ABCD-1234</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Normalize and validate code format
    code = context.args[0].strip().upper()
    if not code.startswith("SIYA-") or len(code) != 14:
        await msg.reply_text(
            "❌ <b>Invalid code format.</b>\n"
            "Valid format: <code>SIYA-XXXX-XXXX</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Check if code exists (for error messages)
    code_info = await codes_collection.find_one({'code': code})
    if not code_info:
        await msg.reply_text("❌ Invalid code. Code not found.", parse_mode=ParseMode.HTML)
        return

    """
    ATOMIC UPDATE - THREAD SAFE
    This single database operation prevents race conditions by:
    1. Checking user hasn't claimed before ($ne operator)
    2. Ensuring quantity limit not reached ($expr with $size)
    3. Only updating if both conditions pass
    This prevents the claimed_by list from ever exceeding quantity limit.
    """
    result = await codes_collection.update_one(
        {
            'code': code,
            'claimed_by': {'$ne': user_id},  # User not in claimed list
            '$expr': {'$lt': [{'$size': '$claimed_by'}, '$quantity']}  # Quantity check
        },
        {
            '$push': {'claimed_by': user_id},
            '$set': {'last_claimed_at': datetime.now(UTC)}
        }
    )

    # Handle update result
    if result.modified_count == 0:
        # Fetch current state for accurate error messages
        current_code_info = await codes_collection.find_one({'code': code})
        if not current_code_info:
            await msg.reply_text("❌ Code no longer exists.", parse_mode=ParseMode.HTML)
            return

        claimed_by = current_code_info.get('claimed_by', [])
        quantity = current_code_info.get('quantity', 0)
        
        # Determine exact failure reason
        if user_id in claimed_by:
            await msg.reply_text(
                "⚠️ <b>Already Claimed:</b> You have already claimed this code.",
                parse_mode=ParseMode.HTML
            )
        elif len(claimed_by) >= quantity:
            await msg.reply_text(
                f"❌ <b>Fully Claimed:</b> This code has reached its limit of {quantity} claims.",
                parse_mode=ParseMode.HTML
            )
        else:
            # This case should rarely occur - indicates database inconsistency
            await msg.reply_text(
                "❌ Unable to process claim. Please try again.",
                parse_mode=ParseMode.HTML
            )
        return

    # --- DISTRIBUTE REWARD BASED ON TYPE ---
    try:
        if code_info['type'] == 'currency':
            # Handle currency reward
            amount = float(code_info['amount'])
            
            await user_collection.update_one(
                {'id': user_id},
                {'$inc': {'balance': amount}},
                upsert=True
            )
            
            formatted_amount = format_currency_amount(amount)
            await msg.reply_text(
                f"🎉 <b>Successfully Redeemed!</b>\n\n"
                f"💰 <b>Received:</b> {formatted_amount} tokens\n"
                f"🔗 <b>Powered by:</b> <a href='https://t.me/siyaprobot'>Siya</a>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            log_detail = f"Amount: {formatted_amount}"

        elif code_info['type'] == 'character':
            # Handle character reward
            waifu_data = code_info['waifu_data']
            
            await user_collection.update_one(
                {'id': user_id},
                {'$addToSet': {'characters': waifu_data}},  # Prevent duplicates
                upsert=True
            )
            
            # Try to send character card with image
            try:
                if waifu_data.get('img_url'):
                    await msg.reply_photo(
                        photo=waifu_data['img_url'],
                        caption=(
                            f"🎉 <b>Character Unlocked!</b>\n\n"
                            f"👤 <b>Name:</b> {html.escape(waifu_data['name'])}\n"
                            f"🏵️ <b>Rarity:</b> {waifu_data.get('rarity', 'Common')}\n"
                            f"📺 <b>Anime:</b> {html.escape(waifu_data.get('anime', 'Unknown'))}"
                        ),
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await msg.reply_text(
                        f"🎉 <b>Character Unlocked!</b>\n\n"
                        f"👤 <b>Name:</b> {html.escape(waifu_data['name'])}",
                        parse_mode=ParseMode.HTML
                    )
            except Exception as e:
                # Fallback to text if photo fails
                await msg.reply_text(
                    f"🎉 <b>Character Unlocked!</b>\n\n"
                    f"👤 <b>Name:</b> {html.escape(waifu_data['name'])}",
                    parse_mode=ParseMode.HTML
                )
                print(f"Photo send error: {e}")
            
            log_detail = f"Character: {html.escape(waifu_data['name'])}"
        else:
            # Rollback claim for unknown reward type
            await codes_collection.update_one(
                {'code': code},
                {'$pull': {'claimed_by': user_id}}
            )
            await msg.reply_text("❌ Unknown reward type. Code has been reset.", parse_mode=ParseMode.HTML)
            return

    except Exception as e:
        # Critical: Rollback claim if reward distribution fails
        await codes_collection.update_one(
            {'code': code},
            {'$pull': {'claimed_by': user_id}}
        )
        await msg.reply_text(
            "❌ <b>Failed to process reward.</b>\n"
            "Your claim has been rolled back. Please try again later.",
            parse_mode=ParseMode.HTML
        )
        print(f"Reward processing error: {e}")
        return

    # Log successful redemption
    user_name = html.escape(msg.from_user.first_name)
    total_claimed = len(code_info.get('claimed_by', [])) + 1
    log_text = (
        f"📢 <b>#REDEEM_LOG</b>\n"
        f"User: {user_name} (<code>{user_id}</code>)\n"
        f"Code: <code>{code}</code>\n"
        f"Reward: {log_detail}\n"
        f"Claims: {total_claimed}/{code_info['quantity']}"
    )
    await send_log(context, log_text)

# --- ADMIN REVOKE COMMAND ---

async def revoke_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to delete redeem codes from database.
    Useful for removing compromised or incorrect codes.
    """
    msg = update.message
    if not await check_auth(update):
        await msg.reply_text("⛔ <b>Access Denied</b>", parse_mode=ParseMode.HTML)
        return

    # Validate command has code argument
    if not context.args:
        await msg.reply_text(
            "Usage: <code>/revoke [Code]</code>\n"
            "Example: <code>/revoke SIYA-ABCD-1234</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Normalize code and delete from database
    code = context.args[0].strip().upper()
    result = await codes_collection.delete_one({'code': code})

    if result.deleted_count > 0:
        await msg.reply_text(
            f"🗑️ <b>Code Revoked</b>\n\n"
            f"Code: <code>{code}</code>\n"
            f"Status: <b>Successfully deleted from database.</b>",
            parse_mode=ParseMode.HTML
        )
        
        # Log the revocation
        executor_name = html.escape(msg.from_user.first_name)
        executor_id = msg.from_user.id
        await send_log(
            context, 
            f"🗑️ <b>#CODE_REVOKED</b>\n"
            f"Code: <code>{code}</code>\n"
            f"By: {executor_name} (<code>{executor_id}</code>)"
        )
    else:
        await msg.reply_text(
            f"❌ <b>Code Not Found</b>\n\n"
            f"Code: <code>{code}</code>\n"
            f"Status: Not found in database.",
            parse_mode=ParseMode.HTML
        )

# --- CODE LIST COMMAND ---

async def list_codes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to view active redeem codes.
    Displays formatted table with code details for easy scanning.
    """
    msg = update.message
    if not await check_auth(update):
        await msg.reply_text("⛔ <b>Access Denied</b>", parse_mode=ParseMode.HTML)
        return

    try:
        # Fetch recent codes from database
        codes = await codes_collection.find().sort('created_at', -1).limit(20).to_list(length=20)
        
        if not codes:
            await msg.reply_text("📭 No active redeem codes found.", parse_mode=ParseMode.HTML)
            return
        
        # Build formatted response with table-like structure
        response_lines = [
            "📋 <b>ACTIVE REDEEM CODES</b> (Last 20)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        for idx, code in enumerate(codes, 1):
            code_type = code.get('type', 'unknown')
            claimed = len(code.get('claimed_by', []))
            total = code.get('quantity', 0)
            created_date = code['created_at'].strftime('%Y-%m-%d')
            code_value = code['code']
            
            if code_type == 'currency':
                amount = format_currency_amount(code.get('amount', 0))
                reward_info = f"💰 {amount} tokens"
            elif code_type == 'character':
                char_name = html.escape(code.get('waifu_data', {}).get('name', 'Unknown'))
                reward_info = f"👤 {char_name}"
            else:
                reward_info = "❓ Unknown reward"
            
            # Format with clear visual separation
            response_lines.append(f"<b>#{idx}:</b> <code>{code_value}</code>")
            response_lines.append(f"   ┣ <b>Type:</b> {code_type.title()}")
            response_lines.append(f"   ┣ <b>Reward:</b> {reward_info}")
            response_lines.append(f"   ┣ <b>Claims:</b> {claimed}/{total}")
            response_lines.append(f"   ┗ <b>Created:</b> {created_date}")
            response_lines.append("")  # Empty line for separation
        
        response_lines.append(f"⏰ <i>Codes expire after {CODE_TTL_DAYS} days automatically</i>")
        
        await msg.reply_text("\n".join(response_lines), parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await msg.reply_text("❌ Failed to fetch codes from database.", parse_mode=ParseMode.HTML)
        print(f"List codes error: {e}")

# --- CLEANUP FUNCTION FOR CACHE ---

async def cleanup_caches():
    """
    Periodically clears old entries from caches to prevent memory leaks.
    Should be run as a background task.
    """
    while True:
        await asyncio.sleep(3600)  # Run every hour
        current_time = time.time()
        
        # Clean rate limit cache (keep only last 2 hours)
        global _redeem_rate_cache
        _redeem_rate_cache = {
            k: v for k, v in _redeem_rate_cache.items() 
            if current_time - v < 7200  # 2 hours
        }
        
        # Clean auth cache (keep only valid entries)
        global _auth_cache
        _auth_cache = {
            k: v for k, v in _auth_cache.items() 
            if current_time - v[1] < _AUTH_CACHE_TTL
        }

# --- REGISTER COMMAND HANDLERS ---
# Note: block=False allows parallel execution of commands

application.add_handler(CommandHandler("gen", gen_command, block=False))
application.add_handler(CommandHandler("sgen", waifu_gen_command, block=False))
application.add_handler(CommandHandler("redeem", redeem_command, block=False))
application.add_handler(CommandHandler("sredeem", redeem_command, block=False))  # Legacy alias
application.add_handler(CommandHandler("revoke", revoke_code_command, block=False))
application.add_handler(CommandHandler("codelist", list_codes_command, block=False))
