// static/js/voice_handler.js
import { handleUnifiedChat } from './chat_api.js';
import { activeConvId } from './app.js';

let mediaRecorder;
let audioChunks = [];
let micStream = null;

/**
 * Asigură accesul la microfon și inițializează MediaRecorder
 */
export async function ensureMicrophone() {
    if (!mediaRecorder || !micStream || micStream.getTracks().every(t => t.readyState === 'ended')) {
        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(micStream);

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                audioChunks = [];
                // Trimitem către API (activeConvId vine din app.js)
                await handleUnifiedChat(null, audioBlob, activeConvId);

                // Oprim hardware-ul microfonului pentru economie/privacy
                if (micStream) {
                    micStream.getTracks().forEach(track => track.stop());
                }
            };
        } catch (err) {
            console.error("[Voice] Microfon inaccesibil:", err);
            return false;
        }
    }
    return true;
}

/**
 * Pornește înregistrarea (PTT Start)
 */
export async function startRecording(pttBtn, micIcon) {
    const ready = await ensureMicrophone();
    if (!ready) return;

    if (mediaRecorder && mediaRecorder.state === "inactive") {
        audioChunks = [];
        mediaRecorder.start();
        pttBtn.classList.replace('btn-outline-primary', 'btn-danger');
        if (micIcon) micIcon.classList.replace('bi-mic-fill', 'bi-mic-mute-fill');
    }
}

/**
 * Oprește înregistrarea (PTT Stop)
 */
export function stopRecording(pttBtn, micIcon) {
    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        pttBtn.classList.replace('btn-danger', 'btn-outline-primary');
        if (micIcon) micIcon.classList.replace('bi-mic-mute-fill', 'bi-mic-fill');
    }
}

/**
 * Redă audio primit de la Piper (Base64)
 */
export function playAudioFromBase64(b64) {
    if (!b64 || b64.length < 200) return; // Filtru zgomot

    try {
        let mimeType = b64.startsWith("GkXfo") ? "audio/webm" : "audio/wav";
        const audio = new Audio(`data:${mimeType};base64,${b64}`);
        audio.volume = 1.0;
        audio.play().catch(err => {
            console.warn("[Voice] Autoplay blocat. E nevoie de interacțiune user.");
        });
    } catch (e) {
        console.error("[Voice] Eroare redare:", e);
    }
}