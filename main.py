import logging
import os
import json
import sys
from datetime import datetime, timedelta
# Import 'error' untuk penanganan error API Telegram yang spesifik
from telegram import Update, error 
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from dotenv import load_dotenv

# --- 1. KONFIGURASI DAN UTILITAS FILE ---
# Memuat variabel lingkungan dari .env
if not load_dotenv():
    print("WARNING: File .env tidak ditemukan. Membaca dari environment global.")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
if not TOKEN:
    print("\n--- ERROR FATAL ---")
    print("TELEGRAM_BOT_TOKEN tidak ditemukan. Harap atur di file .env.")
    print("-------------------\n")
    sys.exit(1)
else:
    print(f"Token berhasil dimuat (Panjang: {len(TOKEN)})")

# --- PERSISTENSI DATA ---
DATA_FILE = "user_data.json"
USER_DATA_STORE = {}

JOBS_FILE = "scheduled_jobs.json"
PENDING_JOBS_STORE = []

# --- KONFIGURASI UNTUK FITUR PENGHAPUS PESAN BARU ---
KEYWORD_TO_DELAY_DELETE = ["Laporan Kata Kunci", "laporan terkirim", "laporan"]
DELAY_MINUTES = 10080  # 1 minggu

BANNED_WORDS = {
    "kontol", "anjing", "babi", "asu", "memek", "pecun", "tolol", "goblok", "jancok"
}

# ID GRUP BOT BERJALAN: Target Deleter IDs
# Bot akan menghapus kata kasar dan menjadwalkan penghapusan "Laporan terkirim" di grup-grup ini.
TARGET_DELETER_IDS = [
    -1003027534985,  # ID Grup 1 (dari pengguna)
    -1001564023478,  # ID Grup 2 (dari pengguna)
    -1002985230022   # ID Grup 3 (baru ditambahkan)
    # Tambahkan ID grup lain di sini
]
# -----------------------------------------------------

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FUNGSI I/O DATA PENGGUNA ---

def load_data():
    """Memuat data profil pengguna dari file JSON saat bot dimulai."""
    global USER_DATA_STORE
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            USER_DATA_STORE = json.load(f)
            logger.info(f"Data pengguna berhasil dimuat dari {DATA_FILE}. Total pengguna terlacak: {len(USER_DATA_STORE)}")
    except (FileNotFoundError, json.JSONDecodeError):
        USER_DATA_STORE = {}
        logger.warning(f"File {DATA_FILE} tidak ditemukan atau rusak. Memulai dengan data kosong.")

def save_data():
    """Menyimpan data profil pengguna ke file JSON."""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(USER_DATA_STORE, f, indent=4, ensure_ascii=False)
        logger.info(f"Data pengguna berhasil ditulis ke {DATA_FILE}.")
    except Exception as e:
        # Catat error I/O file jika environment tidak mengizinkan penulisan
        logger.error(f"Gagal menyimpan data pengguna ke file: {e}. Data HANYA disimpan dalam memori!")

# --- FUNGSI I/O JOB PENJADWALAN ---

def load_jobs():
    """Memuat daftar tugas penghapusan yang tertunda dari file JSON."""
    global PENDING_JOBS_STORE
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            raw_jobs = json.load(f)
            # Konversi string waktu kembali menjadi objek datetime
            PENDING_JOBS_STORE = [
                {**job, 'deletion_time': datetime.fromisoformat(job['deletion_time'])}
                for job in raw_jobs
            ]
            logger.info(f"Scheduled jobs berhasil dimuat dari {JOBS_FILE}. Total jobs: {len(PENDING_JOBS_STORE)}")
    except (FileNotFoundError, json.JSONDecodeError):
        PENDING_JOBS_STORE = []
        logger.warning(f"File {JOBS_FILE} tidak ditemukan atau rusak. Memulai dengan daftar job kosong.")

def save_jobs():
    """Menyimpan daftar tugas penghapusan yang tertunda ke file JSON."""
    try:
        # Konversi objek datetime menjadi string ISO format untuk penyimpanan
        serializable_jobs = [
            {**job, 'deletion_time': job['deletion_time'].isoformat()}
            for job in PENDING_JOBS_STORE
        ]
        with open(JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_jobs, f, indent=4, ensure_ascii=False)
        logger.info(f"Scheduled jobs berhasil ditulis ke {JOBS_FILE}.")
    except Exception as e:
        logger.error(f"Gagal menyimpan scheduled jobs ke file: {e}. Jobs HANYA disimpan dalam memori!")


