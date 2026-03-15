import os
import subprocess
import logging
import asyncio
import threading
import time
import requests
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler, CommandHandler
)

# إعداد السجلات بشكل احترافي
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- جلب البيانات الحساسة من البيئة (Environment) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")

BASE_URL = "https://nshr-6u7f.onrender.com"
REDIRECT_URI = f"{BASE_URL}/callback"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)

app = Flask(__name__)

# --- الجزء الأول: Flask (التوثيق والنبض) ---

@app.route('/')
def home():
    return "Bot is secured and pulsing! 🟢"

@app.route(f'/{VERIFY_PATH}')
def tiktok_verify():
    return VERIFY_CONTENT

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if code:
        return f"<h1>✅ تم الربط!</h1><p>الكود: {code}</p>"
    return "<h1>❌ فشل الربط</h1>"

def send_pulse():
    """النبض لمنع رندر من النوم (كل 10 دقائق)"""
    time.sleep(30) # انتظار قليلاً حتى يقلع السيرفر
    while True:
        try:
            requests.get(BASE_URL)
            logger.info("Pulse: Heartbeat sent to keep server awake.")
        except Exception as e:
            logger.error(f"Pulse failed: {e}")
        time.sleep(600)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# --- الجزء الثاني: منطق البوت (التقسيم والربط) ---

async def login_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
    )
    keyboard = [[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=auth_url)]]
    await update.message.reply_text("اضغط على الزر لربط حسابك:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارسل المقطع يا نجم الإبداع 🎬")
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['video_file_id'] = update.message.video.file_id
    context.user_data['message_id'] = update.message.message_id
    await update.message.reply_text("ارسل العنوان للمقطع 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    await update.message.reply_text("✅ تم الاستلام، جاري المعالجة والتقسيم...")
    
    file_id = context.user_data['video_file_id']
    msg_id = context.user_data['message_id']
    input_path = f"input_{msg_id}.mp4"
    
    new_file = await context.bot.get_file(file_id)
    await new_file.download_to_drive(input_path)
    
    try:
        cmd_dur = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration = float(subprocess.check_output(cmd_dur, shell=True).decode().strip())
        
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            out = f"part_{part_num}_{msg_id}.mp4"
            subprocess.run(f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {out}', shell=True)
            
            if os.path.exists(out):
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"{title} - جـ{part_num}")
                os.remove(out)
        await update.message.reply_text("تم التقسيم بنجاح! 🚀")
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ فني: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

# --- الحل السحري لمشكلة الـ Event Loop في الخيوط ---
def run_bot():
    # إنشاء حلقة أحداث جديدة خصيصاً لهذا الخيط
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]
        },
        fallbacks=[]
    )
    
    application.add_handler(conv)
    application.add_handler(CommandHandler("login", login_tiktok))
    
    logger.info("Bot starting in its own event loop...")
    application.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == '__main__':
    # تشغيل النبض
    threading.Thread(target=send_pulse, daemon=True).start()
    # تشغيل البوت في خيطه الخاص مع معالجة الـ Loop
    threading.Thread(target=run_bot, daemon=True).start()
    # تشغيل Flask على الخيط الرئيسي
    run_flask()
