    import os
import subprocess
import logging
import asyncio
import threading
import time
import requests
import json
import glob
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler, CommandHandler
)
# مكتبات فايربيس للحفظ الدائم
import firebase_admin
from firebase_admin import credentials, firestore

# إعداد السجلات الاحترافية للمطورين
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- جلب المتغيرات من رندر ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") 
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")
REDIRECT_URI = f"{BASE_URL}/callback"
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# --- تهيئة فايربيس (الذاكرة السحابية) ---
db = None
try:
    FIREBASE_CONF = os.getenv("FIREBASE_CONF")
    if FIREBASE_CONF and not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(FIREBASE_CONF))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 متصل بـ Firebase بنجاح! الذاكرة الدائمة مفعلة.")
except Exception as e:
    logger.error(f"🔴 خطأ في Firebase: {e}")

# --- محرك التجديد التلقائي لتوكن تيك توك ---
def refresh_tiktok_token(r_token):
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
            return res['access_token']
    except Exception as e:
        logger.error(f"🔴 فشل التجديد التلقائي: {e}")
    return None

# --- محرك الرفع الاحترافي إلى تيك توك (v2 API) ---
def upload_to_tiktok(video_path, caption):
    try:
        doc = db.collection('tiktok_config').document('auth').get()
        if not doc.exists: return "❌ لا يوجد توثيق سحابي. ارسل /login"
        
        auth_data = doc.to_dict()
        token = auth_data.get('access_token')
        refresh_token = auth_data.get('refresh_token')

        def perform_upload(t):
            file_size = os.path.getsize(video_path)
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            init_body = {
                "post_info": {"title": caption, "privacy_level": "SELF_ONLY"},
                "source_info": {"source": "FILE_UPLOAD", "video_size": file_size, "chunk_size": file_size, "total_chunk_count": 1}
            }
            res_init = requests.post(
                init_url, 
                headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json; charset=UTF-8"},
                json=init_body
            )
            if res_init.status_code == 401: return "EXPIRED"
            
            data_init = res_init.json()
            if "data" not in data_init: return f"❌ فشل تهيئة الرفع: {data_init}"
            
            # الرفع الثنائي (Binary PUT)
            upload_url = data_init["data"]["upload_url"]
            with open(video_path, "rb") as f:
                put_headers = {"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size-1}/{file_size}"}
                r_put = requests.put(upload_url, headers=put_headers, data=f)
            
            return "✅ تم الرفع بنجاح!" if r_put.status_code in (200, 201, 206) else f"❌ فشل PUT: {r_put.text}"

        result = perform_upload(token)
        if result == "EXPIRED" and refresh_token:
            new_token = refresh_tiktok_token(refresh_token)
            if new_token: return perform_upload(new_token)
        return result
    except Exception as e: return f"❌ خطأ تقني: {e}"

# --- Flask Server (النبض والتحقق) ---
@app.route('/')
def home(): return "Bot is Alive 🟢"

@app.route(f'/{VERIFY_PATH}')
def verify_ownership(): return VERIFY_CONTENT

@app.route('/callback')
def callback():
    code = request.args.get('code')
    return f"<h1>✅ تم الربط!</h1><p>انسخ الكود وأرسله للبوت:</p><textarea rows='3' style='width:100%'>{code}</textarea>" if code else "Error"

def send_pulse():
    time.sleep(30)
    while True:
        try: requests.get(BASE_URL)
        except: pass
        time.sleep(600)

# --- Telegram Bot Logic (نظام نجم نشر المتكامل) ---

async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارسل المقطع يا نجم الإبداع 🎬")
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['v_id'] = update.message.video.file_id
    await update.message.reply_text("ارسل العنوان للمقطع 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    status_msg = await update.message.reply_text("📥 جاري تحميل الفيديو من تليجرام...")
    
    file_id = context.user_data['v_id']
    input_path = f"input_{update.message.message_id}.mp4"
    
    try:
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive(input_path)
        
        await status_msg.edit_text("✂️ جاري فحص مدة الفيديو وبدء التقسيم...")
        cmd_dur = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration = float(subprocess.check_output(cmd_dur, shell=True).decode().strip())
        
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            out = f"part_{part_num}_{update.message.message_id}.mp4"
            
            await status_msg.edit_text(f"⚙️ جاري معالجة وتقطيع الجزء ({part_num})...")
            subprocess.run(f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {out}', shell=True)
            
            if os.path.exists(out):
                caption = f"{title} - جـ{part_num}"
                await update.message.reply_text(f"📤 جاري رفع الجزء {part_num} إلى تيك توك...")
                
                # رفع تيك توك
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                
                # إرسال تلجرام للمعاينة
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"✅ {caption}\n📊 نتيجة تيك توك: {res_tk}")
                
                os.remove(out)

        await status_msg.edit_text("✅ تمت جميع العمليات بنجاح! 🚀🎬")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ فني: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

async def post_init(application):
    """تنظيف السيرفر وقتل أي تداخل عند التشغيل"""
    for f in glob.glob("input_*.mp4") + glob.glob("part_*.mp4"):
        try: os.remove(f)
        except: pass
    if ADMIN_ID:
        try: await application.bot.send_message(chat_id=ADMIN_ID, text="🚀 تم تشغيل النسخة النهائية بنجاح! السيرفر نظيف والنسخ القديمة توقفت.")
        except: pass

# --- تشغيل البوت والسيرفر ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False), daemon=True).start()
    
    bot = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # أوامر التوثيق
    bot.add_handler(CommandHandler("login", lambda u, c: u.message.reply_text("رابط التوثيق:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=f"https://www.tiktok.com/v2/auth/authorize/?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri={REDIRECT_URI}")]]))))
    
    async def auth_final(u, c):
        if not c.args: return
        res = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "code": c.args[0], "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            db.collection('tiktok_config').document('auth').set({'access_token': res['access_token'], 'refresh_token': res.get('refresh_token')})
            await u.message.reply_text("✅ تم الحفظ السحابي للأبد! لن يطلب منك البوت تسجيل دخول مجدداً.")
        else: await u.message.reply_text(f"❌ خطأ: {res}")
    
    bot.add_handler(CommandHandler("auth", auth_final))
    bot.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)], states={WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)], WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]}, fallbacks=[]))
    
    bot.run_polling(drop_pending_updates=True)
