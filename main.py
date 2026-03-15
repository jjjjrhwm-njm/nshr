import os
import logging
from moviepy.editor import VideoFileClip
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# إعداد السجلات
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("جاري المعالجة... 🚀")
    input_path = "input_video.mp4"
    
    try:
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive(input_path)
        
        video = VideoFileClip(input_path)
        duration = int(video.duration)
        
        for start in range(0, duration, 50):
            end = min(start + 50, duration)
            output_filename = f"part_{start//50 + 1}.mp4"
            
            clip = video.subclip(start, end)
            clip.write_videofile(output_filename, codec="libx264", audio_codec="aac", logger=None)
            
            with open(output_filename, 'rb') as v:
                await update.message.reply_video(video=v, caption=f"الجزء {start//50 + 1}")
            
            os.remove(output_filename)

        video.close()
        await status_msg.edit_text("تم بنجاح! ✅")
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")
    finally:
        if os.path.exists(input_path): os.remove(input_path)

if __name__ == '__main__':
    # بناء التطبيق بدون استخدام Updater بشكل يدوي لتفني الأخطاء
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    print("✅ Bot is Starting...")
    # تشغيل مباشر
    app.run_polling()
