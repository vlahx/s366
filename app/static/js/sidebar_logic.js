// static/js/sidebar_logic.js

/**
 * Recuperează lista de sesiuni din MariaDB pentru utilizatorul curent
 */

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

/**
 * Șterge o sesiune întreagă (SQLite + referință MariaDB)
 */
export async function deleteSessionRequest(uuid) {
    try {
        const response = await fetch(`/chat/api/sessions/${uuid}`, { method: 'DELETE' });
        return response.ok;
    } catch (err) {
        console.error("[Sidebar] Eroare deleteSession:", err);
        return false;
    }
}

/**
 * Aduce mesajele dintr-o conversație specifică
 */
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