#!/usr/bin/env python3
"""
╔══════════════════════════════════════════╗
║        CLAU TOP UP — TELEGRAM BOT        ║
║     Single-file, fully self-contained    ║
╚══════════════════════════════════════════╝
REQUIREMENTS:
    pip install python-telegram-bot==20.7 aiosqlite

RUN:
    python bot.py
"""

import asyncio
import logging
import sqlite3
import aiosqlite
import os
import re
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
from telegram.constants import ParseMode

# ─── CONFIG ───────────────────────────────────────────────────────────────────

BOT_TOKEN       = "8858485129:AAEgOt00AVaHWllN43yHt_nx9zXCRKn-dgQ"
ADMIN_IDS       = [5048950348]
DB_PATH         = "topup.db"
ORDER_EXPIRY    = 30   # minutes
SUPPORT         = "@yohanesog"
STORE_NAME      = "⚡ Clau Top Up"
WELCOME_TAGLINE = (
    "🇪🇹 Ethiopia's fastest & most trusted digital top-up store!\n"
    "Stars • Premium • TikTok • Free Fire • PUBG"
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ─── CONVERSATION STATES ──────────────────────────────────────────────────────

(
    # Order flow
    ST_GAME_ID, ST_CONFIRM_ID, ST_PAY_METHOD, ST_PROOF,
    # Admin: add product
    AP_CAT, AP_LABEL, AP_AMOUNT, AP_PRICE, AP_CONFIRM,
    # Admin: edit product
    EP_FIELD, EP_VALUE,
    # Admin: payment settings
    PS_FIELD, PS_VALUE,
    # Admin: broadcast
    BC_MSG, BC_TARGET, BC_CONFIRM,
    # Admin: settings
    SET_FIELD, SET_VALUE,
    # Admin: search
    SEARCH_INPUT,
) = range(20)

# ─── DATABASE ─────────────────────────────────────────────────────────────────

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            is_banned   INTEGER DEFAULT 0,
            joined_at   TEXT DEFAULT (datetime('now')),
            total_orders INTEGER DEFAULT 0,
            total_spent  REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS products (
            product_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT NOT NULL,
            label       TEXT NOT NULL,
            amount      REAL NOT NULL,
            price_etb   REAL NOT NULL,
            is_active   INTEGER DEFAULT 1,
            sort_order  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id        TEXT PRIMARY KEY,
            user_id         INTEGER,
            product_id      INTEGER,
            product_label   TEXT,
            game_id         TEXT,
            payment_method  TEXT,
            amount_due      REAL,
            payment_proof   TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now')),
            confirmed_at    TEXT,
            delivered_at    TEXT,
            admin_note      TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(product_id) REFERENCES products(product_id)
        );

        CREATE TABLE IF NOT EXISTS payment_methods (
            method_id       TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            account         TEXT NOT NULL,
            account_name    TEXT NOT NULL,
            instructions    TEXT,
            is_active       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS bot_settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        CREATE TABLE IF NOT EXISTS used_proofs (
            proof TEXT PRIMARY KEY,
            order_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        await db.commit()

        # ── Seed products ──────────────────────────────────────────────
        count = await db.execute("SELECT COUNT(*) FROM products")
        row = await count.fetchone()
        if row[0] == 0:
            products = [
                # (category, label, amount, price_etb, sort_order)
                # Telegram Stars
                ("stars", "⭐ 50 Stars",    50,   190,   1),
                ("stars", "⭐ 100 Stars",   100,  370,   2),
                ("stars", "⭐ 250 Stars",   250,  875,   3),
                ("stars", "⭐ 350 Stars",   350,  1225,  4),
                ("stars", "⭐ 500 Stars",   500,  1700,  5),
                ("stars", "⭐ 750 Stars",   750,  2550,  6),
                ("stars", "⭐ 1000 Stars",  1000, 3300,  7),
                ("stars", "⭐ 1500 Stars",  1500, 4800,  8),
                ("stars", "⭐ 2500 Stars",  2500, 8000,  9),
                # Telegram Premium
                ("premium", "🌟 Premium 1 Month",   1,  700,  1),
                ("premium", "🌟 Premium 3 Months",  3,  2500, 2),
                ("premium", "🌟 Premium 6 Months",  6,  3500, 3),
                ("premium", "🌟 Premium 12 Months", 12, 5900, 4),
                # TikTok Coins
                ("tiktok", "🪙 30 TikTok Coins",    30,   100,   1),
                ("tiktok", "🪙 50 TikTok Coins",    50,   150,   2),
                ("tiktok", "🪙 100 TikTok Coins",   100,  280,   3),
                ("tiktok", "🪙 200 TikTok Coins",   200,  550,   4),
                ("tiktok", "🪙 300 TikTok Coins",   300,  750,   5),
                ("tiktok", "🪙 500 TikTok Coins",   500,  1200,  6),
                ("tiktok", "🪙 1000 TikTok Coins",  1000, 2400,  7),
                ("tiktok", "🪙 2000 TikTok Coins",  2000, 4800,  8),
                ("tiktok", "🪙 3000 TikTok Coins",  3000, 6900,  9),
                ("tiktok", "🪙 5000 TikTok Coins",  5000, 11500, 10),
                ("tiktok", "🪙 7000 TikTok Coins",  7000, 15750, 11),
                ("tiktok", "🪙 10000 TikTok Coins", 10000,22000, 12),
                # Free Fire
                ("freefire", "💎 100+10 Diamonds",  110,  200,  1),
                ("freefire", "💎 210+21 Diamonds",  231,  400,  2),
                ("freefire", "💎 320+21 Diamonds",  341,  600,  3),
                ("freefire", "💎 530+53 Diamonds",  583,  1000, 4),
                ("freefire", "🧧 Weekly Pass (450💎)", 450, 450, 5),
                ("freefire", "🧧 Monthly Pass (2600💎)", 2600, 2200, 6),
                ("freefire", "🧧 Level Up Pass",    0,    950,  7),
                # PUBG UC
                ("pubg", "🎮 30 UC",   30,   120,  1),
                ("pubg", "🎮 60 UC",   60,   180,  2),
                ("pubg", "🎮 120 UC",  120,  395,  3),
                ("pubg", "🎮 180 UC",  180,  590,  4),
                ("pubg", "🎮 325 UC",  325,  900,  5),
                ("pubg", "🎮 660 UC",  660,  1750, 6),
                ("pubg", "🎮 1800 UC", 1800, 4400, 7),
            ]
            await db.executemany(
                "INSERT INTO products (category,label,amount,price_etb,sort_order) VALUES (?,?,?,?,?)",
                products
            )
            await db.commit()

        # ── Seed payment methods ───────────────────────────────────────
        count2 = await db.execute("SELECT COUNT(*) FROM payment_methods")
        row2 = await count2.fetchone()
        if row2[0] == 0:
            await db.execute("""
                INSERT INTO payment_methods (method_id, name, account, account_name, instructions, is_active)
                VALUES ('telebirr','📱 Telebirr','0904772832','Worke',
                'Send the exact amount to the Telebirr number above, then tap ✅ I Paid and send your screenshot.',1)
            """)
            await db.commit()

        # ── Seed bot settings ──────────────────────────────────────────
        settings = [
            ("welcome_msg", f"Welcome to {STORE_NAME}!\n\n{WELCOME_TAGLINE}"),
            ("order_expiry", str(ORDER_EXPIRY)),
            ("support", SUPPORT),
        ]
        for k, v in settings:
            await db.execute(
                "INSERT OR IGNORE INTO bot_settings (key,value) VALUES (?,?)", (k, v)
            )
        await db.commit()

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_get_setting(key):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None

async def db_set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key,value) VALUES (?,?)", (key, value)
        )
        await db.commit()

async def db_upsert_user(user):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
        """, (user.id, user.username or "", user.full_name or ""))
        await db.commit()

async def db_is_banned(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return bool(row and row[0])

async def db_get_products(category):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT product_id,label,price_etb FROM products WHERE category=? AND is_active=1 ORDER BY sort_order",
            (category,)
        )
        return await cur.fetchall()

async def db_get_product(pid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM products WHERE product_id=?", (pid,))
        return await cur.fetchone()

async def db_get_payment_methods():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT method_id,name,account,account_name,instructions FROM payment_methods WHERE is_active=1"
        )
        return await cur.fetchall()

async def db_get_payment_method(mid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM payment_methods WHERE method_id=?", (mid,))
        return await cur.fetchone()

async def db_create_order(order_id, user_id, product_id, product_label, game_id, pay_method, amount_due):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO orders (order_id,user_id,product_id,product_label,game_id,payment_method,amount_due,status)
            VALUES (?,?,?,?,?,?,?,'pending')
        """, (order_id, user_id, product_id, product_label, game_id, pay_method, amount_due))
        await db.commit()

