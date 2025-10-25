<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Simulasi Bot Profile Tracker Firestore</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Firebase Imports -->
    <script type="module">
        import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-app.js";
        import { getAuth, signInAnonymously, signInWithCustomToken, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-auth.js";
        import { getFirestore, doc, getDoc, setDoc, onSnapshot, collection, query, updateDoc, arrayUnion } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-firestore.js";
        import { setLogLevel } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-firestore.js";

        setLogLevel('debug'); // Untuk melihat log koneksi

        // --- GLOBAL VARIABLES (MANDATORY) ---
        const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-tracker-app-id';
        const firebaseConfig = typeof __firebase_config !== 'undefined' ? JSON.parse(__firebase_config) : {};
        const initialAuthToken = typeof __initial_auth_token !== 'undefined' ? __initial_auth_token : null;
        
        // --- FIREBASE INITIALIZATION ---
        const app = initializeApp(firebaseConfig);
        const db = getFirestore(app);
        const auth = getAuth(app);
        
        let userId = null;
        let isAuthReady = false;

        const PROFILE_COLLECTION = 'user_profiles';

        /**
         * Mendapatkan path koleksi publik/bersama.
         * Kami menggunakan koleksi publik karena data pelacakan profil ini 
         * idealnya dibagikan dan dapat diakses oleh semua pengguna dalam grup simulasi.
         */
        function getCollectionRef() {
            // Path: /artifacts/{appId}/public/data/user_profiles
            return collection(db, 'artifacts', appId, 'public', 'data', PROFILE_COLLECTION);
        }

        // --- AUTENTIKASI ---
        async function authenticate() {
            try {
                if (initialAuthToken) {
                    await signInWithCustomToken(auth, initialAuthToken);
                } else {
                    await signInAnonymously(auth);
                }
            } catch (error) {
                console.error("Gagal melakukan autentikasi Firebase:", error);
            }
        }

        onAuthStateChanged(auth, (user) => {
            if (user) {
                userId = user.uid;
                isAuthReady = true;
                console.log("Autentikasi Berhasil. User ID:", userId);
                document.getElementById('current-user-id').textContent = `ID Anda: ${userId}`;
                
                // Setelah autentikasi, kita bisa mulai mendengarkan data profil
                setupProfileListener();
            } else {
                isAuthReady = false;
                userId = null;
                console.warn("User ter-logout atau gagal autentikasi.");
                document.getElementById('current-user-id').textContent = 'Authenticating...';
            }
        });
        
        // --- LOGIKA UTAMA: MELACAK PERUBAHAN ---

        // State yang disimulasikan (ganti dengan input pengguna)
        let simulatedProfile = {
            id: 'simulated_user_123', // ID statis untuk contoh
            fullName: 'Pengguna Uji Coba',
            username: 'tester_simulasi',
            lastUpdated: new Date().toISOString(),
            history: []
        };
        
        /**
         * Menyimpan atau memperbarui profil ke Firestore.
         */
        async function saveProfile(profileData) {
            if (!isAuthReady) {
                console.error("Firestore belum siap. Autentikasi belum selesai.");
                return;
            }
            try {
                const userDocRef = doc(getCollectionRef(), profileData.id);
                // Kita gunakan setDoc dengan merge: true agar tidak menimpa seluruh dokumen
                await setDoc(userDocRef, {
                    fullName: profileData.fullName,
                    username: profileData.username,
                    lastUpdated: profileData.lastUpdated,
                    // Karena arrayUnion digunakan saat log history dibuat, kita tidak perlu 
                    // mengirimkan seluruh array history di sini, cukup update data utama.
                }, { merge: true });
                console.log(`Profil ID ${profileData.id} berhasil disimpan/diperbarui.`);
            } catch (e) {
                console.error("Error saat menyimpan profil ke Firestore: ", e);
            }
        }

        /**
         * Melakukan simulasi perubahan profil dan mencatat riwayat (history) ke Firestore.
         */
        async function checkAndLogChanges(newFullName, newUsername) {
            if (!isAuthReady) {
                console.error("Firestore belum siap.");
                return;
            }

            const userDocRef = doc(getCollectionRef(), simulatedProfile.id);
            const docSnap = await getDoc(userDocRef);
            
            let currentProfile = docSnap.exists() ? docSnap.data() : { fullName: '', username: '', history: [] };
            let changes = [];
            let isChanged = false;
            const timestamp = new Date().toISOString();

            // Cek perubahan Nama
            if (currentProfile.fullName !== newFullName) {
                changes.push({
                    type: 'full_name',
                    oldValue: currentProfile.fullName || 'None',
                    newValue: newFullName,
                    timestamp: timestamp
                });
                isChanged = true;
            }

            // Cek perubahan Username
            if (currentProfile.username !== newUsername) {
                changes.push({
                    type: 'username',
                    oldValue: currentProfile.username || 'None',
                    newValue: newUsername,
                    timestamp: timestamp
                });
                isChanged = true;
            }

            // Update di Firestore
            if (isChanged || !docSnap.exists()) {
                const updateData = {
                    fullName: newFullName,
                    username: newUsername,
                    lastUpdated: timestamp,
                };
                
                if (changes.length > 0) {
                    // Gunakan arrayUnion untuk menambahkan perubahan ke array history
                    updateData.history = arrayUnion(...changes);
                }

                await setDoc(userDocRef, updateData, { merge: true });

                // Tampilkan notifikasi simulasi
                const notificationEl = document.getElementById('notification-area');
                notificationEl.innerHTML = changes.map(c => 
                    `<p class="text-sm font-medium text-blue-600">🚨 Perubahan: ${c.type.toUpperCase()}: ${c.oldValue} → ${c.newValue}</p>`
                ).join('');
                setTimeout(() => notificationEl.innerHTML = '', 5000);
            } else {
                const notificationEl = document.getElementById('notification-area');
                notificationEl.innerHTML = `<p class="text-sm text-gray-500">Tidak ada perubahan profil.</p>`;
                setTimeout(() => notificationEl.innerHTML = '', 3000);
            }
            
            // Simpan data lokal untuk referensi
            simulatedProfile.fullName = newFullName;
            simulatedProfile.username = newUsername;
        }

        /**
         * Set up Listener Realtime (onSnapshot)
         */
        function setupProfileListener() {
            const userDocRef = doc(getCollectionRef(), simulatedProfile.id);
            
            onSnapshot(userDocRef, (docSnap) => {
                const historyList = document.getElementById('history-list');
                historyList.innerHTML = '';
                
                if (docSnap.exists()) {
                    const data = docSnap.data();
                    const history = data.history || [];
                    
                    document.getElementById('current-name-display').textContent = data.fullName || '-';
                    document.getElementById('current-username-display').textContent = data.username ? `@${data.username}` : 'N/A';
                    
                    if (history.length > 0) {
                         // Urutkan riwayat berdasarkan waktu (timestamp) terbaru di atas
                         history.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
                         
                         history.forEach((record, index) => {
                            const date = new Date(record.timestamp).toLocaleString('id-ID', { 
                                year: '2-digit', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
                            });
                            
                            let detail = '';
                            if (record.type === 'full_name') {
                                detail = `Nama: ${record.oldValue} → ${record.newValue}`;
                            } else if (record.type === 'username') {
                                detail = `Username: @${record.oldValue} → @${record.newValue}`;
                            }
                            
                            const listItem = `
                                <li class="p-2 border-b border-gray-100 last:border-b-0 text-sm">
                                    <span class="font-semibold text-gray-700">${date}</span>
                                    <span class="text-xs text-gray-500 ml-2">(${record.type})</span>
                                    <p class="text-xs text-gray-600 mt-1">${detail}</p>
                                </li>
                            `;
                            historyList.innerHTML += listItem;
                        });
                    } else {
                        historyList.innerHTML = '<li class="p-4 text-center text-gray-500">Belum ada riwayat perubahan.</li>';
                    }
                    
                } else {
                    // Dokumen belum ada, tampilkan pesan default
                    historyList.innerHTML = '<li class="p-4 text-center text-gray-500">Profil ini belum pernah dilacak.</li>';
                    document.getElementById('current-name-display').textContent = 'N/A';
                    document.getElementById('current-username-display').textContent = 'N/A';
                }
            }, (error) => {
                console.error("Error onSnapshot:", error);
                document.getElementById('history-list').innerHTML = '<li class="p-4 text-red-500 text-center">Gagal memuat data realtime.</li>';
            });
        }
        
        // --- EVENT HANDLERS ---
        window.onload = () => {
            authenticate();
            
            document.getElementById('fullNameInput').value = simulatedProfile.fullName;
            document.getElementById('usernameInput').value = simulatedProfile.username;
            document.getElementById('simulated-id').textContent = `ID Simulasi: ${simulatedProfile.id}`;

            document.getElementById('updateButton').addEventListener('click', () => {
                const newName = document.getElementById('fullNameInput').value.trim();
                const newUser = document.getElementById('usernameInput').value.trim();
                
                if (newName === "") {
                    alert("Nama lengkap tidak boleh kosong.");
                    return;
                }
                
                checkAndLogChanges(newName, newUser);
            });
        }

    </script>
</head>
<body class="bg-gray-50 min-h-screen p-4 sm:p-8 font-sans">

    <div class="max-w-4xl mx-auto bg-white shadow-xl rounded-2xl overflow-hidden">
        
        <!-- Header -->
        <header class="bg-indigo-600 p-6 text-white">
            <h1 class="text-2xl font-bold">Bot Profile Tracker ⚡️ (Firestore)</h1>
            <p class="text-indigo-200 mt-1">Menggunakan Firestore untuk penyimpanan permanen. Tidak ada lagi masalah file JSON!</p>
            <p id="current-user-id" class="text-xs mt-2 bg-indigo-700 p-1 rounded inline-block">Authenticating...</p>
        </header>

        <main class="grid md:grid-cols-2 gap-8 p-6 sm:p-8">
            
            <!-- 1. Simulasi Input -->
            <div class="bg-white p-6 rounded-xl border border-indigo-100 shadow-lg">
                <h2 class="text-xl font-semibold text-indigo-800 border-b pb-2 mb-4">Simulasi Pesan Baru</h2>
                
                <p id="simulated-id" class="text-sm text-gray-500 mb-4 font-mono"></p>
                
                <div class="space-y-4">
                    <div>
                        <label for="fullNameInput" class="block text-sm font-medium text-gray-700">Nama Lengkap (Simulasi Kirim Pesan)</label>
                        <input type="text" id="fullNameInput" class="mt-1 block w-full border border-gray-300 rounded-lg shadow-sm p-3 focus:ring-indigo-500 focus:border-indigo-500" placeholder="Contoh: Budi Santoso">
                    </div>
                    <div>
                        <label for="usernameInput" class="block text-sm font-medium text-gray-700">Username (@tanpa simbol)</label>
                        <input type="text" id="usernameInput" class="mt-1 block w-full border border-gray-300 rounded-lg shadow-sm p-3 focus:ring-indigo-500 focus:border-indigo-500" placeholder="Contoh: budisanto">
                    </div>
                </div>

                <div id="notification-area" class="mt-4 h-6 text-center"></div>

                <button id="updateButton" class="w-full mt-6 bg-indigo-600 text-white py-3 rounded-lg font-semibold hover:bg-indigo-700 transition duration-150 shadow-md shadow-indigo-300">
                    Kirim Pesan (Cek Perubahan & Simpan ke DB)
                </button>
                
            </div>

            <!-- 2. Display Status Profil Saat Ini -->
            <div class="bg-white p-6 rounded-xl border border-indigo-100 shadow-lg">
                <h2 class="text-xl font-semibold text-indigo-800 border-b pb-2 mb-4">Profil Aktif (Realtime DB)</h2>
                
                <div class="space-y-2 mb-4">
                    <p class="text-gray-600"><strong>Nama Saat Ini:</strong> <span id="current-name-display" class="font-bold text-gray-800">N/A</span></p>
                    <p class="text-gray-600"><strong>Username Saat Ini:</strong> <span id="current-username-display" class="font-bold text-gray-800">N/A</span></p>
                </div>

                <h3 class="text-lg font-medium text-indigo-700 mt-6 mb-3">Riwayat Perubahan (History)</h3>
                
                <div class="bg-gray-50 border rounded-lg h-64 overflow-y-auto">
                    <ul id="history-list">
                        <li class="p-4 text-center text-gray-500">Memuat data dari Firestore...</li>
                    </ul>
                </div>
                
            </div>
        </main>
        
        <footer class="bg-gray-100 p-4 text-center text-xs text-gray-500">
            Data dilacak secara persisten menggunakan Google Firestore.
        </footer>
    </div>

</body>
</html>
