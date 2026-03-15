import os
import subprocess
import logging
import asyncio
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler
)

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") # رقمك لكي يرسل لك البوت رسالة التشغيل

# الحالات الخاصة بالمحادثة المتسلسلة
WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)

# --- الجزء الأول: إرضاء سيرفر رندر + توثيق تيك توك ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running beautifully!"

# مسار توثيق تيك توك السحري 🎯
@app.route('/tiktok6twYohMgjNLIzC9S24nqHs3gXGwucVkL.txt')
def tiktok_verify():
    return "tiktok-developers-site-verification=6twYohMgjNLIzC9S24nqHs3gXGwucVkL"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    # إيقاف رسائل Flask المزعجة في السجلات
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port)

# --- الجزء الثاني: البوت الفعلي (المحادثة والتقسيم) ---

# 1. عند إرسال كلمة "نجم نشر"
async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ارسل المقطع 🎬")
    return WAITING_FOR_VIDEO

# 2. عند استلام الفيديو
async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # حفظ معرف الفيديو مؤقتاً في ذاكرة البوت
    context.user_data['video_file_id'] = update.message.video.file_id
    context.user_data['message_id'] = update.message.message_id
    await update.message.reply_text("ارسل العنوان الذي تريده 📝")
    return WAITING_FOR_TITLE

# 3. عند استلام العنوان والبدء بالقص
async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    await update.message.reply_text("تم الاستلام ✅ جاري التقسيم...")
    
    # استرجاع الفيديو من الذاكرة وتحميله
    file_id = context.user_data['video_file_id']
    msg_id = context.user_data['message_id']
    input_path = f"input_{msg_id}.mp4"
    
    new_file = await context.bot.get_file(file_id)
    await new_file.download_to_drive(input_path)
    
    try:
        # معرفة المدة باستخدام FFmpeg
        cmd_duration = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration_bytes = subprocess.check_output(cmd_duration, shell=True)
        duration = float(duration_bytes.decode('utf-8').strip())
        
        # القص والإرسال
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            output_filename = f"part_{part_num}_{msg_id}.mp4"
            
            # أمر القص السريع بدون رندرة
            cmd_cut = f'ffmpeg -ss {start} -t 50 -i {input_path} -c copy -y {output_filename}'
            subprocess.run(cmd_cut, shell=True)
            
            if os.path.exists(output_filename):
                # دمج العنوان مع رقم الجزء
                caption = f"{title} الجزء {part_num}"
                with open(output_filename, 'rb') as v:
                    await update.message.reply_video(video=v, caption=caption)
                os.remove(output_filename)

        await update.message.reply_text("تم تقسيم وإرسال جميع الأجزاء بنجاح! 🚀")
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text(f"حدث خطأ أثناء المعالجة: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        context.user_data.clear() # تفريغ الذاكرة
        
    return ConversationHandler.END

# 4. دالة الإلغاء في حال أراد المستخدم التراجع
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

# --- رسالة التشغيل التلقائية ---
async def post_init(application: ApplicationBuilder):
    if ADMIN_ID:
        try:
            await application.bot.send_message(chat_id=ADMIN_ID, text="🟢 السيرفر متصل! البوت جاهز للعمل يا نجم الإبداع.")
        except Exception as e:
            logging.error(f"لم أتمكن من إرسال رسالة البدء: {e}")

# --- إعداد وتشغيل البوت ---
def run_bot():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is missing!")
        return
    
    # إنشاء حلقة أحداث جديدة للخيط الفرعي
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # بناء التطبيق مع دالة البدء (post_init)
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # إعداد مدير المحادثة
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)]
        },
        fallbacks=[MessageHandler(filters.Regex("^الغاء$"), cancel)]
    )
    
    application.add_handler(conv_handler)
    logging.info("Bot is starting polling...")
    
    # الحل السحري لمشكلة الخيوط (stop_signals=None)
    application.run_polling(drop_pending_updates=True, stop_signals=None)

if __name__ == '__main__':
    # تشغيل البوت في مسار منفصل لكي لا يوقف سيرفر Flask
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # تشغيل سيرفر Flask على المسار الرئيسي
    run_flask()
