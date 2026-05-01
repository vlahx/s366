// static/js/chat_api.js
import {
    createBubble,
    appendTypingIndicator,
    removeTypingIndicator,
    setStreamingFollow,
} from './chat_ui.js';
import { addToBuffer, setStreamingStatus, startTicker, clearBuffer, waitForStreamIdle } from './streaming.js';

/**
 * Trimite mesajul (text sau audio) către server și procesează stream-ul
 */
export async function handleUnifiedChat(textInput = null, audioBlob = null, activeConvId, options = {}) {
    const { conversationHistory = [] } = options;
    let payload = { conversation_uuid: activeConvId };
    if (conversationHistory && conversationHistory.length > 0) {
        payload.conversation_history = conversationHistory;
    }
    let userBubble = null;

    // 1. Pregătire Payload & Feedback UI
    if (audioBlob) {
        payload.audio_b64 = await blobToBase64(audioBlob);
        userBubble = createBubble('user', '... se procesează vocea ...');
        appendTypingIndicator();
    } else {
        if (!textInput) return;
        payload.message = textInput;
        createBubble('user', textInput);
        appendTypingIndicator();
    }

    try {
        const res = await fetch('/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        let botBubble = null;
        let contentDiv = null;
        let isFirstChunk = true;
        clearBuffer(); // curăță starea ticker între cereri (evită isPrinting „agățat”)
        setStreamingStatus(true);
        setStreamingFollow(true);

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });

            // Reconstituire linii JSON (logică buffer fragmentat)
            let partialLine = (window.chatBuffer || "") + chunk;
            const lines = partialLine.split('\n');
            window.chatBuffer = lines.pop(); // Păstrăm ultima bucată incompletă

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);

                    // A. Update Transcriere (Whisper)
                    if (data.user_transcription && userBubble) {
                        userBubble.querySelector('.msg-content').textContent = data.user_transcription;
                    }

                    // B. Generare Text (LLM)
                    if (data.content) {
                        if (!botBubble) {
                            botBubble = createBubble('assistant');
                            contentDiv = botBubble.querySelector('.msg-content');

                        }
                        if (isFirstChunk) {
                            contentDiv.innerHTML = '';
                            isFirstChunk = false;
                            startTicker(contentDiv);
                        }
                        addToBuffer(data.content);
                    }

                    // C. Redare Audio (Piper)
                    if (data.audio_payload) {
                        // Vom importa funcția asta din audio_handler imediat
                        window.dispatchEvent(new CustomEvent('play-audio', { detail: data.audio_payload }));
                    }
                } catch (e) {
                    console.error("[chat_api] Eroare parsare linie:", e);
                }
            }
        }

        // Stream închis fără niciun chunk LLM: nu pornește ticker-ul
        if (isFirstChunk) {
            removeTypingIndicator();
            setStreamingFollow(false);
        }
        // IMPORTANT: oprește streamul ÎNAINTE de waitForStreamIdle. Ticker-ul din streaming.js
        // golește bufferul doar până la final când !isStreamingActive; dacă false vine doar în finally
        // (după await), rămâne deadlock / timeout 120s sau persist citește DOM-ul parțial (doar ce s-a „tipărit”).
        setStreamingStatus(false);
        await waitForStreamIdle();
    } catch (err) {
        console.error('[chat_api] Fetch error:', err);
        removeTypingIndicator();
        setStreamingFollow(false);
        setStreamingStatus(false);
        await waitForStreamIdle();
    } finally {
        setStreamingStatus(false);
        clearBuffer();
        window.chatBuffer = '';
    }
}

// Helper intern
function blobToBase64(blob) {
    return new Promise((res) => {
        const r = new FileReader();
        r.onloadend = () => res(r.result.split(',')[1]);
        r.readAsDataURL(blob);
    });
}