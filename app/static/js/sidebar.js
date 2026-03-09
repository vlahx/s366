import { fetchSessions, renameSessionRequest, deleteSessionRequest, getConversationMessages } from './sidebar_logic.js';
import { createBubble, scrollBottom } from './chat_ui.js';

export async function renderSessions(activeId, onSwitch) {
    const list = document.getElementById('session-list');
    if (!list) return;

    const sessions = await fetchSessions();
    list.innerHTML = '';

    sessions.forEach(conv => {
        const uuid = conv.conversation_uuid;
        const isSelected = (uuid === activeId);
        const title = conv.title || "Conversație nouă";

        // Cream wrapper-ul sesiunii (clasa ta: session-wrapper)
        const container = document.createElement('div');
        container.className = `session-wrapper d-flex align-items-center justify-content-between p-2 mb-1 ${isSelected ? 'active-session' : ''}`;
        container.style.cursor = 'pointer';

        // 1. Zona de text (Titlul)
        const textZone = document.createElement('div');
        textZone.className = 'flex-grow-1 text-truncate pe-2';
        textZone.innerHTML = `<span class="session-title">${title}</span>`;
        textZone.onclick = () => onSwitch(uuid);

        // 2. Containerul pentru Dropdown (clasa ta: dropdown-custom-container)
        const dropdownContainer = document.createElement('div');
        dropdownContainer.className = 'dropdown-custom-container';

        // Butonul de 3 puncte (clasa ta: dots-icon)
        const dotsBtn = document.createElement('div');
        dotsBtn.className = 'dots-icon';
        dotsBtn.innerHTML = '⋮';

        // Meniul ascuns (clasa ta: custom-dropdown-content)
        const menuContent = document.createElement('div');
        menuContent.className = 'custom-dropdown-content shadow';
        // În interiorul renderSessions, la meniul HTML:
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

        // Logica de deschidere meniu
        dotsBtn.onclick = (e) => {
            e.stopPropagation();
            // Închidem alte meniuri deschise înainte
            document.querySelectorAll('.custom-dropdown-content').forEach(el => {
                if (el !== menuContent) el.classList.remove('show');
            });
            menuContent.classList.toggle('show');
        };

        // Logica pentru acțiuni (Rename/Delete)
        menuContent.onclick = async (e) => {
            e.stopPropagation();
            const actionNode = e.target.closest('[data-action]');
            if (!actionNode) return;

            const action = actionNode.getAttribute('data-action');
            menuContent.classList.remove('show');

            if (action === 'delete') {
                if (confirm("Ștergi această conversație?")) {
                    const success = await deleteSessionRequest(uuid);
                    if (success) {
                        // 1. Curățăm imediat chat-ul (ca la butonul Nou)
                        document.getElementById('chat-box').innerHTML = '';

                        // 2. Cerem lista nouă de sesiuni
                        const updatedSessions = await fetchSessions();

                        if (updatedSessions && updatedSessions.length > 0) {
                            const nextUuid = updatedSessions[0].conversation_uuid;
                            localStorage.setItem('s366_active_conv', nextUuid);


                            await switchConversation(nextUuid, onSwitch);

                            // 4. Redesenăm sidebar-ul (ca să se vadă selecția pe noua sesiune)
                            await renderSessions(nextUuid, onSwitch);
                        } else {
                            // Dacă nu mai e nimic, resetăm tot
                            localStorage.removeItem('s366_active_conv');
                            await renderSessions(null, onSwitch);

                            // Dacă totuși nu s-a închis, forțăm funcția ta de închidere (dacă o ai definită)
                            if (typeof closeSidebar === 'function') closeSidebar();
                        }
                    }
                }
            }
            else if (action === 'rename') {
                const newTitle = prompt("Introdu noul nume pentru conversație:", conv.title);

                // Verificăm să nu fie gol și să fie diferit de cel vechi
                if (newTitle && newTitle.trim() !== "" && newTitle !== conv.title) {
                    const success = await renameSessionRequest(uuid, newTitle.trim());
                    if (success) {
                        // Reîncărcăm lista ca să apară titlul nou în sidebar
                        await renderSessions(activeId, onSwitch);
                    } else {
                        alert("Eroare la redenumire. Încearcă din nou.");
                    }
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

// Închidem meniul dacă dăm click oriunde altundeva în pagină
document.addEventListener('click', () => {
    document.querySelectorAll('.custom-dropdown-content').forEach(el => el.classList.remove('show'));
});

export async function switchConversation(uuid, updateStateCallback) {
    // ... partea cu sidebar ...

    const chatBox = document.getElementById('chat-box');
    chatBox.innerHTML = '';

    // 1. Facem chat-ul INVIZIBIL temporar (ca să nu vadă nimic trecând)
    chatBox.style.visibility = 'hidden';
    chatBox.style.position = 'absolute';  // opțional, ca să nu ocupe spațiu în layout în timpul load-ului

    const messages = await getConversationMessages(uuid);

    // 2. Adaugă toate mesajele VECHI fără niciun scroll
    messages.forEach(msg => {
        createBubble(msg.sender, msg.message, msg.sender === 'assistant', true);
    });

    // 3. Acum facem chat-ul vizibil și forțăm scroll la bottom
    requestAnimationFrame(() => {
        chatBox.style.visibility = 'visible';
        chatBox.style.position = '';  // revenim la normal

        // Scroll direct, fără smooth, ca să fie instant
        chatBox.scrollTop = chatBox.scrollHeight;

        //console.log('Conversatie veche încărcată INVIZIBIL → direct la final');
    });

    if (updateStateCallback) updateStateCallback(uuid);
}