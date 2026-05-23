// static/js/streaming.js
import {
    scrollBottom,
    addSaveButton,
    removeTypingIndicator,
    setStreamingFollow,
} from './chat_ui.js';
import { renderMarkdownWithMath, typesetMathInElement } from './math_markdown.js';

let messageBuffer = "";
let isPrinting = false;
let isStreamingActive = false;
let tickerIntervalId = null;
const DISPLAY_SPEED = 20; // Am mărit puțin viteza pentru fluiditate pe Xeon

function stopTickerInterval() {
    if (tickerIntervalId !== null) {
        clearInterval(tickerIntervalId);
        tickerIntervalId = null;
    }
}

export function startTicker(container) {
    // Oprește orice interval vechi; altfel isPrinting poate rămâne true fără ticker activ
    // și următorul mesaj face return la „if (isPrinting)” → buffer neluat, Send blocat (isSubmitting).
    stopTickerInterval();
    isPrinting = true;

    // Resetăm containerul vizual înainte de a începe
    container.innerHTML = "";
    let rawTextSoFar = "";

    tickerIntervalId = setInterval(() => {
        if (messageBuffer.length > 0) {
            removeTypingIndicator();

            // 1. GESTIONARE TAG-URI (Logica de "Sifon")
            if (messageBuffer[0] === '<') {
                const closingBracketIndex = messageBuffer.indexOf('>');
                if (closingBracketIndex === -1) {
                    // Dacă avem un tag incomplet, verificăm dacă stream-ul s-a oprit
                    // Dacă s-a oprit și tot e incomplet, îl scoatem forțat ca text
                    if (!isStreamingActive) {
                        const char = messageBuffer.charAt(0);
                        rawTextSoFar += char;
                        messageBuffer = messageBuffer.substring(1);
                    }
                    return; // Așteptăm restul tag-ului
                }

                const fullTag = messageBuffer.substring(0, closingBracketIndex + 1);
                rawTextSoFar += fullTag;
                messageBuffer = messageBuffer.substring(closingBracketIndex + 1);
            } else {
                // 2. TEXT NORMAL
                const char = messageBuffer.charAt(0);
                rawTextSoFar += char;
                messageBuffer = messageBuffer.substring(1);
            }

            try {
                container.innerHTML = renderMarkdownWithMath(rawTextSoFar);
            } catch (e) {
                console.warn('[streaming] renderMarkdownWithMath:', e);
                container.textContent = rawTextSoFar;
            }
            enhanceCodeBlocks(container);
            scrollBottom();

        } else if (!isStreamingActive) {
            // FINISH: Buffer gol și stream închis
            stopTickerInterval();
            isPrinting = false;
            removeTypingIndicator();
            enhanceCodeBlocks(container);
            highlightPrismIn(container);
            typesetMathInElement(container);
            addSaveButton(container.parentElement);
            scrollBottom();
            setStreamingFollow(false);
            messageBuffer = "";
        }
    }, DISPLAY_SPEED);
}

// Getters și Setters
export const setStreamingStatus = (status) => { isStreamingActive = status; };

export const addToBuffer = (chunk) => {
    if (chunk) {
        messageBuffer += chunk;
        // Opțional: dacă ticker-ul a murit accidental, îl poți reporni aici
    }
};

export const clearBuffer = () => {
    stopTickerInterval();
    messageBuffer = "";
    isPrinting = false;
};

/** Așteaptă până ticker-ul a golit bufferul după închiderea streamului (pentru citire DOM / LocalStorage). */
export function waitForStreamIdle(maxMs = 120000) {
    return new Promise((resolve) => {
        const t0 = Date.now();
        const tick = () => {
            const idle = !isPrinting && messageBuffer.length === 0 && !isStreamingActive;
            if (idle) {
                resolve();
                return;
            }
            if (Date.now() - t0 > maxMs) {
                resolve();
                return;
            }
            setTimeout(tick, 40);
        };
        tick();
    });
}

/** Prism rulează la DOMContentLoaded; mesajele din stream / istoric trebuie highlight după HTML nou. */
export function highlightPrismIn(container) {
    if (typeof Prism === 'undefined' || !container?.querySelectorAll) return;
    container.querySelectorAll('code[class*="language-"]').forEach((el) => {
        try {
            Prism.highlightElement(el);
        } catch (e) {
            console.warn('[streaming] Prism.highlightElement:', e);
        }
    });
}

/**
 * Injectează butoane de Copy/Run în blocurile de cod
 */
export function enhanceCodeBlocks(container) {
    const blocks = container.querySelectorAll('pre');
    
    blocks.forEach(block => {
    // 1. Verificăm dacă am pus deja butoanele (să nu le dublăm)
    if (block.querySelector('.code-actions')) return;

    const actionContainer = document.createElement('div');
    actionContainer.className = 'code-actions';
    
    // Luăm referința la elementul de cod
    const codeElement = block.querySelector('code');
    if (!codeElement) return;

    // --- Butonul de COPY (Pentru orice tip de cod) ---
    const copyBtn = document.createElement('button');
    copyBtn.innerHTML = '📋 Copiază';
    copyBtn.onclick = () => {
        const code = codeElement.innerText;
        navigator.clipboard.writeText(code);
        copyBtn.innerHTML = '✅ Copiat!';
        setTimeout(() => copyBtn.innerHTML = '📋 Copiază', 2000);
    };
    actionContainer.appendChild(copyBtn);

    // --- Butonul de RUN (Doar pentru HTML/CSS/JS) ---
    // Verificăm dacă marked a pus clasa language-html sau dacă textul pare a fi HTML
    const isHTML = codeElement.classList.contains('language-html') || 
                   codeElement.innerText.trim().startsWith('<!DOCTYPE html>') ||
                   codeElement.innerText.trim().startsWith('<html');

    if (isHTML) {
        const runBtn = document.createElement('button');
        runBtn.innerHTML = '🚀 Execută';
        runBtn.style.marginLeft = '5px'; // Puțin spațiu față de Copy
        runBtn.onclick = () => {
            const code = codeElement.innerText;
            // Creăm un Blob (obiect binar) pentru a simula un fișier .html
            const blob = new Blob([code], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank'); // Deschide rezultatul într-un tab nou
            // Curățăm URL-ul după o scurtă perioadă pentru a nu ocupa memorie
            setTimeout(() => URL.revokeObjectURL(url), 10000);
        };
        actionContainer.appendChild(runBtn);
    }

    block.style.position = 'relative'; 
    block.appendChild(actionContainer);
});
}