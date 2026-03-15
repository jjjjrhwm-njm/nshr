import os
import subprocess
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("المعالجة السريعة بدأت... ⚡")
    input_path = "input.mp4"
    
    try:
        # تحميل الفيديو
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive(input_path)
        
        # معرفة مدة الفيديو باستخدام FFmpeg (أخف من MoviePy)
        cmd_duration = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration = float(subprocess.check_output(cmd_duration, shell=True))

        for start in range(0, int(duration), 50):
            output_filename = f"part_{start//50 + 1}.mp4"
            
            # قص الفيديو بدون رندرة (خفيف جداً على الرام)
            # -ss للبداية، -t للمدة، -c copy لنسخ الكوديك بدون ضغط
            cmd_cut = f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {output_filename}'
            subprocess.run(cmd_cut, shell=True)
            
            if os.path.exists(output_filename):
                with open(output_filename, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"الجزء {start//50 + 1}")
                os.remove(output_filename)

        await status_msg.edit_text("تم التقسيم بأقل استهلاك للذاكرة! ✅")
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.run_polling()
