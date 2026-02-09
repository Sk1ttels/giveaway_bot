# app/bot/handlers.py
from __future__ import annotations

from datetime import datetime
import re
from typing import Dict, Optional, Tuple

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import SessionLocal
from ..models import Giveaway, Participant, Referral, PromoCode, PromoUse
from .config import ADMIN_IDS
from .keyboards import (
    role_choice_kb, admin_root_kb, user_root_kb,
    giveaway_kb, admin_giveaway_kb, confirm_delete_kb
)

router = Router()

# ------------------------
# Runtime per-user mode (in memory)
# ------------------------
USER_MODE: Dict[int, str] = {}  # "admin" | "user"

def is_admin(user_id: int) -> bool:
    return user_id in set(ADMIN_IDS or [])

def mode_of(user_id: int) -> str:
    return USER_MODE.get(user_id, "user")

# ------------------------
# Helpers
# ------------------------
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def valid_code(code: str) -> bool:
    return bool(_CODE_RE.match(code))

_BOT_USERNAME_CACHE: Optional[str] = None

async def bot_username(message_or_cb) -> str:
    global _BOT_USERNAME_CACHE
    if _BOT_USERNAME_CACHE:
        return _BOT_USERNAME_CACHE
    me = await message_or_cb.bot.get_me()
    _BOT_USERNAME_CACHE = me.username or ""
    return _BOT_USERNAME_CACHE

def now_local() -> datetime:
    # naive local time is fine for a single-server bot; store naive in DB.
    return datetime.now()

def deactivate_if_expired(db, g: Giveaway) -> bool:
    """Return True if expired and deactivated."""
    if g.is_active and g.ends_at and g.ends_at <= now_local():
        g.is_active = False
        db.commit()
        return True
    return False

async def ensure_subscribed(bot, user_id: int, chat_username: str) -> bool:
    """Check membership for channel/group. Returns True if subscribed/participant."""
    try:
        m = await bot.get_chat_member(chat_username, user_id)
        # statuses: creator/administrator/member/restricted/left/kicked
        return m.status in ("creator", "administrator", "member", "restricted")
    except Exception:
        # If bot has no access OR chat invalid, treat as not subscribed
        return False

def parse_ref_payload(payload: str) -> Optional[Tuple[int, int]]:
    # payload like: ref_<gid>_<inviterId>
    if not payload.startswith("ref_"):
        return None
    try:
        _, gid, inviter = payload.split("_", 2)
        return int(gid), int(inviter)
    except Exception:
        return None

# ------------------------
# FSM\

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def join_link_kb(channel_username: str, gid: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{channel_username.lstrip('@')}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Перейти в канал/групу", url=url)],
        [InlineKeyboardButton(text="✅ Я підписався (продовжити)", callback_data=f"join_ok:{gid}")]
    ])


async def check_subscription_soft(bot, user_id: int, channel_username: str):
    """
    Returns:
      True  - підписаний (перевірено)
      False - НЕ підписаний (перевірено)
      None  - неможливо перевірити (бот не має доступу/403/інше)
    """
    if not channel_username or channel_username.strip() == "-":
        return True  # перевірка не потрібна

    try:
        m = await bot.get_chat_member(channel_username, user_id)
        status = getattr(m, "status", None)
        # member/administrator/creator — ок; left/kicked — ні
        return status in ("member", "administrator", "creator")
    except Exception:
        # Нема прав / канал закритий / бот не адмін — не блокуємо, просто "умовна підписка"
        return None


# ------------------------
class CreateGiveaway(StatesGroup):
    title = State()
    description = State()
    ends_at = State()
    winners = State()
    channel = State()
    promo = State()  # optional: immediately create promo after giveaway

class CreatePromo(StatesGroup):
    value = State()  # code or code:max

class RedeemPromo(StatesGroup):
    value = State()  # user enters code

