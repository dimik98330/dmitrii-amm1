from aiogram.dispatcher.filters.state import State, StatesGroup


class GameStates(StatesGroup):
    # Основные состояния
    main_menu = State()
    dungeon = State()
    craft = State()
    shop = State()
    pvp = State()

    # Состояния инвентаря
    inventory = State()
    inventory_use = State()

    # Состояния питомцев
    pets = State()
    pet_training = State()
    pet_evolution = State()

    # Состояния магазина
    shop_main = State()
    shop_buy = State()
    shop_sell = State()