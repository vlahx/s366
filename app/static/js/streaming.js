// static/js/streaming.js
import { scrollBottom, addSaveButton, userScrolledUp } from './chat_ui.js';

let messageBuffer = "";
let isPrinting = false;
let isStreamingActive = false;
const DISPLAY_SPEED = 15;

/**
 * Curăță indicatorul de gândire
 */
const removeTypingIndicator = () => {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.remove();
    }
};

/**
 * Pornește efectul de ticker (dactilografiere)
 */
export function startTicker(container) {
    if (isPrinting) return;
    isPrinting = true;
    let rawTextSoFar = "";

    // Configurăm marked global (asumăm că e deja încărcat în chat.html)
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false,
            sanitize: false,
            smartLists: true
        });
    }

    let interval = setInterval(() => {
        if (messageBuffer.length > 0) {
            removeTypingIndicator();

            const char = messageBuffer.charAt(0);
            messageBuffer = messageBuffer.substring(1);
            rawTextSoFar += char;

            if (typeof marked !== 'undefined') {
                // 1. Curățăm eventualele tag-uri <p> puse eronat de model în jurul codului
                let cleanText = rawTextSoFar.replace(/<p>```/g, "```").replace(/```<\/p>/g, "```");

                // 2. Logica de auto-închidere backticks pentru randare corectă în timpul streaming-ului
                let textToRender = cleanText;
                const backtickCount = (cleanText.match(/```/g) || []).length;
                if (backtickCount % 2 !== 0) {
                    textToRender += "\n```";
                }

                // 3. Randăm rezultatul
                container.innerHTML = marked.parse(textToRender);
            } else {
                // Fallback dacă marked nu e disponibil
                container.textContent = rawTextSoFar;
            }

            scrollBottom();
        } else if (!isStreamingActive) {
            clearInterval(interval);
            isPrinting = false;
            removeTypingIndicator();
            addSaveButton(container.parentElement);

            // Resetăm flag-ul după ce mesajul s-a terminat complet
            //console.log('Mesaj terminat → resetăm flag-ul auto-scroll');
        }
    }, DISPLAY_SPEED);
}

// Getters și Setters
export const setStreamingStatus = (status) => { isStreamingActive = status; };

/**
 * Adaugă chunk-ul primit de la server în buffer
 */
export const addToBuffer = (chunk) => {
    if (chunk && chunk.length > 0) {
        removeTypingIndicator();
        messageBuffer += chunk;
    }
};

/**
 * Resetează buffer-ul pentru un mesaj nou
 */
export const clearBuffer = () => {
    messageBuffer = "";
};