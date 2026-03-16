import os
import subprocess
import logging
import asyncio
import threading
import time
import requests
import json
import glob
import ast
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler, CommandHandler
)
import firebase_admin
from firebase_admin import credentials, firestore

# إعداد السجلات
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

FS_COLLECTION = "nshr_bot_metadata" 
FS_DOCUMENT = "tiktok_auth"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# --- تهيئة فايربيس القوية (مع حل مشكلة رندر) ---
db = None
try:
    FIREBASE_CONF_STR = os.getenv("FIREBASE_CONF")
    if FIREBASE_CONF_STR:
        try: cred_dict = json.loads(FIREBASE_CONF_STR)
        except json.JSONDecodeError: cred_dict = ast.literal_eval(FIREBASE_CONF_STR)
        
        if "private_key" in cred_dict:
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 Firebase connected perfectly.")
except Exception as e:
    logger.error(f"🔴 Firebase Error: {e}")

# --- تجديد التوكن ---
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

# --- محرك الرفع ---
def upload_to_tiktok(video_path, caption):
    try:
        if not db: return "❌ قاعدة البيانات مفصولة."
        doc = db.collection(FS_COLLECTION).document(FS_DOCUMENT).get()
        if not doc.exists: return "❌ لا يوجد توثيق."
        
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
            if "data" not in data_init: return f"❌ فشل التهيئة."
            
            upload_url = data_init["data"]["upload_url"]
            with open(video_path, "rb") as f:
                requests.put(upload_url, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size-1}/{file_size}"}, data=f)
            return "✅ تم الرفع بنجاح!"

        result = perform_upload(token)
        if result == "EXPIRED":
            new_token = refresh_tiktok_token(auth_data.get('refresh_token'))
            if new_token: return perform_upload(new_token)
        return result
    except Exception as e: return f"❌ خطأ: {e}"

# --- Flask Server ---
@app.route('/')
def home(): return "Bot is Live! 🟢"

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

# --- أوامر التليجرام (الترتيب الذي طلبته بالضبط) ---
async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("❌ البوت غير متصل بقاعدة البيانات. راجع السجلات.")
        return ConversationHandler.END
        
    doc = db.collection(FS_COLLECTION).document(FS_DOCUMENT).get()
    if doc.exists:
        await update.message.reply_text("ارسل المقطع 🎬")
        return WAITING_FOR_VIDEO
    else:
        await update.message.reply_text("⚠️ أنت غير مسجل الدخول في تيك توك. يرجى إرسال /login أولاً.")
        return ConversationHandler.END

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['v_id'] = update.message.video.file_id
    await update.message.reply_text("ارسل العنوان 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_title = update.message.text
    # رسالة تحديث واحدة فقط حتى لا تزعج الشات
    status_msg = await update.message.reply_text("📥 جاري تحميل المقطع من تليجرام...")
    
    file_id = context.user_data['v_id']
    input_path = f"input_{update.message.message_id}.mp4"
    
    try:
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive(input_path)
        
        await status_msg.edit_text("🔍 تم التحميل! جاري فحص وتقسيم المقطع...")
        duration = float(subprocess.check_output(f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}", shell=True).decode().strip())
        
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            out = f"part_{part_num}_{update.message.message_id}.mp4"
            
            # الإضافة التلقائية للعنوان
            caption = f"{original_title} (الجزء {part_num})"
            
            await status_msg.edit_text(f"✂️ جاري قص: {caption}...")
            subprocess.run(f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {out}', shell=True)
            
            if os.path.exists(out):
                await status_msg.edit_text(f"📤 جاري رفع: {caption} إلى تيك توك...")
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                
                # إرسال المقطع للتأكيد لك
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"✅ {caption}\n📊 الحالة: {res_tk}")
                os.remove(out)

        await status_msg.edit_text("🎉 مبروك! تمت جميع العمليات وتم النشر بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ فني: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
    return ConversationHandler.END

# --- رسالة الإقلاع الذكية للمطور ---
async def post_init(application):
    for f in glob.glob("*.mp4"):
        try: os.remove(f)
        except: pass
        
    if ADMIN_ID:
        if db:
            doc = db.collection(FS_COLLECTION).document(FS_DOCUMENT).get()
            tiktok_status = "✅ مسجل الدخول وجاهز للنشر" if doc.exists else "⚠️ غير مسجل! ارسل /login للربط"
            msg = f"🚀 اشتغل البوت بنجاح!\n\n🗄️ قاعدة البيانات: متصلة ✅\n🎵 تيك توك: {tiktok_status}"
        else:
            msg = "🚀 اشتغل البوت، لكن:\n\n🗄️ قاعدة البيانات: مفصولة ❌ (يوجد خطأ في كود Firebase في رندر)"
            
        try: await application.bot.send_message(chat_id=ADMIN_ID, text=msg)
        except: pass

# --- التشغيل ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False), daemon=True).start()
    
    bot = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    bot.add_handler(CommandHandler("login", lambda u, c: u.message.reply_text("رابط التوثيق:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=f"https://www.tiktok.com/v2/auth/authorize/?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri={REDIRECT_URI}")]]))))
    
    async def auth_final(u, c):
        if not db:
            await u.message.reply_text("❌ البوت غير متصل بقاعدة البيانات.")
            return
        if not c.args: return
        res = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "code": c.args[0], "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            db.collection(FS_COLLECTION).document(FS_DOCUMENT).set({'access_token': res['access_token'], 'refresh_token': res.get('refresh_token')})
            await u.message.reply_text("✅ تم الربط! حسابك الآن محفوظ للأبد.")
        else: await u.message.reply_text("❌ كود خاطئ أو منتهي الصلاحية.")
    
    bot.add_handler(CommandHandler("auth", auth_final))
    bot.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]
        }, fallbacks=[]
    ))
    
    bot.run_polling(drop_pending_updates=True)
