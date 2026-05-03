import { fetchSessions, renameSessionRequest, deleteSessionRequest, getConversationMessages } from './sidebar_logic.js';
import { createBubble } from './chat_ui.js';
import {
    isChatLoggedIn,
    loadGuestStore,
    ensureGuestSession,
    guestSessionsForSidebar,
    deleteGuestSession,
    renameGuestSession,
    toggleGuestPin,
    getGuestMessages,
    GUEST_NEW_THREAD_MSG,
} from './guest_storage.js';

async function loadSessionsUnified() {
    if (isChatLoggedIn()) return fetchSessions();
    return guestSessionsForSidebar(loadGuestStore());
}

async function deleteSessionUnified(uuid) {
    if (isChatLoggedIn()) return deleteSessionRequest(uuid);
    const st = loadGuestStore();
    deleteGuestSession(st, uuid);
    return true;
}

async function renameSessionUnified(uuid, oldTitle, newTitle) {
    if (isChatLoggedIn()) return renameSessionRequest(uuid, newTitle);
    return renameGuestSession(loadGuestStore(), uuid, newTitle);
}

export async function renderSessions(activeId, onSwitch) {
    const list = document.getElementById('session-list');
    if (!list) return;

    if (!isChatLoggedIn() && activeId) {
        const st = loadGuestStore();
        if (!st.sessions.some((s) => s.conversation_uuid === activeId)) {
            ensureGuestSession(st, activeId);
        }
    }

    const sessions = await loadSessionsUnified();
    list.innerHTML = '';

    sessions.forEach((conv) => {
        const uuid = conv.conversation_uuid;
        const isSelected = uuid === activeId;
        const title = conv.title || 'Conversație nouă';

        const container = document.createElement('div');
        container.className = `session-wrapper d-flex align-items-center justify-content-between p-2 mb-1 ${isSelected ? 'active-session' : ''}`;
        container.style.cursor = 'pointer';

        const textZone = document.createElement('div');
        textZone.className = 'flex-grow-1 text-truncate pe-2';
        textZone.innerHTML = `<span class="session-title">${title}</span>`;
        textZone.onclick = () => onSwitch(uuid);

        const dropdownContainer = document.createElement('div');
        dropdownContainer.className = 'dropdown-custom-container';

        const dotsBtn = document.createElement('div');
        dotsBtn.className = 'dots-icon';
        dotsBtn.innerHTML = '⋮';

        const menuContent = document.createElement('div');
        menuContent.className = 'custom-dropdown-content shadow';
        menuContent.innerHTML = `
    <div class="menu-item p-2 rounded d-flex align-items-center" data-action="rename">
        <i class="bi bi-pencil-square me-2"></i> Redenumește
    </div>
    <div class="menu-item p-2 rounded d-flex align-items-center" data-action="pin">
        <i class="bi bi-pin-angle me-2"></i> ${conv.pinned ? 'Unpin' : 'Pin'}
    </div>
    <div class="menu-item p-2 rounded d-flex align-items-center text-danger" data-action="delete">
        <i class="bi bi-trash me-2"></i> Șterge
    </div>
`;

        dotsBtn.onclick = (e) => {
            e.stopPropagation();
            document.querySelectorAll('.custom-dropdown-content').forEach((el) => {
                if (el !== menuContent) el.classList.remove('show');
            });
            menuContent.classList.toggle('show');
        };

        menuContent.onclick = async (e) => {
            e.stopPropagation();
            const actionNode = e.target.closest('[data-action]');
            if (!actionNode) return;

            const action = actionNode.getAttribute('data-action');
            menuContent.classList.remove('show');

            if (action === 'delete') {
                if (confirm('Ștergi această conversație?')) {
                    const success = await deleteSessionUnified(uuid);
                    if (success) {
                        document.getElementById('chat-box').innerHTML = '';

                        const updatedSessions = await loadSessionsUnified();

                        if (updatedSessions && updatedSessions.length > 0) {
                            const nextUuid = updatedSessions[0].conversation_uuid;
                            localStorage.setItem('s366_active_conv', nextUuid);
                            await switchConversation(nextUuid, onSwitch);
                            await renderSessions(nextUuid, onSwitch);
                        } else {
                            localStorage.removeItem('s366_active_conv');
                            await renderSessions(null, onSwitch);
                            if (typeof closeSidebar === 'function') closeSidebar();
                        }
                    }
                }
            } else if (action === 'rename') {
                const newTitle = prompt('Introdu noul nume pentru conversație:', conv.title);
                if (newTitle && newTitle.trim() !== '' && newTitle !== conv.title) {
                    const success = await renameSessionUnified(uuid, conv.title, newTitle.trim());
                    if (success) await renderSessions(activeId, onSwitch);
                    else alert('Eroare la redenumire. Încearcă din nou.');
                }
            } else if (action === 'pin') {
                if (isChatLoggedIn()) {
                    const newPin = conv.pinned ? 0 : 1;
                    const response = await fetch(`/chat/api/sessions/${uuid}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pinned: newPin }),
                    });
                    if (response.ok) await renderSessions(activeId, onSwitch);
                } else {
                    const st = loadGuestStore();
                    toggleGuestPin(st, uuid);
                    await renderSessions(activeId, onSwitch);
                }
            }
        };

        dropdownContainer.appendChild(dotsBtn);
        dropdownContainer.appendChild(menuContent);

        container.appendChild(textZone);
        container.appendChild(dropdownContainer);
        list.appendChild(container);
    });
}

document.addEventListener('click', () => {
    document.querySelectorAll('.custom-dropdown-content').forEach((el) => el.classList.remove('show'));
});

export async function switchConversation(uuid, updateStateCallback) {
    const chatBox = document.getElementById('chat-box');
    chatBox.innerHTML = '';

    chatBox.style.visibility = 'hidden';
    chatBox.style.position = 'absolute';

    let messages;
    if (isChatLoggedIn()) {
        messages = await getConversationMessages(uuid);
    } else {
        messages = getGuestMessages(loadGuestStore(), uuid);
    }

    messages.forEach((msg) => {
        createBubble(msg.sender, msg.message, msg.sender === 'assistant', true);
    });

    if (!isChatLoggedIn() && messages.length === 0) {
        createBubble('assistant', GUEST_NEW_THREAD_MSG, false);
    }

    requestAnimationFrame(() => {
        chatBox.style.visibility = 'visible';
        chatBox.style.position = '';
        chatBox.scrollTop = chatBox.scrollHeight;
    });

    if (updateStateCallback) updateStateCallback(uuid);
}
