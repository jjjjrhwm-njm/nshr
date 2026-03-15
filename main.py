import os
import asyncio
import logging
from moviepy.editor import VideoFileClip
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# إعداد السجلات (Logs) لمراقبة الأخطاء في Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# سحب التوكن من متغيرات البيئة التي وضعتها في رندر
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # إشعار المستخدم بالبدء
    status_msg = await update.message.reply_text("جاري استلام الفيديو ومعالجته... انتظر قليلاً يا نجم الإبداع 🚀")
    
    input_path = "input_video.mp4"
    
    try:
        # 1. تحميل الفيديو من تلجرام
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive(input_path)
        
        # 2. معالجة الفيديو باستخدام MoviePy
        video = VideoFileClip(input_path)
        duration = int(video.duration)
        
        # 3. تقسيم الفيديو إلى قطع (كل قطعة 50 ثانية)
        for start in range(0, duration, 50):
            end = min(start + 50, duration)
            part_num = (start // 50) + 1
            output_filename = f"part_{part_num}.mp4"
            
            # قص المقطع
            clip = video.subclip(start, end)
            
            # حفظ المقطع (إعدادات خفيفة لتناسب رندر)
            clip.write_videofile(
                output_filename, 
                codec="libx264", 
                audio_codec="aac", 
                temp_audiofile=f'temp_audio_{part_num}.m4a', 
                remove_temp=True,
                fps=24,
                logger=None # لتقليل الرسائل في الـ Logs
            )
            
            # 4. إرسال المقطع المقصوص للمستخدم
            with open(output_filename, 'rb') as v:
                await update.message.reply_video(
                    video=v, 
                    caption=f"✅ الجزء رقم {part_num}\nمدة المقطع: {int(end-start)} ثانية"
                )
            
            # حذف المقطع فوراً لتوفير مساحة السيرفر
            if os.path.exists(output_filename):
                os.remove(output_filename)

        video.close()
        await status_msg.edit_text("تم تقسيم الفيديو بنجاح! ميزة الرفع التلقائي لتيك توك قيد البرمجة حالياً.")

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        await update.message.reply_text(f"حدث خطأ فني: {str(e)}")
    
    finally:
        # تنظيف الملف الأصلي
        if os.path.exists(input_path):
            os.remove(input_path)

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("❌ Error: No BOT_TOKEN found! Make sure to add it in Render Environment Variables.")
    else:
        # بناء التطبيق وتشغيله
        print("✅ Bot is starting...")
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # إضافة معالج الفيديوهات (فقط الفيديوهات)
        app.add_handler(MessageHandler(filters.VIDEO, handle_video))
        
        # تشغيل البوت
        app.run_polling(drop_pending_updates=True)
