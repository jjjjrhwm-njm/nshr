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
# مكتبات فايربيس
import firebase_admin
from firebase_admin import credentials, firestore

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- المتغيرات ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")
REDIRECT_URI = f"{BASE_URL}/callback"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)

app = Flask(__name__)

# --- تهيئة فايربيس للذاكرة الدائمة ---
db = None
FIREBASE_CONF = os.getenv("FIREBASE_CONF")
try:
    if FIREBASE_CONF and not firebase_admin._apps:
        cred_dict = json.loads(FIREBASE_CONF)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 تم الاتصال بـ Firebase بنجاح! الذاكرة الدائمة مفعلة.")
except Exception as e:
    logger.error(f"🔴 خطأ في الاتصال بـ Firebase: {e}")

# --- Flask مسارات السيرفر ---
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
        return f"<h1>✅ تم الربط!</h1><p>الكود:</p><textarea rows='4' cols='50'>{code}</textarea><p>انسخ الكود وأرسله للبوت هكذا: <br><b>/auth الكود</b></p>"
    return "<h1>❌ فشل الربط</h1>"

def send_pulse():
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
        except: pass
        time.sleep(600)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# --- نظام توثيق تيك توك ---
async def login_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    auth_url = (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish"
        f"&response_type=code&redirect_uri={REDIRECT_URI}"
    )
    keyboard = [[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=auth_url)]]
    await update.message.reply_text("هذه آخر مرة ستحتاج فيها للربط بإذن الله، اضغط هنا:", reply_markup=InlineKeyboardMarkup(keyboard))

async def auth_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ اكتب /auth ثم مسافة ثم الكود.")
        return

    code = context.args[0]
    msg = await update.message.reply_text("⏳ جاري استخراج وتشفير مفاتيح الدخول الدائمة...")

    url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }

    try:
        res = requests.post(url, headers=headers, data=data).json()
        if "access_token" in res and "refresh_token" in res:
            # حفظ المفتاحين في فايربيس للأبد
            if db:
                db.collection('tiktok_config').document('auth').set({
                    'access_token': res['access_token'],
                    'refresh_token': res['refresh_token']
                })
            await msg.edit_text("✅ مبروك! تم حفظ الدخول بشكل دائم في السحابة. لن يطلب منك البوت تسجيل الدخول مرة أخرى! 🚀🎬")
        else:
            await msg.edit_text(f"❌ فشل السحب (الكود منتهي). استخرج كود جديد بـ /login \nالتفاصيل: {res}")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

# --- محرك التجديد التلقائي (السري) ---
def auto_refresh_token(refresh_token):
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    try:
        res = requests.post(url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data).json()
        if "access_token" in res:
            if db:
                db.collection('tiktok_config').document('auth').set({
                    'access_token': res['access_token'],
                    'refresh_token': res['refresh_token']
                })
            return res['access_token']
    except Exception as e:
        logger.error(f"Failed to auto-refresh token: {e}")
    return None

# --- محرك الرفع إلى تيك توك ---
def upload_to_tiktok(video_path, caption):
    try:
        access_token = None
        refresh_token = None
        
        # جلب المفاتيح من فايربيس
        if db:
            doc = db.collection('tiktok_config').document('auth').get()
            if doc.exists:
                data = doc.to_dict()
                access_token = data.get('access_token')
                refresh_token = data.get('refresh_token')
                
        if not access_token:
            return "❌ خطأ: لم أجد تصريح الدخول. أرسل /login لربط الحساب للمرة الأولى والأخيرة."
            
        file_size = os.path.getsize(video_path)
        
        # دالة الرفع الداخلية
        def do_upload(token):
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            init_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
            init_data = {
                "post_info": {"title": caption, "privacy_level": "SELF_ONLY", "disable_duet": False, "disable_comment": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": file_size, "chunk_size": file_size, "total_chunk_count": 1}
            }
            res_init = requests.post(init_url, headers=init_headers, json=init_data)
            
            # إذا انتهى التوكن، تيك توك سيرد بخطأ 401
            if res_init.status_code == 401:
                return "EXPIRED"
                
            init_response = res_init.json()
            if "data" not in init_response or "upload_url" not in init_response["data"]:
                return f"❌ فشل تهيئة الرفع: {init_response}"
                
            upload_url = init_response["data"]["upload_url"]
            with open(video_path, "rb") as f:
                video_bytes = f.read()
                
            upload_headers = {"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size-1}/{file_size}"}
            res_upload = requests.put(upload_url, headers=upload_headers, data=video_bytes)
            
            if res_upload.status_code in (200, 201, 206):
                return "✅ تم الرفع بنجاح لتيك توك! 🚀"
            else:
                return f"❌ فشل رفع الملف: {res_upload.text}"

        # المحاولة الأولى للرفع
        result = do_upload(access_token)
        
        # إذا انتهت صلاحية المفتاح الأساسي، نجدده تلقائياً ونحاول مرة ثانية!
        if result == "EXPIRED" and refresh_token:
            logger.info("Token expired. Auto-refreshing...")
            new_token = auto_refresh_token(refresh_token)
            if new_token:
                return do_upload(new_token)
            else:
                return "❌ انتهت صلاحية الجلسة بالكامل. تحتاج إرسال /login للتجديد."
                
        return result
            
    except Exception as e:
        return f"❌ خطأ برمجي: {e}"

# --- التقسيم والنشر المزدوج ---
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
    status_msg = await update.message.reply_text("✅ جاري المعالجة والتقسيم والنشر التلقائي...")
    
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
                
                with open(out, 'rb') as v:
                    await update.message.reply_video(video=v, caption=caption)
                
                await update.message.reply_text(f"⏳ جاري الرفع التلقائي لتيك توك (الجزء {part_num})...")
                upload_result = await asyncio.to_thread(upload_to_tiktok, out, caption)
                await update.message.reply_text(f"📊 نتيجة تيك توك:\n{upload_result}")
                
                os.remove(out)

        await status_msg.edit_text("✅ تمت جميع العمليات بنجاح! 🚀")
        
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ فني: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)
        context.user_data.clear()
        
    return ConversationHandler.END

# --- التشغيل ---
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