# ------------------------
# /start and mode switch
# ------------------------
@router.message(Command("start"))
async def start(message: Message):
    # default: user mode
    USER_MODE[message.from_user.id] = "user"

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    # ✅ якщо це рефералка — НЕ показуємо вибір режиму
    if payload.startswith("ref_"):
        # ref формат: ref_<giveaway_id>_<referrer_id>
        try:
            _, gid_str, referrer_str = payload.split("_", 2)
            gid = int(gid_str)
            referrer_id = int(referrer_str)
        except Exception:
            await message.answer("⚠️ Некоректне реферальне посилання.", reply_markup=user_root_kb())
            return

        # якщо користувач сам собі реферер — просто ігноруємо
        if referrer_id == message.from_user.id:
            await message.answer("🔗 Це ваше реферальне посилання. Запрошення себе не рахується ✅",
                                 reply_markup=user_root_kb())
            return

        # тут виклич свою функцію/логіку збереження реферала (якщо в тебе є)
        # await register_referral(gid, referrer_id, message.from_user.id)

        await message.answer("✅ Ви зайшли по реферальному посиланню!", reply_markup=user_root_kb())
        return

    # звичайний /start — показує вибір режиму
    await message.answer("Оберіть режим:", reply_markup=role_choice_kb())

@router.message(F.text == "🛠 Адмін")
async def switch_admin(message: Message):
    if not is_admin(message.from_user.id):
        USER_MODE[message.from_user.id] = "user"
        await message.answer("⛔ Вибачте, ви не адміністратор.", reply_markup=user_root_kb())
        return
    USER_MODE[message.from_user.id] = "admin"
    await message.answer("🛠 Адмін меню:", reply_markup=admin_root_kb())

@router.message(F.text == "👤 Користувач")
async def switch_user(message: Message):
    USER_MODE[message.from_user.id] = "user"
    await message.answer("👤 Меню користувача:", reply_markup=user_root_kb())

# ------------------------
# SHOW ACTIVE GIVEAWAYS
# ------------------------
@router.message(F.text == "🎁 Активні розіграші")
async def show_active_giveaways(message: Message):
    mode = mode_of(message.from_user.id)
    with SessionLocal() as db:
        giveaways = (
            db.execute(select(Giveaway).order_by(Giveaway.id.desc()))
            .scalars()
            .all()
        )

        # filter to active + not expired (and auto-deactivate if expired)
        active = []
        for g in giveaways:
            if deactivate_if_expired(db, g):
                continue
            if g.is_active:
                active.append(g)

    if not active:
        await message.answer("Немає активних розіграшів.")
        return

    for g in active:
        # participation status
        with SessionLocal() as db:
            p = (
                db.execute(
                    select(Participant).where(
                        Participant.giveaway_id == g.id,
                        Participant.user_id == message.from_user.id
                    )
                )
                .scalars()
                .first()
            )
        joined = bool(p)

        ends = g.ends_at.strftime("%Y-%m-%d %H:%M") if g.ends_at else "—"

        text = (
            f"🎁 <b>{g.title}</b>\n\n"
            f"{g.description or ''}\n\n"
            f"🏆 Переможців: <b>{g.winners_count}</b>\n"
            f"⏳ Дедлайн: <b>{ends}</b>\n"
        )
        if g.channel_username:
            text += f"📣 Канал/група: {g.channel_username}\n"
        text += f"Участь: {'✅' if joined else '❌'}"

        if mode == "admin" and is_admin(message.from_user.id):
            await message.answer(text, reply_markup=admin_giveaway_kb(g.id), parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=giveaway_kb(g.id), parse_mode="HTML")

