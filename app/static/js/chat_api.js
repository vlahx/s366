// static/js/chat_api.js
import { createBubble, scrollBottom } from './chat_ui.js';
import { addToBuffer, setStreamingStatus, startTicker, clearBuffer } from './streaming.js';

/**
 * Trimite mesajul (text sau audio) către server și procesează stream-ul
 */
export async function handleUnifiedChat(textInput = null, audioBlob = null, activeConvId) {
    let payload = { conversation_uuid: activeConvId };
    let userBubble = null;

    // 1. Pregătire Payload & Feedback UI
    if (audioBlob) {
        payload.audio_b64 = await blobToBase64(audioBlob);
        userBubble = createBubble('user', '... se procesează vocea ...');
    } else {
        if (!textInput) return;
        payload.message = textInput;
        createBubble('user', textInput);
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
        setStreamingStatus(true);

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
    } catch (err) {
        console.error('[chat_api] Fetch error:', err);
    } finally {
        setStreamingStatus(false);
        window.chatBuffer = "";
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