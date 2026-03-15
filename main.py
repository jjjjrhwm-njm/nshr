import os
import subprocess
import logging
import asyncio
import threading
import time
import requests
import json
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler, CommandHandler
)
# مكتبات فايربيس للحفظ الدائم
import firebase_admin
from firebase_admin import credentials, firestore

# إعداد السجلات - Tracing الاحترافي
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- جلب المتغيرات من رندر (Render Environment) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")
BASE_URL = os.getenv("BASE_URL") 
REDIRECT_URI = f"{BASE_URL}/callback"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)

app = Flask(__name__)

# --- تهيئة فايربيس (الذاكرة السحابية الدائمة) ---
db = None
try:
    FIREBASE_CONF = os.getenv("FIREBASE_CONF")
    if FIREBASE_CONF and not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(FIREBASE_CONF))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 متصل بـ Firebase بنجاح! الذاكرة الدائمة جاهزة.")
except Exception as e:
    logger.error(f"🔴 خطأ في Firebase: {e}")

# --- محرك التجديد التلقائي لتوكن تيك توك ---
def refresh_tiktok_token(r_token):
    """تحديث مفتاح الدخول صمتاً بدون إزعاجك"""
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": r_token
    }
    try:
        res = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            db.collection('tiktok_config').document('auth').set({
                'access_token': res['access_token'],
                'refresh_token': res.get('refresh_token', r_token)
            })
            logger.info("✅ تم تجديد التوكن تلقائياً وحفظه في Firebase.")
            return res['access_token']
    except Exception as e:
        logger.error(f"🔴 فشل التجديد التلقائي: {e}")
    return None

# --- محرك الرفع الاحترافي إلى تيك توك (v2 API) ---
def upload_to_tiktok(video_path, caption):
    try:
        doc = db.collection('tiktok_config').document('auth').get()
        if not doc.exists:
            return "❌ لا يوجد توثيق سحابي. ارسل /login"
        
        auth_data = doc.to_dict()
        current_token = auth_data.get('access_token')
        refresh_token = auth_data.get('refresh_token')

        def perform_upload(token):
            file_size = os.path.getsize(video_path)
            # 1. تهيئة الرفع (Init)
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            init_body = {
                "post_info": {
                    "title": caption,
                    "privacy_level": "SELF_ONLY",
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": file_size,
                    "total_chunk_count": 1
                }
            }
            res_init = requests.post(
                init_url, 
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                json=init_body
            )
            
            if res_init.status_code == 401: return "EXPIRED"

            data_init = res_init.json()
            if "data" not in data_init: return f"❌ فشل تهيئة الرفع: {data_init}"
            
            upload_url = data_init["data"]["upload_url"]
            
            # 2. الرفع الثنائي الفعلي (Binary PUT)
            with open(video_path, "rb") as f:
                put_headers = {
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes 0-{file_size-1}/{file_size}"
                }
                r_put = requests.put(upload_url, headers=put_headers, data=f)
            
            if r_put.status_code in (200, 201, 206):
                return "✅ تم الرفع بنجاح!"
            else:
                return f"❌ فشل رفع الملف: {r_put.text}"

        # المحاولة الأولى
        result = perform_upload(current_token)
        
        # إذا انتهت الصلاحية، جدد وحاول مرة ثانية تلقائياً
        if result == "EXPIRED" and refresh_token:
            logger.info("🔄 انتهى التوكن، جاري التجديد والمحاولة مرة أخرى...")
            new_token = refresh_tiktok_token(refresh_token)
            if new_token:
                return perform_upload(new_token)
            else:
                return "❌ فشل تجديد الدخول التلقائي. ارسل /login"
        
        return result
    except Exception as e:
        return f"❌ خطأ تقني: {e}"

# --- Flask Server (النبض، التوثيق، والتحقق) ---
@app.route('/')
def home():
    return "Bot is pulse-active and Cloud-Connected! 🟢"

@app.route(f'/{VERIFY_PATH}')
def verify_ownership():
    return VERIFY_CONTENT

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if code:
        return f"<h1>✅ تم الربط بنجاح!</h1><p>انسخ الكود وأرسله للبوت:</p><textarea rows='3' style='width:100%'>{code}</textarea>"
    return "<h1>❌ فشل الحصول على الكود</h1>"

def send_pulse():
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
            logger.info("Heartbeat sent to keep server awake.")
        except: pass
        time.sleep(600)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# --- Telegram Bot Logic (نظام نجم نشر) ---

async def login_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
    )
    keyboard = [[InlineKeyboardButton("🔗 ربط حساب تيك توك للمرة الأخيرة", url=auth_url)]]
    await update.message.reply_text("هذه آخر مرة ستحتاج فيها للربط بإذن الله:", reply_markup=InlineKeyboardMarkup(keyboard))

async def auth_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ الطريقة: /auth [الكود]")
        return
    code = context.args[0]
    msg = await update.message.reply_text("⏳ جاري حفظ بياناتك في السحابة للأبد...")
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET,
        "code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI
    }
    try:
        res = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data).json()
        if "access_token" in res:
            if db:
                db.collection('tiktok_config').document('auth').set({
                    'access_token': res['access_token'],
                    'refresh_token': res.get('refresh_token')
                })
            await msg.edit_text("✅ مبروك يا نجم الإبداع! تم تفعيل الحفظ السحابي والتجديد التلقائي بنجاح! 🚀")
        else:
            await msg.edit_text(f"❌ خطأ في الكود: {res}")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

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
    status_msg = await update.message.reply_text("✅ جاري المعالجة، القص، والنشر السحابي...")
    
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
                caption = f"{title} - جـ{part_num}"
                # 1. إرسال تليجرام
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=caption)
                
                # 2. الرفع المباشر لتيك توك
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                await update.message.reply_text(f"📊 تيك توك (جـ{part_num}): {res_tk}")
                
                os.remove(out)

        await status_msg.edit_text("✅ تمت جميع عمليات القص والنشر السحابي بنجاح! 🚀🎬")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ فني: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

# --- التشغيل النهائي المزدوج (Bot + Flask) ---
def run_bot():
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
    application.add_handler(CommandHandler("auth", auth_step))
    
    logger.info("Bot is running...")
    application.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