# ------------------------
# ADMIN: CREATE GIVEAWAY
# ------------------------
@router.message(F.text == "➕ Створити новий розіграш")
async def admin_create_giveaway(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ тільки для адміна.", reply_markup=user_root_kb())
        return
    await state.clear()
    await state.set_state(CreateGiveaway.title)
    await message.answer("Введіть назву розіграшу:")

@router.message(CreateGiveaway.title)
async def create_giveaway_title(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("❌ Назва не може бути пустою. Введіть назву:")
        return
    await state.update_data(title=title)
    await state.set_state(CreateGiveaway.description)
    await message.answer("Введіть опис розіграшу (або '-' якщо без опису):")

@router.message(CreateGiveaway.description)
async def create_giveaway_description(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return
    desc = (message.text or "").strip()
    if desc == "-":
        desc = ""
    await state.update_data(description=desc)
    await state.set_state(CreateGiveaway.ends_at)
    await message.answer("Введіть дедлайн у форматі: 2026-02-07 18:30 (Київ)")

@router.message(CreateGiveaway.ends_at)
async def create_giveaway_deadline(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        dt = datetime.strptime(txt, "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ Невірний формат. Приклад: 2026-02-07 18:30")
        return
    await state.update_data(ends_at=dt)
    await state.set_state(CreateGiveaway.winners)
    await message.answer("Скільки переможців? (число, напр: 1)")

@router.message(CreateGiveaway.winners)
async def create_giveaway_winners(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return
    txt = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❌ Введіть число > 0. Скільки переможців?")
        return
    await state.update_data(winners_count=int(txt))
    await state.set_state(CreateGiveaway.channel)
    await message.answer("Вкажіть @канал або @групу для перевірки підписки (або '-' якщо не потрібно):")

# --- helpers for channel/group input ---
def normalize_chat_input(text: str) -> Optional[str]:
    """Accepts @name or t.me/name links. Returns @name or None."""
    t = (text or "").strip()

    # allow skip with '-'
    if t == "-":
        return ""

    # extract first t.me/... or telegram.me/...
    m = re.search(r"(https?://)?(t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})", t)
    if m:
        return "@" + m.group(3)

    # plain @username
    if t.startswith("@"):
        u = t[1:]
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", u):
            return "@" + u
        return None

    return None


@router.message(CreateGiveaway.channel)
async def create_giveaway_channel(message: Message, state: FSMContext):
    # admin-only
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return

    ch = normalize_chat_input(message.text or "")
    if ch is None:
        await message.answer(
            "❌ Вкажіть публічний канал або групу для перевірки підписки.\n\n"
            "Приклади:\n"
            "@my_chanel\n"
            "https://t.me/my_chanel"
        )

        return

    # If not skipped, validate that it's NOT a private account/bot, only channel/group
    if ch != "":
        try:
            chat = await message.bot.get_chat(ch)
        except Exception:
            await message.answer(
                "⚠️ Не можу знайти цей канал або групу.\n\n"
                "Переконайтесь, що:\n"
                "• канал або група ПУБЛІЧНІ\n"
                "• це не акаунт користувача\n"
                "• бот має доступ\n\n"
                "Приклади:\n"
                "@after_kyiv\n"
                "https://t.me/after_kyiv"
            )

            return

        if chat.type == "private":
            await message.answer(
                "❌ Це username користувача або бота.\n\n"
                "На акаунти не можна підписатися.\n"
                "Вкажіть лише ПУБЛІЧНИЙ канал або групу.\n\n"
                "Приклади:\n"
                "@after_kyiv\n"
                "https://t.me/after_kyiv"
            )

            return

        if chat.type not in ("channel", "group", "supergroup"):
            await message.answer("❌ Потрібен саме @канал або @група.")
            return

    # Create giveaway in DB
    data = await state.get_data()

    g = Giveaway(
        title=data.get("title", "").strip() or "Без назви",
        description=data.get("description", "").strip(),
        ends_at=data.get("ends_at"),
        winners_count=int(data.get("winners_count", 1)),
        channel_username=(ch or None),
        is_active=True,
    )

    with SessionLocal() as db:
        db.add(g)
        db.commit()
        gid = g.id

    await state.update_data(giveaway_id=gid)
    await state.set_state(CreateGiveaway.promo)

    await message.answer(
        f"✅ Розіграш створено! ID: {gid}\n\n"
        "Тепер (опційно) створимо промокод для магазину.\n"
        "Введіть одним повідомленням:\n"
        "• 3432 (MAX=1)\n"
        "• BUY100\n"
        "• BUY100:10\n"
        "або '-' щоб пропустити."
    )

@router.message(CreateGiveaway.promo)
async def create_giveaway_promo(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return

    txt = (message.text or "").strip()
    if txt == "-":
        await state.clear()
        await message.answer("✅ Готово.", reply_markup=admin_root_kb())
        return

    if ":" in txt:
        code, max_uses = txt.split(":", 1)
        code = code.strip()
        max_uses = max_uses.strip()
        if not max_uses.isdigit() or int(max_uses) <= 0:
            await message.answer("❌ MAX має бути числом (напр: BUY100:10)")
            return
        mu = int(max_uses)
    else:
        code = txt.strip()
        mu = 1

    if not valid_code(code):
        await message.answer("❌ Код 1-64 символи: букви/цифри/_- (напр: 123 або BUY100)")
        return

    gid = int((await state.get_data())["giveaway_id"])

    with SessionLocal() as db:
        pc = PromoCode(giveaway_id=gid, code=code, max_uses=mu, uses=0, is_active=True)
        db.add(pc)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            await message.answer("❌ Такий промокод вже існує для цього розіграшу.")
            return

    await state.clear()
    await message.answer(f"✅ Промокод створено: {code} (MAX={mu})", reply_markup=admin_root_kb())

# ------------------------
# ADMIN: LIST & CREATE PROMO FROM CARD
# ------------------------
@router.callback_query(F.data.startswith("adm_code:"))
async def admin_create_code_from_card(cb: CallbackQuery, state: FSMContext):
    if mode_of(cb.from_user.id) != "admin" or not is_admin(cb.from_user.id):
        await cb.answer("⛔ Доступ заборонено", show_alert=True)
        return
    gid = int(cb.data.split(":")[1])
    await state.clear()
    await state.set_state(CreatePromo.value)
    await state.update_data(giveaway_id=gid)
    await cb.message.answer("Введіть промокод: 3432 або BUY100:10")
    await cb.answer()

@router.message(CreatePromo.value)
async def admin_create_code_value(message: Message, state: FSMContext):
    if mode_of(message.from_user.id) != "admin" or not is_admin(message.from_user.id):
        await state.clear()
        return

    txt = (message.text or "").strip()
    if ":" in txt:
        code, max_uses = txt.split(":", 1)
        code = code.strip()
        max_uses = max_uses.strip()
        if not max_uses.isdigit() or int(max_uses) <= 0:
            await message.answer("❌ MAX має бути числом (напр: BUY100:10)")
            return
        mu = int(max_uses)
    else:
        code = txt.strip()
        mu = 1

    if not valid_code(code):
        await message.answer("❌ Код 1-64 символи: букви/цифри/_- (напр: 123 або BUY100)")
        return

    gid = int((await state.get_data())["giveaway_id"])

    with SessionLocal() as db:
        pc = PromoCode(giveaway_id=gid, code=code, max_uses=mu, uses=0, is_active=True)
        db.add(pc)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            await message.answer("❌ Такий промокод вже існує для цього розіграшу.")
            return

    await state.clear()
    await message.answer(f"✅ Промокод створено: {code} (MAX={mu})", reply_markup=admin_root_kb())

@router.callback_query(F.data.startswith("adm_codes:"))
async def admin_list_codes(cb: CallbackQuery):
    if mode_of(cb.from_user.id) != "admin" or not is_admin(cb.from_user.id):
        await cb.answer("⛔ Доступ заборонено", show_alert=True)
        return

    gid = int(cb.data.split(":")[1])
    with SessionLocal() as db:
        codes = (
            db.execute(select(PromoCode).where(PromoCode.giveaway_id == gid).order_by(PromoCode.id.desc()))
            .scalars()
            .all()
        )

    if not codes:
        await cb.message.answer("📄 Промокодів ще немає.")
        await cb.answer()
        return

    lines = ["📄 <b>Промокоди цього розіграшу:</b>\n"]
    for c in codes[:50]:
        ok = c.is_active and c.uses < c.max_uses
        status = "✅" if ok else "❌"
        lines.append(f"{status} <code>{c.code}</code> — {c.uses}/{c.max_uses}")

    await cb.message.answer("\n".join(lines), parse_mode="HTML")
    await cb.answer()

# ------------------------
# ADMIN: DELETE GIVEAWAY
# ------------------------
@router.callback_query(F.data.startswith("del:"))
async def admin_delete_ask(cb: CallbackQuery):
    if mode_of(cb.from_user.id) != "admin" or not is_admin(cb.from_user.id):
        await cb.answer("⛔ Доступ заборонено", show_alert=True)
        return
    gid = int(cb.data.split(":")[1])
    await cb.message.answer("⚠️ Ви впевнені, що хочете видалити розіграш?", reply_markup=confirm_delete_kb(gid))
    await cb.answer()

@router.callback_query(F.data.startswith("del_ok:"))
async def admin_delete_ok(cb: CallbackQuery):
    if mode_of(cb.from_user.id) != "admin" or not is_admin(cb.from_user.id):
        await cb.answer("⛔ Доступ заборонено", show_alert=True)
        return
    gid = int(cb.data.split(":")[1])
    with SessionLocal() as db:
        g = db.get(Giveaway, gid)
        if g:
            g.is_active = False
            db.commit()
    await cb.message.answer("🗑 Розіграш видалено (деактивовано).")
    await cb.answer()

@router.callback_query(F.data == "del_cancel")
async def admin_delete_cancel(cb: CallbackQuery):
    await cb.answer("Скасовано")

# ------------------------
# USER: JOIN / REF / REDEEM
# ------------------------

async def register_participation(cb: CallbackQuery, gid: int):
    with SessionLocal() as db:
        g = db.get(Giveaway, gid)
        if not g:
            await cb.answer("Розіграш не знайдено", show_alert=True)
            return
        if deactivate_if_expired(db, g) or not g.is_active:
            await cb.answer("⛔ Розіграш завершено.", show_alert=True)
            return

    with SessionLocal() as db:
        p = Participant(
            giveaway_id=gid,
            user_id=cb.from_user.id,
            username=cb.from_user.username or "",
            first_name=cb.from_user.first_name or "",
            tickets=1,
            invited_count=0
        )
        db.add(p)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            await cb.answer("✅ Ви вже берете участь.", show_alert=False)
            return

        # реф-бонус (як у тебе було)
        r = (
            db.execute(select(Referral).where(
                Referral.giveaway_id == gid,
                Referral.invited_id == cb.from_user.id
            ))
            .scalars()
            .first()
        )
        if r and r.inviter_id != cb.from_user.id:
            inviter = (
                db.execute(select(Participant).where(
                    Participant.giveaway_id == gid,
                    Participant.user_id == r.inviter_id
                ))
                .scalars()
                .first()
            )
            if inviter:
                inviter.invited_count += 1
                if inviter.invited_count % 5 == 0:
                    inviter.tickets += 1
                    try:
                        await cb.bot.send_message(
                            inviter.user_id,
                            "🎉 +1 шанс! 5 друзів приєднались по вашому посиланню."
                        )
                    except Exception:
                        pass
                db.commit()

    await cb.answer("✅ Ви берете участь!", show_alert=False)


@router.callback_query(F.data.startswith("join:"))
async def user_join(cb: CallbackQuery):
    gid = int(cb.data.split(":")[1])

    with SessionLocal() as db:
        g = db.get(Giveaway, gid)
        if not g:
            await cb.answer("Розіграш не знайдено", show_alert=True)
            return
        if deactivate_if_expired(db, g) or not g.is_active:
            await cb.answer("⛔ Розіграш завершено.", show_alert=True)
            return

    # ФІКТИВНА "ПІДПИСКА": просто показуємо посилання + кнопку "я підписався"
    if g.channel_username:
        await cb.message.answer(
            "📣 Спочатку перейдіть у канал/групу за посиланням, потім натисніть ✅ Я підписався.",
            reply_markup=join_link_kb(g.channel_username, gid)
        )
        await cb.answer()
        return

    # якщо канал не задано — одразу реєструємо
    await register_participation(cb, gid)


@router.callback_query(F.data.startswith("ref:"))
async def user_ref(cb: CallbackQuery):
    gid = int(cb.data.split(":")[1])

    with SessionLocal() as db:
        g = db.get(Giveaway, gid)
        if not g or not g.is_active:
            await cb.answer("Розіграш неактивний", show_alert=True)
            return
        if deactivate_if_expired(db, g) or not g.is_active:
            await cb.answer("⛔ Розіграш завершено.", show_alert=True)
            return

    username = await bot_username(cb)
    link = f"https://t.me/{username}?start=ref_{gid}_{cb.from_user.id}"
    await cb.message.answer(
        f"🔗 Ваше реферальне посилання:\n{link}\n\n"
        f"+1 шанс за кожні 5 друзів, які натиснуть ✅ Участвую."
    )
    await cb.answer()

@router.callback_query(F.data.startswith("join_ok:"))
async def user_join_ok(cb: CallbackQuery):
    gid = int(cb.data.split(":")[1])
    await register_participation(cb, gid)


@router.callback_query(F.data.startswith("code:"))
async def user_code(cb: CallbackQuery, state: FSMContext):
    gid = int(cb.data.split(":")[1])
    await state.clear()
    await state.set_state(RedeemPromo.value)
    await state.update_data(giveaway_id=gid)
    await cb.message.answer("Введіть промокод одним повідомленням (напр: 3432 або BUY100).")
    await cb.answer()

@router.message(RedeemPromo.value)
async def user_redeem_code(message: Message, state: FSMContext):
    gid = int((await state.get_data())["giveaway_id"])
    txt = (message.text or "").strip()
    if not txt:
        await message.answer("❌ Введіть промокод.")
        return

    # take first token (support accidental "CODE XXX")
    parts = txt.split()
    code = parts[-1] if len(parts) >= 2 and parts[0].lower() == "code" else parts[0]

    if ":" in code:
        # user shouldn't pass max_uses; ignore part after :
        code = code.split(":", 1)[0].strip()

    if not valid_code(code):
        await message.answer("❌ Невірний формат коду.")
        return

    with SessionLocal() as db:
        g = db.get(Giveaway, gid)
        if not g or not g.is_active:
            await state.clear()
            await message.answer("⛔ Розіграш неактивний.")
            return
        if deactivate_if_expired(db, g) or not g.is_active:
            await state.clear()
            await message.answer("⛔ Дедлайн минув. Розіграш завершено.")
            return

        p = (
            db.execute(select(Participant).where(Participant.giveaway_id == gid, Participant.user_id == message.from_user.id))
            .scalars()
            .first()
        )
        if not p:
            await message.answer("Спочатку натисни ✅ Участвую у розіграші.")
            return

        pc = (
            db.execute(select(PromoCode).where(PromoCode.giveaway_id == gid, PromoCode.code == code))
            .scalars()
            .first()
        )
        if not pc or not pc.is_active or pc.uses >= pc.max_uses:
            await state.clear()
            await message.answer("❌ Промокод недійсний.")
            return

        use = PromoUse(giveaway_id=gid, user_id=message.from_user.id, code=code)
        db.add(use)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            await state.clear()
            await message.answer("⚠️ Ви вже використовували цей промокод.")
            return

        pc.uses += 1
        p.tickets += 1
        db.commit()

    await state.clear()
    await message.answer("✅ Промокод прийнято! +1 шанс.")
