from datetime import datetime
import math

def calculate_exp_for_level(level: int) -> int:
    """Рассчитывает опыт для следующего уровня"""
    return int(100 * (level ** 1.5))

def format_time(seconds: int) -> str:
    """Форматирует время"""
    minutes = seconds // 60
    hours = minutes // 60
    return f"{hours}ч {minutes % 60}м {seconds % 60}с"

def get_current_time() -> datetime:
    """Возвращает текущее игровое время"""
    from config import CURRENT_DATE
    return CURRENT_DATE

def calculate_damage(base_damage: int, level: int, buffs: dict = None) -> int:
    """Рассчитывает урон с учетом уровня и баффов"""
    damage = base_damage * (1 + level * 0.1)
    if buffs:
        damage *= (1 + buffs.get('damage_multiplier', 0))
    return int(damage)

def calculate_health(base_health: int, vitality: int) -> int:
    """Рассчитывает здоровье персонажа"""
    return base_health + (vitality * 10)