async def db_get_order(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
        return await cur.fetchone()

async def db_update_order_status(order_id, status, extra=None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()
        if status == "confirming":
            await db.execute(
                "UPDATE orders SET status=? WHERE order_id=?", (status, order_id)
            )
        elif status == "completed":
            note = extra or ""
            await db.execute(
                "UPDATE orders SET status=?,delivered_at=?,admin_note=? WHERE order_id=?",
                (status, now, note, order_id)
            )
            # update user stats
            cur = await db.execute("SELECT user_id,amount_due FROM orders WHERE order_id=?", (order_id,))
            row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE users SET total_orders=total_orders+1, total_spent=total_spent+? WHERE user_id=?",
                    (row[1], row[0])
                )
        elif status == "rejected":
            note = extra or ""
            await db.execute(
                "UPDATE orders SET status='failed',admin_note=? WHERE order_id=?",
                (note, order_id)
            )
        elif status == "refunded":
            await db.execute(
                "UPDATE orders SET status='refunded' WHERE order_id=?", (order_id,)
            )
        await db.commit()

async def db_save_proof(order_id, proof):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET payment_proof=?,status='confirming' WHERE order_id=?",
            (proof, order_id)
        )
        await db.execute(
            "INSERT OR IGNORE INTO used_proofs (proof,order_id) VALUES (?,?)",
            (proof, order_id)
        )
        await db.commit()

async def db_proof_used(proof):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM used_proofs WHERE proof=?", (proof,))
        return await cur.fetchone() is not None

async def db_user_active_order(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT order_id FROM orders WHERE user_id=? AND status IN ('pending','confirming')",
            (user_id,)
        )
        return await cur.fetchone()

async def db_get_user_orders(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT order_id,product_label,amount_due,status,created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )
        return await cur.fetchall()

async def db_get_pending_orders():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT order_id,user_id,product_label,game_id,payment_method,amount_due,payment_proof FROM orders WHERE status='confirming' ORDER BY created_at"
        )
        return await cur.fetchall()