# --- 2. HANDLER PERINTAH: /start (Pemeriksaan Kesehatan) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menanggapi perintah /start."""
    chat_type = update.effective_chat.type
    if chat_type in ["group", "supergroup"]:
        # Hanya kirim pesan di grup
        response_text = (
            "🤖 **Bot Aktif dan Siap Melayani**\n\n"
            "Fitur yang aktif:\n"
            "1. Pelacakan perubahan nama/username.\n"
            "2. Penghapusan instan kata kasar.\n"
            "3. Penjadwalan penghapusan pesan laporan (delay: 1 minggu).\n\n"
            "Gunakan /history untuk melihat riwayat perubahan profil.\n"
            "Gunakan **/check_data** untuk melihat data profil internal bot (Debugging)."
        )
        await update.message.reply_text(response_text, parse_mode='Markdown')
        logger.info(f"Bot merespons /start di chat {update.effective_chat.id}")

# --- 3. HANDLER UTAMA: Pelacakan dan Notifikasi ---

async def track_changes_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengecek perubahan nama pengguna. Notifikasi langsung ke chat, TANPA REPLY."""
    
    # Hanya proses jika ada effective_user dan pesan memiliki teks/data.
    if not update.effective_user or not update.message or update.message.text and update.message.text.startswith('/'):
        return

    user = update.effective_user
    user_id = str(user.id)
    current_time = datetime.now().isoformat()
    
    last_data = USER_DATA_STORE.get(user_id)
    
    current_data = {
        'full_name': user.full_name,
        'username': user.username,
        'last_checked': current_time,
        'history': []
    }
    
    notification_parts = []
    is_changed = False

    if last_data:
        # Pindahkan riwayat lama ke data saat ini
        current_data['history'] = last_data.get('history', [])
        
        # 1. Bandingkan Username
        if last_data.get('username') != current_data['username']:
            change_record = {
                'type': 'username',
                'old_value': last_data.get('username'),
                'new_value': current_data['username'],
                'timestamp': current_time
            }
            current_data['history'].append(change_record)
            
            # Format notifikasi: @Old -> @New
            old_user = last_data.get('username') or 'None'
            new_user = current_data['username'] or 'None'
            
            notification_parts.append(f"@ `@{'None' if old_user == 'None' else old_user}` → `@{'None' if new_user == 'None' else new_user}`")
            is_changed = True
            
        # 2. Bandingkan Full Name
        if last_data.get('full_name') != current_data['full_name']:
            change_record = {
                'type': 'full_name',
                'old_value': last_data.get('full_name'),
                'new_value': current_data['full_name'],
                'timestamp': current_time
            }
            current_data['history'].append(change_record)
            
            notification_parts.append(
                f"👤 `{change_record['old_value']}` → `{current_data['full_name']}`"
            )
            is_changed = True

    # Simpan data baru (overwrite jika ada perubahan atau inisialisasi jika baru)
    USER_DATA_STORE[user_id] = current_data
    save_data()
    
    # Kirim Notifikasi jika perubahan terdeteksi
    if is_changed:
        
        header = "🚨 **PROFIL BERUBAH**\n"
        final_notification = header + "\n".join(notification_parts)
        
        # Tambahkan tautan pengguna saat ini di akhir
        mention = f"\nOleh: [{user.full_name}](tg://user?id={user.id})"
        final_notification += mention
        
        try:
            # Menggunakan send_message() untuk mengirim pesan baru
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=final_notification.strip(),
                parse_mode='Markdown'
            )
            logger.info(f"Notifikasi perubahan profil langsung dikirim untuk ID {user_id}")
        except Exception as e:
             logger.error(f"Gagal mengirim notifikasi perubahan profil di chat {update.effective_chat.id}: {e}")

# --- 4. FUNGSI JOB UNTUK PENGHAPUSAN TERTUNDA ---

async def delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fungsi yang dieksekusi oleh job queue untuk menghapus pesan."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    message_id = job_data['message_id']
    
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
        logger.info(f"Pesan (ID: {message_id}) di {chat_id} berhasil dihapus oleh job queue.")
    # Menangkap error spesifik API jika bot gagal menghapus pesan (misal: tidak ada izin)
    except error.BadRequest as e:
        logger.warning(f"Gagal menghapus pesan tertunda (ID: {message_id}) di {chat_id}. Bot mungkin bukan admin atau tidak memiliki izin 'Delete messages': {e}")
    except Exception as e:
        # Pesan mungkin sudah dihapus secara manual atau error umum lainnya
        logger.warning(f"Gagal menghapus pesan tertunda (ID: {message_id}) di {chat_id}: Error umum lainnya: {e}")
        
    # Hapus job dari persistence store, baik berhasil atau gagal
    global PENDING_JOBS_STORE
    initial_count = len(PENDING_JOBS_STORE)
    
    # Filter list, hanya menyisakan job yang TIDAK cocok dengan job yang baru dieksekusi
    PENDING_JOBS_STORE = [
        job for job in PENDING_JOBS_STORE 
        if not (job['chat_id'] == chat_id and job['message_id'] == message_id)
    ]
    
    if len(PENDING_JOBS_STORE) < initial_count:
        save_jobs()
        logger.info(f"Job (ID: {message_id}) dihapus dari persistence store.")


# --- 5. HANDLER UNTUK PENGHAPUS PESAN INSTAN DAN PENJADWALAN ---

async def keyword_deleter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani penghapusan instan untuk kata kasar dan penjadwalan penghapusan tertunda."""
    
    message = update.effective_message
    chat_id = update.effective_chat.id
    
    # Periksa apakah pesan memiliki teks dan berasal dari salah satu grup target
    if not message.text or chat_id not in TARGET_DELETER_IDS:
        return

    text_lower = message.text.lower()
    
    # --- 5.1. PENGHAPUSAN INSTAN (Kata Kasar) ---
    if any(word in text_lower for word in BANNED_WORDS):
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message.message_id
            )
            logger.info(f"Pesan di {chat_id} dihapus INSTAN karena mengandung kata kasar.")
            return # Hentikan pemprosesan lebih lanjut
            
        except error.BadRequest as e:
            # PENTING: Bot tidak akan crash lagi, hanya mencatat ini.
            logger.error(f"Gagal menghapus pesan INSTAN di {chat_id}. Kemungkinan bot bukan admin atau tidak memiliki izin 'Delete messages': {e}")
        except Exception as e:
            logger.error(f"Gagal menghapus pesan INSTAN di {chat_id}. Error umum lainnya, bot tidak crash: {e}")
            
    # --- 5.2. PENJADWALAN PENGHAPUSAN (Multiple Keywords) ---
    if any(keyword.lower() in text_lower for keyword in KEYWORD_TO_DELAY_DELETE):
        
        # 1. Hitung waktu penghapusan target
        now = datetime.now()
        deletion_time = now + timedelta(minutes=DELAY_MINUTES)
        
        # 2. Simpan job ke persistence store
        new_job_record = {
            'chat_id': chat_id,
            'message_id': message.message_id,
            'deletion_time': deletion_time # Objek datetime
        }
        PENDING_JOBS_STORE.append(new_job_record)
        save_jobs() 

        # 3. Data yang diperlukan untuk job queue
        job_data = {
            'chat_id': chat_id,
            'message_id': message.message_id
        }

        # 4. Jadwalkan job
        context.job_queue.run_once(
            delete_message_job, 
            timedelta(minutes=DELAY_MINUTES), 
            data=job_data,
            name=f"del_{chat_id}_{message.message_id}"
        )
        
        logger.info(f"Pesan (keyword ditemukan) di {chat_id} dijadwalkan untuk dihapus pada {deletion_time.strftime('%Y-%m-%d %H:%M:%S')}.")


