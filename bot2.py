"""
📘 FB VIDEO DOWNLOADER BOT — v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Téléchargeur Facebook · Abonnement · Parrainage · Points

INSTALLATION :
    pip install python-telegram-bot

CONFIGURATION (section CONFIG ci-dessous) :
    TOKEN        → Token @BotFather
    CHANNEL_ID   → @username_du_canal  (le bot DOIT être ADMIN du canal)
    CHANNEL_LINK → https://t.me/username_du_canal
    BOT_USERNAME → username du bot SANS @
    ADMIN_ID     → Ton Telegram ID numérique
"""

import logging
import sqlite3
from datetime import date

import urllib.parse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                   CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOKEN          = "8221329718:AAFpyexV6qskJnChZixlI9iWBRIBwpCWsfI"           # Token du bot (@BotFather)
CHANNEL_ID     = "@Ast_Tech26"             # Username du canal (avec @)
CHANNEL_LINK   = "https://t.me/Ast_Tech26" # Lien public du canal
BOT_USERNAME   = "AstucesTech_bot"          # Sans @
ADMIN_ID       = 6371631083                 # Ton Telegram ID numérique

DB_FILE          = "fb_bot.db"

FREE_DAILY_LIMIT = 3    # vidéos gratuites par jour
POINTS_PER_REF   = 5    # points reçus par ami invité
POINTS_PER_DL    = 2    # points nécessaires pour 1 DL bonus

# Tous les formats d'URL Facebook reconnus
FB_DOMAINS = [
    "facebook.com",
    "fb.watch",
    "fb.me",
]


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#              BASE DE DONNÉES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id         INTEGER PRIMARY KEY,
            username        TEXT,
            first_name      TEXT,
            points          INTEGER DEFAULT 0,
            daily_downloads INTEGER DEFAULT 0,
            last_reset      TEXT    DEFAULT '',
            referred_by     INTEGER DEFAULT NULL,
            join_date       TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            date        TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def register_user(user_id: int, username: str, first_name: str, referred_by: int = None) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = str(date.today())
    c.execute(
        "INSERT OR IGNORE INTO users "
        "(user_id, username, first_name, join_date, referred_by, last_reset) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, first_name, today, referred_by, today),
    )
    is_new = c.rowcount > 0
    if is_new and referred_by:
        c.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (POINTS_PER_REF, referred_by),
        )
        c.execute(
            "INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?, ?, ?)",
            (referred_by, user_id, today),
        )
    conn.commit()
    conn.close()
    return is_new