async def db_get_all_products():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT product_id,category,label,price_etb,is_active FROM products ORDER BY category,sort_order"
        )
        return await cur.fetchall()

async def db_get_all_users(limit=50, offset=0):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id,username,full_name,total_orders,total_spent,is_banned FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        )
        return await cur.fetchall()

async def db_get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone()

async def db_get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        today = datetime.now().strftime("%Y-%m-%d")
        month = datetime.now().strftime("%Y-%m")
        stats = {}
        cur = await db.execute("SELECT COUNT(*) FROM users")
        stats["total_users"] = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*),SUM(amount_due) FROM orders WHERE status='completed'")
        r = await cur.fetchone()
        stats["total_orders"] = r[0]
        stats["total_revenue"] = r[1] or 0
        cur = await db.execute(f"SELECT COUNT(*),SUM(amount_due) FROM orders WHERE status='completed' AND created_at LIKE '{today}%'")
        r = await cur.fetchone()
        stats["today_orders"] = r[0]
        stats["today_revenue"] = r[1] or 0
        cur = await db.execute(f"SELECT COUNT(*),SUM(amount_due) FROM orders WHERE status='completed' AND created_at LIKE '{month}%'")
        r = await cur.fetchone()
        stats["month_orders"] = r[0]
        stats["month_revenue"] = r[1] or 0
        cur = await db.execute("SELECT COUNT(*) FROM orders WHERE status='confirming'")
        stats["pending"] = (await cur.fetchone())[0]
        return stats

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def gen_order_id():
    now = datetime.now()
    import random
    return f"ORD-{now.strftime('%Y%m%d')}-{random.randint(1000,9999)}"

def is_admin(user_id):
    return user_id in ADMIN_IDS

def status_badge(status):
    return {
        "pending":    "⏳ Pending",
        "confirming": "🔄 Confirming",
        "completed":  "✅ Completed",
        "failed":     "❌ Failed",
        "refunded":   "↩️ Refunded",
    }.get(status, status)

CATEGORY_INFO = {
    "stars":    ("⭐ Telegram Stars",   "stars"),
    "premium":  ("🌟 Telegram Premium", "premium"),
    "tiktok":   ("🪙 TikTok Coins",     "tiktok"),
    "freefire": ("💎 Free Fire Diamonds","freefire"),
    "pubg":     ("🎮 PUBG UC",          "pubg"),
}

CATEGORY_NOTE = {
    "stars":    "📌 Your Telegram username is required.",
    "premium":  "📌 Login to your Telegram account is required. We'll contact you.",
    "tiktok":   "📌 Login to your TikTok account is required. We'll contact you.",
    "freefire": "📌 Enter your Free Fire Player ID (numeric only).",
    "pubg":     "📌 Enter your PUBG Player ID or username.",
}

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Telegram Stars",    callback_data="cat_stars"),
         InlineKeyboardButton("🌟 Telegram Premium",  callback_data="cat_premium")],
        [InlineKeyboardButton("🪙 TikTok Coins",      callback_data="cat_tiktok"),
         InlineKeyboardButton("💎 Free Fire",         callback_data="cat_freefire")],
        [InlineKeyboardButton("🎮 PUBG UC",           callback_data="cat_pubg")],
        [InlineKeyboardButton("📦 My Orders",         callback_data="my_orders"),
         InlineKeyboardButton("🆘 Support",           callback_data="support")],
    ])

# ─── MIDDLEWARE ───────────────────────────────────────────────────────────────

async def ban_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and await db_is_banned(user.id):
        if update.message:
            await update.message.reply_text("🚫 You have been banned from this store.")
        elif update.callback_query:
            await update.callback_query.answer("🚫 You are banned.", show_alert=True)
        return False
    return True

