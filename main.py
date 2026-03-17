import os
import sys
import subprocess
import logging
import threading
import time
import requests
import arabic_reshaper
from flask import Flask
from pyrogram import Client, filters

# --- 🛑 قاتل النسخ القديمة (حماية السيرفر) 🛑 ---
time.sleep(10)

# --- إعداد السجلات ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- المتغيرات الأساسية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")

API_ID = 6
API_HASH = "eb06d4abfb49dc3eeb1aeb98ae0f581e"

app_flask = Flask(__name__)

# --- تحميل الخط العربي للمونتاج ---
FONT_FILE = "font.ttf"
if not os.path.exists(FONT_FILE):
    logger.info("جاري تحميل الخط العربي...")
    with open(FONT_FILE, 'wb') as f:
        f.write(requests.get("https://github.com/google/fonts/raw/main/ofl/cairo/Cairo-Bold.ttf").content)

# --- Flask Server لحماية رندر من النوم ---
@app_flask.route('/')
def home():
    return "Pyrogram Montage Bot is Live and Clean! 🟢"

def send_pulse():
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
        except:
            pass
        time.sleep(600)

# --- إعداد محرك Pyrogram (in_memory لمنع تعارض النسخ) ---
bot = Client(
    "montage_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True 
)

# --- الدالة المعدلة لمعالجة النص العربي (لحل مشكلة الكتابة الفضائية) ---
def prepare_arabic_text(text):
    # تشبيك الحروف العربية
    reshaped_text = arabic_reshaper.reshape(text)
    # عكس النص يدوياً لضمان ظهوره بشكل صحيح من اليمين لليسار في المونتاج
    reversed_text = reshaped_text[::-1]
    return reversed_text

user_states = {}

# --- أوامر البوت والمونتاج ---
@bot.on_message(filters.regex("^الغاء$"))
async def cancel(client, message):
    user_states.pop(message.chat.id, None)
    await message.reply_text("🚫 تم الإلغاء وتصفير الذاكرة بنجاح.")

@bot.on_message(filters.regex("^نجم نشر$"))
async def start_cmd(client, message):
    user_states[message.chat.id] = {"state": "WAITING_VIDEO"}
    await message.reply_text("🎬 أهلاً بك يا نجم الإبداع!\n\nأرسل لي **مقطع الفيديو** مباشرة هنا (مسموح حتى 2 جيجابايت)..\n\n*(أو أرسل `الغاء` للإيقاف في أي وقت)*")

@bot.on_message(filters.video | filters.document)
async def receive_video(client, message):
    chat_id = message.chat.id
    if user_states.get(chat_id, {}).get("state") == "WAITING_VIDEO":
        if message.video or (message.document and message.document.mime_type.startswith('video/')):
            user_states[chat_id]["msg"] = message
            user_states[chat_id]["state"] = "WAITING_TITLE"
            await message.reply_text("📝 ممتاز تم استلام المقطع! أرسل لي **عنوان الفيديو** الآن:\n\n*(مثال: مقطع تحفيزي)*")

@bot.on_message(filters.text & ~filters.command(["start", "help"]))
async def receive_title(client, message):
    chat_id = message.chat.id
    text = message.text
    
    if text == "الغاء": 
        return
        
    if user_states.get(chat_id, {}).get("state") == "WAITING_TITLE":
        original_title = text
        video_msg = user_states[chat_id]["msg"]
        
        status_msg = await message.reply_text("📥 جاري تحميل المقطع من تليجرام إلى السيرفر... (يتم استخدام أقصى سرعة)")
        
        user_states.pop(chat_id, None)
        input_path = f"{os.getcwd()}/input_{message.id}.mp4"
        
        try:
            await video_msg.download(file_name=input_path)
            await status_msg.edit_text("🔍 تم التحميل بنجاح! جاري حساب المدة وبدء المونتاج الآلي...")
            
            duration_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
            duration = float(subprocess.check_output(duration_cmd, shell=True).decode().strip())
            
            for start in range(0, int(duration), 50):
                part_num = (start // 50) + 1
                out_file = f"{os.getcwd()}/part_{part_num}_{message.id}.mp4"
                
                raw_title = f"{original_title} (الجزء {part_num})"
                safe_text = prepare_arabic_text(raw_title).replace("'", "\\'").replace(":", "\\:")
                
                await status_msg.edit_text(f"✂️ ✍️ جاري دمج وكتابة: '{raw_title}'...")
                
                # --- أمر المونتاج المعدّل (رفع النص للأعلى وإضافة خلفية سوداء واضحة) ---
                ffmpeg_cmd = (
                    f'ffmpeg -ss {start} -t 50 -i {input_path} '
                    f'-vf "drawtext=fontfile={FONT_FILE}:text=\'{safe_text}\':fontcolor=red:fontsize=w/12:x=(w-text_w)/2:y=10:box=1:boxcolor=black@0.5:boxborderw=5" '
                    f'-c:v libx264 -preset ultrafast -threads 2 -crf 28 -c:a aac -y {out_file}'
                )
                subprocess.run(ffmpeg_cmd, shell=True)
                
                if os.path.exists(out_file):
                    await status_msg.edit_text(f"📤 جاري إرسال (الجزء {part_num}) إليك...")
                    await client.send_video(chat_id, video=out_file, caption=f"✅ {raw_title}")
                    os.remove(out_file)

            await status_msg.edit_text("🎉 مبروك! تمت جميع عمليات المونتاج والإرسال، وتم تنظيف السيرفر بالكامل.")
            
        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ فني أثناء المعالجة: {e}")
        finally:
            if os.path.exists(input_path):
                os.remove(input_path)
            
# --- تشغيل البوت والسيرفر ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    logger.info("جاري تشغيل البوت...")
    bot.run()
