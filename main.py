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

# إعداد السجلات
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
# الرابط الذي أضفته أنت الآن في رندر
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")
REDIRECT_URI = f"{BASE_URL}/callback"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)

app = Flask(__name__)

# --- تهيئة فايربيس للذاكرة الدائمة (عشان ما يطلب دخول مرة ثانية) ---
db = None
FIREBASE_CONF = os.getenv("FIREBASE_CONF")
try:
    if FIREBASE_CONF and not firebase_admin._apps:
        cred_dict = json.loads(FIREBASE_CONF)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 تم الاتصال بـ Firebase بنجاح! الحفظ الدائم مفعل.")
except Exception as e:
    logger.error(f"🔴 خطأ في الاتصال بـ Firebase: {e}")

# --- الجزء الأول: Flask (النبض وتوثيق تيك توك) ---

@app.route('/')
def home():
    return "Bot is secured, pulsing, and connected to DB! 🟢"

@app.route(f'/{VERIFY_PATH}')
def tiktok_verify():
    return VERIFY_CONTENT

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if code:
        return f"<h1>✅ تم الربط بنجاح!</h1><p>انسخ الكود التالي وأرسله للبوت في تلجرام:</p><textarea rows='3' style='width:100%'>{code}</textarea><p>اكتب في البوت: <br><b>/auth [الكود]</b></p>"
    return "<h1>❌ فشل الحصول على الكود</h1>"

def send_pulse():
    """دالة النبض لإبقاء السيرفر مستيقظاً"""
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
            logger.info("Pulse sent.")
        except: pass
        time.sleep(600)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# --- الجزء الثاني: منطق تيك توك (التجديد التلقائي والرفع) ---

async def login_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
    )
    keyboard = [[InlineKeyboardButton("🔗 ربط حساب تيك توك للمرة الأخيرة", url=auth_url)]]
    await update.message.reply_text("لتفعيل الحفظ الدائم، اربط حسابك الآن:", reply_markup=InlineKeyboardMarkup(keyboard))

async def auth_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ الطريقة: /auth [الكود]")
        return
    code = context.args[0]
    msg = await update.message.reply_text("⏳ جاري حفظ مفاتيح الدخول في السحابة...")

    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET,
        "code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI
    }
    try:
        res = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data).json()
        if "access_token" in res:
            if db: # حفظ في فايربيس
                db.collection('tiktok_config').document('auth').set({
                    'access_token': res['access_token'],
                    'refresh_token': res.get('refresh_token')
                })
            await msg.edit_text("✅ مبروك! تم حفظ الدخول للأبد. لن يطلب منك البوت تسجيل الدخول مجدداً! 🚀")
        else:
            await msg.edit_text(f"❌ خطأ: {res}")
    except Exception as e:
        await msg.edit_text(f"❌ حدث خطأ: {e}")

def auto_refresh_token(refresh_token):
    """تجديد التصريح تلقائياً بدون إزعاج المستخدم"""
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token", "refresh_token": refresh_token
    }
    try:
        res = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data).json()
        if "access_token" in res:
            if db:
                db.collection('tiktok_config').document('auth').set({
                    'access_token': res['access_token'],
                    'refresh_token': res.get('refresh_token', refresh_token)
                })
            return res['access_token']
    except: pass
    return None

def upload_to_tiktok(video_path, caption):
    """محرك الرفع الذكي"""
    try:
        if not db: return "❌ قاعدة البيانات غير متصلة"
        doc = db.collection('tiktok_config').document('auth').get()
        if not doc.exists: return "❌ لم يتم الربط بعد. أرسل /login"
        
        data = doc.to_dict()
        token = data.get('access_token')
        
        def process_upload(t):
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            headers = {"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=UTF-8"}
            body = {
                "post_info": {"title": caption, "privacy_level": "SELF_ONLY"},
                "source_info": {"source": "FILE_UPLOAD", "video_size": os.path.getsize(video_path), 
                                "chunk_size": os.path.getsize(video_path), "total_chunk_count": 1}
            }
            r = requests.post(init_url, headers=headers, json=body)
            if r.status_code == 401: return "EXPIRED"
            
            res_init = r.json()
            if "data" not in res_init: return f"Error: {res_init}"
            
            upload_url = res_init["data"]["upload_url"]
            with open(video_path, "rb") as f:
                requests.put(upload_url, headers={"Content-Type": "video/mp4"}, data=f)
            return "✅ تم النشر بنجاح!"

        result = process_upload(token)
        if result == "EXPIRED": # التوكن انتهى؟ جدده فوراً وكمل الرفع
            new_token = auto_refresh_token(data.get('refresh_token'))
            if new_token: return process_upload(new_token)
            return "❌ فشل التجديد التلقائي. ارسل /login"
        return result
    except Exception as e: return f"❌ خطأ: {e}"

# --- الجزء الثالث: معالجة الفيديو والقص ---

async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارسل المقطع يا نجم الإبداع 🎬")
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['video_file_id'] = update.message.video.file_id
    context.user_data['message_id'] = update.message.message_id
    await update.message.reply_text("ارسل العنوان 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    status = await update.message.reply_text("✅ جاري المعالجة، القص، والنشر السحابي...")
    
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
                # إرسال تلجرام
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=caption)
                # رفع تيك توك
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                await update.message.reply_text(f"📊 تيك توك (جـ{part_num}): {res_tk}")
                os.remove(out)

        await status.edit_text("✅ اكتملت المهمة بنجاح! 🚀")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

# --- التشغيل النهائي ---
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
    application.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