# --- 6. HANDLER PERINTAH: /history (RINGKAS) ---

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan riwayat perubahan nama pengguna, diurutkan dari yang paling lama, dengan format ringkas."""
    
    target_user_id = None
    
    # 1. Tentukan ID Pengguna Target
    if update.message.reply_to_message:
        target_user_id = str(update.message.reply_to_message.from_user.id)
    elif context.args:
        username = context.args[0].lstrip('@')
        for user_id_key, data in USER_DATA_STORE.items():
            if data.get('username', '').lower() == username.lower():
                target_user_id = user_id_key
                break
    else:
        target_user_id = str(update.effective_user.id)

    # 2. Ambil Data
    data = USER_DATA_STORE.get(target_user_id)
    
    if not data:
        response = "Pengguna tidak ditemukan atau belum pernah mengirim pesan sejak bot aktif."
    else:
        history = data.get('history', [])
        
        # Format Judul
        user_display = data.get('full_name', 'Nama Tidak Diketahui')
        if data.get('username'):
            user_display += f" (@{data['username']})"
            
        response = f"**Riwayat Profil ({len(history)} Perubahan):** {user_display}\n\n"
        
        if not history:
            response += "_Belum ada perubahan tercatat._"
        else:
            # Format Riwayat Ringkas
            for i, record in enumerate(history):
                try:
                    time_str = datetime.fromisoformat(record['timestamp']).strftime('%y/%m/%d %H:%M') # Format waktu ringkas
                except ValueError:
                    time_str = "Waktu Invalid"
                
                # Gabungkan semua dalam satu baris: [Waktu] [Tipe] [Lama] -> [Baru]
                if record['type'] == 'full_name':
                    line = (
                        f"`{time_str}` 👤 `{record['old_value']}` → `{record['new_value']}`"
                    )
                
                elif record['type'] == 'username':
                    # Pastikan 'None' muncul untuk username yang hilang
                    old_user = record['old_value'] or 'None'
                    new_user = record['new_value'] or 'None'
                    line = (
                        f"`{time_str}` @ `@{'None' if old_user == 'None' else old_user}` → `@{'None' if new_user == 'None' else new_user}`"
                    )
                    
                response += f"{i+1}. {line}\n"

    # 3. Kirim Respons
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=response, 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal mengirim riwayat profil di chat {update.effective_chat.id}: {e}")

    # 4. Hapus Pesan Perintah Asli
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
        logger.info(f"Pesan perintah /history (ID: {update.message.message_id}) berhasil dihapus.")
    except Exception as e:
        logger.warning(f"Gagal menghapus pesan perintah /history (setelah respons): {e}")


# --- 6.5. HANDLER PERINTAH: /check_data (Debugging) ---

async def check_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan status data in-memory saat ini untuk tujuan debugging."""
    chat_id = update.effective_chat.id
    
    # Pilih ID pengguna yang akan dicek (sendiri atau dari reply)
    target_user_id = str(update.effective_user.id)
    if update.message.reply_to_message:
        target_user_id = str(update.message.reply_to_message.from_user.id)

    data = USER_DATA_STORE.get(target_user_id)
    
    if data:
        # Menggunakan JSON dump untuk representasi data yang mudah dibaca
        debug_output = json.dumps(data, indent=2, ensure_ascii=False)
        response = (
            f"**DEBUG DATA UNTUK USER ID `{target_user_id}` (Internal Store):**\n\n"
            f"```json\n{debug_output}\n```"
        )
    else:
        response = f"Data pengguna ID `{target_user_id}` tidak ditemukan di penyimpanan in-memory saat ini."

    try:
        await context.bot.send_message(
            chat_id=chat_id, 
            text=response, 
            parse_mode='Markdown'
        )
        logger.info(f"Debug data dikirim ke {chat_id} untuk user ID {target_user_id}.")
    except Exception as e:
        logger.error(f"Gagal mengirim debug data: {e}")

