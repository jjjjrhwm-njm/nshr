import os
import subprocess
import logging
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- الجزء الأول: إرضاء سيرفر رندر (فتح بورت وهمي) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running beautifully!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- الجزء الثاني: البوت الفعلي (تقسيم الفيديو) ---
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("بدأ القص السريع... ⚡")
    input_path = f"input_{update.message.message_id}.mp4"
    
    try:
        # 1. تحميل الفيديو
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive(input_path)
        
        # 2. معرفة المدة باستخدام FFmpeg
        cmd_duration = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration_bytes = subprocess.check_output(cmd_duration, shell=True)
        duration = float(duration_bytes.decode('utf-8').strip())
        
        # 3. القص والإرسال
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            output_filename = f"part_{part_num}_{update.message.message_id}.mp4"
            
            # أمر القص السريع بدون رندرة
            cmd_cut = f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {output_filename}'
            subprocess.run(cmd_cut, shell=True)
            
            if os.path.exists(output_filename):
                with open(output_filename, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"الجزء {part_num}")
                os.remove(output_filename)

        await status_msg.edit_text("تم التقسيم بنجاح! ✅")
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await status_msg.edit_text(f"حدث خطأ: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

def run_bot():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is missing!")
        return
    
    # يجب إنشاء حدث جديد للبوت لأنه يعمل في خيط (Thread) منفصل
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    logging.info("Bot is starting polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    # تشغيل البوت في مسار منفصل لكي لا يوقف سيرفر Flask
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # تشغيل سيرفر Flask على المسار الرئيسي (لكي يظل رندر سعيداً)
    run_flask()
