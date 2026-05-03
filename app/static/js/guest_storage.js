/**
 * Conversații vizitator (fără cont): listă + mesaje în LocalStorage — fără SQLite pe server.
 * (Fără import din chat_ui.js — evită ciclul chat_ui ↔ streaming ↔ chat_ui la încărcare.)
 */
const STORE_KEY = 's366_guest_conversations_v1';

/** Ultimul schimb user → assistant din #chat-box (după stream). Caută ultimul răspuns bot real, apoi user-ul din fața lui. */
function readLastGuestExchangeFromDom() {
    const box = document.getElementById('chat-box');
    if (!box) return null;
    const bubbles = [...box.querySelectorAll('.msg-bubble')];
    if (bubbles.length < 2) return null;

    let botIdx = -1;
    for (let i = bubbles.length - 1; i >= 0; i--) {
        const el = bubbles[i];
        if (!el.classList.contains('bot-msg')) continue;
        const content = el.querySelector('.msg-content');
        if (!content) continue;
        if (content.querySelector('.typing')) continue;
        const html = content.innerHTML || '';
        if (!html.trim()) continue;
        botIdx = i;
        break;
    }
    if (botIdx < 1) return null;

    let userIdx = -1;
    for (let j = botIdx - 1; j >= 0; j--) {
        if (bubbles[j].classList.contains('user-msg')) {
            userIdx = j;
            break;
        }
    }
    if (userIdx < 0) return null;

    const u = bubbles[userIdx].querySelector('.msg-content');
    const a = bubbles[botIdx].querySelector('.msg-content');
    if (!u || !a) return null;
    const userText = (u.textContent || '').trim();
    const assistantHtml = a.innerHTML || '';
    if (!userText || !assistantHtml.trim()) return null;
    return { userText, assistantHtml };
}

/** Mesaj afișat la conversație nouă / thread gol (vizitator) — îndemn la autentificare. */
export const GUEST_NEW_THREAD_MSG =
    'Salutare! Ai început o conversație nouă. Îți recomandăm autentificarea: același istoric pe orice dispozitiv și organizare clară în cont. Fără cont, mesajele se păstrează doar în acest browser (local), util pentru o probă rapidă.';

export function isChatLoggedIn() {
    const v = (document.getElementById('wrapper')?.dataset.loggedIn || '').toLowerCase();
    return v === 'true' || v === '1';
}

export function loadGuestStore() {
    try {
        const raw = localStorage.getItem(STORE_KEY);
        if (!raw) return { sessions: [], messages: {} };
        const data = JSON.parse(raw);
        if (!data.sessions) data.sessions = [];
        if (!data.messages) data.messages = {};
        repairGuestStoreSessions(data);
        return data;
    } catch {
        return { sessions: [], messages: {} };
    }
}

/** Dacă există mesaje dar lipsește rândul în sessions (date vechi / incomplete), îl refacem. */
function repairGuestStoreSessions(store) {
    let changed = false;
    for (const uuid of Object.keys(store.messages || {})) {
        const msgs = store.messages[uuid];
        if (!msgs || msgs.length === 0) continue;
        if (!store.sessions.some((s) => s.conversation_uuid === uuid)) {
            store.sessions.push({
                conversation_uuid: uuid,
                title: 'Conversație nouă',
                pinned: 0,
                updatedAt: Date.now(),
            });
            changed = true;
        }
    }
    if (changed) saveGuestStore(store);
}

export function saveGuestStore(store) {
    try {
        localStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch (e) {
        console.warn('[guest_storage] Nu s-a putut salva LocalStorage:', e);
    }
}

export function ensureGuestSession(store, uuid, title = 'Conversație nouă') {
    let s = store.sessions.find((x) => x.conversation_uuid === uuid);
    if (!s) {
        s = {
            conversation_uuid: uuid,
            title,
            pinned: 0,
            updatedAt: Date.now(),
        };
        store.sessions.push(s);
    }
    if (!store.messages[uuid]) store.messages[uuid] = [];
    saveGuestStore(store);
    return s;
}

/** Listează sesiunile în forma așteptată de sidebar (ca API). */
export function guestSessionsForSidebar(store) {
    const list = [...store.sessions].sort((a, b) => {
        if (a.pinned !== b.pinned) return (b.pinned || 0) - (a.pinned || 0);
        return (b.updatedAt || 0) - (a.updatedAt || 0);
    });
    return list.map((s) => ({
        conversation_uuid: s.conversation_uuid,
        title: s.title || 'Conversație nouă',
        pinned: s.pinned || 0,
    }));
}

export function getGuestMessages(store, uuid) {
    return store.messages[uuid] || [];
}

/** Mesaje {sender, message} → istoric pentru LLM (text simplu). */
export function guestMessagesToConversationHistory(msgs) {
    const out = [];
    for (const m of msgs) {
        const role = m.sender === 'user' ? 'user' : 'assistant';
        let content = (m.message || '').trim();
        if (!content) continue;
        if (role === 'assistant') {
            const tmp = document.createElement('div');
            tmp.innerHTML = content;
            content = (tmp.textContent || tmp.innerText || '').trim();
        }
        if (!content) continue;
        out.push({ role, content });
    }
    return out;
}

export function appendGuestMessages(store, uuid, userText, assistantHtml) {
    ensureGuestSession(store, uuid);
    const arr = store.messages[uuid] || [];
    arr.push({ sender: 'user', message: userText });
    arr.push({ sender: 'assistant', message: assistantHtml });
    store.messages[uuid] = arr;
    const s = store.sessions.find((x) => x.conversation_uuid === uuid);
    if (s) s.updatedAt = Date.now();
    saveGuestStore(store);
}

export function deleteGuestSession(store, uuid) {
    store.sessions = store.sessions.filter((x) => x.conversation_uuid !== uuid);
    delete store.messages[uuid];
    saveGuestStore(store);
}

export function renameGuestSession(store, uuid, title) {
    const s = store.sessions.find((x) => x.conversation_uuid === uuid);
    if (s) {
        s.title = title;
        saveGuestStore(store);
        return true;
    }
    return false;
}

export function toggleGuestPin(store, uuid) {
    const s = store.sessions.find((x) => x.conversation_uuid === uuid);
    if (!s) return false;
    s.pinned = s.pinned ? 0 : 1;
    saveGuestStore(store);
    return true;
}

/** După un răspuns reușit: salvează ultimul user+assistant din DOM în LocalStorage. */
export function persistGuestTurnIfNeeded(uuid, loggedIn) {
    if (loggedIn || !uuid) return;
    const ex = readLastGuestExchangeFromDom();
    if (!ex || !ex.userText) return;
    const st = loadGuestStore();
    appendGuestMessages(st, uuid, ex.userText, ex.assistantHtml);
}
