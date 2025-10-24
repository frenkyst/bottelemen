import logging
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# --- 1. KONFIGURASI DAN UTILITAS FILE ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN tidak ditemukan. Harap atur di file .env.")

# --- PERSISTENSI DATA ---
# Untuk riwayat perubahan nama/username
DATA_FILE = "user_data.json"
USER_DATA_STORE = {}

# Untuk tugas penghapusan pesan yang dijadwalkan
JOBS_FILE = "scheduled_jobs.json"
PENDING_JOBS_STORE = []

# --- KONFIGURASI UNTUK FITUR PENGHAPUS PESAN BARU ---
# Kata kunci untuk penghapusan TERTUNDA (setelah 10 menit)
# TELAH DIUBAH MENJADI DAFTAR UNTUK MENDUKUNG BEBERAPA FRASA
KEYWORD_TO_DELAY_DELETE = ["Laporan Kata Kunci", "laporan terkirim", "laporan"]
DELAY_MINUTES = 100 

# Kata-kata kasar/spam yang dihapus SECARA INSTAN (Case Insensitive)
BANNED_WORDS = {
    "kontol", "anjing", "babi", "asu", "memek", "pecun", "tolol", "goblok", "jancok"
    # Tambahkan kata-kata kasar/spam lainnya di sini.
}

# ID GRUP BOT BERJALAN: Target Deleter IDs
# Bot akan menghapus kata kasar dan menjadwalkan penghapusan "Laporan terkirim" di grup-grup ini.
# ID grup Supergroup/Channel harus dimulai dengan -100...
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
    except Exception as e:
        logger.error(f"Gagal menyimpan data pengguna ke file: {e}")

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
    except Exception as e:
        logger.error(f"Gagal menyimpan scheduled jobs ke file: {e}")


# --- 2. HANDLER UTAMA: Pelacakan dan Notifikasi (FINAL: TANPA REPLY) ---

async def track_changes_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengecek perubahan nama pengguna. Notifikasi langsung ke chat, TANPA REPLY."""
    
    # Hanya proses non-perintah dan jika ada effective_user (bukan pesan sistem)
    if not update.effective_user or (update.message.text and update.message.text.startswith('/')):
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
        current_data['history'] = last_data.get('history', [])
        
        # 1. Bandingkan Username (DIPROSES DULU)
        if last_data.get('username') != current_data['username']:
            change_record = {
                'type': 'username',
                'old_value': last_data.get('username'),
                'new_value': current_data['username'],
                'timestamp': current_time
            }
            current_data['history'].append(change_record)
            
            notification_parts.append(
                f"@ `@{'None' if not change_record['old_value'] else change_record['old_value']}` → `@{'None' if not current_data['username'] else current_data['username']}`"
            )
            is_changed = True
            
        # 2. Bandingkan Full Name (DIPROSES KEDUA)
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

    # Simpan data baru
    USER_DATA_STORE[user_id] = current_data
    save_data()
    
    # Kirim Notifikasi jika perubahan terdeteksi
    if is_changed and update.message:
        
        header = "🚨 **PROFIL BERUBAH**\n"
        final_notification = header + "\n".join(notification_parts)
        
        # Tambahkan tautan pengguna saat ini di akhir
        mention = f"\nOleh: [{user.full_name}](tg://user?id={user.id})"
        final_notification += mention
        
        # Menggunakan send_message() untuk mengirim pesan baru
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=final_notification.strip(),
            parse_mode='Markdown'
        )
        logger.info(f"Notifikasi perubahan profil langsung dikirim untuk ID {user_id}")
    
    elif not last_data and update.message:
         # Hanya menyimpan data untuk pengguna baru
         pass

# --- 3. FUNGSI JOB UNTUK PENGHAPUSAN TERTUNDA ---

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
        logger.info(f"Pesan (ID: {message_id}) di {chat_id} berhasil dihapus.")
    except Exception as e:
        # Pesan mungkin sudah dihapus secara manual atau bot tidak lagi menjadi admin
        logger.warning(f"Gagal menghapus pesan tertunda (ID: {message_id}) di {chat_id}: {e}")
        
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


# --- 4. HANDLER UNTUK PENGHAPUS PESAN INSTAN DAN PENJADWALAN ---

async def keyword_deleter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani penghapusan instan untuk kata kasar dan penjadwalan penghapusan tertunda."""
    
    message = update.effective_message
    chat_id = update.effective_chat.id
    
    # Periksa apakah pesan memiliki teks dan berasal dari salah satu grup target
    if not message.text or chat_id not in TARGET_DELETER_IDS:
        return

    text_lower = message.text.lower()
    
    # --- 4.1. PENGHAPUSAN INSTAN (Kata Kasar) ---
    if any(word in text_lower for word in BANNED_WORDS):
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message.message_id
            )
            logger.info(f"Pesan di {chat_id} dihapus INSTAN karena mengandung kata kasar.")
            return # Hentikan pemprosesan lebih lanjut
            
        except Exception as e:
            logger.error(f"Gagal menghapus pesan INSTAN di {chat_id}: {e}")
            
    # --- 4.2. PENJADWALAN PENGHAPUSAN (Multiple Keywords) ---
    # Cek apakah ADA SALAH SATU kata kunci dalam daftar ditemukan di pesan
    # Logika yang benar: Iterasi melalui list, konversi masing-masing keyword ke lowercase, lalu cek
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

        # 4. Jadwalkan job dalam 10 menit
        context.job_queue.run_once(
            delete_message_job, 
            timedelta(minutes=DELAY_MINUTES), 
            data=job_data,
            name=f"del_{chat_id}_{message.message_id}"
        )
        
        logger.info(f"Pesan (salah satu dari kata kunci penundaan ditemukan) di {chat_id} dijadwalkan untuk dihapus pada {deletion_time.strftime('%H:%M:%S')}.")


