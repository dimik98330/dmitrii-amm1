import asyncio
import random
from datetime import datetime, timedelta
from enum import Enum
import json
import logging
import os
from typing import List, Dict, Optional
import math

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Boolean, Float, JSON
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

# Импорт из наших модулей
from config import (
    API_TOKEN,
    DATABASE_URL,
    ADMIN_IDS,
    CURRENT_USER,
    CURRENT_DATE,
    MAX_LEVEL,
    BASE_EXP_MULTIPLIER,
    ENERGY_REGEN_RATE,
    MAX_INVENTORY_SLOTS
)
from states import GameStates

# Настройка логирования
LOG_FILENAME = f"logs/bot_{datetime.now().strftime('%Y-%m-%d')}.log"

# Создаем директорию для логов, если её нет
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s - User: dimik98330 - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Настройка базы данных
Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=True)  # echo=True для отладки SQL запросов
Session = sessionmaker(bind=engine)
# Константы игры
ENERGY_REGEN_RATE = 1  # энергия в минуту
MAX_INVENTORY_SLOTS = 50
HEALTH_REGEN_RATE = 5  # здоровье в минуту
EXPERIENCE_MULTIPLIER = 1.5
BASE_ENERGY_COST = 5
BASE_HEALTH_COST = 10


# Игровые перечисления
class ItemType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    HELMET = "helmet"
    BOOTS = "boots"
    AMULET = "amulet"
    RING = "ring"
    POTION = "potion"
    QUEST_ITEM = "quest_item"
    MATERIAL = "material"


class ItemRarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    MYTHICAL = "mythical"


class QuestType(str, Enum):
    KILL_MONSTERS = "kill_monsters"
    COLLECT_ITEMS = "collect_items"
    CRAFT_ITEMS = "craft_items"
    WIN_PVP = "win_pvp"
    COMPLETE_DUNGEON = "complete_dungeon"


class AchievementType(str, Enum):
    MONSTER_KILLS = "monster_kills"
    ITEMS_COLLECTED = "items_collected"
    QUESTS_COMPLETED = "quests_completed"
    PVP_WINS = "pvp_wins"
    DUNGEONS_COMPLETED = "dungeons_completed"
    ITEMS_CRAFTED = "items_crafted"


class BattleType(str, Enum):
    PVE = "pve"
    PVP = "pvp"
    DUNGEON = "dungeon"
    BOSS = "boss"
    EVENT = "event"


# Декораторы
def admin_required(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id not in ADMIN_IDS:
            await message.reply("⛔ У вас нет прав для выполнения этой команды!")
            logger.warning(f"Unauthorized access attempt by user {message.from_user.id}")
            return
        return await func(message, *args, **kwargs)

    return wrapper


def energy_required(amount: int):
    def decorator(func):
        async def wrapper(message: types.Message, *args, **kwargs):
            session = Session()
            try:
                player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                if not player or player.energy < amount:
                    await message.reply(f"⚡ Недостаточно энергии! Требуется: {amount}")
                    logger.info(f"User {message.from_user.id} - insufficient energy for action")
                    return

                return await func(message, *args, **kwargs)
            finally:
                session.close()

        return wrapper

    return decorator


# Служебные функции
def calculate_level_exp(level: int) -> int:
    """Рассчитывает опыт, необходимый для следующего уровня"""
    return int(BASE_EXP_MULTIPLIER * (level ** EXPERIENCE_MULTIPLIER))


def format_duration(seconds: int) -> str:
    """Форматирует время в читаемый вид"""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes}м")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


def get_item_rarity_color(rarity: ItemRarity) -> str:
    """Возвращает цвет для редкости предмета"""
    colors = {
        ItemRarity.COMMON: "⚪",
        ItemRarity.UNCOMMON: "🟢",
        ItemRarity.RARE: "🔵",
        ItemRarity.EPIC: "🟣",
        ItemRarity.LEGENDARY: "🟡",
        ItemRarity.MYTHICAL: "🔴"
    }
    return colors.get(rarity, "⚪")


def calculate_damage(base_damage: int, level: int, buffs: Dict = None) -> int:
    """Рассчитывает итоговый урон с учетом уровня и баффов"""
    damage = base_damage * (1 + level * 0.1)
    if buffs:
        damage *= (1 + buffs.get('damage_multiplier', 0))
    return int(damage)


# Функции для работы с временем
def get_time_diff(last_time: datetime) -> int:
    """Возвращает разницу во времени в секундах"""
    now = CURRENT_DATE
    return int((now - last_time).total_seconds())


def calculate_energy_restore(last_restore: datetime) -> int:
    """Рассчитывает восстановленную энергию"""
    seconds_passed = get_time_diff(last_restore)
    return int(seconds_passed * (ENERGY_REGEN_RATE / 60))


def calculate_health_restore(last_restore: datetime) -> int:
    """Рассчитывает восстановленное здоровье"""
    seconds_passed = get_time_diff(last_restore)
    return int(seconds_passed * (HEALTH_REGEN_RATE / 60))