# ─── /START ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ban_check(update, context):
        return
    user = update.effective_user
    await db_upsert_user(user)
    welcome = await db_get_setting("welcome_msg") or f"Welcome to {STORE_NAME}!"
    text = (
        f"╔══════════════════════════╗\n"
        f"║   {STORE_NAME}   ║\n"
        f"╚══════════════════════════╝\n\n"
        f"{welcome}\n\n"
        f"👇 Choose a product to get started:"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ─── MAIN MENU CALLBACK ───────────────────────────────────────────────────────

async def cb_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ban_check(update, context):
        return
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "main_menu":
        welcome = await db_get_setting("welcome_msg") or f"Welcome to {STORE_NAME}!"
        text = (
            f"╔══════════════════════════╗\n"
            f"║   {STORE_NAME}   ║\n"
            f"╚══════════════════════════╝\n\n"
            f"{welcome}\n\n"
            f"👇 Choose a product to get started:"
        )
        await q.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data == "support":
        support = await db_get_setting("support") or SUPPORT
        await q.edit_message_text(
            f"🆘 *Support*\n\nFor any issues, contact us directly:\n👉 {support}\n\nWe usually respond within a few minutes.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
        )
        return

    if data == "my_orders":
        await show_my_orders(update, context)
        return

    if data.startswith("cat_"):
        cat = data[4:]
        await show_category(update, context, cat)
        return

    if data.startswith("pack_"):
        pid = int(data[5:])
        await show_pack(update, context, pid)
        return

# ─── CATEGORY LISTING ─────────────────────────────────────────────────────────

async def show_category(update, context, cat):
    q = update.callback_query
    products = await db_get_products(cat)
    cat_name = CATEGORY_INFO[cat][0]

    if not products:
        await q.edit_message_text(
            f"{cat_name}\n\n⚠️ No products available right now. Check back soon!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
        )
        return

    buttons = []
    for pid, label, price in products:
        buttons.append([InlineKeyboardButton(
            f"{label} — {int(price):,} ETB", callback_data=f"pack_{pid}"
        )])
    buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")])

    await q.edit_message_text(
        f"*{cat_name}*\n\n👇 Select a pack:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ─── PACK DETAIL ──────────────────────────────────────────────────────────────

async def show_pack(update, context, pid):
    q = update.callback_query
    p = await db_get_product(pid)
    if not p:
        await q.answer("Product not found.", show_alert=True)
        return

    _, cat, label, amount, price_etb, is_active, sort_order = p
    note = CATEGORY_NOTE.get(cat, "")

    text = (
        f"🛍️ *{label}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Price: *{int(price_etb):,} ETB*\n"
        f"⏱ Delivery: Usually within 30 minutes\n\n"
        f"{note}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Buy Now", callback_data=f"buy_{pid}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"cat_{cat}")]
    ])
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ─── ORDER FLOW (ConversationHandler) ─────────────────────────────────────────

async def cb_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ban_check(update, context):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    pid = int(q.data[4:])
    p = await db_get_product(pid)
    if not p:
        await q.answer("Product not found.", show_alert=True)
        return ConversationHandler.END

    # One active order check
    active = await db_user_active_order(q.from_user.id)
    if active:
        await q.edit_message_text(
            f"⚠️ You already have an active order (*{active[0]}*).\n\n"
            "Please wait for it to complete or contact support.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
        )
        return ConversationHandler.END

    context.user_data["order_pid"] = pid
    context.user_data["order_cat"] = p[1]
    context.user_data["order_label"] = p[2]
    context.user_data["order_price"] = p[4]

    cat = p[1]
    prompts = {
        "stars":    "Please enter your *Telegram username* (e.g. @yourname):",
        "premium":  "Please enter your *Telegram username* (e.g. @yourname):",
        "tiktok":   "Please enter your *TikTok username*:",
        "freefire": "Please enter your *Free Fire Player ID* (numeric ID only):",
        "pubg":     "Please enter your *PUBG Player ID or username*:",
    }
    prompt = prompts.get(cat, "Please enter your game/account ID:")
    await q.edit_message_text(
        f"🛒 *{p[2]}*\n💰 *{int(p[4]):,} ETB*\n\n{prompt}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]])
    )
    return ST_GAME_ID

async def recv_game_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ban_check(update, context):
        return ConversationHandler.END
    gid = update.message.text.strip()
    context.user_data["order_gid"] = gid
    label = context.user_data["order_label"]
    price = int(context.user_data["order_price"])
    await update.message.reply_text(
        f"📋 *Order Summary*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Product: *{label}*\n"
        f"💰 Price: *{price:,} ETB*\n"
        f"🎮 Account ID: `{gid}`\n\n"
        f"Is this correct?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Continue", callback_data="confirm_id"),
             InlineKeyboardButton("✏️ Re-enter", callback_data="reenter_id")]
        ])
    )
    return ST_CONFIRM_ID

async def cb_confirm_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "reenter_id":
        cat = context.user_data.get("order_cat", "")
        prompts = {
            "stars":    "Please re-enter your *Telegram username*:",
            "premium":  "Please re-enter your *Telegram username*:",
            "tiktok":   "Please re-enter your *TikTok username*:",
            "freefire": "Please re-enter your *Free Fire Player ID*:",
            "pubg":     "Please re-enter your *PUBG Player ID*:",
        }
        await q.edit_message_text(
            prompts.get(cat, "Please re-enter your ID:"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ST_GAME_ID

    # Show payment methods
    methods = await db_get_payment_methods()
    if not methods:
        await q.edit_message_text(
            "⚠️ No payment methods available. Please contact support.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(m[1], callback_data=f"pm_{m[0]}")] for m in methods]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")])
    await q.edit_message_text(
        "💳 *Choose Payment Method:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_PAY_METHOD

async def cb_pay_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mid = q.data[3:]
    method = await db_get_payment_method(mid)
    if not method:
        await q.answer("Method not found.", show_alert=True)
        return ST_PAY_METHOD

    # method: (method_id, name, account, account_name, instructions, is_active)
    context.user_data["order_pm"] = mid
    context.user_data["order_pm_name"] = method[1]

    order_id = gen_order_id()
    context.user_data["order_id"] = order_id
    price = int(context.user_data["order_price"])
    label = context.user_data["order_label"]
    gid   = context.user_data["order_gid"]
    instructions = method[4] or ""

    text = (
        f"📱 *{method[1]} Payment*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔖 Order: `{order_id}`\n"
        f"📦 Product: {label}\n"
        f"💰 Amount: *{price:,} ETB*\n\n"
        f"📲 Send To: `{method[2]}`\n"
        f"👤 Account Name: *{method[3]}*\n\n"
        f"⚠️ Send *EXACTLY {price:,} ETB*\n"
        f"⏳ Order expires in {ORDER_EXPIRY} minutes\n\n"
        f"ℹ️ {instructions}"
    )

    # Create order in DB
    await db_create_order(order_id, q.from_user.id, context.user_data["order_pid"],
                          label, gid, mid, price)

    # Schedule expiry
    context.job_queue.run_once(
        expire_order,
        when=ORDER_EXPIRY * 60,
        data={"order_id": order_id, "user_id": q.from_user.id, "bot": q.get_bot()},
        name=f"expire_{order_id}"
    )

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Paid", callback_data="i_paid")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]
        ])
    )
    return ST_PROOF