def get_daily_downloads(user_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = str(date.today())
    c.execute("SELECT daily_downloads, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    count = 0
    if row:
        count, last_reset = row
        if last_reset != today:
            c.execute(
                "UPDATE users SET daily_downloads = 0, last_reset = ? WHERE user_id = ?",
                (today, user_id),
            )
            conn.commit()
            count = 0
    conn.close()
    return count


def increment_downloads(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET daily_downloads = daily_downloads + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_points(user_id: int) -> int:
    u = get_user(user_id)
    return u[3] if u else 0


def spend_points(user_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0] >= POINTS_PER_DL:
        c.execute("UPDATE users SET points = points - ? WHERE user_id = ?", (POINTS_PER_DL, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def get_referral_count(user_id: int) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_total_users() -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#          VÉRIFICATION ABONNEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    ⚠️  Le bot DOIT être ADMINISTRATEUR du canal.
    Canal → Gérer → Administrateurs → Ajouter le bot.
    """
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        logger.info("sub_check user=%s status=%s", user_id, member.status)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("is_subscribed ERREUR user=%s — %s: %s", user_id, type(e).__name__, e)
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#              UI — CLAVIERS & MESSAGES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥  Télécharger une vidéo Facebook", callback_data="start_download")],
        [
            InlineKeyboardButton("👥 Inviter des amis",  callback_data="menu_referral"),
            InlineKeyboardButton("💰 Mes points",        callback_data="menu_points"),
        ],
        [InlineKeyboardButton("📢 Notre canal",           url=CHANNEL_LINK)],
    ])


def sub_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Rejoindre le canal",       url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ J'ai rejoint — Vérifier",  callback_data="check_sub")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="back_main")]])


def limit_keyboard(has_points: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_points:
        rows.append([InlineKeyboardButton(
            f"💰 Utiliser {POINTS_PER_DL} pts → 1 DL bonus",
            callback_data="use_points_dl",
        )])
    rows.append([InlineKeyboardButton("👥 Inviter des amis (+points)", callback_data="menu_referral")])
    rows.append([InlineKeyboardButton("🔙 Retour",                     callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def stats_bar(user_id: int) -> str:
    """Barre de statut compact pour chaque message."""
    dl    = get_daily_downloads(user_id)
    pts   = get_points(user_id)
    left  = max(0, FREE_DAILY_LIMIT - dl)
    dots_filled = "🟦" * left + "⬜" * (FREE_DAILY_LIMIT - left)
    return f"📥 {dots_filled}  {left}/{FREE_DAILY_LIMIT}  •  💰 {pts} pts"


async def _safe_edit(msg, text: str, reply_markup=None):
    """Édition silencieuse — ignore les erreurs Telegram."""
    try:
        kwargs = {"parse_mode": "Markdown"}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        await msg.edit_text(text, **kwargs)
    except Exception:
        pass


async def _reply_or_edit(query, text: str, keyboard=None):
    """Tente edit, fallback reply — ne reste jamais silencieux."""
    kb = keyboard
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.error("_reply_or_edit échec total : %s", e)


async def _show_sub_wall(query, label: str):
    """Popup garantie + message abonnement."""
    await query.answer(f"🔒 Rejoins le canal pour : {label}", show_alert=True)
    text = (
        "🔒 *Abonnement requis*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Pour *{label}*, tu dois d'abord\n"
        f"rejoindre notre canal Telegram.\n\n"
        f"1️⃣ Clique sur *📢 Rejoindre le canal*\n"
        f"2️⃣ Abonne-toi\n"
        f"3️⃣ Reviens et clique *✅ J'ai rejoint*"
    )
    await _reply_or_edit(query, text, sub_keyboard())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                   /start
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            ref_id = int(args[0][4:])
            if ref_id != user.id:
                referred_by = ref_id
        except ValueError:
            pass

    is_new = register_user(user.id, user.username or "", user.first_name, referred_by)

    if is_new and referred_by:
        try:
            pts = get_points(referred_by)
            await context.bot.send_message(
                referred_by,
                f"🎉 *{user.first_name}* a rejoint grâce à ton lien !\n"
                f"*+{POINTS_PER_REF} points* crédités 💰\n"
                f"Total : *{pts} pts*",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    welcome = "👋 Bon retour" if not is_new else "👋 Bienvenue"
    text = (
        f"📘 *FB Video Downloader*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{welcome}, *{user.first_name}* !\n\n"
        f"{stats_bar(user.id)}\n\n"
        f"Colle un lien Facebook ci-dessous\n"
        f"ou appuie sur le bouton 👇"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard(), parse_mode="Markdown")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#          GESTIONNAIRE DE BOUTONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    data    = query.data

    # ── check_sub ─────────────────────────────────────────────────────
    if data == "check_sub":
        await query.answer()
        if await is_subscribed(user_id, context):
            text = (
                "✅ *Abonnement confirmé !*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Bienvenue ! Tu peux maintenant utiliser le bot 🎉\n\n"
                f"{stats_bar(user_id)}"
            )
            await _reply_or_edit(query, text, main_keyboard())
        else:
            text = (
                "❌ *Pas encore abonné*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Tu n'es pas encore membre du canal.\n\n"
                "1️⃣ Clique sur *📢 Rejoindre le canal*\n"
                "2️⃣ Abonne-toi\n"
                "3️⃣ Clique *✅ J'ai rejoint*"
            )
            await _reply_or_edit(query, text, sub_keyboard())
        return

    # ── back_main ──────────────────────────────────────────────────────
    if data == "back_main":
        await query.answer()
        text = (
            "📘 *FB Video Downloader*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{stats_bar(user_id)}\n\n"
            "Envoie un lien Facebook ou appuie sur le bouton 👇"
        )
        await _reply_or_edit(query, text, main_keyboard())
        return

    # ── start_download ─────────────────────────────────────────────────
    if data == "start_download":
        if not await is_subscribed(user_id, context):
            await _show_sub_wall(query, "télécharger une vidéo")
            return
        await query.answer()
        context.user_data["waiting_link"] = True
        text = (
            "📥 *Téléchargement Facebook*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Envoie le lien de ta vidéo 👇\n\n"
            "⚡ Le téléchargement démarre automatiquement !"
        )
        await _reply_or_edit(query, text, back_keyboard())
        return

    # ── menu_referral ──────────────────────────────────────────────────
    if data == "menu_referral":
        await query.answer()
        pts       = get_points(user_id)
        ref_count = get_referral_count(user_id)
        ref_link  = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        dl_bonus  = pts // POINTS_PER_DL
        text = (
            "👥 *Programme Parrainage*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔗 *Ton lien :*\n`{ref_link}`\n\n"
            f"👥 Amis invités : *{ref_count}*\n"
            f"💰 Tes points : *{pts} pts*\n"
            f"📥 DL bonus disponibles : *{dl_bonus}*\n\n"
            "🎁 *Comment ça marche :*\n"
            f"➊ Partage ton lien\n"
            f"➋ Ami rejoint → *+{POINTS_PER_REF} pts* pour toi\n"
            f"➌ *{POINTS_PER_DL} pts* = 1 téléchargement bonus\n\n"
            "👆 _Appuie sur le lien pour le copier_"
        )
        await _reply_or_edit(query, text, back_keyboard())
        return

    # ── menu_points ────────────────────────────────────────────────────
    if data == "menu_points":
        await query.answer()
        pts      = get_points(user_id)
        dl_bonus = pts // POINTS_PER_DL
        text = (
            "💰 *Mes Points*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Solde : *{pts} pts*\n"
            f"📥 DL bonus disponibles : *{dl_bonus}*\n\n"
            "📈 *Gagner des points :*\n"
            f"▸ Invite un ami → *+{POINTS_PER_REF} pts*\n\n"
            "🎁 *Utiliser des points :*\n"
            f"▸ *{POINTS_PER_DL} pts* = 1 DL bonus\n"
            "_Quand ta limite journalière est atteinte_"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Inviter des amis", callback_data="menu_referral")],
            [InlineKeyboardButton("🔙 Retour",           callback_data="back_main")],
        ])
        await _reply_or_edit(query, text, kb)
        return

    # ── use_points_dl ──────────────────────────────────────────────────
    if data == "use_points_dl":
        await query.answer()
        if spend_points(user_id):
            context.user_data["bonus_download"] = True
            context.user_data["waiting_link"]   = True
            pts = get_points(user_id)
            text = (
                "✅ *Points utilisés !*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"*{POINTS_PER_DL} pts* déduits · Solde restant : *{pts} pts*\n\n"
                "Envoie maintenant ton lien Facebook 👇"
            )
            await _reply_or_edit(query, text, back_keyboard())
        else:
            await query.answer("❌ Pas assez de points !", show_alert=True)
        return

    await query.answer()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#      GÉNÉRATION DE LIENS DE TÉLÉCHARGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_download_links(fb_url: str) -> InlineKeyboardMarkup:
    """Génère des boutons pointant vers des sites tiers avec l'URL pré-remplie."""
    enc = urllib.parse.quote(fb_url, safe="")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬇️  SaveFrom",  url=f"https://savefrom.net/1-facebook-video-downloader/?url={enc}")],
        [InlineKeyboardButton("⬇️  9xBuddy",   url=f"https://9xbuddy.org/process?url={enc}")],
        [InlineKeyboardButton("⬇️  Loader.to", url=f"https://loader.to/api/button/?url={enc}&f=360")],
        [InlineKeyboardButton("🔁  Nouvelle vidéo", callback_data="start_download")],
    ])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#         GESTIONNAIRE DE MESSAGES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    msg_text = update.message.text.strip()

    # ── Est-ce un lien Facebook ? ─────────────────────────────────────
    is_fb = any(d in msg_text for d in FB_DOMAINS)

    if not is_fb:
        waiting = context.user_data.get("waiting_link", False)
        if waiting:
            await update.message.reply_text(
                "⚠️ *Ce n'est pas un lien Facebook !*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Envoie uniquement un lien Facebook valide.\n\n"
                "↩️ _Réessaie ou clique Retour._",
                reply_markup=back_keyboard(),
                parse_mode="Markdown",
            )
        else:
            context.user_data["waiting_link"] = True
            await update.message.reply_text(
                "📥 *Téléchargement Facebook*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Envoie le lien de ta vidéo Facebook 👇\n\n"
                "⚡ Le lien de téléchargement sera généré instantanément !",
                reply_markup=back_keyboard(),
                parse_mode="Markdown",
            )
        return

    # ── Vérification abonnement ───────────────────────────────────────
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "🔒 *Abonnement requis*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Pour télécharger, rejoins d'abord notre canal.\n\n"
            f"📢 {CHANNEL_LINK}\n\n"
            "1️⃣ Rejoins le canal\n"
            "2️⃣ Clique *✅ J'ai rejoint* ci-dessous",
            reply_markup=sub_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Vérification limite journalière ──────────────────────────────
    dl_today   = get_daily_downloads(user_id)
    bonus_dl   = context.user_data.get("bonus_download", False)
    points     = get_points(user_id)
    has_points = points >= POINTS_PER_DL

    if dl_today >= FREE_DAILY_LIMIT and not bonus_dl:
        await update.message.reply_text(
            "⛔ *Limite journalière atteinte*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Tu as utilisé tes *{FREE_DAILY_LIMIT} vidéos gratuites* du jour.\n\n"
            f"💰 Tes points : *{points} pts*\n"
            f"📥 Besoin : *{POINTS_PER_DL} pts* pour 1 lien bonus\n\n"
            "Que faire ?\n"
            "▸ Utilise tes points si tu en as\n"
            "▸ Invite des amis pour en gagner\n"
            "▸ Reviens demain 🌅",
            reply_markup=limit_keyboard(has_points),
            parse_mode="Markdown",
        )
        return

    # Réinitialiser flags
    context.user_data["bonus_download"] = False
    context.user_data["waiting_link"]   = False

    # ── Génération instantanée des liens ─────────────────────────────
    increment_downloads(user_id)

    await update.message.reply_text(
        "✅ *Liens de téléchargement prêts !*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{stats_bar(user_id)}\n\n"
        "👇 Choisis un site et clique pour télécharger :",
        reply_markup=make_download_links(msg_text),
        parse_mode="Markdown",
    )



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#            COMMANDE ADMIN /stats
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total = get_total_users()
    await update.message.reply_text(
        f"📊 *Statistiques*\n\n👥 Utilisateurs : *{total}*",
        parse_mode="Markdown",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#                    MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(600)
        .write_timeout(600)
        .connect_timeout(30)
        .pool_timeout(10)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📘 FB VIDEO DOWNLOADER v2.0")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Canal    : {CHANNEL_ID}")
    print(f"  Limite   : {FREE_DAILY_LIMIT} DL/jour")
    print(f"  Parrain  : +{POINTS_PER_REF} pts par ami")
    print(f"  Points   : {POINTS_PER_DL} pts = 1 DL bonus")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    app.run_polling()


if __name__ == "__main__":
    main()
