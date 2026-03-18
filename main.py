import os
import sys
import subprocess
import logging
import threading
import time
import requests
import glob
from flask import Flask, send_from_directory
from pyrogram import Client, filters

# --- 🛑 قاتل النسخ القديمة ---
time.sleep(10)

# --- إعداد السجلات ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- المتغيرات الأساسية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
# تأكدنا أن الرابط ما يكون في نهايته شرطة مائلة للروابط المباشرة
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com").rstrip('/')

API_ID = 6
API_HASH = "eb06d4abfb49dc3eeb1aeb98ae0f581e"

# --- إعداد سيرفر الروابط المباشرة (Flask) ---
app_flask = Flask(__name__)
os.makedirs("downloads", exist_ok=True) # إنشاء مجلد التنزيلات

@app_flask.route('/')
def home():
    return "Fast Splitter Bot with Direct Links is Live! 🟢"

# مسار تحميل الملفات من الروابط
@app_flask.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('downloads', filename, as_attachment=True)

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

@bot.on_message(filters.regex("^تنظيف$"))
async def clean_files(client, message):
    # أمر جديد لمسح جميع الملفات من السيرفر بضغطة زر
    files = glob.glob("downloads/*")
    for f in files:
        try:
            os.remove(f)
        except:
            pass
    await message.reply_text("🧹 تم مسح جميع الملفات والروابط القديمة من السيرفر بنجاح! المساحة الآن فارغة 100%.")

@bot.on_message(filters.regex("^نجم نشر$"))
async def start_cmd(client, message):
    user_states[message.chat.id] = {"state": "WAITING_VIDEO"}
    await message.reply_text("🎬 أهلاً بك يا بطل!\n\nأرسل لي **مقطع الفيديو** مباشرة هنا (مسموح حتى 2 جيجابايت)..\n\n*(أو أرسل `الغاء` للإيقاف)*")

@bot.on_message(filters.video | filters.document)
async def process_video(client, message):
    chat_id = message.chat.id
    if user_states.get(chat_id, {}).get("state") == "WAITING_VIDEO":
        if message.video or (message.document and message.document.mime_type.startswith('video/')):
            user_states[chat_id]["msg"] = message
            user_states[chat_id]["state"] = "WAITING_DURATION"
            await message.reply_text("⏱️ ممتاز! كم تريد مدة الجزء الواحد **بالثواني**؟\n*(مثلاً أرسل: 50 أو 60 أو 120)*")

@bot.on_message(filters.text & ~filters.command(["start", "help"]))
async def handle_text(client, message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    # تجاهل الأوامر الأساسية عشان ما تتداخل
    if text in ["الغاء", "تنظيف", "نجم نشر"]: 
        return
        
    state = user_states.get(chat_id, {}).get("state")
    
    # 1. استقبال مدة القص
    if state == "WAITING_DURATION":
        if not text.isdigit() or int(text) <= 0:
            await message.reply_text("❌ أرقام فقط يا غالي! أرسل رقماً صحيحاً مثل 50.")
            return
        user_states[chat_id]["duration"] = int(text)
        user_states[chat_id]["state"] = "WAITING_METHOD"
        await message.reply_text("📦 كيف تفضل استلام المقاطع المقطصة؟\n\nأرسل كلمة `رابط` (للتحميل السريع عبر المتصفح)\nأو أرسل كلمة `تليجرام` (لإرسالها كفيديو هنا)")
        return
        
    # 2. استقبال طريقة التوصيل وبدء العمل
    if state == "WAITING_METHOD":
        if text not in ["رابط", "تليجرام"]:
            await message.reply_text("❌ خيار غير صحيح! أرسل إما `رابط` أو `تليجرام` (بدون مسافات إضافية).")
            return
            
        method = text
        video_msg = user_states[chat_id]["msg"]
        split_duration = user_states[chat_id]["duration"]
        
        status_msg = await message.reply_text(f"📥 جاري استلام المقطع من تليجرام...")
        user_states.pop(chat_id, None) # تصفير الحالة
        
        input_path = f"downloads/input_{message.id}.mp4"
        
        try:
            # التحميل
            await video_msg.download(file_name=input_path)
            await status_msg.edit_text(f"🔍 تم التحميل! جاري القص السريع كل ({split_duration} ثانية)...")
            
            # حساب المدة
            duration_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
            duration = float(subprocess.check_output(duration_cmd, shell=True).decode().strip())
            
            # القص الصاروخي
            for start in range(0, int(duration), split_duration):
                part_num = (start // split_duration) + 1
                out_filename = f"part_{part_num}_{message.id}.mp4"
                out_file = f"downloads/{out_filename}"
                
                await status_msg.edit_text(f"✂️ جاري قص (الجزء {part_num})...")
                
                ffmpeg_cmd = f'ffmpeg -ss {start} -i {input_path} -t {split_duration} -c copy -y {out_file}'
                subprocess.run(ffmpeg_cmd, shell=True)
                
                if os.path.exists(out_file):
                    if method == "تليجرام":
                        await status_msg.edit_text(f"📤 جاري إرسال (الجزء {part_num}) إليك...")
                        await client.send_video(chat_id, video=out_file, caption=f"✅ الجزء {part_num}")
                        os.remove(out_file) # مسح فوري
                    else:
                        # إنشاء الرابط المباشر
                        download_link = f"{BASE_URL}/download/{out_filename}"
                        await message.reply_text(f"✅ (الجزء {part_num}) جاهز!\n🔗 للتحميل السريع اضغط الرابط أدناه:\n{download_link}")

            # رسالة الختام حسب الطريقة
            if method == "رابط":
                await status_msg.edit_text("🎉 مبروك! تمت جميع عمليات التقسيم وصناعة الروابط.\n\n⚠️ **تنبيه هام:** المقاطع الآن محفوظة في السيرفر. بعد أن تنتهي من تحميلها جميعاً إلى جوالك، أرسل كلمة `تنظيف` لمسحها وتفريغ السيرفر!")
            else:
                await status_msg.edit_text("🎉 مبروك! تمت جميع عمليات التقسيم والإرسال بنجاح، وتم تنظيف السيرفر بالكامل.")
                
        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ فني أثناء المعالجة: {e}")
        finally:
            # مسح المقطع الأساسي دائماً لتوفير المساحة
            if os.path.exists(input_path):
                os.remove(input_path)
            
# --- تشغيل البوت والسيرفر ---
if __name__ == '__main__':
    threading.Thread(target=send_pulse, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app_flask.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    logger.info("جاري تشغيل البوت...")
    bot.run()