async def cb_i_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mid = context.user_data.get("order_pm", "telebirr")
    await q.edit_message_text(
        "📸 *Payment Proof Required*\n\n"
        "Please send a *screenshot* of your payment receipt as an image.\n\n"
        "_(Make sure the amount and date are clearly visible)_",
        parse_mode=ParseMode.MARKDOWN
    )
    return ST_PROOF

async def recv_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ban_check(update, context):
        return ConversationHandler.END

    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("⚠️ Session expired. Please start a new order.")
        return ConversationHandler.END

    # Accept photo or document
    proof = None
    if update.message.photo:
        proof = update.message.photo[-1].file_id
    elif update.message.document:
        proof = update.message.document.file_id
    else:
        await update.message.reply_text("⚠️ Please send an *image* (screenshot) of your payment.", parse_mode=ParseMode.MARKDOWN)
        return ST_PROOF

    # Duplicate check
    if await db_proof_used(proof):
        await update.message.reply_text("⚠️ This screenshot has already been used. Please send a new one.")
        return ST_PROOF

    await db_save_proof(order_id, proof)

    user = update.effective_user
    label    = context.user_data.get("order_label", "")
    gid      = context.user_data.get("order_gid", "")
    pm_name  = context.user_data.get("order_pm_name", "")
    price    = int(context.user_data.get("order_price", 0))

    await update.message.reply_text(
        f"✅ *Payment proof received!*\n\n"
        f"🔖 Order: `{order_id}`\n"
        f"📦 {label}\n"
        f"💰 {price:,} ETB\n\n"
        f"⏳ Your order is under review. You'll be notified once confirmed — usually within *15–30 minutes*.\n\n"
        f"Thank you for shopping with {STORE_NAME}! 🎉",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📦 My Orders", callback_data="my_orders")]])
    )

    # Notify all admins
    uname = f"@{user.username}" if user.username else user.full_name
    alert = (
        f"🆕 *NEW ORDER — Action Required*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔖 Order: `{order_id}`\n"
        f"👤 Customer: {uname} (ID: `{user.id}`)\n"
        f"📦 Product: {label}\n"
        f"🎮 Account ID: `{gid}`\n"
        f"💳 Payment: {pm_name}\n"
        f"💰 Amount: {price:,} ETB\n"
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Deliver", callback_data=f"adm_confirm_{order_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{order_id}")],
        [InlineKeyboardButton("↩️ Refund", callback_data=f"adm_refund_{order_id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, alert, parse_mode=ParseMode.MARKDOWN, reply_markup=admin_kb)
            # Forward screenshot
            await context.bot.send_photo(admin_id, proof, caption=f"📸 Proof for {order_id}")
        except Exception as e:
            log.warning(f"Could not notify admin {admin_id}: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_order_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = context.user_data.get("order_id")
    if order_id:
        await db_update_order_status(order_id, "rejected", "Cancelled by user")
    context.user_data.clear()
    await q.edit_message_text(
        "❌ Order cancelled.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])
    )
    return ConversationHandler.END

# ─── ORDER EXPIRY ─────────────────────────────────────────────────────────────

async def expire_order(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    order_id = data["order_id"]
    user_id  = data["user_id"]
    order = await db_get_order(order_id)
    if order and order[8] in ("pending", "confirming"):
        await db_update_order_status(order_id, "rejected", "Order expired")
        try:
            await context.bot.send_message(
                user_id,
                f"⏰ Your order `{order_id}` has *expired* (30 minutes passed).\n\n"
                "Please place a new order if you still want to purchase.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Shop Again", callback_data="main_menu")]])
            )
        except Exception:
            pass

# ─── MY ORDERS ────────────────────────────────────────────────────────────────

async def show_my_orders(update, context):
    user_id = update.effective_user.id
    orders  = await db_get_user_orders(user_id)
    q = update.callback_query

    if not orders:
        await q.edit_message_text(
            "📦 *My Orders*\n\nYou haven't placed any orders yet.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
        )
        return

    lines = ["📦 *My Recent Orders*\n━━━━━━━━━━━━━━━━━━━━"]
    for oid, label, amount, status, created in orders:
        date = created[:10]
        lines.append(f"\n🔖 `{oid}`\n📦 {label}\n💰 {int(amount):,} ETB | {status_badge(status)} | {date}")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]])
    )

# ─── ADMIN CALLBACKS ──────────────────────────────────────────────────────────

