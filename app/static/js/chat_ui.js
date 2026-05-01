// static/js/chat_ui.js

/**
 * Gestionează scroll-ul automat la finalul listei de mesaje
 */
export let userScrolledUp = false;

/** În timpul răspunsului AI: urmărim fundul chiar dacă user a fost sus (scroll instant). */
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
    typingDiv.className = 'bot-msg msg-bubble';
    typingDiv.innerHTML = `
        <div class="typing">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>`;
    chatBox.appendChild(typingDiv);
    scrollBottom();
}

export function scrollBottom() {
    if (!streamingFollow && userScrolledUp) return;

    const box = document.getElementById('chat-box');
    if (!box) return;

    // În timpul streamului, smooth se „întinde” mereu în urmă: folosim instant.
    if (streamingFollow) {
        box.scrollTop = box.scrollHeight;
    } else {
        box.scrollTo({
            top: box.scrollHeight,
            behavior: 'smooth'
        });
    }
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

    // Listener clasic pe scroll (bun pentru desktop și momentum)
    chatBox.addEventListener('scroll', () => {
        clearTimeout(debounceTimeout);

        debounceTimeout = setTimeout(() => {
            const distanceFromBottom = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight;

            if (distanceFromBottom > 80) {  // mai sensibil decât 100
                userScrolledUp = true;
                // console.log('Scroll detectat → oprim auto-scroll (distanță:', distanceFromBottom, 'px)');
            } else if (distanceFromBottom < 40) {
                userScrolledUp = false;
                // console.log('User jos → reluăm auto-scroll');
            }
        }, 80); // debounce mic ca să nu tremure
    }, { passive: true });

    // Detectare touch pentru mobil (esențial!)
    chatBox.addEventListener('touchstart', (e) => {
        touchStartY = e.touches[0].clientY;
    }, { passive: true });

    chatBox.addEventListener('touchmove', (e) => {
        if (e.touches.length !== 1) return;

        const touchCurrentY = e.touches[0].clientY;
        const deltaY = touchCurrentY - touchStartY;

        // Dacă trage în sus (deltaY pozitiv = scroll up pe touch)
        if (deltaY > 25) {  // 25 px e foarte sensibil pe mobil
            if (!userScrolledUp) {
                userScrolledUp = true;
                // console.log('Touch up detectat → oprim auto-scroll');
            }
        }
    }, { passive: true });

    // La touchend verificăm poziția finală (ca să repornim dacă user-ul a revenit jos)
    chatBox.addEventListener('touchend', () => {
        clearTimeout(debounceTimeout);

        debounceTimeout = setTimeout(() => {
            const distanceFromBottom = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight;
            if (distanceFromBottom < 40) {
                userScrolledUp = false;
                // console.log('Touch end – user jos → reluăm auto-scroll');
            }
        }, 120);
    }, { passive: true });
}
// Pornim inițializarea
initScrollDetection();


import { enhanceCodeBlocks } from './streaming.js';

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
                    }
                }
            });
        });
    });

    // Începem monitorizarea
    observer.observe(chatContainer, { childList: true, subtree: true });
    
    // 2. Executăm o dată MANUAL pentru mesajele care sunt DEJA în pagină la Refresh
    enhanceCodeBlocks(chatContainer);
}

// Pornim totul când s-a încărcat DOM-ul
document.addEventListener('DOMContentLoaded', startObservingChat);