# Модели базы данных
# noinspection Annotator
class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    name = Column(String)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    batons = Column(Integer, default=100)
    premium_currency = Column(Integer, default=0)
    strength = Column(Integer, default=10)
    agility = Column(Integer, default=10)
    intelligence = Column(Integer, default=10)
    vitality = Column(Integer, default=10)
    energy = Column(Integer, default=100)
    max_energy = Column(Integer, default=100)
    health = Column(Integer, default=100)
    max_health = Column(Integer, default=100)
    last_daily = Column(DateTime, nullable=True)
    last_energy_regen = Column(DateTime, default=datetime.utcnow)
    last_health_regen = Column(DateTime, default=datetime.utcnow)
    clan_id = Column(Integer, ForeignKey('clans.id'), nullable=True)
    rank = Column(String, default="Новичок")
    pvp_rating = Column(Integer, default=1000)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    quest_points = Column(Integer, default=0)
    achievement_points = Column(Integer, default=0)
    crafting_level = Column(Integer, default=1)
    crafting_experience = Column(Integer, default=0)
    last_location = Column(String, default="town")
    inventory_slots = Column(Integer, default=20)

    # Отношения
    equipment = relationship("Equipment", uselist=False, back_populates="player")
    inventory = relationship("Inventory", back_populates="player")
    quests = relationship("PlayerQuest", back_populates="player")
    achievements = relationship("PlayerAchievement", back_populates="player")
    skills = relationship("PlayerSkill", back_populates="player")

    def get_total_stats(self, session) -> Dict[str, int]:
        """Подсчет всех характеристик игрока с учетом снаряжения и баффов"""
        total_stats = {
            'strength': self.strength,
            'agility': self.agility,
            'intelligence': self.intelligence,
            'vitality': self.vitality,
            'health': self.max_health,
            'energy': self.max_energy,
            'damage': self.strength * 2,
            'defense': self.vitality * 1.5,
            'critical_chance': self.agility * 0.5,
            'dodge_chance': self.agility * 0.3
        }

        # Добавляем бонусы от снаряжения
        if self.equipment:
            for slot in ['weapon_id', 'armor_id', 'helmet_id', 'boots_id', 'amulet_id', 'ring_id']:
                item_id = getattr(self.equipment, slot)
                if item_id:
                    item = session.query(Item).get(item_id)
                    if item:
                        total_stats['strength'] += item.strength_bonus
                        total_stats['agility'] += item.agility_bonus
                        total_stats['intelligence'] += item.intelligence_bonus
                        total_stats['vitality'] += item.vitality_bonus
                        total_stats['health'] += item.health_bonus
                        total_stats['energy'] += item.energy_bonus
                        total_stats['damage'] += item.damage_bonus
                        total_stats['defense'] += item.defense_bonus

        active_buffs = session.query(PlayerBuff).filter_by(
            player_id=self.id
        ).filter(
            PlayerBuff.expires_at > datetime.utcnow()
        ).all()

        for buff in active_buffs:
            if buff.stat_bonuses:
                for stat, bonus in buff.stat_bonuses.items():
                    if stat in total_stats:
                        total_stats[stat] += bonus

        return total_stats

    def can_equip_item(self, item: "Item") -> bool:
        """Проверка возможности экипировать предмет"""
        return (
                item.is_equippable and
                self.level >= item.level_required and
                self.strength >= item.strength_required and
                self.agility >= item.agility_required and
                self.intelligence >= item.intelligence_required
        )

    def regenerate_energy(self):
        """Регенерация энергии"""
        now = datetime.utcnow()
        if self.last_energy_regen:
            minutes_passed = (now - self.last_energy_regen).total_seconds() / 60
            energy_gain = int(minutes_passed * ENERGY_REGEN_RATE)
            if energy_gain > 0:
                self.energy = min(self.max_energy, self.energy + energy_gain)
                self.last_energy_regen = now

    def regenerate_health(self):
        """Регенерация здоровья"""
        now = datetime.utcnow()
        if self.last_health_regen:
            minutes_passed = (now - self.last_health_regen).total_seconds() / 60
            health_gain = int(minutes_passed * HEALTH_REGEN_RATE)
            if health_gain > 0:
                self.health = min(self.max_health, self.health + health_gain)
                self.last_health_regen = now

    def add_experience(self, amount: int) -> bool:
        """Добавление опыта и проверка повышения уровня"""
        self.experience += amount
        level_up = False

        while self.experience >= self.get_next_level_exp():
            self.level += 1
            level_up = True
            # Бонусы за уровень
            self.strength += 2
            self.agility += 2
            self.intelligence += 2
            self.vitality += 2
            self.max_health += 20
            self.max_energy += 10

        return level_up

        def get_next_level_exp(self) -> int:
            """Расчет опыта для следующего уровня"""
            return int(100 * (self.level ** EXPERIENCE_MULTIPLIER))

    class Item(Base):
        __tablename__ = 'items'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        item_type = Column(String)
        rarity = Column(String)
        level_required = Column(Integer, default=1)
        strength_required = Column(Integer, default=0)
        agility_required = Column(Integer, default=0)
        intelligence_required = Column(Integer, default=0)
        strength_bonus = Column(Integer, default=0)
        agility_bonus = Column(Integer, default=0)
        intelligence_bonus = Column(Integer, default=0)
        vitality_bonus = Column(Integer, default=0)
        health_bonus = Column(Integer, default=0)
        energy_bonus = Column(Integer, default=0)
        damage_bonus = Column(Integer, default=0)
        defense_bonus = Column(Integer, default=0)
        price = Column(Integer)
        sell_price = Column(Integer)
        is_equippable = Column(Boolean, default=False)
        is_tradeable = Column(Boolean, default=True)
        is_stackable = Column(Boolean, default=False)
        max_stack = Column(Integer, default=1)
        durability = Column(Integer, nullable=True)
        max_durability = Column(Integer, nullable=True)
        effects = Column(JSON, nullable=True)

    class Equipment(Base):
        __tablename__ = 'equipment'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        weapon_id = Column(Integer, ForeignKey('items.id'), nullable=True)
        armor_id = Column(Integer, ForeignKey('items.id'), nullable=True)
        helmet_id = Column(Integer, ForeignKey('items.id'), nullable=True)
        boots_id = Column(Integer, ForeignKey('items.id'), nullable=True)
        amulet_id = Column(Integer, ForeignKey('items.id'), nullable=True)
        ring_id = Column(Integer, ForeignKey('items.id'), nullable=True)

        player = relationship("Player", back_populates="equipment")
        weapon = relationship("Item", foreign_keys=[weapon_id])
        armor = relationship("Item", foreign_keys=[armor_id])
        helmet = relationship("Item", foreign_keys=[helmet_id])
        boots = relationship("Item", foreign_keys=[boots_id])
        amulet = relationship("Item", foreign_keys=[amulet_id])
        ring = relationship("Item", foreign_keys=[ring_id])

    class Monster(Base):
        __tablename__ = 'monsters'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        level = Column(Integer)
        health = Column(Integer)
        damage = Column(Integer)
        defense = Column(Integer)
        experience_reward = Column(Integer)
        baton_reward_min = Column(Integer)
        baton_reward_max = Column(Integer)
        drop_table = Column(JSON)  # {item_id: drop_chance}
        special_abilities = Column(JSON, nullable=True)
        location = Column(String)
        respawn_time = Column(Integer, default=60)  # в секундах
        is_boss = Column(Boolean, default=False)
        required_level = Column(Integer, default=1)

    class Dungeon(Base):
        __tablename__ = 'dungeons'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        min_level = Column(Integer)
        max_players = Column(Integer)
        monster_groups = Column(JSON)  # [{monster_id: count}]
        boss_id = Column(Integer, ForeignKey('monsters.id'), nullable=True)
        rewards = Column(JSON)  # {item_id: drop_chance}
        completion_time = Column(Integer)  # в минутах
        energy_cost = Column(Integer)
        cooldown = Column(Integer)  # в часах

    class DungeonProgress(Base):
        __tablename__ = 'dungeon_progress'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        dungeon_id = Column(Integer, ForeignKey('dungeons.id'))
        completed_times = Column(Integer, default=0)
        best_time = Column(Integer, nullable=True)
        last_attempt = Column(DateTime, nullable=True)
        current_progress = Column(JSON, nullable=True)

    class Quest(Base):
        __tablename__ = 'quests'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        quest_type = Column(String)
        min_level = Column(Integer)
        requirements = Column(JSON)  # {monster_kills: count, item_collect: {item_id: count}}
        time_limit = Column(Integer, nullable=True)  # в минутах
        reward_experience = Column(Integer)
        reward_batons = Column(Integer)
        reward_items = Column(JSON)  # {item_id: count}
        energy_cost = Column(Integer)
        cooldown = Column(Integer)  # в часах
        is_daily = Column(Boolean, default=False)
        is_repeatable = Column(Boolean, default=False)
        required_quests = Column(JSON)  # [quest_ids]
        story_chapter = Column(Integer, nullable=True)

    class PlayerQuest(Base):
        __tablename__ = 'player_quests'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        quest_id = Column(Integer, ForeignKey('quests.id'))
        status = Column(String, default='active')  # active, completed, failed
        progress = Column(JSON)  # {requirement_key: current_value}
        started_at = Column(DateTime, default=datetime.utcnow)
        completed_at = Column(DateTime, nullable=True)
        times_completed = Column(Integer, default=0)

    class Achievement(Base):
        __tablename__ = 'achievements'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        achievement_type = Column(String)
        requirements = Column(JSON)  # {type: value}
        reward_title = Column(String, nullable=True)
        reward_batons = Column(Integer)
        reward_items = Column(JSON, nullable=True)
        icon = Column(String, nullable=True)
        points = Column(Integer)

    class PlayerAchievement(Base):
        __tablename__ = 'player_achievements'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        achievement_id = Column(Integer, ForeignKey('achievements.id'))
        progress = Column(JSON)
        completed = Column(Boolean, default=False)
        completed_at = Column(DateTime, nullable=True)

    class Skill(Base):
        __tablename__ = 'skills'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        skill_type = Column(String)
        max_level = Column(Integer)
        base_damage = Column(Integer, nullable=True)
        energy_cost = Column(Integer)
        cooldown = Column(Integer)  # в секундах
        effects = Column(JSON, nullable=True)
        requirements = Column(JSON)  # {level: value, strength: value, etc}

    class PlayerSkill(Base):
        __tablename__ = 'player_skills'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        skill_id = Column(Integer, ForeignKey('skills.id'))
        level = Column(Integer, default=1)
        experience = Column(Integer, default=0)
        last_used = Column(DateTime, nullable=True)

    class Shop(Base):
        __tablename__ = 'shops'
        id = Column(Integer, primary_key=True)
        name = Column(String)
        description = Column(String)
        shop_type = Column(String)  # regular, premium, special
        items = Column(JSON)  # {item_id: {price: value, quantity: value, restock_time: value}}
        refresh_interval = Column(Integer)  # в часах
        last_refresh = Column(DateTime)
        required_level = Column(Integer, default=1)
        required_reputation = Column(Integer, default=0)

    class PlayerBuff(Base):
        __tablename__ = 'player_buffs'
        id = Column(Integer, primary_key=True)
        player_id = Column(Integer, ForeignKey('players.id'))
        name = Column(String)
        description = Column(String)
        stat_bonuses = Column(JSON)  # {stat: bonus_value}
        duration = Column(Integer)  # в секундах
        started_at = Column(DateTime, default=datetime.utcnow)
        expires_at = Column(DateTime)

    # Игровые состояния
    class GameStates(StatesGroup):
        main_menu = State()
        battle = State()
        shop = State()
        inventory = State()
        equipment = State()
        quest = State()
        dungeon = State()
        craft = State()
        trade = State()
        clan = State()
        skills = State()
        achievements = State()
        settings = State()

    # Функции для боевой системы
    async def battle_calculation(player: Player, monster: Monster, session) -> Dict:
        """Расчет результатов боя между игроком и монстром"""
        player_stats = player.get_total_stats(session)
        battle_log = []

        player_hp = player_stats['health']
        monster_hp = monster.health
        rounds = 0

        while player_hp > 0 and monster_hp > 0 and rounds < 20:
            # Ход игрока
            player_damage = max(1, player_stats['damage'] - monster.defense // 2)
            crit_chance = random.random() < (player_stats['critical_chance'] / 100)
            if crit_chance:
                player_damage *= 2
                battle_log.append(f"💥 Критический удар! {player.name} наносит {player_damage} урона!")
            else:
                battle_log.append(f"⚔️ {player.name} наносит {player_damage} урона!")
            monster_hp -= player_damage

            # Ход монстра
            if monster_hp > 0:
                monster_damage = max(1, monster.damage - player_stats['defense'] // 2)
                dodge_chance = random.random() < (player_stats['dodge_chance'] / 100)
                if dodge_chance:
                    battle_log.append(f"🌟 {player.name} уклоняется от атаки!")
                else:
                    player_hp -= monster_damage
                    battle_log.append(f"🗡️ {monster.name} наносит {monster_damage} урона!")

            rounds += 1

        victory = player_hp > 0

        return {
            'victory': victory,
            'remaining_hp': player_hp,
            'battle_log': battle_log,
            'rounds': rounds
        }

    async def process_battle_rewards(player: Player, monster: Monster, session):
        """Обработка наград после победы над монстром"""
        exp_reward = monster.experience_reward
        baton_reward = random.randint(monster.baton_reward_min, monster.baton_reward_max)

        level_up = player.add_experience(exp_reward)
        player.batons += baton_reward

        # Обработка выпадения предметов
        dropped_items = []
        if monster.drop_table:
            for item_id, chance in monster.drop_table.items():
                if random.random() < chance:
                    item = session.query(Item).get(item_id)
                    if item:
                        inventory_item = Inventory(
                            player_id=player.id,
                            item_id=item_id,
                            quantity=1
                        )
                        session.add(inventory_item)
                        dropped_items.append(item.name)

        session.commit()
        return {
            'experience': exp_reward,
            'batons': baton_reward,
            'level_up': level_up,
            'dropped_items': dropped_items
        }

    # Обработчики команд для боевой системы
    @dp.message_handler(lambda message: message.text == "⚔️ Битва", state=GameStates.main_menu)
    async def handle_battle(message: types.Message, state: FSMContext):
        session = Session()
        player = session.query(Player).filter_by(user_id=message.from_user.id).first()

        if player.energy < 10:
            await message.answer("⚠️ У вас недостаточно энергии для битвы! Подождите пока она восстановится.")
            return

        # Выбор монстра в соответствии с уровнем игрока
        available_monsters = session.query(Monster).filter(
            Monster.required_level <= player.level
        ).all()

        if not available_monsters:
            await message.answer("🔍 Не удалось найти подходящих монстров для битвы.")
            return

        monster = random.choice(available_monsters)

        # Создаем клавиатуру для битвы
        battle_keyboard = types.InlineKeyboardMarkup()
        battle_keyboard.add(types.InlineKeyboardButton("⚔️ Атаковать", callback_data=f"battle_attack_{monster.id}"))
        battle_keyboard.add(types.InlineKeyboardButton("🏃 Убежать", callback_data="battle_flee"))

        await message.answer(
            f"Вы встретили {monster.name}!\n"
            f"Уровень: {monster.level}\n"
            f"❤️ Здоровье: {monster.health}\n"
            f"⚔️ Урон: {monster.damage}\n"
            f"🛡️ Защита: {monster.defense}\n\n"
            f"{monster.description}\n\n"
            "Что будете делать?",
            reply_markup=battle_keyboard
        )

        await GameStates.battle.set()
        await state.update_data(monster_id=monster.id)

    @dp.callback_query_handler(lambda c: c.data.startswith('battle_'), state=GameStates.battle)
    async def process_battle_action(callback_query: types.CallbackQuery, state: FSMContext):
        session = Session()
        player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()

        if callback_query.data == "battle_flee":
            energy_loss = 5
            player.energy = max(0, player.energy - energy_loss)
            session.commit()

            await callback_query.message.edit_text(
                f"Вы сбежали из битвы!\n"
                f"Потеряно {energy_loss} энергии."
            )
            await GameStates.main_menu.set()
            return

        data = await state.get_data()
        monster_id = data.get('monster_id')
        monster = session.query(Monster).get(monster_id)

        if not monster:
            await callback_query.message.edit_text("Ошибка: монстр не найден.")
            await GameStates.main_menu.set()
            return

        # Проводим бой
        battle_result = await battle_calculation(player, monster, session)

        # Обновляем здоровье и энергию игрока
        player.health = battle_result['remaining_hp']
        player.energy -= 10

        battle_log = "\n".join(battle_result['battle_log'])

        if battle_result['victory']:
            rewards = await process_battle_rewards(player, monster, session)

            reward_text = (
                f"🎉 Победа!\n\n"
                f"Получено:\n"
                f"✨ Опыт: {rewards['experience']}\n"
                f"🥖 Батоны: {rewards['batons']}\n"
            )

            if rewards['dropped_items']:
                reward_text += f"📦 Предметы: {', '.join(rewards['dropped_items'])}\n"

            if rewards['level_up']:
                reward_text += f"\n🎊 Поздравляем! Вы достигли {player.level} уровня!"

            await callback_query.message.edit_text(
                f"{battle_log}\n\n{reward_text}",
                parse_mode=types.ParseMode.HTML
            )
        else:
            await callback_query.message.edit_text(
                f"{battle_log}\n\n"
                "☠️ Вы проиграли битву!\n"
                "Потеряно 10 энергии."
            )

        session.commit()
        await GameStates.main_menu.set()

    # Система подземелий
    @dp.message_handler(lambda message: message.text == "🏰 Подземелья", state=GameStates.main_menu)
    async def show_dungeons(message: types.Message):
        session = Session()
        player = session.query(Player).filter_by(user_id=message.from_user.id).first()

        available_dungeons = session.query(Dungeon).filter(
            Dungeon.min_level <= player.level
        ).all()

        if not available_dungeons:
            await message.answer("🏰 Доступных подземелий пока нет. Повысьте свой уровень!")
            return

        dungeon_keyboard = types.InlineKeyboardMarkup()
        for dungeon in available_dungeons:
            dungeon_keyboard.add(
                types.InlineKeyboardButton(
                    f"{dungeon.name} (Ур. {dungeon.min_level}+)",
                    callback_data=f"dungeon_{dungeon.id}"
                )
            )

        await message.answer(
            "🏰 Доступные подземелья:\n"
            "Выберите подземелье для исследования:",
            reply_markup=dungeon_keyboard
        )
        await GameStates.dungeon.set()

    @dp.callback_query_handler(lambda c: c.data.startswith('dungeon_'), state=GameStates.dungeon)
    async def process_dungeon_selection(callback_query: types.CallbackQuery, state: FSMContext):
        session = Session()
        player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()

        dungeon_id = int(callback_query.data.split('_')[1])
        dungeon = session.query(Dungeon).get(dungeon_id)

        if not dungeon:
            await callback_query.message.edit_text("Ошибка: подземелье не найдено.")
            await GameStates.main_menu.set()
            return

        # Проверяем кулдаун
        progress = session.query(DungeonProgress).filter_by(
            player_id=player.id,
            dungeon_id=dungeon_id
        ).first()

        if progress and progress.last_attempt:
            cooldown_end = progress.last_attempt + timedelta(hours=dungeon.cooldown)
            if datetime.utcnow() < cooldown_end:
                time_left = cooldown_end - datetime.utcnow()
                hours, remainder = divmod(int(time_left.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)

                await callback_query.message.edit_text(
                    f"⏳ Подземелье еще не восстановилось!\n"
                    f"Осталось времени: {hours}ч {minutes}м"
                )
                return

        if player.energy < dungeon.energy_cost:
            await callback_query.message.edit_text(
                f"⚠️ Для входа в подземелье требуется {dungeon.energy_cost} энергии.\n"
                f"У вас есть только {player.energy} энергии."
            )
            return

            # Начинаем прохождение подземелья
        player.energy -= dungeon.energy_cost

        # Создаем или обновляем прогресс подземелья
        if not progress:
            progress = DungeonProgress(
                player_id=player.id,
                dungeon_id=dungeon_id,
                completed_times=0
            )
            session.add(progress)

        progress.last_attempt = datetime.utcnow()
        progress.current_progress = {
            'current_room': 0,
            'monsters_defeated': 0,
            'hp_remaining': player.health,
            'start_time': datetime.utcnow().timestamp()
        }

        dungeon_keyboard = types.InlineKeyboardMarkup()
        dungeon_keyboard.add(
            types.InlineKeyboardButton("➡️ Следующая комната", callback_data=f"dungeon_next_{dungeon_id}"))
        dungeon_keyboard.add(types.InlineKeyboardButton("🏃 Покинуть подземелье", callback_data="dungeon_leave"))

        await callback_query.message.edit_text(
            f"🏰 Вы вошли в подземелье {dungeon.name}!\n\n"
            f"Описание: {dungeon.description}\n"
            f"Уровень сложности: {dungeon.min_level}+\n"
            f"Комнат до босса: {len(dungeon.monster_groups)}\n"
            f"Время на прохождение: {dungeon.completion_time} минут\n\n"
            "Приготовьтесь к битве!",
            reply_markup=dungeon_keyboard
        )
        session.commit()

    @dp.callback_query_handler(lambda c: c.data.startswith('dungeon_next_'), state=GameStates.dungeon)
    async def process_dungeon_room(callback_query: types.CallbackQuery, state: FSMContext):
        session = Session()
        player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
        dungeon_id = int(callback_query.data.split('_')[2])
        dungeon = session.query(Dungeon).get(dungeon_id)
        progress = session.query(DungeonProgress).filter_by(
            player_id=player.id,
            dungeon_id=dungeon_id
        ).first()

        if not progress or not progress.current_progress:
            await callback_query.message.edit_text("Ошибка: прогресс подземелья не найден.")
            await GameStates.main_menu.set()
            return

        current_room = progress.current_progress['current_room']

        # Проверяем время прохождения
        elapsed_time = datetime.utcnow().timestamp() - progress.current_progress['start_time']
        if elapsed_time > dungeon.completion_time * 60:
            await callback_query.message.edit_text(
                "⏰ Время вышло! Вы не успели пройти подземелье.\n"
                "Попробуйте снова после восстановления подземелья."
            )
            await GameStates.main_menu.set()
            return

        # Генерируем монстров для комнаты
        if current_room < len(dungeon.monster_groups):
            room_monsters = []
            for monster_id, count in dungeon.monster_groups[current_room].items():
                monster = session.query(Monster).get(monster_id)
                if monster:
                    room_monsters.extend([monster] * count)

            # Сражение с монстрами комнаты
            battle_logs = []
            for monster in room_monsters:
                battle_result = await battle_calculation(player, monster, session)
                battle_logs.extend(battle_result['battle_log'])

                if not battle_result['victory']:
                    await callback_query.message.edit_text(
                        f"{'⚔️ '.join(battle_logs)}\n\n"
                        "☠️ Вы пали в бою! Подземелье не пройдено."
                    )
                    await GameStates.main_menu.set()
                    return

                player.health = battle_result['remaining_hp']
                progress.current_progress['monsters_defeated'] += 1

            # Обновляем прогресс
            progress.current_progress['current_room'] += 1
            progress.current_progress['hp_remaining'] = player.health

            # Проверяем, достигнут ли босс
            if progress.current_progress['current_room'] >= len(dungeon.monster_groups):
                if dungeon.boss_id:
                    # Битва с боссом
                    boss = session.query(Monster).get(dungeon.boss_id)
                    boss_battle = await battle_calculation(player, boss, session)
                    battle_logs.extend(boss_battle['battle_log'])

                    if boss_battle['victory']:
                        # Награды за прохождение
                        rewards = await process_dungeon_rewards(player, dungeon, session)
                        progress.completed_times += 1

                        if not progress.best_time or elapsed_time < progress.best_time:
                            progress.best_time = int(elapsed_time)

                        reward_text = (
                            f"🎉 Поздравляем! Вы прошли подземелье {dungeon.name}!\n\n"
                            f"Награды:\n"
                            f"✨ Опыт: {rewards['experience']}\n"
                            f"🥖 Батоны: {rewards['batons']}\n"
                        )

                        if rewards['items']:
                            reward_text += f"📦 Предметы:\n" + "\n".join([f"- {item}" for item in rewards['items']])

                        if rewards['level_up']:
                            reward_text += f"\n🎊 Вы достигли {player.level} уровня!"

                        await callback_query.message.edit_text(reward_text)

                        # Проверяем достижения
                    if boss:  # Предполагаем, что здесь должна быть проверка на наличие босса
                        if victory:  # Предполагаем, что здесь должна быть проверка победы над боссом
                            await check_achievements(player, session, {
                                'dungeon_completed': dungeon.id,
                                'monsters_killed': progress.current_progress['monsters_defeated']
                            })
                        else:
                            await callback_query.message.edit_text(
                                f"{'⚔️ '.join(battle_logs)}\n\n"
                                f"☠️ Босс {boss.name} оказался слишком силён! Подземелье не пройдено."
                            )
                    else:
                        # Подземелье без босса
                        rewards = await process_dungeon_rewards(player, dungeon, session)
                        await callback_query.message.edit_text(
                            f"🎉 Подземелье {dungeon.name} пройдено!\n\n"
                            f"Получено:\n"
                            f"✨ Опыт: {rewards['experience']}\n"
                            f"🥖 Батоны: {rewards['batons']}\n"
                            f"📦 Предметы: {', '.join(rewards['items']) if rewards['items'] else 'нет'}"
                        )
                    # Продолжаем исследование подземелья
                    dungeon_keyboard = types.InlineKeyboardMarkup()
                    dungeon_keyboard.add(
                        types.InlineKeyboardButton("➡️ Следующая комната", callback_data=f"dungeon_next_{dungeon_id}")
                    )
                    dungeon_keyboard.add(
                        types.InlineKeyboardButton("🏃 Покинуть подземелье", callback_data="dungeon_leave")
                    )

                    await callback_query.message.edit_text(
                        f"Комната {progress.current_progress['current_room']} пройдена!\n\n"
                        f"{'⚔️ '.join(battle_logs)}\n\n"
                        f"❤️ Здоровье: {player.health}/{player.max_health}\n"
                        f"⚡ Энергия: {player.energy}/{player.max_energy}\n"
                        f"Монстров побеждено: {progress.current_progress['monsters_defeated']}\n"
                        f"До босса осталось комнат: {len(dungeon.monster_groups) - progress.current_progress['current_room']}",
                        reply_markup=dungeon_keyboard
                    )

                session.commit()

                # Система крафтинга
                class Recipe(Base):
                    __tablename__ = 'recipes'
                    id = Column(Integer, primary_key=True)
                    name = Column(String)
                    result_item_id = Column(Integer, ForeignKey('items.id'))
                    result_quantity = Column(Integer, default=1)
                    required_level = Column(Integer, default=1)
                    energy_cost = Column(Integer)
                    materials = Column(JSON)  # {item_id: quantity}
                    crafting_time = Column(Integer)  # в секундах
                    experience = Column(Integer)
                    category = Column(String)

                @dp.message_handler(lambda message: message.text == "🛠️ Крафтинг", state=GameStates.main_menu)
                async def show_crafting(message: types.Message):
                    session = Session()
                    player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                    # Получаем доступные рецепты
                    available_recipes = session.query(Recipe).filter(
                        Recipe.required_level <= player.level
                    ).all()

                    if not available_recipes:
                        await message.answer(
                            "🛠️ У вас пока нет доступных рецептов.\n"
                            "Повысьте уровень, чтобы открыть новые рецепты!"
                        )
                        return

                    # Группируем рецепты по категориям
                    recipes_by_category = {}
                    for recipe in available_recipes:
                        if recipe.category not in recipes_by_category:
                            recipes_by_category[recipe.category] = []
                        recipes_by_category[recipe.category].append(recipe)

                    # Создаем клавиатуру с категориями
                    keyboard = types.InlineKeyboardMarkup()
                    for category in recipes_by_category.keys():
                        keyboard.add(types.InlineKeyboardButton(
                            f"📑 {category}",
                            callback_data=f"craft_category_{category}"
                        ))

                    await message.answer(
                        "🛠️ Мастерская крафта\n\n"
                        "Выберите категорию рецептов:",
                        reply_markup=keyboard
                    )
                    await GameStates.craft.set()

                @dp.callback_query_handler(lambda c: c.data.startswith('craft_category_'), state=GameStates.craft)
                async def show_category_recipes(callback_query: types.CallbackQuery):
                    category = callback_query.data.split('_')[2]
                    session = Session()
                    player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()

                    recipes = session.query(Recipe).filter(
                        Recipe.category == category,
                        Recipe.required_level <= player.level
                    ).all()

                    keyboard = types.InlineKeyboardMarkup()
                    for recipe in recipes:
                        result_item = session.query(Item).get(recipe.result_item_id)
                        keyboard.add(types.InlineKeyboardButton(
                            f"{result_item.name} (Ур. {recipe.required_level})",
                            callback_data=f"craft_recipe_{recipe.id}"
                        ))
                    keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="craft_back"))

                    await callback_query.message.edit_text(
                        f"🛠️ Рецепты категории {category}:\n"
                        "Выберите предмет для крафта:",
                        reply_markup=keyboard
                    )

                @dp.callback_query_handler(lambda c: c.data.startswith('craft_recipe_'), state=GameStates.craft)
                async def show_recipe_details(callback_query: types.CallbackQuery):
                    recipe_id = int(callback_query.data.split('_')[2])
                    session = Session()

                    recipe = session.query(Recipe).get(recipe_id)
                    result_item = session.query(Item).get(recipe.result_item_id)

                    # Проверяем наличие материалов у игрока
                    player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                    materials_text = ""
                    can_craft = True

                    for material_id, required_qty in recipe.materials.items():
                        material_item = session.query(Item).get(material_id)
                        player_material = session.query(Inventory).filter_by(
                            player_id=player.id,
                            item_id=material_id
                        ).first()

                        has_qty = player_material.quantity if player_material else 0
                        materials_text += f"\n{'✅' if has_qty >= required_qty else '❌'} {material_item.name}: {has_qty}/{required_qty}"

                        if has_qty < required_qty:
                            can_craft = False

                    keyboard = types.InlineKeyboardMarkup()
                    if can_craft and player.energy >= recipe.energy_cost:
                        keyboard.add(types.InlineKeyboardButton(
                            "🛠️ Создать",
                            callback_data=f"craft_create_{recipe_id}"
                        ))
                    keyboard.add(
                        types.InlineKeyboardButton("⬅️ Назад", callback_data=f"craft_category_{recipe.category}"))

                    await callback_query.message.edit_text(
                        f"📑 Рецепт: {result_item.name}\n"
                        f"Описание: {result_item.description}\n\n"
                        f"Требования:\n"
                        f"- Уровень крафта: {recipe.required_level}\n"
                        f"- Энергия: {recipe.energy_cost}\n"
                        f"- Время создания: {recipe.crafting_time} сек.\n\n"
                        f"Необходимые материалы:{materials_text}\n\n"
                        f"Результат: {result_item.name} x{recipe.result_quantity}",
                        reply_markup=keyboard
                    )

                @dp.callback_query_handler(lambda c: c.data.startswith('craft_create_'), state=GameStates.craft)
                async def create_item(callback_query: types.CallbackQuery):
                    recipe_id = int(callback_query.data.split('_')[2])
                    session = Session()

                    recipe = session.query(Recipe).get(recipe_id)
                    player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()

                    # Проверяем наличие материалов и энергии
                    if player.energy < recipe.energy_cost:
                        await callback_query.message.edit_text(
                            "⚠️ Недостаточно энергии для крафта!"
                        )
                        return

                    # Проверяем и расходуем материалы
                    for material_id, required_qty in recipe.materials.items():
                        inventory_item = session.query(Inventory).filter_by(
                            player_id=player.id,
                            item_id=material_id
                        ).first()

                        if not inventory_item or inventory_item.quantity < required_qty:
                            await callback_query.message.edit_text(
                                "⚠️ Недостаточно материалов для крафта!"
                            )
                            return

                        inventory_item.quantity -= required_qty
                        if inventory_item.quantity == 0:
                            session.delete(inventory_item)

                    # Создаем предмет
                    result_item = session.query(Item).get(recipe.result_item_id)
                    existing_item = session.query(Inventory).filter_by(
                        player_id=player.id,
                        item_id=recipe.result_item_id
                    ).first()

                    if existing_item:
                        existing_item.quantity += recipe.result_quantity
                    else:
                        new_item = Inventory(
                            player_id=player.id,
                            item_id=recipe.result_item_id,
                            quantity=recipe.result_quantity
                        )
                        session.add(new_item)

                    # Расходуем энергию и начисляем опыт
                    player.energy -= recipe.energy_cost
                    player.crafting_experience += recipe.experience

                    # Проверяем повышение уровня крафта
                    old_level = player.crafting_level
                    while player.crafting_experience >= get_next_crafting_level_exp(player.crafting_level):
                        player.crafting_level += 1

                    level_up_text = f"\n🎊 Уровень крафта повышен до {player.crafting_level}!" if player.crafting_level > old_level else ""

                    session.commit()

                    await callback_query.message.edit_text(
                        f"🎉 Успешно создано: {result_item.name} x{recipe.result_quantity}\n"
                        f"Потрачено энергии: {recipe.energy_cost}\n"
                        f"Получено опыта крафта: {recipe.experience}{level_up_text}"
                    )

                # Система достижений
                @dp.message_handler(lambda message: message.text == "🏆 Достижения", state=GameStates.main_menu)
                async def show_achievements(message: types.Message):
                    session = Session()
                    player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                    # Получаем все достижения и прогресс игрока
                    achievements = session.query(Achievement).all()
                    player_achievements = {
                        pa.achievement_id: pa
                        for pa in session.query(PlayerAchievement).filter_by(player_id=player.id).all()
                    }

                    # Группируем достижения по типам
                    achievements_by_type = {}
                    for achievement in achievements:
                        if achievement.achievement_type not in achievements_by_type:
                            achievements_by_type[achievement.achievement_type] = []
                        achievements_by_type[achievement.achievement_type].append(achievement)

                    response_text = f"🏆 Достижения игрока {player.name}\n"
                    response_text += f"Очки достижений: {player.achievement_points}\n\n"

                    for achievement_type, type_achievements in achievements_by_type.items():
                        response_text += f"📑 {achievement_type}:\n"
                        for achievement in type_achievements:
                            player_achievement = player_achievements.get(achievement.id)
                            if player_achievement and player_achievement.completed:
                                status = "✅"
                            else:
                                status = "❌"

                            progress = ""
                            if player_achievement and achievement.requirements:
                                for req_type, req_value in achievement.requirements.items():
                                    current_value = player_achievement.progress.get(req_type, 0)
                                    progress = f" ({current_value}/{req_value})"

                            response_text += f"{status} {achievement.name}{progress}\n"
                            if player_achievement and player_achievement.completed:
                                response_text += f"    🎁 Награда: {achievement.reward_batons} батонов"
                                if achievement.reward_title:
                                    response_text += f", титул '{achievement.reward_title}'"
                                if achievement.reward_items:
                                    items = []
                                    for item_id, quantity in achievement.reward_items.items():
                                        item = session.query(Item).get(item_id)
                                        if item:
                                            items.append(f"{item.name} x{quantity}")
                                    if items:
                                        response_text += f", предметы: {', '.join(items)}"
                                response_text += "\n"
                            response_text += "\n"

                        # Разбиваем длинное сообщение на части, если нужно
                    if len(response_text) > 4096:
                        parts = [response_text[i:i + 4096] for i in range(0, len(response_text), 4096)]
                        for part in parts:
                            await message.answer(part)
                    else:
                        await message.answer(response_text)

                    async def check_achievements(player: Player, session, event_data: dict):
                        """Проверка и обновление достижений игрока"""
                        achievements = session.query(Achievement).all()

                        for achievement in achievements:
                            player_achievement = session.query(PlayerAchievement).filter_by(
                                player_id=player.id,
                                achievement_id=achievement.id
                            ).first()

                            if not player_achievement:
                                player_achievement = PlayerAchievement(
                                    player_id=player.id,
                                    achievement_id=achievement.id,
                                    progress={}
                                )
                                session.add(player_achievement)

                            if not player_achievement.completed:
                                # Обновляем прогресс достижения
                                updated = False
                                for req_type, req_value in achievement.requirements.items():
                                    if req_type in event_data:
                                        current_value = player_achievement.progress.get(req_type, 0)
                                        if req_type == event_data.get('type'):
                                            player_achievement.progress[req_type] = current_value + event_data.get(
                                                'value', 1)
                                        updated = True

                                # Проверяем выполнение достижения
                                if updated:
                                    completed = True
                                    for req_type, req_value in achievement.requirements.items():
                                        current_value = player_achievement.progress.get(req_type, 0)
                                        if current_value < req_value:
                                            completed = False
                                            break

                                    if completed:
                                        player_achievement.completed = True
                                        player_achievement.completed_at = datetime.utcnow()

                                        # Выдаем награды
                                        player.batons += achievement.reward_batons
                                        player.achievement_points += achievement.points

                                        if achievement.reward_items:
                                            for item_id, quantity in achievement.reward_items.items():
                                                existing_item = session.query(Inventory).filter_by(
                                                    player_id=player.id,
                                                    item_id=item_id
                                                ).first()

                                                if existing_item:
                                                    existing_item.quantity += quantity
                                                else:
                                                    new_item = Inventory(
                                                        player_id=player.id,
                                                        item_id=item_id,
                                                        quantity=quantity
                                                    )
                                                    session.add(new_item)

                                        # Отправляем уведомление игроку
                                        await bot.send_message(
                                            player.user_id,
                                            f"🎊 Достижение разблокировано: {achievement.name}!\n"
                                            f"Награды:\n"
                                            f"🥖 {achievement.reward_batons} батонов\n"
                                            f"🏆 {achievement.points} очков достижений"
                                            + (
                                                f"\n👑 Титул: {achievement.reward_title}" if achievement.reward_title else "")
                                        )

                    # Система ежедневных заданий
                    class DailyQuest(Base):
                        __tablename__ = 'daily_quests'
                        id = Column(Integer, primary_key=True)
                        name = Column(String)
                        description = Column(String)
                        requirements = Column(JSON)  # {type: value}
                        reward_batons = Column(Integer)
                        reward_experience = Column(Integer)
                        reward_items = Column(JSON, nullable=True)  # {item_id: quantity}
                        energy_cost = Column(Integer)

                    class PlayerDailyQuest(Base):
                        __tablename__ = 'player_daily_quests'
                        id = Column(Integer, primary_key=True)
                        player_id = Column(Integer, ForeignKey('players.id'))
                        quest_id = Column(Integer, ForeignKey('daily_quests.id'))
                        progress = Column(JSON)
                        completed = Column(Boolean, default=False)
                        date = Column(DateTime, default=datetime.utcnow)

                    @dp.message_handler(lambda message: message.text == "📅 Ежедневные задания",
                                        state=GameStates.main_menu)
                    async def show_daily_quests(message: types.Message):
                        session = Session()
                        player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                        # Получаем текущие задания игрока
                        today = datetime.utcnow().date()
                        player_quests = session.query(PlayerDailyQuest).filter(
                            PlayerDailyQuest.player_id == player.id,
                            func.date(PlayerDailyQuest.date) == today
                        ).all()

                        if not player_quests:
                            # Генерируем новые задания
                            available_quests = session.query(DailyQuest).all()
                            daily_quests = random.sample(available_quests, min(3, len(available_quests)))

                            for quest in daily_quests:
                                new_quest = PlayerDailyQuest(
                                    player_id=player.id,
                                    quest_id=quest.id,
                                    progress={req_type: 0 for req_type in quest.requirements.keys()}
                                )
                                session.add(new_quest)

                            session.commit()
                            player_quests = daily_quests

                        response_text = "📅 Ежедневные задания:\n\n"

                        for player_quest in player_quests:
                            quest = session.query(DailyQuest).get(player_quest.quest_id)
                            status = "✅" if player_quest.completed else "❌"

                            response_text += f"{status} {quest.name}\n"
                            response_text += f"📝 {quest.description}\n"

                            # Показываем прогресс
                            for req_type, req_value in quest.requirements.items():
                                current_value = player_quest.progress.get(req_type, 0)
                                response_text += f"- {req_type}: {current_value}/{req_value}\n"

                            response_text += f"Награды:\n"
                            response_text += f"🥖 {quest.reward_batons} батонов\n"
                            response_text += f"✨ {quest.reward_experience} опыта\n"

                            if quest.reward_items:
                                response_text += "📦 Предметы:\n"
                                for item_id, quantity in quest.reward_items.items():
                                    item = session.query(Item).get(item_id)
                                    if item:
                                        response_text += f"- {item.name} x{quantity}\n"

                            response_text += f"⚡ Требуется энергии: {quest.energy_cost}\n\n"

                        keyboard = types.InlineKeyboardMarkup()
                        for player_quest in player_quests:
                            if not player_quest.completed:
                                quest = session.query(DailyQuest).get(player_quest.quest_id)
                                keyboard.add(types.InlineKeyboardButton(
                                    f"Выполнить: {quest.name}",
                                    callback_data=f"daily_quest_{player_quest.id}"
                                ))

                        await message.answer(response_text, reply_markup=keyboard)

                        @dp.callback_query_handler(lambda c: c.data.startswith('daily_quest_'),
                                                   state=GameStates.main_menu)
                        async def process_daily_quest(callback_query: types.CallbackQuery):
                            quest_id = int(callback_query.data.split('_')[2])
                            session = Session()
                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            player_quest = session.query(PlayerDailyQuest).get(quest_id)
                            quest = session.query(DailyQuest).get(player_quest.quest_id)

                            if player.energy < quest.energy_cost:
                                await callback_query.answer("⚠️ Недостаточно энергии для выполнения задания!")
                                return

                            # Списываем энергию
                            player.energy -= quest.energy_cost

                            # Генерируем результат выполнения
                            success_chance = 0.7  # 70% шанс успеха
                            success = random.random() < success_chance

                            if success:
                                # Обновляем прогресс задания
                                for req_type, req_value in quest.requirements.items():
                                    current_value = player_quest.progress.get(req_type, 0)
                                    progress_increment = random.randint(1, min(5, req_value - current_value))
                                    player_quest.progress[req_type] = min(req_value, current_value + progress_increment)

                                # Проверяем завершение задания
                                completed = all(
                                    player_quest.progress.get(req_type, 0) >= req_value
                                    for req_type, req_value in quest.requirements.items()
                                )

                                if completed:
                                    player_quest.completed = True

                                    # Выдаем награды
                                    player.batons += quest.reward_batons
                                    level_up = player.add_experience(quest.reward_experience)

                                    # Выдаем предметы
                                    received_items = []
                                    if quest.reward_items:
                                        for item_id, quantity in quest.reward_items.items():
                                            item = session.query(Item).get(item_id)
                                            if item:
                                                existing_item = session.query(Inventory).filter_by(
                                                    player_id=player.id,
                                                    item_id=item_id
                                                ).first()

                                                if existing_item:
                                                    existing_item.quantity += quantity
                                                else:
                                                    new_item = Inventory(
                                                        player_id=player.id,
                                                        item_id=item_id,
                                                        quantity=quantity
                                                    )
                                                    session.add(new_item)
                                                received_items.append(f"{item.name} x{quantity}")

                                    # Формируем текст награды
                                    reward_text = (
                                        f"🎉 Задание \"{quest.name}\" выполнено!\n\n"
                                        f"Получено:\n"
                                        f"🥖 {quest.reward_batons} батонов\n"
                                        f"✨ {quest.reward_experience} опыта"
                                    )

                                    if received_items:
                                        reward_text += f"\n📦 Предметы:\n" + "\n".join(
                                            f"- {item}" for item in received_items)

                                    if level_up:
                                        reward_text += f"\n\n🎊 Поздравляем! Вы достигли {player.level} уровня!"

                                    await callback_query.message.edit_text(reward_text)
                                else:
                                    # Показываем обновленный прогресс
                                    progress_text = f"📈 Прогресс задания \"{quest.name}\":\n\n"
                                    for req_type, req_value in quest.requirements.items():
                                        current = player_quest.progress.get(req_type, 0)
                                        progress_text += f"- {req_type}: {current}/{req_value}\n"

                                    await callback_query.message.edit_text(
                                        f"{progress_text}\n⚡ Потрачено энергии: {quest.energy_cost}"
                                    )
                            else:
                                await callback_query.message.edit_text(
                                    f"❌ Неудача при выполнении задания \"{quest.name}\"!\n"
                                    f"⚡ Потрачено энергии: {quest.energy_cost}"
                                )

                            session.commit()

                        # Система PvP
                        @dp.message_handler(lambda message: message.text == "⚔️ PvP Арена", state=GameStates.main_menu)
                        async def show_pvp_arena(message: types.Message):
                            session = Session()
                            player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                            # Проверяем уровень игрока
                            if player.level < 5:
                                await message.answer(
                                    "⚠️ PvP арена доступна с 5 уровня!\n"
                                    f"Ваш текущий уровень: {player.level}"
                                )
                                return

                            # Получаем список возможных противников
                            opponents = session.query(Player).filter(
                                Player.id != player.id,
                                Player.level.between(player.level - 2, player.level + 2)
                            ).order_by(func.random()).limit(5).all()

                            if not opponents:
                                await message.answer("😔 Подходящих противников не найдено. Попробуйте позже!")
                                return

                            response_text = (
                                "⚔️ PvP Арена\n\n"
                                f"Ваш рейтинг: {player.pvp_rating}\n"
                                f"Победы: {player.wins} | Поражения: {player.losses}\n\n"
                                "Доступные противники:\n"
                            )

                            keyboard = types.InlineKeyboardMarkup()
                            for opponent in opponents:
                                response_text += (
                                    f"👤 {opponent.name}\n"
                                    f"Уровень: {opponent.level} | Рейтинг: {opponent.pvp_rating}\n"
                                    f"Победы: {opponent.wins} | Поражения: {opponent.losses}\n\n"
                                )
                                keyboard.add(types.InlineKeyboardButton(
                                    f"⚔️ Атаковать {opponent.name}",
                                    callback_data=f"pvp_attack_{opponent.id}"
                                ))

                            await message.answer(response_text, reply_markup=keyboard)
                            await GameStates.pvp.set()

                        @dp.callback_query_handler(lambda c: c.data.startswith('pvp_attack_'), state=GameStates.pvp)
                        async def process_pvp_attack(callback_query: types.CallbackQuery, state: FSMContext):
                            opponent_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            opponent = session.query(Player).get(opponent_id)

                            if player.energy < 20:
                                await callback_query.answer("⚠️ Недостаточно энергии для PvP битвы!")
                                return

                            # Списываем энергию
                            player.energy -= 20

                            # Получаем статы обоих игроков
                            player_stats = player.get_total_stats(session)
                            opponent_stats = opponent.get_total_stats(session)

                            battle_log = []
                            player_hp = player_stats['health']
                            opponent_hp = opponent_stats['health']
                            rounds = 0

                            while player_hp > 0 and opponent_hp > 0 and rounds < 20:
                                # Ход игрока
                                player_damage = max(1, player_stats['damage'] - opponent_stats['defense'] // 2)
                                crit_chance = random.random() < (player_stats['critical_chance'] / 100)
                                if crit_chance:
                                    player_damage *= 2
                                    battle_log.append(
                                        f"💥 Критический удар! {player.name} наносит {player_damage} урона!")
                                else:
                                    battle_log.append(f"⚔️ {player.name} наносит {player_damage} урона!")

                                dodge_chance = random.random() < (opponent_stats['dodge_chance'] / 100)
                                if dodge_chance:
                                    battle_log.append(f"🌟 {opponent.name} уклоняется от атаки!")
                                else:
                                    opponent_hp -= player_damage

                                # Ход противника
                                if opponent_hp > 0:
                                    opponent_damage = max(1, opponent_stats['damage'] - player_stats['defense'] // 2)
                                    crit_chance = random.random() < (opponent_stats['critical_chance'] / 100)
                                    if crit_chance:
                                        opponent_damage *= 2
                                        battle_log.append(
                                            f"💥 Критический удар! {opponent.name} наносит {opponent_damage} урона!")
                                    else:
                                        battle_log.append(f"⚔️ {opponent.name} наносит {opponent_damage} урона!")

                                    dodge_chance = random.random() < (player_stats['dodge_chance'] / 100)
                                    if dodge_chance:
                                        battle_log.append(f"🌟 {player.name} уклоняется от атаки!")
                                    else:
                                        player_hp -= opponent_damage

                                rounds += 1

                            victory = player_hp > 0

                            # Обновляем статистику
                            if victory:
                                player.wins += 1
                                opponent.losses += 1

                                # Рассчитываем изменение рейтинга
                                rating_diff = calculate_rating_change(player.pvp_rating, opponent.pvp_rating, True)
                                player.pvp_rating += rating_diff
                                opponent.pvp_rating -= rating_diff

                                # Награды за победу
                                reward_batons = random.randint(50, 100)
                                reward_exp = random.randint(100, 200)

                                player.batons += reward_batons
                                level_up = player.add_experience(reward_exp)

                                result_text = (
                                    f"🎉 Победа в PvP битве!\n\n"
                                    f"{'⚔️ '.join(battle_log)}\n\n"
                                    f"Награды:\n"
                                    f"🥖 {reward_batons} батонов\n"
                                    f"✨ {reward_exp} опыта\n"
                                    f"📊 Рейтинг: +{rating_diff}"
                                )

                                if level_up:
                                    result_text += f"\n\n🎊 Поздравляем! Вы достигли {player.level} уровня!"
                            else:
                                player.losses += 1
                                opponent.wins += 1

                                rating_diff = calculate_rating_change(player.pvp_rating, opponent.pvp_rating, False)
                                player.pvp_rating -= rating_diff
                                opponent.pvp_rating += rating_diff

                                result_text = (
                                    f"❌ Поражение в PvP битве!\n\n"
                                    f"{'⚔️ '.join(battle_log)}\n\n"
                                    f"📊 Рейтинг: -{rating_diff}"
                                )

                            session.commit()
                            await callback_query.message.edit_text(result_text)
                            await GameStates.main_menu.set()

                        def calculate_rating_change(winner_rating: int, loser_rating: int, is_winner: bool) -> int:
                            """Рассчитывает изменение рейтинга по системе ELO"""
                            K = 32  # Коэффициент изменения рейтинга
                            expected = 1 / (1 + 10 ** ((loser_rating - winner_rating) / 400))
                            change = round(K * (1 - expected) if is_winner else K * (0 - expected))
                            return abs(change)

                        # Система титулов и рангов
                        class Title(Base):
                            __tablename__ = 'titles'
                            id = Column(Integer, primary_key=True)
                            name = Column(String)
                            description = Column(String)
                            requirement_type = Column(String)  # pvp_rating, achievement_points, level, etc.
                            requirement_value = Column(Integer)
                            bonus_strength = Column(Integer, default=0)
                            bonus_agility = Column(Integer, default=0)
                            bonus_intelligence = Column(Integer, default=0)
                            bonus_vitality = Column(Integer, default=0)
                            rarity = Column(String)
                            icon = Column(String, nullable=True)

                        class PvPRank(Base):
                            __tablename__ = 'pvp_ranks'
                            id = Column(Integer, primary_key=True)
                            name = Column(String)
                            min_rating = Column(Integer)
                            max_rating = Column(Integer)
                            rewards = Column(JSON)  # {daily_batons: int, weekly_batons: int, etc}
                            icon = Column(String)

                        PVP_RANKS = [
                            {'name': 'Новичок', 'min_rating': 0, 'max_rating': 1199},
                            {'name': 'Боец', 'min_rating': 1200, 'max_rating': 1499},
                            {'name': 'Ветеран', 'min_rating': 1500, 'max_rating': 1799},
                            {'name': 'Мастер', 'min_rating': 1800, 'max_rating': 2099},
                            {'name': 'Гроссмейстер', 'min_rating': 2100, 'max_rating': 2399},
                            {'name': 'Чемпион', 'min_rating': 2400, 'max_rating': 2699},
                            {'name': 'Легенда', 'min_rating': 2700, 'max_rating': 999999}
                        ]

                        # Добавляем функции для работы с титулами и рангами
                        async def check_new_titles(player: Player, session) -> List[Title]:
                            """Проверяет и выдает новые доступные титулы игроку"""
                            new_titles = []
                            all_titles = session.query(Title).all()

                            for title in all_titles:
                                # Проверяем, нет ли уже этого титула у игрока
                                has_title = session.query(PlayerTitle).filter_by(
                                    player_id=player.id,
                                    title_id=title.id
                                ).first()

                                if not has_title:
                                    # Проверяем требования для получения титула
                                    if title.requirement_type == 'pvp_rating' and player.pvp_rating >= title.requirement_value:
                                        earned = True
                                    elif title.requirement_type == 'achievement_points' and player.achievement_points >= title.requirement_value:
                                        earned = True
                                    elif title.requirement_type == 'level' and player.level >= title.requirement_value:
                                        earned = True
                                    else:
                                        earned = False

                                    if earned:
                                        new_title = PlayerTitle(
                                            player_id=player.id,
                                            title_id=title.id
                                        )
                                        session.add(new_title)
                                        new_titles.append(title)

                            if new_titles:
                                session.commit()

                            return new_titles

                        def get_player_rank(rating: int) -> dict:
                            """Получает текущий ранг игрока по рейтингу"""
                            for rank in PVP_RANKS:
                                if rank['min_rating'] <= rating <= rank['max_rating']:
                                    return rank
                            return PVP_RANKS[0]  # Возвращаем начальный ранг, если ничего не найдено

                        @dp.message_handler(lambda message: message.text == "👑 Титулы", state=GameStates.main_menu)
                        async def show_titles(message: types.Message):
                            session = Session()
                            player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                            # Получаем все титулы игрока
                            player_titles = session.query(PlayerTitle).filter_by(player_id=player.id).all()

                            # Проверяем новые доступные титулы
                            new_titles = await check_new_titles(player, session)

                            # Получаем текущий PvP ранг
                            current_rank = get_player_rank(player.pvp_rating)

                            response_text = (
                                f"👑 Титулы и ранги игрока {player.name}\n\n"
                                f"🏆 PvP ранг: {current_rank['name']}\n"
                                f"📊 Рейтинг: {player.pvp_rating}\n"
                                f"До следующего ранга: {current_rank['max_rating'] - player.pvp_rating + 1} очков\n\n"
                                "Доступные титулы:\n"
                            )

                            # Создаем клавиатуру для управления титулами
                            keyboard = types.InlineKeyboardMarkup(row_width=2)

                            for player_title in player_titles:
                                title = player_title.title
                                status = "✅" if player_title.is_active else "⭕"

                                response_text += (
                                    f"{status} {title.name}\n"
                                    f"└ {title.description}\n"
                                    f"└ Бонусы: "
                                )

                                bonuses = []
                                if title.bonus_strength: bonuses.append(f"+{title.bonus_strength} к силе")
                                if title.bonus_agility: bonuses.append(f"+{title.bonus_agility} к ловкости")
                                if title.bonus_intelligence: bonuses.append(f"+{title.bonus_intelligence} к интеллекту")
                                if title.bonus_vitality: bonuses.append(f"+{title.bonus_vitality} к живучести")

                                response_text += ", ".join(bonuses) + "\n\n"

                                # Добавляем кнопки для активации/деактивации титула
                                keyboard.add(
                                    types.InlineKeyboardButton(
                                        f"{'Снять' if player_title.is_active else 'Надеть'} {title.name}",
                                        callback_data=f"title_toggle_{player_title.id}"
                                    )
                                )

                            if new_titles:
                                response_text += "\n🎉 Получены новые титулы:\n"
                                for title in new_titles:
                                    response_text += f"- {title.name}\n"

                            await message.answer(response_text, reply_markup=keyboard)

                        @dp.callback_query_handler(lambda c: c.data.startswith('title_toggle_'),
                                                   state=GameStates.main_menu)
                        async def toggle_title(callback_query: types.CallbackQuery):
                            title_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            # Получаем титул игрока
                            player_title = session.query(PlayerTitle).get(title_id)
                            if not player_title:
                                await callback_query.answer("Ошибка: титул не найден!")
                                return

                            # Если активируем титул, деактивируем все остальные
                            if not player_title.is_active:
                                other_active_titles = session.query(PlayerTitle).filter_by(
                                    player_id=player_title.player_id,
                                    is_active=True
                                ).all()

                                for other_title in other_active_titles:
                                    other_title.is_active = False

                            # Переключаем статус титула
                            player_title.is_active = not player_title.is_active
                            session.commit()

                            # Обновляем сообщение с титулами
                            await show_titles(callback_query.message)
                            await callback_query.answer(
                                f"Титул {'активирован' if player_title.is_active else 'деактивирован'}!"
                            )

                        # Добавляем ежедневные награды за PvP ранг
                        async def give_daily_rank_rewards():
                            """Выдает ежедневные награды за PvP ранг"""
                            session = Session()
                            players = session.query(Player).all()

                            for player in players:
                                rank = get_player_rank(player.pvp_rating)
                                daily_batons = rank.get('daily_batons', 0)

                                if daily_batons > 0:
                                    player.batons += daily_batons

                                    try:
                                        await bot.send_message(
                                            player.user_id,
                                            f"📅 Ежедневная награда за PvP ранг {rank['name']}:\n"
                                            f"🥖 +{daily_batons} батонов"
                                        )
                                    except:
                                        pass  # Игнорируем ошибки отправки сообщения

                            session.commit()

                        # Запускаем задачу выдачи ежедневных наград
                        async def schedule_rank_rewards():
                            while True:
                                now = datetime.utcnow()
                                next_day = (now + timedelta(days=1)).replace(
                                    hour=0, minute=0, second=0, microsecond=0
                                )
                                await asyncio.sleep((next_day - now).total_seconds())
                                await give_daily_rank_rewards()

                        # Добавляем запуск задачи в основной код
                        def start_scheduler():
                            loop = asyncio.get_event_loop()
                            loop.create_task(schedule_rank_rewards())

                        # Система питомцев
                        class Pet(Base):
                            __tablename__ = 'pets'
                            id = Column(Integer, primary_key=True)
                            name = Column(String)
                            type = Column(String)  # dragon, wolf, cat, etc.
                            rarity = Column(String)  # common, rare, epic, legendary
                            base_damage = Column(Integer)
                            base_defense = Column(Integer)
                            base_health = Column(Integer)
                            special_ability = Column(String)
                            evolution_level = Column(Integer, default=1)
                            max_evolution_level = Column(Integer)
                            image = Column(String)

                        class PlayerPet(Base):
                            __tablename__ = 'player_pets'
                            id = Column(Integer, primary_key=True)
                            player_id = Column(Integer, ForeignKey('players.id'))
                            pet_id = Column(Integer, ForeignKey('pets.id'))
                            nickname = Column(String, nullable=True)
                            level = Column(Integer, default=1)
                            experience = Column(Integer, default=0)
                            happiness = Column(Integer, default=100)  # 0-100
                            hunger = Column(Integer, default=0)  # 0-100
                            last_fed = Column(DateTime, default=datetime.utcnow)
                            is_active = Column(Boolean, default=False)
                            bonus_stats = Column(JSON, default={})  # Дополнительные бонусы от тренировок

                            pet = relationship("Pet")
                            player = relationship("Player")

                            def get_total_stats(self) -> Dict[str, int]:
                                """Рассчитывает общие характеристики питомца с учетом уровня и бонусов"""
                                level_multiplier = 1 + (self.level - 1) * 0.1

                                return {
                                    'damage': int(
                                        self.pet.base_damage * level_multiplier + self.bonus_stats.get('damage', 0)),
                                    'defense': int(
                                        self.pet.base_defense * level_multiplier + self.bonus_stats.get('defense', 0)),
                                    'health': int(
                                        self.pet.base_health * level_multiplier + self.bonus_stats.get('health', 0))
                                }

                            def add_experience(self, amount: int) -> bool:
                                """Добавляет опыт питомцу и проверяет повышение уровня"""
                                self.experience += amount
                                level_up = False

                                while self.experience >= self.get_next_level_exp():
                                    self.level += 1
                                    level_up = True

                                return level_up

                            def get_next_level_exp(self) -> int:
                                """Рассчитывает требуемый опыт для следующего уровня"""
                                return int(100 * (self.level ** 1.5))

                            def update_status(self):
                                """Обновляет статус питомца (голод и счастье)"""
                                hours_since_fed = (datetime.utcnow() - self.last_fed).total_seconds() / 3600

                                # Увеличиваем голод со временем
                                self.hunger = min(100, self.hunger + int(hours_since_fed * 5))

                                # Уменьшаем счастье, если питомец голоден
                                if self.hunger > 50:
                                    happiness_loss = int((self.hunger - 50) * 0.5)
                                    self.happiness = max(0, self.happiness - happiness_loss)

                        @dp.message_handler(lambda message: message.text == "🐾 Питомцы", state=GameStates.main_menu)
                        async def show_pets(message: types.Message):
                            session = Session()
                            player = session.query(Player).filter_by(user_id=message.from_user.id).first()

                            # Получаем всех питомцев игрока
                            player_pets = session.query(PlayerPet).filter_by(player_id=player.id).all()

                            if not player_pets:
                                # Создаем клавиатуру для получения первого питомца
                                keyboard = types.InlineKeyboardMarkup()
                                starter_pets = session.query(Pet).filter_by(rarity='common').all()

                                for pet in starter_pets:
                                    keyboard.add(types.InlineKeyboardButton(
                                        f"Выбрать {pet.name}",
                                        callback_data=f"choose_starter_pet_{pet.id}"
                                    ))

                                await message.answer(
                                    "🐾 Добро пожаловать в питомник!\n"
                                    "У вас пока нет питомцев. Выберите своего первого питомца:",
                                    reply_markup=keyboard
                                )
                                return

                            # Показываем информацию о питомцах
                            response_text = "🐾 Ваши питомцы:\n\n"
                            keyboard = types.InlineKeyboardMarkup(row_width=2)

                            for player_pet in player_pets:
                                pet = player_pet.pet
                                player_pet.update_status()
                                stats = player_pet.get_total_stats()

                                status = "✅" if player_pet.is_active else "⭕"
                                nickname = player_pet.nickname or pet.name

                                response_text += (
                                    f"{status} {nickname} ({pet.type})\n"
                                    f"├ Уровень: {player_pet.level} ({player_pet.experience}/{player_pet.get_next_level_exp()} опыта)\n"
                                    f"├ Редкость: {pet.rarity}\n"
                                    f"├ Эволюция: {pet.evolution_level}/{pet.max_evolution_level}\n"
                                    f"├ Счастье: {'❤️' * (player_pet.happiness // 20)}{'🖤' * ((100 - player_pet.happiness) // 20)}\n"
                                    f"├ Голод: {'🍖' * (player_pet.hunger // 20)}{'⚪' * ((100 - player_pet.hunger) // 20)}\n"
                                    f"├ Урон: {stats['damage']}\n"
                                    f"├ Защита: {stats['defense']}\n"
                                    f"└ Здоровье: {stats['health']}\n\n"
                                )

                                # Добавляем кнопки управления питомцем
                                pet_buttons = [
                                    types.InlineKeyboardButton(
                                        f"{'Деактивировать' if player_pet.is_active else 'Активировать'}",
                                        callback_data=f"pet_toggle_{player_pet.id}"
                                    ),
                                    types.InlineKeyboardButton(
                                        "Покормить",
                                        callback_data=f"pet_feed_{player_pet.id}"
                                    )
                                ]
                                keyboard.add(*pet_buttons)

                                keyboard.add(types.InlineKeyboardButton(
                                    f"Тренировать {nickname}",
                                    callback_data=f"pet_train_{player_pet.id}"
                                ))

                                if pet.evolution_level < pet.max_evolution_level:
                                    keyboard.add(types.InlineKeyboardButton(
                                        f"Эволюция {nickname}",
                                        callback_data=f"pet_evolve_{player_pet.id}"
                                    ))

                            keyboard.add(types.InlineKeyboardButton(
                                "🛍️ Магазин питомцев",
                                callback_data="pet_shop"
                            ))

                            session.commit()
                            await message.answer(response_text, reply_markup=keyboard)

                        @dp.callback_query_handler(lambda c: c.data.startswith('choose_starter_pet_'))
                        async def process_starter_pet_choice(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[3])
                            session = Session()

                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            pet = session.query(Pet).get(pet_id)

                            # Создаем нового питомца для игрока
                            player_pet = PlayerPet(
                                player_id=player.id,
                                pet_id=pet_id,
                                is_active=True
                            )
                            session.add(player_pet)
                            session.commit()

                            await callback_query.message.edit_text(
                                f"🎉 Поздравляем! Вы получили питомца {pet.name}!\n"
                                "Ухаживайте за ним, кормите и тренируйте, чтобы сделать его сильнее."
                            )

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_toggle_'))
                        async def toggle_pet(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            player_pet = session.query(PlayerPet).get(pet_id)
                            if not player_pet:
                                await callback_query.answer("Ошибка: питомец не найден!")
                                return

                            # Деактивируем всех остальных питомцев
                            if not player_pet.is_active:
                                other_active_pets = session.query(PlayerPet).filter_by(
                                    player_id=player_pet.player_id,
                                    is_active=True
                                ).all()

                                for other_pet in other_active_pets:
                                    other_pet.is_active = False

                            player_pet.is_active = not player_pet.is_active
                            session.commit()

                            await show_pets(callback_query.message)
                            await callback_query.answer(
                                f"Питомец {'активирован' if player_pet.is_active else 'деактивирован'}!"
                            )

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_feed_'))
                        async def feed_pet(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            player_pet = session.query(PlayerPet).get(pet_id)

                            if player.batons < 10:
                                await callback_query.answer("Недостаточно батонов для кормления питомца!")
                                return

                            player.batons -= 10
                            player_pet.hunger = max(0, player_pet.hunger - 50)
                            player_pet.happiness = min(100, player_pet.happiness + 20)
                            player_pet.last_fed = datetime.utcnow()

                            session.commit()

                            await show_pets(callback_query.message)
                            await callback_query.answer("Питомец накормлен!")

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_train_'))
                        async def show_training_options(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            player_pet = session.query(PlayerPet).get(pet_id)

                            if not player_pet:
                                await callback_query.answer("Ошибка: питомец не найден!")
                                return

                            # Создаем клавиатуру с вариантами тренировки
                            keyboard = types.InlineKeyboardMarkup(row_width=1)
                            training_options = [
                                ("Тренировка атаки (20 🥖)", "damage", 20),
                                ("Тренировка защиты (20 🥖)", "defense", 20),
                                ("Тренировка здоровья (20 🥖)", "health", 20)
                            ]

                            for name, stat, cost in training_options:
                                keyboard.add(types.InlineKeyboardButton(
                                    name,
                                    callback_data=f"pet_train_stat_{pet_id}_{stat}_{cost}"
                                ))

                            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_back"))

                            stats = player_pet.get_total_stats()
                            bonus_stats = player_pet.bonus_stats

                            await callback_query.message.edit_text(
                                f"🎯 Тренировка питомца {player_pet.nickname or player_pet.pet.name}\n\n"
                                f"Текущие характеристики:\n"
                                f"⚔️ Урон: {stats['damage']} (+{bonus_stats.get('damage', 0)} от тренировок)\n"
                                f"🛡️ Защита: {stats['defense']} (+{bonus_stats.get('defense', 0)} от тренировок)\n"
                                f"❤️ Здоровье: {stats['health']} (+{bonus_stats.get('health', 0)} от тренировок)\n\n"
                                f"У вас есть: {player.batons} 🥖",
                                reply_markup=keyboard
                            )

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_train_stat_'))
                        async def train_pet_stat(callback_query: types.CallbackQuery):
                            _, _, _, pet_id, stat, cost = callback_query.data.split('_')
                            pet_id, cost = int(pet_id), int(cost)

                            session = Session()
                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            player_pet = session.query(PlayerPet).get(pet_id)

                            if player.batons < cost:
                                await callback_query.answer("Недостаточно батонов для тренировки!")
                                return

                            # Списываем батоны
                            player.batons -= cost

                            # Обновляем бонусные статы питомца
                            if not player_pet.bonus_stats:
                                player_pet.bonus_stats = {}

                            current_bonus = player_pet.bonus_stats.get(stat, 0)
                            gain = random.randint(1, 3)  # Случайное увеличение стата

                            if player_pet.happiness < 50:  # Уменьшаем прирост при низком счастье
                                gain = max(1, gain // 2)

                            player_pet.bonus_stats[stat] = current_bonus + gain

                            # Добавляем опыт питомцу
                            level_up = player_pet.add_experience(random.randint(10, 20))

                            session.commit()

                            result_text = f"Тренировка успешна! +{gain} к {stat}"
                            if level_up:
                                result_text += f"\n🎉 Питомец достиг {player_pet.level} уровня!"

                            await callback_query.answer(result_text)
                            await show_training_options(callback_query)

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_evolve_'))
                        async def show_evolution_confirm(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[2])
                            session = Session()

                            player_pet = session.query(PlayerPet).get(pet_id)
                            pet = player_pet.pet

                            if pet.evolution_level >= pet.max_evolution_level:
                                await callback_query.answer("Питомец уже достиг максимальной эволюции!")
                                return

                            # Требования для эволюции
                            required_level = pet.evolution_level * 10
                            required_batons = pet.evolution_level * 100

                            keyboard = types.InlineKeyboardMarkup()
                            keyboard.add(
                                types.InlineKeyboardButton(
                                    "✨ Эволюционировать",
                                    callback_data=f"pet_evolution_confirm_{pet_id}"
                                )
                            )
                            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_back"))

                            await callback_query.message.edit_text(
                                f"✨ Эволюция питомца {player_pet.nickname or pet.name}\n\n"
                                f"Текущая эволюция: {pet.evolution_level}/{pet.max_evolution_level}\n\n"
                                f"Требования для эволюции:\n"
                                f"- Уровень питомца: {player_pet.level}/{required_level}\n"
                                f"- Батоны: {required_batons} 🥖\n\n"
                                f"После эволюции характеристики питомца значительно улучшатся!",
                                reply_markup=keyboard
                            )

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_evolution_confirm_'))
                        async def evolve_pet(callback_query: types.CallbackQuery):
                            pet_id = int(callback_query.data.split('_')[3])
                            session = Session()

                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            player_pet = session.query(PlayerPet).get(pet_id)
                            pet = player_pet.pet

                            required_level = pet.evolution_level * 10
                            required_batons = pet.evolution_level * 100

                            if player_pet.level < required_level:
                                await callback_query.answer("Недостаточный уровень питомца!")
                                return

                            if player.batons < required_batons:
                                await callback_query.answer("Недостаточно батонов!")
                                return

                            # Проводим эволюцию
                            player.batons -= required_batons
                            pet.evolution_level += 1

                            # Увеличиваем базовые характеристики
                            evolution_multiplier = 1.5
                            pet.base_damage = int(pet.base_damage * evolution_multiplier)
                            pet.base_defense = int(pet.base_defense * evolution_multiplier)
                            pet.base_health = int(pet.base_health * evolution_multiplier)

                            session.commit()

                            await callback_query.message.edit_text(
                                f"🎉 Поздравляем! Питомец {player_pet.nickname or pet.name} эволюционировал!\n"
                                f"Новая эволюция: {pet.evolution_level}/{pet.max_evolution_level}\n\n"
                                f"Характеристики улучшены в {evolution_multiplier}x раз!"
                            )

                        @dp.callback_query_handler(lambda c: c.data == "pet_shop")
                        async def show_pet_shop(callback_query: types.CallbackQuery):
                            session = Session()
                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()

                            # Получаем доступных питомцев для покупки
                            available_pets = session.query(Pet).filter(
                                Pet.evolution_level == 1,  # Только базовые питомцы
                                Pet.id.notin_([pp.pet_id for pp in player.pets])  # Исключаем уже имеющихся
                            ).all()

                            if not available_pets:
                                await callback_query.message.edit_text(
                                    "🏪 Магазин питомцев пуст!\n"
                                    "Приходите позже, когда появятся новые питомцы."
                                )
                                return

                            response_text = (
                                "🏪 Магазин питомцев\n"
                                f"У вас есть: {player.batons} 🥖\n\n"
                                "Доступные питомцы:\n"
                            )

                            keyboard = types.InlineKeyboardMarkup(row_width=1)

                            for pet in available_pets:
                                price = {
                                    'common': 100,
                                    'rare': 300,
                                    'epic': 1000,
                                    'legendary': 5000
                                }.get(pet.rarity, 100)

                                response_text += (
                                    f"\n{pet.name} ({pet.type})\n"
                                    f"├ Редкость: {pet.rarity}\n"
                                    f"├ Урон: {pet.base_damage}\n"
                                    f"├ Защита: {pet.base_defense}\n"
                                    f"├ Здоровье: {pet.base_health}\n"
                                    f"└ Цена: {price} 🥖\n"
                                )

                                keyboard.add(types.InlineKeyboardButton(
                                    f"Купить {pet.name} за {price} 🥖",
                                    callback_data=f"pet_buy_{pet.id}_{price}"
                                ))

                            keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_back"))

                            await callback_query.message.edit_text(
                                response_text,
                                reply_markup=keyboard
                            )

                        @dp.callback_query_handler(lambda c: c.data.startswith('pet_buy_'))
                        async def buy_pet(callback_query: types.CallbackQuery):
                            _, _, pet_id, price = callback_query.data.split('_')
                            pet_id, price = int(pet_id), int(price)

                            session = Session()
                            player = session.query(Player).filter_by(user_id=callback_query.from_user.id).first()
                            pet = session.query(Pet).get(pet_id)

                            if player.batons < price:
                                await callback_query.answer("Недостаточно батонов для покупки питомца!")
                                return

                            # Проверяем, нет ли уже такого питомца у игрока
                            existing_pet = session.query(PlayerPet).filter_by(
                                player_id=player.id,
                                pet_id=pet_id
                            ).first()

                            if existing_pet:
                                await callback_query.answer("У вас уже есть такой питомец!")
                                return

                            # Покупаем питомца
                            player.batons -= price
                            new_pet = PlayerPet(
                                player_id=player.id,
                                pet_id=pet_id,
                                is_active=False  # Новый питомец не активен по умолчанию
                            )
                            session.add(new_pet)
                            session.commit()

                            await callback_query.message.edit_text(
                                f"🎉 Поздравляем с покупкой питомца {pet.name}!\n"
                                f"Потрачено: {price} 🥖"
                            )

                            # Специальные способности питомцев
                            class PetAbility(Base):
                                __tablename__ = 'pet_abilities'
                                id = Column(Integer, primary_key=True)
                                name = Column(String)
                                description = Column(String)
                                type = Column(String)  # combat, support, passive
                                effect = Column(JSON)  # {type: value} например {"heal": 20, "damage": 30}
                                cooldown = Column(Integer)  # в раундах для боя
                                energy_cost = Column(Integer)
                                required_evolution = Column(Integer, default=1)

                            # Добавляем связь способностей с питомцами
                            Pet.abilities = relationship("PetAbility", secondary="pet_ability_links")

                            class PetAbilityLink(Base):
                                __tablename__ = 'pet_ability_links'
                                pet_id = Column(Integer, ForeignKey('pets.id'), primary_key=True)
                                ability_id = Column(Integer, ForeignKey('pet_abilities.id'), primary_key=True)

                            @dp.callback_query_handler(lambda c: c.data.startswith('pet_abilities_'))
                            async def show_pet_abilities(callback_query: types.CallbackQuery):
                                pet_id = int(callback_query.data.split('_')[2])
                                session = Session()

                                player_pet = session.query(PlayerPet).get(pet_id)
                                pet = player_pet.pet

                                response_text = f"✨ Способности питомца {player_pet.nickname or pet.name}:\n\n"

                                for ability in pet.abilities:
                                    if ability.required_evolution <= pet.evolution_level:
                                        response_text += (
                                            f"🔮 {ability.name}\n"
                                            f"├ Тип: {ability.type}\n"
                                            f"├ {ability.description}\n"
                                            f"├ Перезарядка: {ability.cooldown} ходов\n"
                                            f"└ Энергия: {ability.energy_cost}\n\n"
                                        )

                                keyboard = types.InlineKeyboardMarkup()
                                keyboard.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_back"))

                                await callback_query.message.edit_text(
                                    response_text,
                                    reply_markup=keyboard
                                )

                            # Система питомцев-компаньонов для подземелий
                            class DungeonPetEffect:
                                def __init__(self, player_pet: PlayerPet):
                                    self.player_pet = player_pet
                                    self.ability_cooldowns = {}

                                def apply_passive_effects(self, player_stats: dict) -> dict:
                                    """Применяет пассивные эффекты питомца к статам игрока"""
                                    pet_stats = self.player_pet.get_total_stats()

                                    # Базовое увеличение характеристик
                                    player_stats['damage'] += int(pet_stats['damage'] * 0.2)
                                    player_stats['defense'] += int(pet_stats['defense'] * 0.2)
                                    player_stats['health'] += int(pet_stats['health'] * 0.2)

                                    # Применяем пассивные способности
                                    for ability in self.player_pet.pet.abilities:
                                        if ability.type == 'passive' and ability.required_evolution <= self.player_pet.pet.evolution_level:
                                            for stat, value in ability.effect.items():
                                                if stat in player_stats:
                                                    player_stats[stat] += value

                                    return player_stats

                                def use_combat_ability(self, battle_state: dict) -> tuple[str, dict]:
                                    """Использует боевую способность питомца"""
                                    available_abilities = [
                                        ability for ability in self.player_pet.pet.abilities
                                        if ability.type == 'combat'
                                           and ability.required_evolution <= self.player_pet.pet.evolution_level
                                           and self.ability_cooldowns.get(ability.id, 0) <= 0
                                    ]

                                    if not available_abilities:
                                        return "", battle_state

                                    # Выбираем случайную доступную способность
                                    ability = random.choice(available_abilities)
                                    self.ability_cooldowns[ability.id] = ability.cooldown

                                    effect_text = f"🔮 Питомец {self.player_pet.nickname or self.player_pet.pet.name} использует {ability.name}!\n"

                                    # Применяем эффекты способности
                                    if 'damage' in ability.effect:
                                        damage = ability.effect['damage']
                                        battle_state['monster_hp'] -= damage
                                        effect_text += f"⚔️ Нанесено {damage} урона!\n"

                                    if 'heal' in ability.effect:
                                        heal = ability.effect['heal']
                                        battle_state['player_hp'] = min(
                                            battle_state['player_hp'] + heal,
                                            battle_state['player_max_hp']
                                        )
                                        effect_text += f"💚 Восстановлено {heal} здоровья!\n"

                                    return effect_text, battle_state

                                def update_cooldowns(self):
                                    """Обновляет перезарядку способностей"""
                                    for ability_id in list(self.ability_cooldowns.keys()):
                                        self.ability_cooldowns[ability_id] = max(0,
                                                                                 self.ability_cooldowns[ability_id] - 1)

                            # Обновляем логику боя в подземелье с учетом питомцев
                            async def dungeon_battle(player: Player, monster: Monster, session) -> Dict:
                                # Получаем активного питомца игрока
                                player_pet = session.query(PlayerPet).filter_by(
                                    player_id=player.id,
                                    is_active=True
                                ).first()

                                pet_effect = DungeonPetEffect(player_pet) if player_pet else None

                                # Получаем базовые статы игрока
                                player_stats = player.get_total_stats(session)

                                # Применяем эффекты питомца
                                if pet_effect:
                                    player_stats = pet_effect.apply_passive_effects(player_stats)

                                battle_state = {
                                    'player_hp': player_stats['health'],
                                    'player_max_hp': player_stats['health'],
                                    'monster_hp': monster.health,
                                    'monster_max_hp': monster.health
                                }

                                battle_log = []
                                rounds = 0

                                while battle_state['player_hp'] > 0 and battle_state['monster_hp'] > 0 and rounds < 20:
                                    # Ход игрока
                                    player_damage = max(1, player_stats['damage'] - monster.defense // 2)
                                    crit_chance = random.random() < (player_stats['critical_chance'] / 100)

                                    if crit_chance:
                                        player_damage *= 2
                                        battle_log.append(
                                            f"💥 Критический удар! {player.name} наносит {player_damage} урона!")
                                    else:
                                        battle_log.append(f"⚔️ {player.name} наносит {player_damage} урона!")

                                    battle_state['monster_hp'] -= player_damage

                                    # Ход питомца
                                    if pet_effect and battle_state['monster_hp'] > 0:
                                        pet_action, battle_state = pet_effect.use_combat_ability(battle_state)
                                        if pet_action:
                                            battle_log.append(pet_action)

                                    # Ход монстра
                                    if battle_state['monster_hp'] > 0:
                                        monster_damage = max(1, monster.damage - player_stats['defense'] // 2)
                                        dodge_chance = random.random() < (player_stats['dodge_chance'] / 100)

                                        if dodge_chance:
                                            battle_log.append(f"🌟 {player.name} уклоняется от атаки!")
                                        else:
                                            battle_state['player_hp'] -= monster_damage
                                            battle_log.append(f"🗡️ {monster.name} наносит {monster_damage} урона!")

                                    # Обновляем кулдауны способностей питомца
                                    if pet_effect:
                                        pet_effect.update_cooldowns()

                                    rounds += 1

                                victory = battle_state['player_hp'] > 0

                                return {
                                    'victory': victory,
                                    'remaining_hp': battle_state['player_hp'],
                                    'battle_log': battle_log,
                                    'rounds': rounds
                                }

                                # Обработка завершения битвы в подземелье
                                async def process_dungeon_rewards(player: Player, dungeon: Dungeon, session) -> Dict:
                                    """Обрабатывает награды за прохождение подземелья"""
                                    rewards = {
                                        'experience': random.randint(100, 200) * dungeon.min_level,
                                        'batons': random.randint(50, 100) * dungeon.min_level,
                                        'items': [],
                                        'level_up': False
                                    }

                                    # Добавляем опыт и проверяем повышение уровня
                                    level_before = player.level
                                    level_up = player.add_experience(rewards['experience'])
                                    rewards['level_up'] = level_up

                                    # Добавляем батоны
                                    player.batons += rewards['batons']

                                    # Выдаем награды питомцу, если есть активный
                                    active_pet = session.query(PlayerPet).filter_by(
                                        player_id=player.id,
                                        is_active=True
                                    ).first()

                                    if active_pet:
                                        pet_exp = int(rewards['experience'] * 0.5)  # 50% от опыта игрока
                                        active_pet.add_experience(pet_exp)
                                        active_pet.happiness = min(100, active_pet.happiness + 10)

                                    # Генерируем предметы из добычи подземелья
                                    if dungeon.possible_loot:
                                        for item_id, chance in dungeon.possible_loot.items():
                                            if random.random() < chance:
                                                item = session.query(Item).get(item_id)
                                                if item:
                                                    quantity = random.randint(1, 3)
                                                    existing_item = session.query(Inventory).filter_by(
                                                        player_id=player.id,
                                                        item_id=item_id
                                                    ).first()

                                                    if existing_item:
                                                        existing_item.quantity += quantity
                                                    else:
                                                        new_item = Inventory(
                                                            player_id=player.id,
                                                            item_id=item_id,
                                                            quantity=quantity
                                                        )
                                                        session.add(new_item)

                                                    rewards['items'].append(f"{item.name} x{quantity}")

                                    # Сохраняем изменения
                                    session.commit()
                                    return rewards

                                # Обновляем статистику подземелья
                                async def update_dungeon_stats(player: Player, dungeon: Dungeon, completion_time: float,
                                                               session):
                                    """Обновляет статистику прохождения подземелья"""
                                    stats = session.query(DungeonStats).filter_by(
                                        player_id=player.id,
                                        dungeon_id=dungeon.id
                                    ).first()

                                    if not stats:
                                        stats = DungeonStats(
                                            player_id=player.id,
                                            dungeon_id=dungeon.id,
                                            times_completed=0,
                                            fastest_time=None,
                                            total_time=0
                                        )
                                        session.add(stats)

                                    stats.times_completed += 1
                                    stats.total_time += completion_time

                                    if stats.fastest_time is None or completion_time < stats.fastest_time:
                                        stats.fastest_time = completion_time

                                        # Проверяем рекорд подземелья
                                        current_record = session.query(DungeonRecord).filter_by(
                                            dungeon_id=dungeon.id
                                        ).first()

                                        if not current_record or completion_time < current_record.completion_time:
                                            new_record = DungeonRecord(
                                                dungeon_id=dungeon.id,
                                                player_id=player.id,
                                                completion_time=completion_time,
                                                achieved_at=datetime.utcnow()
                                            )
                                            session.add(new_record)

                                            # Уведомляем игрока о новом рекорде
                                            await bot.send_message(
                                                player.user_id,
                                                f"🏆 Поздравляем! Вы установили новый рекорд прохождения подземелья {dungeon.name}!\n"
                                                f"Время: {completion_time:.2f} секунд"
                                            )

                                    session.commit()

                                # Главный обработчик завершения подземелья
                                async def complete_dungeon(callback_query: types.CallbackQuery, player: Player,
                                                           dungeon: Dungeon,
                                                           progress: DungeonProgress, session):
                                    """Обрабатывает завершение подземелья"""
                                    completion_time = datetime.utcnow().timestamp() - progress.current_progress[
                                        'start_time']

                                    # Проверяем время прохождения
                                    if completion_time > dungeon.completion_time * 60:
                                        await callback_query.message.edit_text(
                                            "⏰ Время вышло! Вы не успели пройти подземелье.\n"
                                            "Попробуйте снова после восстановления подземелья."
                                        )
                                        await GameStates.main_menu.set()
                                        return

                                    # Обрабатываем награды
                                    rewards = await process_dungeon_rewards(player, dungeon, session)

                                    # Обновляем статистику
                                    await update_dungeon_stats(player, dungeon, completion_time, session)

                                    # Формируем текст награды
                                    reward_text = (
                                        f"🎉 Подземелье {dungeon.name} пройдено!\n\n"
                                        f"⏱️ Время прохождения: {completion_time:.2f} секунд\n"
                                        f"👿 Побеждено монстров: {progress.current_progress['monsters_defeated']}\n\n"
                                        f"Награды:\n"
                                        f"✨ Опыт: {rewards['experience']}\n"
                                        f"🥖 Батоны: {rewards['batons']}\n"
                                    )

                                    if rewards['items']:
                                        reward_text += f"\n📦 Добыча:\n" + "\n".join(
                                            [f"- {item}" for item in rewards['items']])

                                    if rewards['level_up']:
                                        reward_text += f"\n\n🎊 Поздравляем! Вы достигли {player.level} уровня!"

                                    # Проверяем достижения
                                    await check_achievements(player, session, {
                                        'dungeon_completed': dungeon.id,
                                        'monsters_killed': progress.current_progress['monsters_defeated'],
                                        'dungeon_time': completion_time
                                    })

                                    # Сбрасываем прогресс подземелья
                                    progress.current_progress = None
                                    session.commit()

                                    # Отправляем сообщение о завершении
                                    await callback_query.message.edit_text(reward_text)
                                    await GameStates.main_menu.set()

                                    # Если у вас есть какие-либо дополнительные функции или обработчики, добавьте их здесь

                                    # Регистрация обработчиков
                                    def register_handlers(dp: Dispatcher):
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_toggle_'))(
                                            toggle_pet)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_feed_'))(feed_pet)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_train_'))(
                                            show_training_options)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_train_stat_'))(
                                            train_pet_stat)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_evolve_'))(
                                            show_evolution_confirm)
                                        dp.callback_query_handler(
                                            lambda c: c.data.startswith('pet_evolution_confirm_'))(evolve_pet)
                                        dp.callback_query_handler(lambda c: c.data == "pet_shop")(show_pet_shop)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_buy_'))(buy_pet)
                                        dp.callback_query_handler(lambda c: c.data.startswith('pet_abilities_'))(
                                            show_pet_abilities)
                                        dp.callback_query_handler(lambda c: c.data.startswith('choose_starter_pet_'))(
                                            process_starter_pet_choice)

                                        # Добавьте обработчики для других функций
                                        # Например, для завершения подземелий, проверок достижений и так далее

                                    if __name__ == "__main__":
                                        from aiogram import executor
                                        from app.handlers import register_handlers

                                        # Настройка базы данных и логирования
                                        engine = create_engine(DATABASE_URL, echo=True)
                                        Session = sessionmaker(bind=engine)
                                        Base.metadata.create_all(engine)

                                        # Инициализация бота
                                        bot = Bot(token=API_TOKEN)
                                        storage = MemoryStorage()
                                        dp = Dispatcher(bot, storage=storage)

                                        # Регистрация обработчиков
                                        register_handlers(dp)

                                        # Запуск бота
                                        executor.start_polling(dp, on_startup=on_startup)