async def cb_admin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("🚫 Unauthorized", show_alert=True)
        return
    await q.answer()
    data = q.data  # adm_confirm_ORDERID | adm_reject_ORDERID | adm_refund_ORDERID

    parts  = data.split("_", 2)
    action = parts[1]
    oid    = parts[2]
    order  = await db_get_order(oid)
    if not order:
        await q.edit_message_reply_markup(None)
        await q.message.reply_text("⚠️ Order not found.")
        return

    user_id     = order[1]
    label       = order[4] if len(order) > 4 else order[3]
    product_label = order[3]
    game_id     = order[4]
    amount_due  = order[6]

    if action == "confirm":
        await db_update_order_status(oid, "completed", "Confirmed by admin")
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(f"✅ Order `{oid}` confirmed and delivered.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                user_id,
                f"✅ *Payment Confirmed & Delivered!*\n\n"
                f"🔖 Order: `{oid}`\n"
                f"📦 {product_label}\n"
                f"🎮 Account: `{game_id}`\n\n"
                f"Your top-up has been sent to your account. Thank you for shopping with {STORE_NAME}! 🎉",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Buy Again", callback_data="main_menu"),
                     InlineKeyboardButton("📦 My Orders", callback_data="my_orders")]
                ])
            )
        except Exception as e:
            log.warning(f"Could not notify user {user_id}: {e}")

    elif action == "reject":
        await db_update_order_status(oid, "rejected", "Rejected by admin")
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(f"❌ Order `{oid}` rejected.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                user_id,
                f"❌ *Order Rejected*\n\n"
                f"🔖 Order: `{oid}`\n\n"
                f"Unfortunately your payment could not be verified. Please contact support: {SUPPORT}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    elif action == "refund":
        await db_update_order_status(oid, "refunded")
        await q.edit_message_reply_markup(None)
        await q.message.reply_text(f"↩️ Order `{oid}` marked as refunded.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                user_id,
                f"↩️ *Order Refunded*\n\n"
                f"🔖 Order: `{oid}`\n\n"
                f"Your order has been refunded. Please contact support for details: {SUPPORT}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

# ─── ADMIN PANEL ──────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return  # Silently ignore
    await update.message.reply_text(
        f"🔐 *{STORE_NAME} — Admin Panel*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_main_kb()
    )

def admin_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Pending Orders",  callback_data="adm_pending"),
         InlineKeyboardButton("📊 Stats",           callback_data="adm_stats")],
        [InlineKeyboardButton("📦 Products",        callback_data="adm_products"),
         InlineKeyboardButton("💳 Payments",        callback_data="adm_payments")],
        [InlineKeyboardButton("👥 Users",           callback_data="adm_users"),
         InlineKeyboardButton("📣 Broadcast",       callback_data="adm_broadcast")],
        [InlineKeyboardButton("⚙️ Settings",        callback_data="adm_settings")],
    ])