# --- 7. FUNGSI UTAMA: Main Program ---

def main() -> None:
    """Membuat dan menjalankan bot menggunakan Long Polling."""
    
    load_data()
    
    # Menggunakan application.job_queue secara default
    application = Application.builder().token(TOKEN).build()
    
    # --- MEMULAI ULANG JOB YANG TERTUNDA DARI FILE ---
    load_jobs()
    now = datetime.now()
    
    jobs_to_reschedule = PENDING_JOBS_STORE[:] # Copy list untuk iterasi
    jobs_after_reschedule = [] # List baru untuk job yang masih valid
    
    for job in jobs_to_reschedule:
        chat_id = job['chat_id']
        message_id = job['message_id']
        deletion_time = job['deletion_time']
        
        # Hitung sisa waktu
        remaining_delay = deletion_time - now
        
        job_data = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        
        if remaining_delay.total_seconds() > 0:
            # Job masih di masa depan, jadwalkan dengan sisa waktu
            application.job_queue.run_once(
                delete_message_job, 
                remaining_delay, 
                data=job_data,
                name=f"del_{chat_id}_{message_id}"
            )
            jobs_after_reschedule.append(job)
            logger.info(f"Job (ID: {message_id}) dijadwalkan ulang. Sisa waktu: {remaining_delay}")
        else:
            # Job sudah lewat waktunya, jadwalkan untuk dihapus segera (1 detik)
            application.job_queue.run_once(
                delete_message_job, 
                timedelta(seconds=1), 
                data=job_data,
                name=f"del_{chat_id}_{message_id}_immediate"
            )
            jobs_after_reschedule.append(job) # Tetap di store sampai delete_message_job menghapusnya
            logger.warning(f"Job (ID: {message_id}) sudah lewat waktu. Dijadwalkan untuk dihapus segera.")

    # PENDING_JOBS_STORE akan diperbarui oleh delete_message_job, jadi tidak perlu save_jobs() di sini, 
    # karena job yang sudah lewat waktu akan segera dihapus dan memicu save_jobs() dari job function.
    
    # --- PENDAFTARAN HANDLER ---
    
    # Handler 1: Perintah /start
    application.add_handler(CommandHandler("start", start_command))

    # Handler 2: Penghapus Pesan dan Penjadwalan (Hanya di TARGET_DELETER_IDS)
    deleter_handler = MessageHandler(
        filters=filters.TEXT & filters.Chat(TARGET_DELETER_IDS), 
        callback=keyword_deleter
    )
    application.add_handler(deleter_handler)
    
    # Handler 3: Perintah /history
    application.add_handler(CommandHandler("history", show_history))
    
    # Handler 4: Debug Data
    application.add_handler(CommandHandler("check_data", check_data_command))
    
    # Handler 5: Pelacakan Profil (Jalankan pada semua pesan non-perintah)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_changes_notify))

    logger.info("Bot berjalan. Siap memberi notifikasi perubahan profil dan mengelola job tertunda.")
    application.run_polling(poll_interval=1)

if __name__ == '__main__':
    main()
