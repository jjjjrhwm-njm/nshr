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

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- المتغيرات الأساسية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")
REDIRECT_URI = f"{BASE_URL}/callback"
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# ذاكرة مؤقتة لاختبار الرفع
memory_db = {"access_token": None, "refresh_token": None}

# --- محرك الرفع الاحترافي لتيك توك ---
def upload_to_tiktok(video_path, caption):
    try:
        token = memory_db.get("access_token")
        if not token: return "❌ لا يوجد توثيق. ارسل /login"

        file_size = os.path.getsize(video_path)
        init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
        init_body = {
            "post_info": {"title": caption, "privacy_level": "SELF_ONLY"},
            "source_info": {"source": "FILE_UPLOAD", "video_size": file_size, "chunk_size": file_size, "total_chunk_count": 1}
        }
        res_init = requests.post(init_url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=init_body)
        
        if res_init.status_code == 401: return "❌ انتهت صلاحية التوكن (EXPIRED). يرجى التوثيق مجدداً."
        
        data_init = res_init.json()
        if "data" not in data_init: return f"❌ فشل التهيئة: {data_init}"
        
        upload_url = data_init["data"]["upload_url"]
        with open(video_path, "rb") as f:
            headers_put = {"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{file_size-1}/{file_size}"}
            r_put = requests.put(upload_url, headers=headers_put, data=f)
        
        return "✅ تم الرفع بنجاح!" if r_put.status_code in (200, 201, 206) else f"❌ فشل الرفع: {r_put.text}"
    except Exception as e: return f"❌ خطأ تقني: {e}"

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

# --- أوامر التليجرام والنشر ---
async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not memory_db["access_token"]:
        await update.message.reply_text("⚠️ أنت غير مسجل الدخول في تيك توك. يرجى إرسال /login أولاً للتوثيق.")
        return ConversationHandler.END
        
    await update.message.reply_text("ارسل المقطع 🎬")
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['v_id'] = update.message.video.file_id
    await update.message.reply_text("ارسل العنوان 📝")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_title = update.message.text
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
                # الرفع لتيك توك
                res_tk = await asyncio.to_thread(upload_to_tiktok, out, caption)
                
                # إرسال المقطع للتأكيد
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

# --- التشغيل ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False), daemon=True).start()
    
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    
    bot.add_handler(CommandHandler("login", lambda u, c: u.message.reply_text("رابط التوثيق:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ربط حساب تيك توك", url=f"https://www.tiktok.com/v2/auth/authorize/?client_key={CLIENT_KEY}&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri={REDIRECT_URI}")]]))))
    
    async def auth_final(u, c):
        if not c.args: return
        res = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "code": c.args[0], "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" in res:
            memory_db["access_token"] = res['access_token']
            memory_db["refresh_token"] = res.get('refresh_token')
            await u.message.reply_text("✅ تم الربط مؤقتاً! جرب محرك النشر الآن.")
        else: await u.message.reply_text(f"❌ كود خاطئ أو منتهي الصلاحية: {res}")
    
    bot.add_handler(CommandHandler("auth", auth_final))
    bot.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]
        }, fallbacks=[]
    ))
    
    bot.run_polling(drop_pending_updates=True)
