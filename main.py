import os
import sys
import subprocess
import logging
import threading
import time
import requests
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

# --- Flask Server لحماية رندر من النوم ---
@app_flask.route('/')
def home():
    return "Fast Splitter Bot is Live! 🟢"

def send_pulse():
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
        except:
            pass
        time.sleep(600)

# --- إعداد محرك Pyrogram ---
bot = Client(
    "montage_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True 
)

user_states = {}

# --- أوامر البوت والتقسيم الصاروخي ---
@bot.on_message(filters.regex("^الغاء$"))
async def cancel(client, message):
    user_states.pop(message.chat.id, None)
    await message.reply_text("🚫 تم الإلغاء وتصفير الذاكرة بنجاح.")

@bot.on_message(filters.regex("^نجم نشر$"))
async def start_cmd(client, message):
    user_states[message.chat.id] = {"state": "WAITING_VIDEO"}
    await message.reply_text("🎬 أهلاً بك يا بطل!\n\nأرسل لي **مقطع الفيديو** مباشرة هنا للتقسيم السريع (مسموح حتى 2 جيجابايت)..\n\n*(أو أرسل `الغاء` للإيقاف في أي وقت)*")

@bot.on_message(filters.video | filters.document)
async def process_video(client, message):
    chat_id = message.chat.id
    if user_states.get(chat_id, {}).get("state") == "WAITING_VIDEO":
        if message.video or (message.document and message.document.mime_type.startswith('video/')):
            
            status_msg = await message.reply_text("📥 جاري استلام المقطع من تليجرام... (بأقصى سرعة)")
            
            # تصفير حالة المستخدم فوراً للبدء بالعمل
            user_states.pop(chat_id, None)
            input_path = f"{os.getcwd()}/input_{message.id}.mp4"
            
            try:
                # 1. التحميل
                await message.download(file_name=input_path)
                await status_msg.edit_text("🔍 تم التحميل! جاري القص الصاروخي...")
                
                # 2. حساب المدة
                duration_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
                duration = float(subprocess.check_output(duration_cmd, shell=True).decode().strip())
                
                # 3. القص السريع (بدون رندرة - يستغرق ثواني فقط)
                for start in range(0, int(duration), 50):
                    part_num = (start // 50) + 1
                    out_file = f"{os.getcwd()}/part_{part_num}_{message.id}.mp4"
                    
                    await status_msg.edit_text(f"✂️ جاري قص (الجزء {part_num})...")
                    
                    # استخدمنا (-c copy) للقص الفوري بدون استهلاك معالج السيرفر
                    ffmpeg_cmd = f'ffmpeg -ss {start} -i {input_path} -t 50 -c copy -y {out_file}'
                    subprocess.run(ffmpeg_cmd, shell=True)
                    
                    # 4. الإرسال والحذف الفوري
                    if os.path.exists(out_file):
                        await status_msg.edit_text(f"📤 جاري إرسال (الجزء {part_num}) إليك...")
                        await client.send_video(chat_id, video=out_file, caption=f"✅ الجزء {part_num}")
                        os.remove(out_file)

                await status_msg.edit_text("🎉 مبروك! تمت جميع عمليات التقسيم والإرسال بنجاح، وتم تنظيف السيرفر بالكامل.")
                
            except Exception as e:
                await message.reply_text(f"❌ حدث خطأ فني أثناء المعالجة: {e}")
            finally:
                # الكنس النهائي
                if os.path.exists(input_path):
                    os.remove(input_path)
            
# --- تشغيل البوت والسيرفر ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    logger.info("جاري تشغيل البوت...")
    bot.run()
