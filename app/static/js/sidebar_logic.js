// static/js/sidebar_logic.js

export async function fetchSessions() {
    try {
        const res = await fetch('/chat/api/sessions');
        if (!res.ok) throw new Error("Nu s-au putut încărca sesiunile");
        return await res.json();
    } catch (err) {
        console.error("[Sidebar] Eroare fetchSessions:", err);
        return [];
    }
}


export async function renameSessionRequest(uuid, newTitle) {
    try {
        const response = await fetch(`/chat/api/sessions/${uuid}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        return response.ok;
    } catch (err) {
        console.error("[Sidebar] Eroare renameSession:", err);
        return false;
    }
}


export async function deleteSessionRequest(uuid) {
    try {
        const response = await fetch(`/chat/api/sessions/${uuid}`, { method: 'DELETE' });
        return response.ok;
    } catch (err) {
        console.error("[Sidebar] Eroare deleteSession:", err);
        return false;
    }
}


export async function getConversationMessages(uuid) {
    try {
        const response = await fetch(`/chat/api/messages/${uuid}`);
        if (!response.ok) throw new Error("Eroare la încărcarea mesajelor");
        return await response.json();
    } catch (err) {
        console.error("[Sidebar] Eroare getConversationMessages:", err);
        return [];
    }
}