// static/js/chat_ui.js

/**
 * Gestionează scroll-ul automat la finalul listei de mesaje
 */
export let userScrolledUp = false;

/** Răspuns AI în curs (pentru logică UI). Urmărirea fundului depinde de userScrolledUp — dacă user a urcat, nu îl tragem înapoi. */
let streamingFollow = false;

export function setStreamingFollow(on) {
    streamingFollow = !!on;
}

/** La trimitere mesaj nou: reluăm auto-scroll (altfel rămâne blocat pe vechiul userScrolledUp). */
export function resetUserScrollState() {
    userScrolledUp = false;
}

export function removeTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

/** Indicator „gândește” imediat sub ultimul mesaj user, deasupra locului răspunsului AI. */
export function appendTypingIndicator() {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) return;
    removeTypingIndicator();
    const typingDiv = document.createElement('div');
    typingDiv.id = 'typing-indicator';
    typingDiv.className = 'bot-msg msg-bubble typing-indicator-bubble';
    typingDiv.innerHTML = `
        <div class="typing">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>`;
    chatBox.appendChild(typingDiv);
    scrollBottom();
}

/** Scroll forțat la fundul #chat-box (compensare subpixel + scroll anchoring). */
function scrollChatBoxToBottom() {
    const box = document.getElementById('chat-box');
    if (!box) return;

    const maxTop = Math.max(0, box.scrollHeight - box.clientHeight);
    box.scrollTop = maxTop;

    const last = box.lastElementChild;
    if (last) {
        try {
            last.scrollIntoView({ block: 'end', inline: 'nearest', behavior: 'auto' });
        } catch {
            last.scrollIntoView(false);
        }
    }
}

export function scrollBottom() {
    if (userScrolledUp) return;

    const apply = () => {
        if (streamingFollow) {
            scrollChatBoxToBottom();
        } else {
            const box = document.getElementById('chat-box');
            if (!box) return;
            box.scrollTo({
                top: Math.max(0, box.scrollHeight - box.clientHeight),
                behavior: 'smooth',
            });
        }
    };

    apply();
    requestAnimationFrame(() => {
        apply();
        requestAnimationFrame(apply);
    });
}

/**
 * Creează și injectează o bulă de chat în DOM
 */
export function createBubble(role, content = '', isHTML = false) {
    const box = document.getElementById('chat-box');
    const bubble = document.createElement('div');
    bubble.className = `msg-bubble ${role === 'user' ? 'user-msg' : 'bot-msg'}`;

    const textDiv = document.createElement('div');
    textDiv.className = 'msg-content';

    if (content) {
        if (isHTML) textDiv.innerHTML = content;
        else textDiv.textContent = content;
    } else {
        // Placeholder pentru starea de "typing"
        textDiv.innerHTML = `
    <div class="typing">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    </div>`;
    }

    bubble.appendChild(textDiv);
    box.appendChild(bubble);
    scrollBottom();
    return bubble;
}

/**
 * Adaugă butonul de salvare tip .txt pentru răspunsurile asistentului
 */
