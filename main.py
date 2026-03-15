import os
from moviepy.editor import VideoFileClip
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# سحب المفاتيح من متغيرات البيئة في رندر تلقائياً
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # إشعار المستخدم بالبدء
    msg = await update.message.reply_text("جاري استلام الفيديو ومعالجته... انتظر قليلاً يا نجم الإبداع 🚀")
    
    try:
        # تحميل الفيديو من تلجرام
        video_file = await update.message.video.get_file()
        input_path = "input_video.mp4"
        await video_file.download_to_drive(input_path)
        
        # فتح الفيديو وحساب مدته
        video = VideoFileClip(input_path)
        duration = int(video.duration)
        
        # تقسيم الفيديو إلى قطع كل قطعة 50 ثانية
        for start in range(0, duration, 50):
            end = min(start + 50, duration)
            part_num = start // 50 + 1
            output_filename = f"part_{part_num}.mp4"
            
            # قص المقطع وحفظه بجودة مناسبة للسيرفر
            clip = video.subclip(start, end)
            clip.write_videofile(output_filename, codec="libx264", audio_codec="aac", temp_audiofile='temp-audio.m4a', remove_temp=True)
            
            # إرسال المقطع المقصوص إليك في تلجرام
            with open(output_filename, 'rb') as v:
                await update.message.reply_video(video=v, caption=f"الجزء رقم {part_num}")
            
            # حذف المقطع بعد إرساله لتوفير مساحة السيرفر
            os.remove(output_filename)

        video.close()
        os.remove(input_path)
        await msg.edit_text("تم تقسيم الفيديو بنجاح! ميزة الرفع التلقائي لتيك توك قيد التطوير البرمجي الآن.")

    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء المعالجة: {str(e)}")

if __name__ == '__main__':
    # تشغيل البوت بنظام Polling
    if not BOT_TOKEN:
        print("خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.VIDEO, handle_video))
        print("البوت يعمل الآن ومستعد لتقسيم الفيديوهات...")
        app.run_polling()
