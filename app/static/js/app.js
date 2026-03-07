// static/js/app.js

// 1. IMPORTURI
import { createBubble, scrollBottom } from './chat_ui.js';
import { startTicker, addToBuffer, setStreamingStatus, clearBuffer } from './streaming.js';
import { startRecording, stopRecording, playAudioFromBase64 } from './voice_handler.js';
import { handleUnifiedChat } from './chat_api.js';
import { renderSessions, switchConversation } from './sidebar.js';

// 2. STARE GLOBALĂ
const STORAGE_KEY = 's366_active_conv';
let activeConvId = localStorage.getItem(STORAGE_KEY) || null;

// 3. FUNCȚII HELPER
function initMobileSidebar() {
    const sidebar = document.querySelector('#sidebar-left');
    const hamburgerBtn = document.querySelector('#sidebar-hamburger');
    const chatContainer = document.querySelector('#chat-container');

    if (chatContainer && sidebar) {
        chatContainer.addEventListener('click', () => {
            if (sidebar.classList.contains('show') && window.innerWidth < 992) {
                sidebar.classList.remove('show');
            }
        });
    }

    if (sidebar) {
        sidebar.addEventListener('click', (e) => {
            if (e.target.closest('.session-btn') || e.target.closest('.session-title') || e.target.closest('#new-chat-btn')) {
                if (window.innerWidth < 992) {
                    sidebar.classList.remove('show');
                }
            }
        });
    }

    if (hamburgerBtn && sidebar) {
        hamburgerBtn.replaceWith(hamburgerBtn.cloneNode(true));
        const newBtn = document.querySelector('#sidebar-hamburger');
        newBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            sidebar.classList.toggle('show');
        });
    }
}

// 4. LOGICA DE URGENȚĂ
window.addEventListener('play-audio', (e) => {
    playAudioFromBase64(e.detail);
});

// 5. INIȚIALIZARE DOM
window.addEventListener('DOMContentLoaded', () => {
    //console.log("[s366_turbo] Sistem modular activat!");

    const pttBtn = document.getElementById('ptt-voice-btn');
    const micIcon = pttBtn ? pttBtn.querySelector('i') : null;
    const chatForm = document.getElementById('chat-form');
    const textarea = document.getElementById('user-input');
    const newChatBtn = document.getElementById('new-chat-btn');
    const chatBox = document.getElementById('chat-box');

    initMobileSidebar();

    // --- A. GESTIUNE SESIUNI ---
    const handleSwitch = (uuid) => {
        switchConversation(uuid, (newId) => {
            activeConvId = newId;
            localStorage.setItem(STORAGE_KEY, newId);
            renderSessions(activeConvId, handleSwitch);
        });
    };

    const startNewChat = () => {
        activeConvId = crypto.randomUUID();
        localStorage.setItem(STORAGE_KEY, activeConvId);
        if (chatBox) chatBox.innerHTML = '';
        createBubble('assistant', 'Salut, frate! Sesiune nouă pe s366_turbo.');
        renderSessions(activeConvId, handleSwitch);
    };

    if (newChatBtn) newChatBtn.onclick = startNewChat;

    // Inițializare Sidebar la start
    renderSessions(activeConvId, handleSwitch);

    if (activeConvId) {
        handleSwitch(activeConvId);
    } else {
        createBubble('assistant', 'Bună! Sunt gata să te ajut pe noul motor Turbo.');
    }

    // --- B. INPUT ȘI EVENIMENTE ---
    if (textarea) {
        textarea.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        });

        textarea.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                chatForm.dispatchEvent(new Event('submit'));
            }
        });
    }

    // În app.js, în interiorul chatForm.addEventListener('submit', ...)

    // static/js/app.js

    // Definirea flag-ului în afara oricărei funcții, sus de tot
    let isSubmitting = false;

    if (chatForm) {
        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            // 1. Verificare imediată
            if (isSubmitting) return;

            const text = textarea.value.trim();
            if (!text) return;

            // 2. Blocare
            isSubmitting = true;
            const sendBtn = document.getElementById('send-btn'); // Asigură-te că butonul are ID-ul ăsta
            if (sendBtn) sendBtn.disabled = true;

            try {
                // VERIFICARE: Dacă nu avem sesiune, facem una ACUM (preventiv)
                if (!activeConvId) {
                    activeConvId = crypto.randomUUID();
                    localStorage.setItem(STORAGE_KEY, activeConvId);
                    //console.log("Generat UUID nou pentru sesiune goală:", activeConvId);
                }

                textarea.value = '';
                textarea.style.height = 'auto';

                const chatBox = document.getElementById('chat-box');
                const typingDiv = document.createElement('div');
                typingDiv.id = 'typing-indicator';
                typingDiv.className = 'bot-msg msg-bubble';
                typingDiv.innerHTML = `
                    <div class="typing">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                `;

                chatBox.append(typingDiv);
                scrollBottom();

                // 5. API Call - acum suntem SIGURI că activeConvId nu e null
                await handleUnifiedChat(text, null, activeConvId);

            } catch (err) {
                console.error("Eroare:", err);
                const indicator = document.getElementById('typing-indicator');
                if (indicator) indicator.remove();
            } finally {
                // 6. Deblocare
                isSubmitting = false;
                if (sendBtn) sendBtn.disabled = false;

                setTimeout(() => {
                    renderSessions(activeConvId, handleSwitch);
                }, 800);
            }
        });
    }

    if (pttBtn) {
        pttBtn.addEventListener('mousedown', () => startRecording(pttBtn, micIcon));
        window.addEventListener('mouseup', () => stopRecording(pttBtn, micIcon));
        pttBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(pttBtn, micIcon); });
        pttBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(pttBtn, micIcon); });
    }
});

export { activeConvId, STORAGE_KEY };