import logging
import os
import json
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# --- 1. KONFIGURASI DAN UTILITAS FILE ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN tidak ditemukan. Harap atur di file .env.")

DATA_FILE = "user_data.json"
USER_DATA_STORE = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def load_data():
    """Memuat data dari file JSON saat bot dimulai."""
    global USER_DATA_STORE
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            USER_DATA_STORE = json.load(f)
            logger.info(f"Data berhasil dimuat dari {DATA_FILE}. Total pengguna terlacak: {len(USER_DATA_STORE)}")
    except (FileNotFoundError, json.JSONDecodeError):
        USER_DATA_STORE = {}
        logger.warning(f"File {DATA_FILE} tidak ditemukan atau rusak. Memulai dengan data kosong.")

def save_data():
    """Menyimpan data ke file JSON."""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(USER_DATA_STORE, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Gagal menyimpan data ke file: {e}")

# --- 2. HANDLER UTAMA: Pelacakan dan Notifikasi (FINAL: TANPA REPLY) ---

async def track_changes_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengecek perubahan nama pengguna. Notifikasi langsung ke chat, TANPA REPLY."""
    
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
        
        # --- PERBAIKAN KRUSIAL DI SINI ---
        # Menggunakan send_message() untuk mengirim pesan baru
        await context.bot.send_message(
            chat_id=update.effective_chat.id,  # Mengirim ke chat yang sama
            text=final_notification.strip(),
            parse_mode='Markdown'
        )
        logger.info(f"Notifikasi perubahan profil langsung dikirim untuk ID {user_id}")
    
    elif not last_data and update.message:
         # Hanya menyimpan data untuk pengguna baru
         pass


# --- 3. HANDLER PERINTAH: /history (RINGKAS) ---

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

    await update.message.reply_text(response, parse_mode='Markdown')


# --- 4. FUNGSI UTAMA: Main Program ---

def main() -> None:
    """Membuat dan menjalankan bot menggunakan Long Polling."""
    
    load_data()
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("history", show_history))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, track_changes_notify))

    logger.info("Bot berjalan. Siap memberi notifikasi perubahan profil.")
    application.run_polling(poll_interval=1)

if __name__ == '__main__':
    main()