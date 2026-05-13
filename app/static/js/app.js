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
import { initChatUserSettingsModal, renderMemoryL0List } from './memory_l0.js';

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
    const chatImageInput = document.getElementById('chat-image-input');
    const chatAttachBtn = document.getElementById('chat-attach-image-btn');
    const isLoggedIn =
        ((wrapper?.dataset.loggedIn || '') + '').toLowerCase() === 'true' ||
        (wrapper?.dataset.loggedIn || '') === '1';

    const MAX_VISION_ATTACH = 4;
    let pendingVisionDataUrls = [];

    function renderVisionPreviews() {
        const wrap = document.getElementById('chat-vision-previews');
        if (!wrap) return;
        wrap.innerHTML = '';
        if (!pendingVisionDataUrls.length) {
            wrap.classList.add('d-none');
            return;
        }
        wrap.classList.remove('d-none');
        pendingVisionDataUrls.forEach((url, idx) => {
            const chip = document.createElement('div');
            chip.className = 'chat-vision-chip';
            const img = document.createElement('img');
            img.src = url;
            img.alt = '';
            const rm = document.createElement('button');
            rm.type = 'button';
            rm.className = 'chat-vision-chip-remove';
            rm.dataset.i = String(idx);
            rm.setAttribute('aria-label', 'Elimină imaginea');
            rm.textContent = '×';
            chip.appendChild(img);
            chip.appendChild(rm);
            wrap.appendChild(chip);
        });
        wrap.querySelectorAll('.chat-vision-chip-remove').forEach((btn) => {
            btn.addEventListener('click', () => {
                const i = parseInt(btn.dataset.i, 10);
                if (!Number.isNaN(i)) pendingVisionDataUrls.splice(i, 1);
                renderVisionPreviews();
            });
        });
    }

    function addVisionFilesFromInput(fileList) {
        if (!fileList || !fileList.length) return;
        const files = [...fileList].filter((f) => f.type.startsWith('image/'));
        const room = MAX_VISION_ATTACH - pendingVisionDataUrls.length;
        const take = files.slice(0, Math.max(0, room));
        for (const f of take) {
            const r = new FileReader();
            r.onload = () => {
                pendingVisionDataUrls.push(r.result);
                renderVisionPreviews();
            };
            r.readAsDataURL(f);
        }
    }

    if (chatAttachBtn && chatImageInput) {
        chatAttachBtn.addEventListener('click', () => chatImageInput.click());
        chatImageInput.addEventListener('change', () => {
            if (chatImageInput.files?.length) addVisionFilesFromInput(chatImageInput.files);
            chatImageInput.value = '';
        });
    }

    initMobileSidebar();
    if (isLoggedIn) {
        initChatUserSettingsModal();
    }

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
        pendingVisionDataUrls = [];
        renderVisionPreviews();
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
            const hasVision = pendingVisionDataUrls.length > 0;
            if (!text && !hasVision) return;

            // 2. Blocare
            isSubmitting = true;
            const sendBtn = document.getElementById('send-btn'); // Asigură-te că butonul are ID-ul ăsta
            if (sendBtn) sendBtn.disabled = true;

            const visionCopy = hasVision ? [...pendingVisionDataUrls] : null;
            pendingVisionDataUrls = [];
            renderVisionPreviews();

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
                if (visionCopy && visionCopy.length) chatOpts.imagesB64 = visionCopy;

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
                if (isLoggedIn) {
                    renderMemoryL0List().catch(() => {});
                }
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