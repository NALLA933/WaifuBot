import random
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Dict, Tuple, Set
from functools import wraps
from collections import defaultdict, deque
import asyncio
import hashlib

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, TimedOut
from cachetools import TTLCache, LRUCache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import io
from concurrent.futures import ThreadPoolExecutor

from shivu import application, user_collection, collection, sudo_users

KOLKATA_TZ = pytz.timezone('Asia/Kolkata')
UTC_TZ = pytz.UTC

class RarityType(Enum):
    MYTHIC = ("mythic", "🔮 Mythic", 1, 12, "#8A2BE2")
    COSMIC = ("cosmic", "🌌 Cosmic", 2, 11, "#191970")
    CELESTIAL = ("celestial", "🪽 Celestial", 3, 10, "#9370DB")
    EXCLUSIVE = ("exclusive", "🥴 Exclusive", 4, 9, "#C71585")
    LEGENDARY = ("legendary", "🟠 Legendary", 5, 8, "#FFA500")
    PREMIUM = ("premium", "💎 Premium Edition", 6, 7, "#00CED1")
    NEON = ("neon", "⚡ Neon", 8, 6, "#00FFFF")
    PEARL = ("pearl", "🐚 Pearl", 10, 6, "#F0EAD6")
    SWEET = ("sweet", "🍭 Sweet", 12, 5, "#FF85C2")
    SPECIAL = ("special", "🟡 Special Edition", 14, 5, "#FFD700")
    VALENTINE = ("valentine", "💋 Valentine", 10, 5, "#FF1493")
    WINTER = ("winter", "❄️ Winter", 10, 4, "#87CEEB")
    EROTIC = ("erotic", "🥵 Erotic", 12, 4, "#DC143C")
    RARE = ("rare", "🔵 Rare", 20, 3, "#1E90FF")
    COMMON = ("common", "🟢 Common", 50, 1, "#32CD32")
    DEFAULT = ("default", None, 0, 0, "#808080")
    
    def __init__(self, key: str, display: Optional[str], weight: int, multiplier: int, color: str):
        self.key = key
        self.display = display
        self.weight = weight
        self.multiplier = multiplier
        self.color = color
    
    @property
    def emoji(self) -> str:
        if self.display:
            return self.display.split()[0]
        return "🎴"

@dataclass(frozen=True)
class ClaimConfig:
    LOG_GROUP_ID: int = -1002956939145
    SUPPORT_LINK: str = "https://t.me/THE_DRAGON_SUPPORT"
    COOLDOWN_HOURS: int = 24
    STREAK_RESET_HOURS: int = 48
    MAX_STREAK: int = 7
    CLAIM_TIMEOUT: int = 35
    CACHE_TTL: int = 300
    MAX_RETRIES: int = 3
    RATE_LIMIT_WINDOW: int = 60
    MAX_REQUESTS_PER_WINDOW: int = 3
    BONUS_STREAK_MILESTONES: Tuple[int, ...] = (3, 5, 7, 10, 14, 21, 30)
    LUCKY_BOOST_CHANCE: float = 0.18
    PITY_SYSTEM_THRESHOLD: int = 25
    IMAGE_CACHE_SIZE: int = 150
    PARALLEL_WORKERS: int = 6
    SEASONAL_BOOST_MULTIPLIER: float = 1.5

CONFIG = ClaimConfig()