async def cb_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("🚫 Unauthorized", show_alert=True)
        return
    await q.answer()
    data = q.data

    # ── Pending orders ────────────────────────────────────────────────
    if data == "adm_pending":
        orders = await db_get_pending_orders()
        if not orders:
            await q.edit_message_text(
                "📋 *Pending Orders*\n\nNo pending orders right now. ✅",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]) 
            )
            return
        lines = ["📋 *Pending Orders*\n━━━━━━━━━━━━━━━━━━━━"]
        for oid, uid, label, gid, pm, amount, proof in orders:
            lines.append(f"\n🔖 `{oid}`\n📦 {label}\n🎮 `{gid}`\n💳 {pm} | 💰 {int(amount):,} ETB")
        kb = []
        for oid, uid, label, gid, pm, amount, proof in orders:
            kb.append([
                InlineKeyboardButton(f"✅ {oid}", callback_data=f"adm_confirm_{oid}"),
                InlineKeyboardButton(f"❌ Reject", callback_data=f"adm_reject_{oid}")
            ])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="adm_back")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))

    # ── Stats ─────────────────────────────────────────────────────────
    elif data == "adm_stats":
        s = await db_get_stats()
        text = (
            f"📊 *Store Statistics*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users: {s['total_users']}\n\n"
            f"📦 All-time Orders: {s['total_orders']}\n"
            f"💰 All-time Revenue: {s['total_revenue']:,.0f} ETB\n\n"
            f"📅 Today Orders: {s['today_orders']}\n"
            f"💰 Today Revenue: {s['today_revenue']:,.0f} ETB\n\n"
            f"📆 This Month Orders: {s['month_orders']}\n"
            f"💰 This Month Revenue: {s['month_revenue']:,.0f} ETB\n\n"
            f"⏳ Awaiting Confirmation: {s['pending']}"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    # ── Products ──────────────────────────────────────────────────────
    elif data == "adm_products":
        products = await db_get_all_products()
        cat_groups = {}
        for pid, cat, label, price, active in products:
            cat_groups.setdefault(cat, []).append((pid, label, price, active))
        lines = ["📦 *Product List*\n━━━━━━━━━━━━━━━━━━━━"]
        for cat, items in cat_groups.items():
            lines.append(f"\n*{CATEGORY_INFO[cat][0]}*")
            for pid, label, price, active in items:
                status = "🟢" if active else "🔴"
                lines.append(f"{status} [{pid}] {label} — {int(price):,} ETB")
        lines.append("\n_To edit a product, use /editproduct <id>_")
        lines.append("_To add a product, use /addproduct_")
        lines.append("_To toggle active, use /toggleproduct <id>_")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    # ── Payments ──────────────────────────────────────────────────────
    elif data == "adm_payments":
        methods = await db_get_payment_methods()
        lines = ["💳 *Payment Methods*\n━━━━━━━━━━━━━━━━━━━━"]
        for mid, name, account, account_name, instructions in methods:
            lines.append(f"\n*{name}*\n📲 {account}\n👤 {account_name}")
        lines.append("\n_Use /editpayment <method_id> to update_")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    # ── Users ─────────────────────────────────────────────────────────
    elif data == "adm_users":
        users = await db_get_all_users(limit=20)
        lines = ["👥 *Users (last 20)*\n━━━━━━━━━━━━━━━━━━━━"]
        for uid, uname, fname, orders, spent, banned in users:
            b = "🚫" if banned else "✅"
            name = f"@{uname}" if uname else fname
            lines.append(f"{b} {name} | {orders} orders | {int(spent):,} ETB")
        lines.append("\n_Use /banuser <id> or /unbanuser <id>_")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    # ── Broadcast ─────────────────────────────────────────────────────
    elif data == "adm_broadcast":
        await q.edit_message_text(
            "📣 *Broadcast*\n\nUse the command:\n`/broadcast <your message>`\n\nThis will send your message to ALL users.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    # ── Settings ──────────────────────────────────────────────────────
    elif data == "adm_settings":
        welcome = await db_get_setting("welcome_msg") or ""
        support = await db_get_setting("support") or ""
        expiry  = await db_get_setting("order_expiry") or "30"
        text = (
            f"⚙️ *Bot Settings*\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💬 Welcome Message:\n_{welcome[:100]}..._\n\n"
            f"🆘 Support: {support}\n"
            f"⏳ Order Expiry: {expiry} min\n\n"
            f"_Use commands:_\n"
            f"`/setwelcome <text>` — change welcome\n"
            f"`/setsupport <@username>` — change support\n"
            f"`/setexpiry <minutes>` — change expiry"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_back")]]))

    elif data == "adm_back":
        await q.edit_message_text(
            f"🔐 *{STORE_NAME} — Admin Panel*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=admin_main_kb()
        )

# ─── ADMIN COMMANDS ───────────────────────────────────────────────────────────

async def cmd_addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    usage = (
        "➕ *Add Product*\n\n"
        "Usage:\n`/addproduct <category> | <label> | <amount> | <price_etb>`\n\n"
        "Categories: `stars` `premium` `tiktok` `freefire` `pubg`\n\n"
        "Example:\n`/addproduct freefire | 💎 1060+106 Diamonds | 1166 | 1900`"
    )
    if not context.args:
        await update.message.reply_text(usage, parse_mode=ParseMode.MARKDOWN)
        return
    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("⚠️ Wrong format.\n\n" + usage, parse_mode=ParseMode.MARKDOWN)
        return
    cat, label, amount, price = parts
    if cat not in CATEGORY_INFO:
        await update.message.reply_text(f"⚠️ Unknown category `{cat}`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        amount_f = float(amount)
        price_f  = float(price)
    except ValueError:
        await update.message.reply_text("⚠️ Amount and price must be numbers.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products (category,label,amount,price_etb,sort_order) VALUES (?,?,?,?,99)",
            (cat, label, amount_f, price_f)
        )
        await db.commit()
    await update.message.reply_text(f"✅ Product added: *{label}* — {int(price_f):,} ETB", parse_mode=ParseMode.MARKDOWN)

async def cmd_editproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    usage = "Usage: `/editproduct <id> | <field> | <value>`\nFields: `label` `price_etb` `amount` `sort_order`"
    if not context.args:
        await update.message.reply_text(usage, parse_mode=ParseMode.MARKDOWN); return
    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        await update.message.reply_text("⚠️ Wrong format.\n" + usage, parse_mode=ParseMode.MARKDOWN); return
    pid, field, value = parts
    allowed = ["label", "price_etb", "amount", "sort_order", "is_active"]
    if field not in allowed:
        await update.message.reply_text(f"⚠️ Allowed fields: {', '.join(allowed)}"); return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE products SET {field}=? WHERE product_id=?", (value, int(pid)))
        await db.commit()
    await update.message.reply_text(f"✅ Product `{pid}` updated: `{field}` = `{value}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_toggleproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/toggleproduct <id>`", parse_mode=ParseMode.MARKDOWN); return
    pid = int(context.args[0])
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT is_active,label FROM products WHERE product_id=?", (pid,))
        row = await cur.fetchone()
        if not row:
            await update.message.reply_text("⚠️ Product not found."); return
        new_state = 0 if row[0] else 1
        await db.execute("UPDATE products SET is_active=? WHERE product_id=?", (new_state, pid))
        await db.commit()
    state_txt = "🟢 Active" if new_state else "🔴 Inactive"
    await update.message.reply_text(f"✅ *{row[1]}* is now {state_txt}", parse_mode=ParseMode.MARKDOWN)

async def cmd_editpayment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    usage = "Usage: `/editpayment <method_id> | <field> | <value>`\nFields: `account` `account_name` `instructions` `is_active`"
    if not context.args:
        await update.message.reply_text(usage, parse_mode=ParseMode.MARKDOWN); return
    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        await update.message.reply_text("⚠️ Wrong format.\n" + usage, parse_mode=ParseMode.MARKDOWN); return
    mid, field, value = parts
    allowed = ["account", "account_name", "instructions", "is_active", "name"]
    if field not in allowed:
        await update.message.reply_text(f"⚠️ Allowed fields: {', '.join(allowed)}"); return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE payment_methods SET {field}=? WHERE method_id=?", (value, mid))
        await db.commit()
    await update.message.reply_text(f"✅ Payment method `{mid}` updated.", parse_mode=ParseMode.MARKDOWN)

async def cmd_banuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/banuser <user_id>`", parse_mode=ParseMode.MARKDOWN); return
    uid = int(context.args[0])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (uid,))
        await db.commit()
    await update.message.reply_text(f"🚫 User `{uid}` has been banned.", parse_mode=ParseMode.MARKDOWN)

async def cmd_unbanuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/unbanuser <user_id>`", parse_mode=ParseMode.MARKDOWN); return
    uid = int(context.args[0])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (uid,))
        await db.commit()
    await update.message.reply_text(f"✅ User `{uid}` has been unbanned.", parse_mode=ParseMode.MARKDOWN)

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN); return
    msg = " ".join(context.args)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE is_banned=0")
        users = await cur.fetchall()
    success, fail = 0, 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, f"📣 *Announcement*\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"📣 Broadcast complete!\n✅ Sent: {success}\n❌ Failed: {fail}")

async def cmd_setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/setwelcome <message>`", parse_mode=ParseMode.MARKDOWN); return
    msg = " ".join(context.args)
    await db_set_setting("welcome_msg", msg)
    await update.message.reply_text("✅ Welcome message updated.")

async def cmd_setsupport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/setsupport @username`", parse_mode=ParseMode.MARKDOWN); return
    await db_set_setting("support", context.args[0])
    await update.message.reply_text(f"✅ Support set to {context.args[0]}")

async def cmd_setexpiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/setexpiry <minutes>`", parse_mode=ParseMode.MARKDOWN); return
    await db_set_setting("order_expiry", context.args[0])
    await update.message.reply_text(f"✅ Order expiry set to {context.args[0]} minutes.")

async def cmd_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: look up any order by ID"""
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: `/order <ORDER_ID>`", parse_mode=ParseMode.MARKDOWN); return
    oid = context.args[0]
    order = await db_get_order(oid)
    if not order:
        await update.message.reply_text("⚠️ Order not found.")
        return
    # columns: order_id,user_id,product_id,product_label,game_id,payment_method,amount_due,payment_proof,status,created_at,...
    text = (
        f"🔍 *Order Details*\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🔖 ID: `{order[0]}`\n"
        f"👤 User: `{order[1]}`\n"
        f"📦 Product: {order[3]}\n"
        f"🎮 Account: `{order[4]}`\n"
        f"💳 Payment: {order[5]}\n"
        f"💰 Amount: {int(order[6]):,} ETB\n"
        f"📊 Status: {status_badge(order[8])}\n"
        f"🕐 Created: {order[9]}\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"adm_confirm_{oid}"),
         InlineKeyboardButton("❌ Reject",  callback_data=f"adm_reject_{oid}"),
         InlineKeyboardButton("↩️ Refund",  callback_data=f"adm_refund_{oid}")]
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ─── HELP ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        text = (
            "🔐 *Admin Commands*\n━━━━━━━━━━━━━━━━━━━━\n"
            "/admin — Open admin panel\n"
            "/order <id> — Look up any order\n\n"
            "*Products:*\n"
            "/addproduct — Add new product\n"
            "/editproduct <id> | <field> | <value>\n"
            "/toggleproduct <id> — Activate/deactivate\n\n"
            "*Payment:*\n"
            "/editpayment <id> | <field> | <value>\n\n"
            "*Users:*\n"
            "/banuser <id>\n"
            "/unbanuser <id>\n\n"
            "*Broadcast:*\n"
            "/broadcast <message>\n\n"
            "*Settings:*\n"
            "/setwelcome <text>\n"
            "/setsupport @username\n"
            "/setexpiry <minutes>"
        )
    else:
        support = await db_get_setting("support") or SUPPORT
        text = (
            f"❓ *Help*\n━━━━━━━━━━━━━━━━━━━━\n"
            f"/start — Open the store\n"
            f"📦 My Orders — View your order history\n"
            f"🆘 Support — Contact us at {support}\n\n"
            f"For any issues with your order, please contact {support}"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ─── UNKNOWN ──────────────────────────────────────────────────────────────────

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "👋 Tap /start to open the store.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Open Store", callback_data="main_menu")]])
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

async def post_init(app):
    await db_init()
    log.info("✅ Database initialized")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Order conversation
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_buy, pattern=r"^buy_\d+$")],
        states={
            ST_GAME_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_game_id)],
            ST_CONFIRM_ID: [CallbackQueryHandler(cb_confirm_id, pattern=r"^(confirm_id|reenter_id)$")],
            ST_PAY_METHOD: [CallbackQueryHandler(cb_pay_method, pattern=r"^pm_")],
            ST_PROOF:      [
                CallbackQueryHandler(cb_i_paid, pattern=r"^i_paid$"),
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, recv_proof)
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_order_cb, pattern=r"^cancel_order$")],
        allow_reentry=True,
    )

    # Handlers
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("admin",          cmd_admin))
    app.add_handler(CommandHandler("order",          cmd_order))
    app.add_handler(CommandHandler("addproduct",     cmd_addproduct))
    app.add_handler(CommandHandler("editproduct",    cmd_editproduct))
    app.add_handler(CommandHandler("toggleproduct",  cmd_toggleproduct))
    app.add_handler(CommandHandler("editpayment",    cmd_editpayment))
    app.add_handler(CommandHandler("banuser",        cmd_banuser))
    app.add_handler(CommandHandler("unbanuser",      cmd_unbanuser))
    app.add_handler(CommandHandler("broadcast",      cmd_broadcast))
    app.add_handler(CommandHandler("setwelcome",     cmd_setwelcome))
    app.add_handler(CommandHandler("setsupport",     cmd_setsupport))
    app.add_handler(CommandHandler("setexpiry",      cmd_setexpiry))
    app.add_handler(order_conv)
    app.add_handler(CallbackQueryHandler(cb_admin_order, pattern=r"^adm_(confirm|reject|refund)_"))
    app.add_handler(CallbackQueryHandler(cb_admin_panel,  pattern=r"^adm_"))
    app.add_handler(CallbackQueryHandler(cb_main))
    app.add_handler(MessageHandler(filters.ALL, unknown_message))

    log.info(f"🚀 {STORE_NAME} bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