# --- 5. HANDLER PERINTAH: /history (RINGKAS) ---

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menampilkan riwayat perubahan nama pengguna, diurutkan dari yang paling lama, dengan format ringkas."""
    
    target_user_id = None
    
    # Tentukan ID Pengguna Target (sama seperti sebelumnya)
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

    # Ambil Data
    if not target_user_id or target_user_id not in USER_DATA_STORE:
        await update.message.reply_text("Pengguna tidak ditemukan atau belum pernah mengirim pesan sejak bot aktif.")
        
        # --- Hapus pesan perintah asli di sini juga jika gagal ---
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
            logger.info(f"Pesan perintah /history (ID: {update.message.message_id}) dihapus setelah respons pengguna tidak ditemukan.")
        except Exception as e:
            logger.warning(f"Gagal menghapus pesan perintah /history (gagal pertama): {e}")
        # --------------------------------------------------------
        
        return

    data = USER_DATA_STORE[target_user_id]
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
                line = (
                    f"`{time_str}` @ `@{'None' if not record['old_value'] else record['old_value']}` → `@{'None' if not record['new_value'] else record['new_value']}`"
                )
                
            response += f"{i+1}. {line}\n"

    # Ganti reply_text dengan send_message
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=response, 
        parse_mode='Markdown'
    )

    # --- Hapus Pesan Perintah Asli ---
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
        logger.info(f"Pesan perintah /history (ID: {update.message.message_id}) berhasil dihapus.")
    except Exception as e:
        logger.warning(f"Gagal menghapus pesan perintah /history (setelah respons): {e}")


# --- 6. FUNGSI UTAMA: Main Program ---

def main() -> None:
    """Membuat dan menjalankan bot menggunakan Long Polling."""
    
    load_data()
    
    # Menggunakan application.job_queue secara default
    application = Application.builder().token(TOKEN).build()
    
    # --- MEMULAI ULANG JOB YANG TERTUNDA DARI FILE ---
    load_jobs()
    now = datetime.now()
    jobs_to_reschedule = PENDING_JOBS_STORE[:] # Copy list untuk iterasi
    
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
            logger.info(f"Job (ID: {message_id}) dijadwalkan ulang. Sisa waktu: {remaining_delay}")
        else:
            # Job sudah lewat waktunya, jadwalkan untuk dihapus segera (1 detik)
            application.job_queue.run_once(
                delete_message_job, 
                timedelta(seconds=1), 
                data=job_data,
                name=f"del_{chat_id}_{message_id}_immediate"
            )
            logger.warning(f"Job (ID: {message_id}) sudah lewat waktu. Dijadwalkan untuk dihapus segera.")

    # --- PENDAFTARAN HANDLER ---
    
    # Handler 1: Penghapus Pesan dan Penjadwalan
    deleter_handler = MessageHandler(
        filters=filters.ALL & filters.Chat(TARGET_DELETER_IDS), 
        callback=keyword_deleter
    )
    application.add_handler(deleter_handler)
    
    # Handler 2: Perintah /history
    application.add_handler(CommandHandler("history", show_history))
    
    # Handler 3: Pelacakan Profil (Jalankan pada semua pesan non-perintah)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_changes_notify))

    logger.info("Bot berjalan. Siap memberi notifikasi perubahan profil dan mengelola job tertunda.")
    application.run_polling(poll_interval=1)

if __name__ == '__main__':
    main()
