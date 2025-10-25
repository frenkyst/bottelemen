import os
import logging
from dotenv import load_dotenv

# Import pustaka Telegram dan Google Cloud Firestore
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google.cloud import firestore

# --- 1. SETUP LOGGER DAN ENVIRONMENT ---
# Atur logging agar pesan penting (seperti error) terlihat di terminal
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Muat variabel lingkungan dari file .env
load_dotenv()

# Dapatkan Token Bot dari .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("❌ ERROR: TELEGRAM_TOKEN tidak ditemukan di file .env!")
    exit(1)

# --- 2. INISIALISASI FIRESTORE ---
try:
    # Firestore Client akan otomatis menggunakan kredensial dari lingkungan
    db = firestore.Client()
    logging.info("✅ Firestore Client berhasil diinisialisasi.")
except Exception as e:
    logging.error(f"❌ ERROR: Gagal inisialisasi Firestore: {e}")
    # Berhenti jika koneksi database gagal
    exit(1)

# --- 3. FUNGSI UTILITY DATABASE ---

async def save_user_data(user_id: str, update: Update):
    """
    Mengambil data pengguna dari Telegram dan menyimpannya ke Firestore.
    """
    user = update.effective_user
    user_ref = db.collection('bot_users').document(str(user_id))
    
    # Data yang akan disimpan/diperbarui
    data = {
        'full_name': user.full_name,
        'username': user.username,
        'last_update': firestore.SERVER_TIMESTAMP,
        # Menggunakan ArrayUnion untuk menambahkan pesan baru
        'history': firestore.ArrayUnion([
            {'text': update.message.text, 'timestamp': firestore.SERVER_TIMESTAMP}
        ])
    }
    
    try:
        # Menggunakan set(merge=True) agar data baru ditambahkan ke data yang sudah ada
        user_ref.set(data, merge=True)
        # LOG KONFIRMASI PENTING!
        logging.info(f"💾 DATA SAVED: Data pengguna {user_id} berhasil disimpan ke Firestore.")
        return True
    except Exception as e:
        logging.error(f"❌ FIRESTORE WRITE FAILED: Gagal menyimpan data untuk {user_id}: {e}")
        return False

# --- 4. HANDLER UNTUK PESAN ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani perintah /start dan menyimpan data."""
    user_id = update.effective_user.id
    
    # Simpan data pengguna segera
    if await save_user_data(user_id, update):
        await update.message.reply_text(
            f"Halo, {update.effective_user.first_name}!\n"
            "Saya sudah berhasil menyimpan data Anda ke Firestore. Silakan cek konsol Anda!"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani semua pesan teks lain dan menyimpannya."""
    user_id = update.effective_user.id
    
    # Simpan data pengguna
    if await save_user_data(user_id, update):
        # Tambahkan konfirmasi ke terminal, tapi balas dengan pesan sederhana
        logging.info(f"Received message from {user_id}: {update.message.text}")
        await update.message.reply_text(
            "Pesan diterima. Data Anda telah diperbarui di Firestore."
        )
    else:
        # Balas jika penyimpanan gagal
        await update.message.reply_text(
            "Pesan diterima, namun terjadi kesalahan saat menyimpan ke database."
        )


# --- 5. MAIN FUNCTION ---

def main() -> None:
    """Memulai bot."""
    logging.info("🚀 Memulai Bot Telegram...")
    
    # Buat Aplikasi Bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Daftarkan Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Mulai Polling Bot (agar bot terus berjalan)
    logging.info("👂 Bot siap menerima pesan...")
    application.run_polling(poll_interval=1.0)

if __name__ == "__main__":
    main()
