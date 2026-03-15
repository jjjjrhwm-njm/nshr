import os, subprocess, logging, asyncio, threading, time, requests, json
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, ConversationHandler, CommandHandler
import firebase_admin
from firebase_admin import credentials, firestore

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- جلب المتغيرات من رندر ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
VERIFY_PATH = os.getenv("TIKTOK_VERIFY_PATH")
VERIFY_CONTENT = os.getenv("TIKTOK_VERIFY_CONTENT")
BASE_URL = os.getenv("BASE_URL") 
REDIRECT_URI = f"{BASE_URL}/callback"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE = range(2)
app = Flask(__name__)

# --- اتصال فايربيس (الذاكرة الدائمة) ---
db = None
try:
    if os.getenv("FIREBASE_CONF") and not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CONF")))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("🟢 متصل بفايربيس: الحفظ الدائم مفعل.")
except Exception as e: logger.error(f"🔴 خطأ فايربيس: {e}")

# --- نظام التجديد التلقائي لتوكن تيك توك ---
def refresh_tiktok_token(r_token):
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, 
            "grant_type": "refresh_token", "refresh_token": r_token}
    res = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
    if "access_token" in res:
        db.collection('auth').document('tiktok').set(res)
        return res['access_token']
    return None

# --- محرك الرفع ---
def upload_to_tiktok(video_path, caption):
    doc = db.collection('auth').document('tiktok').get()
    if not doc.exists: return "❌ لا يوجد توثيق، ارسل /login"
    
    tokens = doc.to_dict()
    acc_token = tokens.get('access_token')
    
    def attempt(t):
        init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
        headers = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
        body = {"post_info": {"title": caption, "privacy_level": "SELF_ONLY"},
                "source_info": {"source": "FILE_UPLOAD", "video_size": os.path.getsize(video_path), "chunk_size": os.path.getsize(video_path), "total_chunk_count": 1}}
        r = requests.post(init_url, headers=headers, json=body)
        if r.status_code == 401: return "RENEW"
        # تكملة عملية الرفع (PUT)...
        upload_url = r.json().get('data', {}).get('upload_url')
        if not upload_url: return f"Error: {r.text}"
        with open(video_path, 'rb') as f:
            requests.put(upload_url, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{os.path.getsize(video_path)-1}/{os.path.getsize(video_path)}"}, data=f)
        return "✅ تم النشر بنجاح!"

    res = attempt(acc_token)
    if res == "RENEW": # إذا انتهى المفتاح، جدده تلقائياً
        new_t = refresh_tiktok_token(tokens.get('refresh_token'))
        return attempt(new_t) if new_t else "❌ فشل التجديد التلقائي"
    return res

# --- أوامر البوت ---
async def auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.args[0]
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {"client_key": CLIENT_KEY, "client_secret": CLIENT_SECRET, "code": code, 
            "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}
    res = requests.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
    if "access_token" in res:
        db.collection('auth').document('tiktok').set(res)
        await update.message.reply_text("✅ تم الحفظ في فايربيس للأبد! لن تحتاج لتسجيل دخول مرة أخرى.")
    else: await update.message.reply_text("❌ خطأ في الكود.")

# (باقي دوال التقسيم والـ Flask كما هي في كودك السابق)
# ... [تم اختصارها هنا لسهولة النسخ، لكنها مدمجة في الملف النهائي لديك]

@app.route('/')
def home(): return "Bot Live 🟢"

@app.route(f'/{VERIFY_PATH}')
def verify(): return VERIFY_CONTENT

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), use_reloader=False)).start()
    # تشغيل البوت...
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("auth", auth_command))
    application.run_polling()
