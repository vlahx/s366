// static/js/app.js

// 1. IMPORTURI
import { createBubble, resetUserScrollState } from './chat_ui.js';
import { startRecording, stopRecording, playAudioFromBase64 } from './voice_handler.js';
import { handleUnifiedChat } from './chat_api.js';
import { renderSessions, switchConversation } from './sidebar.js';
import {
    loadGuestStore,
    ensureGuestSession,
    getGuestMessages,
    guestMessagesToConversationHistory,
    persistGuestTurnIfNeeded,
    GUEST_NEW_THREAD_MSG,
} from './guest_storage.js';

// 2. STARE GLOBALĂ
const STORAGE_KEY = 's366_active_conv';
let activeConvId = localStorage.getItem(STORAGE_KEY) || null;

// 3. FUNCȚII HELPER
function initMobileSidebar() {
    const sidebar = document.querySelector('#sidebar-left');
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

    // Delegare pe document: evită pierderea listenerului (clone/re-render) și trece peste straturi care blochează bubble-ul
    document.body.addEventListener(
        'click',
        (e) => {
            const btn = e.target.closest('#sidebar-hamburger');
            if (!btn || !sidebar) return;
            if (window.innerWidth >= 992) return;
            e.preventDefault();
            e.stopPropagation();
            sidebar.classList.toggle('show');
        },
        true,
    );
}

// 4. LOGICA DE URGENȚĂ
window.addEventListener('play-audio', (e) => {
    playAudioFromBase64(e.detail);
});

// 5. INIȚIALIZARE DOM
window.addEventListener('DOMContentLoaded', () => {
    //console.log("[S366 AI] Sistem modular activat!");

    const pttBtn = document.getElementById('ptt-voice-btn');
    const micIcon = pttBtn ? pttBtn.querySelector('i') : null;
    const chatForm = document.getElementById('chat-form');
    const textarea = document.getElementById('user-input');
    const newChatBtn = document.getElementById('new-chat-btn');
    const chatBox = document.getElementById('chat-box');
    const wrapper = document.getElementById('wrapper');
    const isLoggedIn =
        ((wrapper?.dataset.loggedIn || '') + '').toLowerCase() === 'true' ||
        (wrapper?.dataset.loggedIn || '') === '1';

    initMobileSidebar();

    // --- A. GESTIUNE SESIUNI ---
    const handleSwitch = (uuid) => {
        switchConversation(uuid, (newId) => {
            activeConvId = newId;
            localStorage.setItem(STORAGE_KEY, newId);
            renderSessions(activeConvId, handleSwitch);
        });
    };

    window.__s366ChatAfterGuestTurn = () => {
        renderSessions(activeConvId, handleSwitch);
    };

    const welcomeGuestFirst =
        'Bună! Sunt gata să te ajut cu S366 AI. Autentifică-te pentru același istoric pe orice dispozitiv; fără cont, discuțiile rămân doar în acest browser (local).';

    const startNewChat = () => {
        activeConvId = crypto.randomUUID();
        localStorage.setItem(STORAGE_KEY, activeConvId);
        if (chatBox) chatBox.innerHTML = '';
        if (isLoggedIn) {
            createBubble(
                'assistant',
                'Salutare! Ai deschis o sesiune nouă. Redenumește conversația în sidebar când ai terminat, ca să o regăsești ușor.',
            );
        } else {
            const st = loadGuestStore();
            ensureGuestSession(st, activeConvId);
            if (!st.messages[activeConvId]) st.messages[activeConvId] = [];
            createBubble('assistant', GUEST_NEW_THREAD_MSG, false);
        }
        renderSessions(activeConvId, handleSwitch);
    };

    if (newChatBtn) newChatBtn.onclick = startNewChat;

    // Inițializare Sidebar la start
    renderSessions(activeConvId, handleSwitch);

    if (activeConvId) {
        handleSwitch(activeConvId);
    } else {
        const welcome = 'Bună! Sunt gata să te ajut cu S366 AI.';
        createBubble('assistant', isLoggedIn ? welcome : welcomeGuestFirst, false);
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
                resetUserScrollState();

                // VERIFICARE: Dacă nu avem sesiune, facem una ACUM (preventiv)
                if (!activeConvId) {
                    activeConvId = crypto.randomUUID();
                    localStorage.setItem(STORAGE_KEY, activeConvId);
                }
                if (!isLoggedIn) {
                    const st = loadGuestStore();
                    ensureGuestSession(st, activeConvId);
                    await renderSessions(activeConvId, handleSwitch);
                }

                textarea.value = '';
                textarea.style.height = 'auto';

                const chatOpts = {};
                if (!isLoggedIn) {
                    const st = loadGuestStore();
                    const hist = guestMessagesToConversationHistory(getGuestMessages(st, activeConvId));
                    if (hist.length) chatOpts.conversationHistory = hist;
                }

                await handleUnifiedChat(text, null, activeConvId, chatOpts);
                if (!isLoggedIn) {
                    persistGuestTurnIfNeeded(activeConvId, isLoggedIn);
                    await renderSessions(activeConvId, handleSwitch);
                }

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