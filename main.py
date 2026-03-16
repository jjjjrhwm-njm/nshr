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
import firebase_admin
from firebase_admin import credentials, firestore

# إعداد السجلات لتتبع العمليات باحترافية
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- المتغيرات الأساسية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")
REDIRECT_URI = f"{BASE_URL}/callback"
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")

# مسارات فايربيس المعزولة (لحماية البوتات الأخرى)
FS_COLLECTION = "nshr_bot_metadata" 
FS_DOCUMENT = "tiktok_auth"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# --- تهيئة فايربيس الآمنة ---
db = None
try:
    FIREBASE_CONF = os.getenv("FIREBASE_CONF")
    if FIREBASE_CONF:
        if not firebase_admin._apps:
            cred = credentials.Certificate(json.loads(FIREBASE_CONF))
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 Firebase connected safely.")
except Exception as e:
    logger.error(f"🔴 Firebase Error: {e}")

# --- محرك التجديد التلقائي لتوكن تيك توك ---
def refresh_tiktok_token(r_token):
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "grant_type": "refresh_token", "refresh_token": r_token}
    try:
        res = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            db.collection(FS_COLLECTION).document(FS_DOCUMENT).set({
                'access_token': res['access_token'],
                'refresh_token': res.get('refresh_token', r_token)
            })
            return res['access_token']
    except: pass
    return None

# --- محرك الرفع الاحترافي ---
def upload_to_tiktok(video_path, caption):
    try:
        doc = db.collection(FS_COLLECTION).document(FS_DOCUMENT).get()
        if not doc.exists: return "❌ لا يوجد توثيق سحابي."
        
        auth_data = doc.to_dict()
        token = auth_data.get('access_token')

        def perform_upload(t):
            file_size = os.path.getsize(video_path)
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            init_body = {
                "post_info": {"title": caption, "privacy_level": "SELF_ONLY"},
                "source_info": {"source": "FILE_UPLOAD", "video_size": file_size, "chunk_size": file_size, "total_chunk_count": 1}
            }
            res_init = requests.post(init_url, headers={"Authorization": f"Bearer {t}", "Content-Type": "application/json"}, json=init_body)
            if res_init.status_code == 401: return "EXPIRED"
            
            data_init = res_init.json()
            if "data" not in data_init: return f"❌ فشل التهيئة: {data_init}"
            
            upload_url = data_init["data"]["upload_url"]
            with open(video_path, "rb") as f:
                requests.put(upload_url, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size-1}/{file_size}"}, data=f)
            return "✅ تم النشر بنجاح!"

        result = perform_upload(token)
        if result == "EXPIRED":
            new_token = refresh_tiktok_token(auth_data.get('refresh_token'))
            if new_token: return perform_upload(new_token)
        return result
    except Exception as e: return f"❌ خطأ: {e}"

# --- Flask Server ---
@app.route('/')
def home(): return "Bot Safe & Pulsing! 🟢"

@app.route(f'/{VERIFY_PATH}')
def verify(): return VERIFY_CONTENT

@app.route('/callback')
def callback():
    code = request.args.get('code')
    return f"<h1>✅ تم الربط!</h1><textarea rows='3' style='width:100%'>{code}</textarea>" if code else "Error"

def send_pulse():
    time.sleep(30)
    while True:
        try: requests.get(BASE_URL)
        except: pass
        time.sleep(600)

# --- Telegram Bot Logic ---

async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # فحص حالة تسجيل الدخول قبل البدء
    doc = db.collection(FS_COLLECTION).document(FS_DOCUMENT).get()
    if doc.exists:
        await update.message.reply_text("✅ حساب تيك توك الخاص بك (محفوظ) سحابياً وجاهز.\nالآن، ارسل المقطع المراد نشره 🎬")
        return WAITING_FOR_VIDEO
    else:
        await update.message.reply_text("⚠️ حسابك غير مسجل حالياً. يرجى إرسال /login لربط الحساب أولاً.")
        return ConversationHandler.END

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['v_id'] = update.message.video.file_id
    await update.message.reply_text("جميل جداً! الآن أرسل (عنوان المقطع) 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    status_msg = await update.message.reply_text("📥 (1/4) جاري سحب المقطع من سيرفرات تليجرام...")
    
    file_id = context.user_data['v_id']
    input_path = f"input_{update.message.message_id}.mp4"
    
    try:
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive(input_path)
        
        await status_msg.edit_text("🔍 (2/4) تم التحميل. جاري فحص مدة المقطع للبدء بالتقسيم...")
        duration = float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}", shell=True).decode().strip())
        
        # حلقة التقسيم والرفع (كل 50 ثانية)
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            out = f"part_{part_num}_{update.message.message_id}.mp4"
            
            # تنسيق العنوان المطلوب: (الجزء١)
            caption = f"{title} (الجزء{part_num})"
            
            await status_msg.edit_text(f"✂️ (3/4) جاري الآن معالجة وقص {caption}...")
            subprocess.run(f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {out}', shell=True)
            
            if os.path.exists(out):
                await update.message.reply_text(f"📤 (4/4) جاري رفع {caption} إلى حسابك في تيك توك...")
                
                # الرفع الفعلي
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                
                # إرسال الجزء للتليجرام للتأكيد
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"✅ {caption}\n📊 نتيجة النشر: {res_tk}")
                
                # حذف الجزء بعد الانتهاء لضمان نظافة السيرفر
                os.remove(out)

        await status_msg.edit_text("🎉 مبروك يا نجم الإبداع! تمت جميع العمليات بنجاح وتم النشر السحابي.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ فني أثناء المعالجة: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

async def post_init(application):
    """تنظيف شامل عند كل إقلاع للبوت"""
    for f in glob.glob("*.mp4"):
        try: os.remove(f)
        except: pass
    if ADMIN_ID:
        try: await application.bot.send_message(chat_id=ADMIN_ID, text="🚀 تم تشغيل البوت بنسخته النهائية.\n✅ السيرفر نظيف.\n✅ الربط بفايربيس مستقر.")
        except: pass

# --- التشغيل النهائي ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False), daemon=True).start()
    
    bot = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    bot.add_handler(CommandHandler("login", lambda u, c: u.message.reply_text("رابط التوثيق (للمرة الأولى فقط):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=f"https://www.tiktok.com/v2/auth/authorize/?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri={REDIRECT_URI}")]]))))
    
    async def auth_final(u, c):
        if not c.args: return
        res = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "code": c.args[0], "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            db.collection(FS_COLLECTION).document(FS_DOCUMENT).set({'access_token': res['access_token'], 'refresh_token': res.get('refresh_token')})
            await u.message.reply_text("✅ تم الحفظ السحابي الآمن والربط بنجاح!")
        else: await u.message.reply_text(f"❌ خطأ في الكود المرسل.")
    
    bot.add_handler(CommandHandler("auth", auth_final))
    bot.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]
        }, fallbacks=[]
    ))
    
    bot.run_polling(drop_pending_updates=True)