claim_semaphore = asyncio.Semaphore(100)
active_claims: Set[int] = set()
rate_limit_tracker = defaultdict(lambda: deque(maxlen=CONFIG.MAX_REQUESTS_PER_WINDOW))
character_cache = TTLCache(maxsize=1500, ttl=CONFIG.CACHE_TTL)
user_cache = TTLCache(maxsize=7000, ttl=CONFIG.CACHE_TTL)
image_cache = LRUCache(maxsize=CONFIG.IMAGE_CACHE_SIZE)
pity_counter = defaultdict(int)
executor = ThreadPoolExecutor(max_workers=CONFIG.PARALLEL_WORKERS)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('claims.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class CharacterNotFound(Exception):
    pass

def get_kolkata_time() -> datetime:
    return datetime.now(KOLKATA_TZ)

def to_kolkata(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = UTC_TZ.localize(dt)
    return dt.astimezone(KOLKATA_TZ)

def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = KOLKATA_TZ.localize(dt)
    return dt.astimezone(UTC_TZ)

def rate_limit_check(user_id: int) -> bool:
    now = datetime.now()
    user_requests = rate_limit_tracker[user_id]
    user_requests.append(now)
    
    if len(user_requests) >= CONFIG.MAX_REQUESTS_PER_WINDOW:
        oldest = user_requests[0]
        if (now - oldest).total_seconds() < CONFIG.RATE_LIMIT_WINDOW:
            return False
    return True

def rate_limit(func):
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext):
        user_id = update.effective_user.id
        
        if not rate_limit_check(user_id):
            remaining = CONFIG.RATE_LIMIT_WINDOW - int((datetime.now() - rate_limit_tracker[user_id][0]).total_seconds())
            await update.message.reply_text(
                f"⚠️ <b>ʀᴀᴛᴇ ʟɪᴍɪᴛ</b>\nWait {remaining}s.",
                parse_mode=ParseMode.HTML
            )
            return
        
        if user_id in active_claims:
            await update.message.reply_text("⚙️ <b>ᴘʀᴏᴄᴇssɪɴɢ...</b>", parse_mode=ParseMode.HTML)
            return
        
        active_claims.add(user_id)
        try:
            async with claim_semaphore:
                return await asyncio.wait_for(func(update, context), timeout=CONFIG.CLAIM_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout for user {user_id}")
            await update.message.reply_text("⏱️ <b>ᴛɪᴍᴇᴏᴜᴛ</b>\nTry again.", parse_mode=ParseMode.HTML)
        finally:
            active_claims.discard(user_id)
    return wrapper

def sudo_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: CallbackContext):
        if str(update.effective_user.id) not in sudo_users:
            await update.message.reply_text("🚫 <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>", parse_mode=ParseMode.HTML)
            return
        return await func(update, context)
    return wrapper

class TimeFormatter:
    @staticmethod
    def format_duration(delta: timedelta) -> str:
        seconds = int(delta.total_seconds())
        periods = [('ᴅ', 86400), ('ʜ', 3600), ('ᴍ', 60), ('s', 1)]
        parts = []
        for suffix, count in periods:
            value = seconds // count
            if value:
                parts.append(f"{value}{suffix}")
                seconds %= count
        return ' '.join(parts[:3]) if parts else '0s'
    
    @staticmethod
    def format_datetime(dt: datetime) -> str:
        local_dt = to_kolkata(dt)
        return local_dt.strftime('%d %b %Y, %I:%M %p IST')
    
    @staticmethod
    def get_time_emoji(hour: int) -> str:
        emojis = {range(0, 6): '🌙', range(6, 12): '🌅', range(12, 18): '☀️', range(18, 24): '🌆'}
        for time_range, emoji in emojis.items():
            if hour in time_range:
                return emoji
        return '🕐'
    
    @staticmethod
    def get_seasonal_event() -> Optional[RarityType]:
        now = get_kolkata_time()
        month = now.month
        seasonal_map = {
            2: RarityType.VALENTINE,
            (12, 1, 2): RarityType.WINTER
        }
        
        for key, rarity in seasonal_map.items():
            if isinstance(key, tuple) and month in key:
                return rarity
            elif month == key:
                return rarity
        return None
    
    @staticmethod
    def get_day_bonus(day: int) -> str:
        special_days = {0: "💙 ᴍᴏɴᴅᴀʏ", 4: "🎉 ғʀɪᴅᴀʏ", 5: "🌟 sᴀᴛᴜʀᴅᴀʏ", 6: "✨ sᴜɴᴅᴀʏ"}
        return special_days.get(day, "")

class CacheManager:
    @staticmethod
    def generate_cache_key(*args) -> str:
        return hashlib.md5('_'.join(map(str, args)).encode()).hexdigest()
    
    @staticmethod
    async def get_user_data(user_id: int) -> Optional[Dict]:
        cache_key = CacheManager.generate_cache_key('user', user_id)
        if cache_key in user_cache:
            return user_cache[cache_key]
        user_data = await user_collection.find_one({'id': user_id})
        if user_data:
            user_cache[cache_key] = user_data
        return user_data
    
    @staticmethod
    def invalidate_user_cache(user_id: int):
        cache_key = CacheManager.generate_cache_key('user', user_id)
        user_cache.pop(cache_key, None)

class PitySystem:
    @staticmethod
    def check_pity(user_id: int) -> bool:
        count = pity_counter[user_id]
        if count >= CONFIG.PITY_SYSTEM_THRESHOLD:
            pity_counter[user_id] = 0
            return True
        pity_counter[user_id] += 1
        return False
    
    @staticmethod
    def get_pity_progress(user_id: int) -> Tuple[int, int]:
        return pity_counter[user_id], CONFIG.PITY_SYSTEM_THRESHOLD
    
    @staticmethod
    def reset_pity(user_id: int):
        pity_counter[user_id] = 0

class LuckSystem:
    @staticmethod
    def calculate_luck_factor(user_id: int, streak: int) -> float:
        base_luck = 1.0
        streak_bonus = min(streak * 0.06, 0.35)
        random_factor = random.uniform(-0.1, 0.25)
        time_bonus = LuckSystem._get_time_bonus()
        seasonal_bonus = LuckSystem._get_seasonal_bonus()
        return base_luck + streak_bonus + random_factor + time_bonus + seasonal_bonus
    
    @staticmethod
    def _get_time_bonus() -> float:
        hour = get_kolkata_time().hour
        if 6 <= hour < 9 or 20 <= hour < 23:
            return 0.20
        elif 12 <= hour < 14:
            return 0.10
        return 0.0
    
    @staticmethod
    def _get_seasonal_bonus() -> float:
        seasonal_event = TimeFormatter.get_seasonal_event()
        if seasonal_event:
            return 0.15
        return 0.0
    
    @staticmethod
    def is_lucky_boost() -> bool:
        return random.random() < CONFIG.LUCKY_BOOST_CHANCE
    
    @staticmethod
    def is_ultra_lucky() -> bool:
        return random.random() < 0.05

class ImageProcessor:
    @staticmethod
    async def create_claim_card(character: Dict, user_name: str, streak: int, rarity: RarityType) -> io.BytesIO:
        return await asyncio.get_event_loop().run_in_executor(
            executor, ImageProcessor._generate_card, character, user_name, streak, rarity
        )
    
    @staticmethod
    def _generate_card(character: Dict, user_name: str, streak: int, rarity: RarityType) -> io.BytesIO:
        cache_key = f"{character['id']}_{streak}_{user_name}_{rarity.key}"
        if cache_key in image_cache:
            return image_cache[cache_key]
        
        width, height = 900, 650
        img = Image.new('RGB', (width, height), color='#0a0a1e')
        draw = ImageDraw.Draw(img)
        
        gradient = Image.new('RGB', (width, height), color='#16213e')
        draw_gradient = ImageDraw.Draw(gradient)
        for i in range(height):
            color = ImageProcessor._interpolate_color('#0f1629', rarity.color, i / height)
            draw_gradient.line([(0, i), (width, i)], fill=color)
        
        img = Image.blend(img, gradient, alpha=0.75)
        img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
        
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)
        
        draw = ImageDraw.Draw(img)
        
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 45)
            text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        except:
            title_font = text_font = small_font = ImageFont.load_default()
        
        glow_size = 8
        for offset in range(1, glow_size):
            alpha = int(50 / offset)
            glow_color = ImageProcessor._hex_to_rgba(rarity.color, alpha)
            draw.text((width//2 + offset, 70 + offset), f"{rarity.emoji} {character['name']}", 
                     fill=glow_color, font=title_font, anchor='mm')
        
        draw.text((width//2, 70), f"{rarity.emoji} {character['name']}", 
                 fill='white', font=title_font, anchor='mm', stroke_width=2, stroke_fill=rarity.color)
        
        draw.text((width//2, 150), f"🎬 {character['anime']}", 
                 fill='#e8e8e8', font=text_font, anchor='mm')
        
        rarity_bg_x = width//2 - 150
        rarity_bg_y = 195
        draw.rounded_rectangle(
            [(rarity_bg_x, rarity_bg_y), (rarity_bg_x + 300, rarity_bg_y + 45)],
            radius=23, fill=ImageProcessor._hex_to_rgba(rarity.color, 40), 
            outline=rarity.color, width=3
        )
        draw.text((width//2, 217), f"⭐ {rarity.display}", 
                 fill=rarity.color, font=text_font, anchor='mm', stroke_width=1, stroke_fill='white')
        
        streak_y = 290
        streak_bar_width = 450
        streak_bar_height = 50
        streak_x = (width - streak_bar_width) // 2
        
        shadow_offset = 4
        draw.rounded_rectangle(
            [(streak_x + shadow_offset, streak_y + shadow_offset), 
             (streak_x + streak_bar_width + shadow_offset, streak_y + streak_bar_height + shadow_offset)],
            radius=25, fill='#000000'
        )
        
        draw.rounded_rectangle(
            [(streak_x, streak_y), (streak_x + streak_bar_width, streak_y + streak_bar_height)],
            radius=25, fill='#1a1f3a', outline=rarity.color, width=4
        )
        
        filled_width = int((min(streak, CONFIG.MAX_STREAK) / CONFIG.MAX_STREAK) * (streak_bar_width - 12))
        if filled_width > 0:
            gradient_fill = Image.new('RGB', (filled_width, streak_bar_height - 12), color=rarity.color)
            draw_fill = ImageDraw.Draw(gradient_fill)
            for i in range(filled_width):
                color = ImageProcessor._interpolate_color(rarity.color, '#ffffff', i / filled_width * 0.3)
                draw_fill.line([(i, 0), (i, streak_bar_height - 12)], fill=color)
            
            mask = Image.new('L', (filled_width, streak_bar_height - 12), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (filled_width, streak_bar_height - 12)], radius=20, fill=255)
            img.paste(gradient_fill, (streak_x + 6, streak_y + 6), mask)
        
        streak_text = f"🔥 Streak: {streak}"
        if streak > CONFIG.MAX_STREAK:
            streak_text += f" 👑"
        draw.text((width//2, streak_y + 25), streak_text, 
                 fill='white', font=text_font, anchor='mm', stroke_width=2, stroke_fill='#000000')
        
        multiplier = min(streak, 10) * 0.5 + 1
        stats_y = 380
        stats = [
            f"⚡ Multiplier: {multiplier:.1f}x",
            f"🎯 Pity: {pity_counter.get(hash(user_name), 0)}/{CONFIG.PITY_SYSTEM_THRESHOLD}",
            f"🏆 ID: {character['id']}"
        ]
        
        for i, stat in enumerate(stats):
            y_pos = stats_y + (i * 45)
            draw.rounded_rectangle(
                [(width//2 - 200, y_pos - 18), (width//2 + 200, y_pos + 18)],
                radius=18, fill=ImageProcessor._hex_to_rgba('#1a1f3a', 150), 
                outline=rarity.color, width=2
            )
            draw.text((width//2, y_pos), stat, fill='#ffffff', font=small_font, anchor='mm')
        
        owner_y = 550
        draw.text((width//2, owner_y), f"👤 Claimed by: {user_name}", 
                 fill='#b8b8b8', font=text_font, anchor='mm')
        
        border_width = 8
        draw.rectangle([(0, 0), (width, height)], outline=rarity.color, width=border_width)
        
        for i in range(border_width):
            alpha = int(100 - (i * 12))
            inner_color = ImageProcessor._hex_to_rgba(rarity.color, alpha)
            draw.rectangle([(i, i), (width - i, height - i)], outline=inner_color, width=1)
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True, quality=90)
        buffer.seek(0)
        image_cache[cache_key] = buffer
        return buffer
    
    @staticmethod
    def _interpolate_color(color1: str, color2: str, factor: float) -> str:
        c1 = tuple(int(color1[i:i+2], 16) for i in (1, 3, 5))
        c2 = tuple(int(color2[i:i+2], 16) for i in (1, 3, 5))
        r = int(c1[0] + (c2[0] - c1[0]) * factor)
        g = int(c1[1] + (c2[1] - c1[1]) * factor)
        b = int(c1[2] + (c2[2] - c1[2]) * factor)
        return f'#{r:02x}{g:02x}{b:02x}'
    
    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return (r, g, b, alpha)

class CharacterManager:
    @staticmethod
    @retry(stop=stop_after_attempt(CONFIG.MAX_RETRIES), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_exception_type(Exception))
    async def fetch_character(user_id: int, target_rarity: Optional[str] = None, luck_factor: float = 1.0) -> Tuple[Optional[Dict], RarityType, bool, bool]:
        try:
            user_data = await CacheManager.get_user_data(user_id)
            claimed_ids = [c['id'] for c in user_data.get('characters', [])] if user_data else []
            
            is_pity = PitySystem.check_pity(user_id)
            is_ultra = LuckSystem.is_ultra_lucky()
            is_lucky = LuckSystem.is_lucky_boost()
            seasonal_event = TimeFormatter.get_seasonal_event()
            
            selected_rarity = None
            
            if is_ultra:
                selected_rarity = RarityType.MYTHIC
                logger.info(f"Ultra lucky for user {user_id}")
            elif is_pity:
                high_tier = [RarityType.MYTHIC, RarityType.CELESTIAL, RarityType.LEGENDARY]
                selected_rarity = random.choice(high_tier)
                logger.info(f"Pity triggered for user {user_id} - {selected_rarity.display}")
            elif seasonal_event and random.random() < 0.30:
                selected_rarity = seasonal_event
                logger.info(f"Seasonal boost for user {user_id} - {selected_rarity.display}")
            elif target_rarity:
                selected_rarity = CharacterManager._get_rarity_by_display(target_rarity)
            elif is_lucky:
                selected_rarity = CharacterManager._select_rarity_lucky(luck_factor)
                logger.info(f"Lucky boost for user {user_id} - {selected_rarity.display}")
            else:
                selected_rarity = CharacterManager._select_rarity(luck_factor)
            
            cache_key = CacheManager.generate_cache_key(
                'char', user_id, selected_rarity.key, len(claimed_ids), int(luck_factor * 100)
            )
            
            if cache_key in character_cache:
                cached_char = character_cache[cache_key]
                return cached_char, selected_rarity, is_lucky or is_ultra, is_pity
            
            pipeline = [
                {'$match': {'rarity': selected_rarity.display, 'id': {'$nin': claimed_ids}}},
                {'$sample': {'size': 1}}
            ]
            
            cursor = collection.aggregate(pipeline)
            result = await cursor.to_list(length=1)
            
            if not result:
                fallback_pipeline = [
                    {'$match': {'id': {'$nin': claimed_ids}}},
                    {'$sample': {'size': 1}}
                ]
                cursor = collection.aggregate(fallback_pipeline)
                result = await cursor.to_list(length=1)
                
                if result:
                    char_rarity = result[0].get('rarity', '')
                    selected_rarity = CharacterManager._get_rarity_by_display(char_rarity)
            
            if result:
                character_cache[cache_key] = result[0]
                return result[0], selected_rarity, is_lucky or is_ultra, is_pity
            
            raise CharacterNotFound("No available characters")
        except Exception as e:
            logger.error(f"Character fetch failed: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _get_rarity_by_display(display: str) -> RarityType:
        for rarity in RarityType:
            if rarity.display == display:
                return rarity
        return RarityType.DEFAULT
    
    @staticmethod
    def _select_rarity(luck_factor: float = 1.0) -> RarityType:
        rarities = [r for r in RarityType if r != RarityType.DEFAULT and r.weight > 0]
        weights = [r.weight * luck_factor for r in rarities]
        total = sum(weights)
        weights = [w / total for w in weights]
        selected = np.random.choice(rarities, p=weights)
        return selected
    
    @staticmethod
    def _select_rarity_lucky(luck_factor: float = 1.0) -> RarityType:
        high_tier = [
            RarityType.MYTHIC, RarityType.CELESTIAL, RarityType.LEGENDARY,
            RarityType.PREMIUM, RarityType.NEON, RarityType.EXCLUSIVE,
            RarityType.COSMIC, RarityType.PEARL
        ]
        weights = [r.weight * luck_factor * 2.5 for r in high_tier]
        total = sum(weights)
        weights = [w / total for w in weights]
        selected = np.random.choice(high_tier, p=weights)
        return selected

class StreakManager:
    @staticmethod
    def calculate_streak(last_claim: Optional[datetime], current_streak: int, now: datetime) -> Tuple[int, bool, bool]:
        if not last_claim:
            return 1, False, False
        if last_claim.tzinfo is None:
            last_claim = UTC_TZ.localize(last_claim)
        elapsed = now - last_claim
        if elapsed > timedelta(hours=CONFIG.STREAK_RESET_HOURS):
            return 1, False, True
        new_streak = current_streak + 1
        is_bonus = new_streak in CONFIG.BONUS_STREAK_MILESTONES
        return new_streak, is_bonus, False
    
    @staticmethod
    def generate_progress_bar(streak: int, max_streak: int = CONFIG.MAX_STREAK) -> str:
        display_streak = min(streak, max_streak)
        filled = "🔥" * display_streak
        empty = "⏳" * max(0, max_streak - display_streak)
        percentage = min(100, (streak / max_streak) * 100)
        
        if streak > max_streak:
            return f"{filled} ({percentage:.0f}%) 👑 LEGEND"
        return f"{filled}{empty} ({percentage:.0f}%)"
    
    @staticmethod
    def get_streak_multiplier(streak: int) -> float:
        if streak >= 30:
            return 5.0
        elif streak >= 21:
            return 4.0
        elif streak >= 14:
            return 3.5
        elif streak >= 10:
            return 3.0
        elif streak >= 7:
            return 2.5
        elif streak >= 5:
            return 2.0
        elif streak >= 3:
            return 1.5
        return 1.0
    
    @staticmethod
    def get_streak_message(streak: int) -> str:
        messages = {
            1: "🌟 ғʀᴇsʜ sᴛᴀʀᴛ!",
            3: "🔥 ʜᴇᴀᴛɪɴɢ ᴜᴘ!",
            5: "⚡ ᴏɴ ғɪʀᴇ!",
            7: "💎 ᴜɴsᴛᴏᴘᴘᴀʙʟᴇ!",
            10: "👑 ʟᴇɢᴇɴᴅᴀʀʏ!",
            14: "🏆 ᴍᴀsᴛᴇʀ!",
            21: "⭐ ᴇʟɪᴛᴇ!",
            30: "💫 ɢᴏᴅ ᴛɪᴇʀ!"
        }
        for threshold in sorted(messages.keys(), reverse=True):
            if streak >= threshold:
                return messages[threshold]
        return "💪 ᴋᴇᴇᴘ ɢᴏɪɴɢ!"

class MessageBuilder:
    @staticmethod
    def build_claim_message(user: object, character: Dict, streak: int, rarity: RarityType, is_lucky: bool = False, is_pity: bool = False) -> Tuple[str, InlineKeyboardMarkup]:
        now_kolkata = get_kolkata_time()
        time_emoji = TimeFormatter.get_time_emoji(now_kolkata.hour)
        day_bonus = TimeFormatter.get_day_bonus(now_kolkata.weekday())
        seasonal_event = TimeFormatter.get_seasonal_event()
        
        multiplier = StreakManager.get_streak_multiplier(streak)
        streak_msg = StreakManager.get_streak_message(streak)
        pity_progress, pity_max = PitySystem.get_pity_progress(user.id)
        
        special_tags = []
        if is_lucky:
            special_tags.append("🍀 ʟᴜᴄᴋʏ ʙᴏᴏsᴛ")
        if is_pity:
            special_tags.append("⭐ ᴘɪᴛʏ ʙᴏɴᴜs")
        if seasonal_event:
            special_tags.append(f"{seasonal_event.emoji} sᴇᴀsᴏɴᴀʟ")
        if day_bonus:
            special_tags.append(day_bonus)
        
        special_line = f"\n🎊 {' • '.join(special_tags)}\n" if special_tags else ""
        
        caption = (
            f"<b>✨ ᴅᴀɪʟʏ ᴄʟᴀɪᴍ sᴜᴄᴄᴇss!</b>\n"
            f"{'━' * 30}\n"
            f"👤 <b>ᴘʟᴀʏᴇʀ:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
            f"{rarity.emoji} <b>ᴄʜᴀʀᴀᴄᴛᴇʀ:</b> <code>{character.get('name')}</code>\n"
            f"🎬 <b>ᴀɴɪᴍᴇ:</b> <code>{character.get('anime')}</code>\n"
            f"⭐ <b>ʀᴀʀɪᴛʏ:</b> {rarity.display}\n"
            f"🆔 <b>ɪᴅ:</b> <code>{character.get('id')}</code>\n"
            f"{time_emoji} <b>ᴛɪᴍᴇ:</b> <code>{TimeFormatter.format_datetime(now_kolkata)}</code>\n"
            f"{special_line}"
            f"{'━' * 30}\n"
            f"📈 <b>sᴛʀᴇᴀᴋ:</b> {streak}/{CONFIG.MAX_STREAK} {streak_msg}\n"
            f"{StreakManager.generate_progress_bar(streak)}\n"
            f"⚡ <b>ᴍᴜʟᴛɪᴘʟɪᴇʀ:</b> {multiplier}x\n"
            f"🎯 <b>ᴘɪᴛʏ ᴘʀᴏɢʀᴇss:</b> {pity_progress}/{pity_max}\n"
            f"{'━' * 30}\n"
            f"💡 <i>ᴄʟᴀɪᴍ ᴅᴀɪʟʏ ғᴏʀ ʙᴇᴛᴛᴇʀ ʀᴇᴡᴀʀᴅs!</i>"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎒 ᴄᴏʟʟᴇᴄᴛɪᴏɴ", switch_inline_query_current_chat=f"collection.{user.id}")],
            [InlineKeyboardButton("🐉 sᴜᴘᴘᴏʀᴛ", url=CONFIG.SUPPORT_LINK)]
        ])
        
        return caption, keyboard
    
    @staticmethod
    def build_log_message(user: object, character: Dict, streak: int, rarity: RarityType) -> str:
        now_kolkata = get_kolkata_time()
        time_emoji = TimeFormatter.get_time_emoji(now_kolkata.hour)
        return (
            f"<b>#ᴅᴀɪʟʏ_ᴄʟᴀɪᴍ_ʟᴏɢ</b>\n\n"
            f"👤 <b>ᴜsᴇʀ:</b> {user.first_name} (<code>{user.id}</code>)\n"
            f"🎴 <b>ᴄʜᴀʀᴀᴄᴛᴇʀ:</b> {character.get('name')}\n"
            f"🎬 <b>ᴀɴɪᴍᴇ:</b> {character.get('anime')}\n"
            f"⭐ <b>ʀᴀʀɪᴛʏ:</b> {rarity.display}\n"
            f"🆔 <b>ɪᴅ:</b> <code>{character.get('id')}</code>\n"
            f"🔥 <b>sᴛʀᴇᴀᴋ:</b> {streak}/{CONFIG.MAX_STREAK}\n"
            f"⚡ <b>ᴍᴜʟᴛɪᴘʟɪᴇʀ:</b> {StreakManager.get_streak_multiplier(streak)}x\n"
            f"{time_emoji} <b>ɪsᴛ:</b> {TimeFormatter.format_datetime(now_kolkata)}\n"
            f"🌐 <b>ᴜᴛᴄ:</b> {datetime.now(UTC_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    @staticmethod
    def build_cooldown_message(remaining: timedelta, streak: int, user_id: int) -> str:
        next_claim = get_kolkata_time() + remaining
        pity_progress, pity_max = PitySystem.get_pity_progress(user_id)
        multiplier = StreakManager.get_streak_multiplier(streak)
        
        return (
            f"🕒 <b>ᴄᴏᴏʟᴅᴏᴡɴ ᴀᴄᴛɪᴠᴇ</b>\n\n"
            f"⌛ <b>ᴛɪᴍᴇ ʟᴇғᴛ:</b> <code>{TimeFormatter.format_duration(remaining)}</code>\n"
            f"🎯 <b>ɴᴇxᴛ ᴄʟᴀɪᴍ:</b> <code>{TimeFormatter.format_datetime(next_claim)}</code>\n"
            f"🔥 <b>ᴄᴜʀʀᴇɴᴛ sᴛʀᴇᴀᴋ:</b> {streak}/{CONFIG.MAX_STREAK}\n"
            f"⚡ <b>ᴍᴜʟᴛɪᴘʟɪᴇʀ:</b> {multiplier}x\n"
            f"🎯 <b>ᴘɪᴛʏ:</b> {pity_progress}/{pity_max}\n\n"
            f"💡 <i>sᴇᴛ ᴀ ʀᴇᴍɪɴᴅᴇʀ ᴛᴏ ᴋᴇᴇᴘ ʏᴏᴜʀ sᴛʀᴇᴀᴋ!</i>"
        )

@sudo_only
async def reset_cooldown(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>ᴜsᴀɢᴇ:</b> <code>/pro [User_ID] [option]</code>\n\n"
            "<b>ᴏᴘᴛɪᴏɴs:</b>\n"
            "• cooldown - Reset cooldown\n"
            "• streak - Reset streak\n"
            "• pity - Reset pity counter\n"
            "• all - Reset everything",
            parse_mode=ParseMode.HTML
        )
        return
    
    try:
        target_id = int(context.args[0])
        reset_type = context.args[1].lower() if len(context.args) > 1 else 'cooldown'
        reset_date = datetime(2000, 1, 1, tzinfo=UTC_TZ)
        update_fields = {}
        
        if reset_type in ['cooldown', 'all']:
            update_fields['last_daily_claim'] = reset_date
        if reset_type in ['streak', 'all']:
            update_fields['claim_streak'] = 0
        if reset_type in ['pity', 'all']:
            PitySystem.reset_pity(target_id)
        
        if update_fields:
            result = await user_collection.update_one({'id': target_id}, {'$set': update_fields}, upsert=True)
        else:
            result = type('obj', (object,), {'modified_count': 1})()
        
        CacheManager.invalidate_user_cache(target_id)
        
        status = "✅ <b>ʀᴇsᴇᴛ sᴜᴄᴄᴇss</b>" if result.modified_count > 0 else "ℹ️ <b>ᴜᴘᴅᴀᴛᴇᴅ</b>"
        reset_info = {
            'cooldown': 'ᴄᴏᴏʟᴅᴏᴡɴ',
            'streak': 'sᴛʀᴇᴀᴋ',
            'pity': 'ᴘɪᴛʏ ᴄᴏᴜɴᴛᴇʀ',
            'all': 'ᴀʟʟ ᴅᴀᴛᴀ'
        }.get(reset_type, 'ᴜɴᴋɴᴏᴡɴ')
        
        await update.message.reply_text(
            f"{status}\n"
            f"ᴜsᴇʀ <code>{target_id}</code> {reset_info} ʜᴀs ʙᴇᴇɴ ʀᴇsᴇᴛ.\n"
            f"🕐 <b>ᴛɪᴍᴇ:</b> {TimeFormatter.format_datetime(get_kolkata_time())}",
            parse_mode=ParseMode.HTML
        )
    except ValueError:
        await update.message.reply_text("❌ <b>ɪɴᴠᴀʟɪᴅ ᴜsᴇʀ ɪᴅ</b>\nProvide a valid numeric ID.", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Reset error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ <b>ᴇʀʀᴏʀ</b>\n<code>{str(e)[:100]}</code>", parse_mode=ParseMode.HTML)

@rate_limit
async def daily_claim(update: Update, context: CallbackContext):
    user = update.effective_user
    now = datetime.now(UTC_TZ)
    
    try:
        user_data = await CacheManager.get_user_data(user.id) or {}
        last_claimed = user_data.get('last_daily_claim')
        current_streak = user_data.get('claim_streak', 0)
        
        if last_claimed:
            if last_claimed.tzinfo is None:
                last_claimed = UTC_TZ.localize(last_claimed)
            
            elapsed = now - last_claimed
            
            if elapsed < timedelta(hours=CONFIG.COOLDOWN_HOURS):
                remaining = timedelta(hours=CONFIG.COOLDOWN_HOURS) - elapsed
                cooldown_msg = MessageBuilder.build_cooldown_message(remaining, current_streak, user.id)
                await update.message.reply_text(cooldown_msg, parse_mode=ParseMode.HTML)
                return
        
        new_streak, is_bonus, is_reset = StreakManager.calculate_streak(last_claimed, current_streak, now)
        
        luck_factor = LuckSystem.calculate_luck_factor(user.id, new_streak)
        
        target_rarity = None
        if is_bonus:
            high_tier = [RarityType.MYTHIC, RarityType.CELESTIAL, RarityType.LEGENDARY]
            target_rarity = random.choice(high_tier).display
        
        character, rarity, is_lucky, is_pity = await CharacterManager.fetch_character(user.id, target_rarity, luck_factor)
        
        if not character:
            await update.message.reply_text(
                "❗ <b>ɴᴏ ᴄʜᴀʀᴀᴄᴛᴇʀs ᴀᴠᴀɪʟᴀʙʟᴇ</b>\n"
                "All characters claimed or database empty.",
                parse_mode=ParseMode.HTML
            )
            return
        
        await user_collection.update_one(
            {'id': user.id},
            {
                '$push': {'characters': character},
                '$set': {
                    'last_daily_claim': now,
                    'claim_streak': new_streak,
                    'first_name': user.first_name,
                    'last_updated': now
                },
                '$inc': {'total_claims': 1}
            },
            upsert=True
        )
        
        CacheManager.invalidate_user_cache(user.id)
        
        try:
            card_image = await ImageProcessor.create_claim_card(character, user.first_name, new_streak, rarity)
            
            caption, keyboard = MessageBuilder.build_claim_message(user, character, new_streak, rarity, is_lucky, is_pity)
            
            await update.message.reply_photo(
                photo=card_image,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            
            card_image.seek(0)
        except Exception as img_error:
            logger.error(f"Image generation failed: {img_error}")
            caption, keyboard = MessageBuilder.build_claim_message(user, character, new_streak, rarity, is_lucky, is_pity)
            
            await update.message.reply_photo(
                photo=character.get('img_url'),
                caption=caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        
        log_caption = MessageBuilder.build_log_message(user, character, new_streak, rarity)
        asyncio.create_task(send_log_async(context, character, log_caption))
        
    except CharacterNotFound:
        logger.warning(f"No characters for user {user.id}")
        await update.message.reply_text(
            "❗ <b>ɴᴏ ᴍᴏʀᴇ ᴄʜᴀʀᴀᴄᴛᴇʀs</b>\n"
            "You've claimed all available characters!",
            parse_mode=ParseMode.HTML
        )
    except (RetryAfter, TimedOut) as e:
        logger.error(f"Telegram API error: {e}")
        await update.message.reply_text(
            "⚠️ <b>sᴇʀᴠᴇʀ ʙᴜsʏ</b>\nPlease try again.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Claim error for user {user.id}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ <b>ᴄʟᴀɪᴍ ғᴀɪʟᴇᴅ</b>\n"
            f"<code>{str(e)[:100]}</code>\n\n"
            "Contact support if this persists.",
            parse_mode=ParseMode.HTML
        )

async def send_log_async(context: CallbackContext, character: Dict, caption: str):
    try:
        await context.bot.send_photo(
            chat_id=CONFIG.LOG_GROUP_ID,
            photo=character.get('img_url'),
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except TelegramError as e:
        logger.error(f"Log send failed: {e}")

application.add_handler(CommandHandler(['sclaim', 'claim'], daily_claim, block=False))
application.add_handler(CommandHandler('pro', reset_cooldown, block=False))
