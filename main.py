import os
import subprocess
import logging
import asyncio
import threading
import time
import requests
import yt_dlp
import arabic_reshaper
from bidi.algorithm import get_display
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, filters,
    ConversationHandler
)

# --- إعداد السجلات لمتابعة عمل السيرفر ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- المتغيرات الأساسية ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://nshr-6u7f.onrender.com")

WAITING_FOR_URL, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# --- تحميل الخط العربي تلقائياً (لكتابة العنوان على الفيديو) ---
FONT_FILE = "font.ttf"
def download_font():
    if not os.path.exists(FONT_FILE):
        logger.info("جاري تحميل الخط العربي...")
        font_url = "https://github.com/google/fonts/raw/main/ofl/cairo/Cairo-Bold.ttf"
        try:
            with open(FONT_FILE, 'wb') as f:
                f.write(requests.get(font_url).content)
        except Exception as e:
            logger.error(f"خطأ في تحميل الخط: {e}")

download_font()

# --- Flask Server (لإبقاء رندر متيقظاً 24 ساعة) ---
@app.route('/')
def home():
    return "Montage Bot is Live and Clean! 🟢"

def send_pulse():
    time.sleep(30)
    while True:
        try:
            requests.get(BASE_URL)
        except:
            pass
        time.sleep(600)

# --- معالجة النص العربي ليظهر متصلاً وصحيحاً في المونتاج ---
def prepare_arabic_text(text):
    reshaped_text = arabic_reshaper.reshape(text)
    bidi_text = get_display(reshaped_text)
    return bidi_text

# --- أوامر التليجرام ونظام المونتاج ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 تم الإلغاء بنجاح. تم تنظيف ذاكرة البوت بالكامل.")
    context.user_data.clear()
    return ConversationHandler.END

async def start_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "الغاء":
        return await cancel(update, context)
        
    await update.message.reply_text("🔗 أهلاً بك في مصنع المونتاج!\n\nأرسل لي **رابط الفيديو** الآن..\n\n*(أو أرسل `الغاء` للإيقاف في أي وقت)*", parse_mode="Markdown")
    return WAITING_FOR_URL

async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "الغاء":
        return await cancel(update, context)
    
    context.user_data['v_url'] = text
    await update.message.reply_text("📝 ممتاز! أرسل لي **عنوان المقطع** الآن:\n*(مثال: فيلم السهرة)*\n\n*(أو أرسل `الغاء`)*", parse_mode="Markdown")
    return WAITING_FOR_TITLE

async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "الغاء":
        return await cancel(update, context)
    
    original_title = text
    video_url = context.user_data['v_url']
    status_msg = await update.message.reply_text("📥 جاري سحب الفيديو من الرابط... (الرجاء الانتظار)")
    
    input_path = f"input_{update.message.message_id}.mp4"
    
    try:
        # 1. تحميل الفيديو بأسرع طريقة ممكنة
        ydl_opts = {'outtmpl': input_path, 'format': 'best'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(ydl.download, [video_url])
            
        await status_msg.edit_text("🔍 تم السحب بنجاح! جاري حساب المدة وبدء المونتاج الآلي...")
        
        # 2. استخراج مدة الفيديو الكلية
        duration_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {input_path}"
        duration_str = subprocess.check_output(duration_cmd, shell=True).decode().strip()
        duration = float(duration_str)
        
        # 3. التقسيم كل 50 ثانية والكتابة على الفيديو
        for start in range(0, int(duration), 50):
            part_num = (start // 50) + 1
            out_file = f"part_{part_num}_{update.message.message_id}.mp4"
            
            # تجهيز العنوان مع رقم الجزء (مثال: فيلم السهرة (الجزء 1))
            raw_title = f"{original_title} (الجزء {part_num})"
            arabic_ready_text = prepare_arabic_text(raw_title)
            # حماية الكود من الرموز الخاصة في العنوان
            safe_text = arabic_ready_text.replace("'", "\\'").replace(":", "\\:")
            
            await status_msg.edit_text(f"✂️ ✍️ جاري دمج وكتابة: '{raw_title}'\n*(عملية المونتاج تحتاج وقت، اترك البوت يعمل براحته)*...")
            
            # أمر ffmpeg للقص السريع وكتابة النص باللون الأحمر في أعلى المنتصف
            ffmpeg_cmd = (
                f'ffmpeg -ss {start} -t 50 -i {input_path} '
                f'-vf "drawtext=fontfile={FONT_FILE}:text=\'{safe_text}\':fontcolor=red:fontsize=w/15:x=(w-text_w)/2:y=50" '
                f'-c:v libx264 -preset ultrafast -crf 28 -c:a aac -y {out_file}'
            )
            subprocess.run(ffmpeg_cmd, shell=True)
            
            # 4. إرسال المقطع الجاهز ثم حذفه فوراً من السيرفر (Garbage Collection)
            if os.path.exists(out_file):
                await status_msg.edit_text(f"📤 جاري إرسال (الجزء {part_num}) إليك...")
                with open(out_file, 'rb') as v:
                    await update.message.reply_video(video=v, caption=f"✅ {raw_title}")
                
                # مسح الجزء بعد إرساله لتنظيف ذاكرة السيرفر
                os.remove(out_file)

        await status_msg.edit_text("🎉 مبروك! تمت جميع عمليات المونتاج والإرسال بنجاح، وتم تنظيف السيرفر بالكامل.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ فني أثناء المعالجة: {e}")
    finally:
        # الكنس النهائي: مسح المقطع الأساسي الكبير في كل الحالات (سواء نجح أو فشل)
        if os.path.exists(input_path):
            os.remove(input_path)
        context.user_data.clear()
        
    return ConversationHandler.END

# --- التشغيل الأساسي للبوت ---
if __name__ == '__main__':
    # تشغيل النبض لضمان بقاء السيرفر
    threading.Thread(target=send_pulse, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    
    # بناء البوت
    bot = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # فلتر عام لالتقاط كلمة "الغاء"
    cancel_filter = filters.Regex("^الغاء$")
    
    # تسلسل المحادثة
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^نجم نشر$"), start_publish)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_video)]
        },
        fallbacks=[MessageHandler(cancel_filter, cancel)]
    )
    
    bot.add_handler(conv_handler)
    # إضافة الفلتر هنا يضمن استجابة البوت للإلغاء حتى لو كان معلقاً
    bot.add_handler(MessageHandler(cancel_filter, cancel))
    
    bot.run_polling(drop_pending_updates=True)
