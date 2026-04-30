// static/js/streaming.js
import { scrollBottom, addSaveButton } from './chat_ui.js';

let messageBuffer = "";
let isPrinting = false;
let isStreamingActive = false;
const DISPLAY_SPEED = 20; // Am mărit puțin viteza pentru fluiditate pe Xeon

const removeTypingIndicator = () => {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) indicator.remove();
};

export function startTicker(container) {
    if (isPrinting) return;
    isPrinting = true;
    
    // Resetăm containerul vizual înainte de a începe
    container.innerHTML = "";
    let rawTextSoFar = "";

    let interval = setInterval(() => {
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

    
            container.innerHTML = marked.parse(rawTextSoFar);
            enhanceCodeBlocks(container);           
            scrollBottom();

        } else if (!isStreamingActive) {
            // FINISH: Buffer gol și stream închis
            clearInterval(interval);
            isPrinting = false;
            removeTypingIndicator();
            addSaveButton(container.parentElement);
            scrollBottom();
            // Curățăm bufferul global pentru următorul mesaj
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
    messageBuffer = "";
    isPrinting = false;
};

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