# app/bot/keyboards.py
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

def role_choice_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🛠 Адмін"), KeyboardButton(text="👤 Користувач")]],
        resize_keyboard=True
    )

def admin_root_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Активні розіграші")],
            [KeyboardButton(text="➕ Створити новий розіграш")],
        ],
        resize_keyboard=True
    )

def user_root_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Активні розіграші")],
        ],
        resize_keyboard=True
    )

def giveaway_kb(gid: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Участвую", callback_data=f"join:{gid}")],
            [InlineKeyboardButton(text="🔗 Реферальне посилання", callback_data=f"ref:{gid}")],
            [InlineKeyboardButton(text="🎟 Ввести промокод", callback_data=f"code:{gid}")],
        ]
    )

def admin_giveaway_kb(gid: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Створити промокод", callback_data=f"adm_code:{gid}")],
            [InlineKeyboardButton(text="📄 Промокоди", callback_data=f"adm_codes:{gid}")],
            [InlineKeyboardButton(text="🗑 Видалити розіграш", callback_data=f"del:{gid}")],
        ]
    )

def confirm_delete_kb(gid: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"del_ok:{gid}"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="del_cancel"),
            ]
        ]
    )