export function addSaveButton(bubble) {
    if (bubble.querySelector('.save-btn')) return;
    const saveBtn = document.createElement('a');
    saveBtn.href = '#';
    saveBtn.className = 'save-btn text-muted d-block mt-2 text-decoration-none';
    saveBtn.style.fontSize = '0.7rem';
    saveBtn.textContent = '💾 Salvează răspunsul (.txt)';

    saveBtn.onclick = (e) => {
        e.preventDefault();
        const text = bubble.querySelector('.msg-content').innerText.trim();
        if (!text) return;
        const blob = new Blob(['\ufeff' + text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `s366-export-${new Date().getTime()}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    };
    bubble.appendChild(saveBtn);
}

// Exemplu de apel în chat_ui.js
function showTypingIndicator() {
    const chatBox = document.getElementById('chat-box');
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble bot-msg typing-indicator-bubble'; // Adaugă o clasă extra pentru control
    bubble.id = 'typing-bubble';

    bubble.innerHTML = `
        <div class="typing">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;

    chatBox.appendChild(bubble);
    scrollBottom();
}

function renderCodeBlock(code, language = 'text') {
    const pre = document.createElement('pre');
    pre.className = `language-${language}`;
    const codeEl = document.createElement('code');
    codeEl.className = `language-${language}`;
    codeEl.textContent = code;
    pre.appendChild(codeEl);

    // Adaugă copy button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-code-btn';
    copyBtn.textContent = 'Copy';
    copyBtn.onclick = () => {
        navigator.clipboard.writeText(code);
        copyBtn.textContent = 'Copied!';
        setTimeout(() => copyBtn.textContent = 'Copy', 2000);
    };
    pre.appendChild(copyBtn);

    return pre;
}


function initScrollDetection() {
    const chatBox = document.getElementById('chat-box');
    if (!chatBox) return;

    let debounceTimeout = null;
    let touchStartY = 0;
    let lastScrollTop = chatBox.scrollTop;

    // Distanța de la fund nu e suficientă în timpul streamului (conținutul crește fără scrollTop să urmărească) — folosim și „scrollTop a scăzut” = user a urcat.
    chatBox.addEventListener('scroll', () => {
        clearTimeout(debounceTimeout);

        debounceTimeout = setTimeout(() => {
            const st = chatBox.scrollTop;
            const distanceFromBottom = chatBox.scrollHeight - st - chatBox.clientHeight;

            // Nu folosi doar distanceFromBottom mare: la creșterea conținutului în stream, fără scrollTop actualizat încă, ar opri urmărirea pe fals.
            if (lastScrollTop >= 0 && st < lastScrollTop - 2) {
                userScrolledUp = true;
            } else if (distanceFromBottom < 40) {
                userScrolledUp = false;
            }
            lastScrollTop = st;
        }, 40);
    }, { passive: true });

    chatBox.addEventListener(
        'wheel',
        (e) => {
            if (e.deltaY < -2) userScrolledUp = true;
            if (e.deltaY > 2) {
                const d = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight;
                if (d < 48) userScrolledUp = false;
            }
        },
        { passive: true },
    );

    chatBox.addEventListener('touchstart', (e) => {
        touchStartY = e.touches[0].clientY;
    }, { passive: true });

    chatBox.addEventListener('touchmove', (e) => {
        if (e.touches.length !== 1) return;

        const touchCurrentY = e.touches[0].clientY;
        const deltaY = touchCurrentY - touchStartY;

        if (deltaY > 25) {
            userScrolledUp = true;
        }
    }, { passive: true });

    chatBox.addEventListener('touchend', () => {
        clearTimeout(debounceTimeout);

        debounceTimeout = setTimeout(() => {
            const distanceFromBottom = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight;
            if (distanceFromBottom < 40) {
                userScrolledUp = false;
            }
        }, 120);
    }, { passive: true });

    // În timpul streamului: auto-scroll doar dacă user nu a ales să citească mai sus.
    let moRaf = 0;
    const mo = new MutationObserver(() => {
        if (!streamingFollow || userScrolledUp) return;
        if (moRaf) return;
        moRaf = requestAnimationFrame(() => {
            moRaf = 0;
            if (!streamingFollow || userScrolledUp) return;
            scrollChatBoxToBottom();
        });
    });
    mo.observe(chatBox, { childList: true, subtree: true });
}
// Pornim inițializarea
initScrollDetection();


import { enhanceCodeBlocks, highlightPrismIn } from './streaming.js';
import { typesetMathInElement } from './math_markdown.js';

// 1. Funcția care pornește "Paznicul"
function startObservingChat() {
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) return;

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                // Verificăm dacă nodul adăugat este un element HTML
                if (node.nodeType === 1) { 
                    // Dacă e un <pre> sau conține unul, îi punem butoane
                    if (node.tagName === 'PRE' || node.querySelector('pre')) {
                        enhanceCodeBlocks(chatContainer);
                        highlightPrismIn(chatContainer);
                    }
                }
            });
        });
    });

    // Începem monitorizarea
    observer.observe(chatContainer, { childList: true, subtree: true });
    
    // 2. Executăm o dată MANUAL pentru mesajele care sunt DEJA în pagină la Refresh
    enhanceCodeBlocks(chatContainer);
    highlightPrismIn(chatContainer);
    typesetMathInElement(chatContainer);
}

// Pornim totul când s-a încărcat DOM-ul
document.addEventListener('DOMContentLoaded', startObservingChat);