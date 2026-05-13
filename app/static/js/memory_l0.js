/**
 * Setări cont chat (modal): Memorie L0 — listă / edit / ștergere / adăugare manuală.
 */

async function fetchMemoryList() {
    const res = await fetch('/chat/api/memory', { credentials: 'same-origin' });
    if (res.status === 401) return null;
    if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
    }
    return res.json();
}

async function patchMemory(id, title, content) {
    const res = await fetch(`/chat/api/memory/${id}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
    });
    if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || (await res.text()));
    }
}

async function deleteMemory(id) {
    const res = await fetch(`/chat/api/memory/${id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
    });
    if (!res.ok) throw new Error(await res.text());
}

async function postMemory(title, content) {
    const res = await fetch('/chat/api/memory', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
    });
    if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || (await res.text()));
    }
    return res.json();
}

function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function escapeAttr(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

export async function renderMemoryL0List() {
    const list = document.getElementById('memory-l0-list');
    if (!list) return;

    list.innerHTML = '<span class="text-body-secondary">Se încarcă…</span>';
    try {
        const rows = await fetchMemoryList();
        if (rows === null) {
            list.innerHTML = '';
            return;
        }
        if (!rows.length) {
            list.innerHTML =
                '<p class="text-body-secondary mb-0">Nicio înregistrare. Cere în chat: „salvează asta” sau adaugă manual mai jos.</p>';
            return;
        }

        list.innerHTML = rows
            .map((row) => {
                const id = row.id;
                const title = row.title || '';
                const content = row.content || '';
                return `
<div class="memory-l0-card mb-2 p-2 border rounded" data-id="${id}">
  <label class="form-label small mb-0 text-body-secondary">Titlu</label>
  <input type="text" class="form-control form-control-sm mb-1 mem-title" maxlength="500" value="${escapeAttr(title)}" />
  <label class="form-label small mb-0 text-body-secondary">Conținut</label>
  <textarea class="form-control form-control-sm mem-body" rows="5">${escapeHtml(content)}</textarea>
  <div class="d-flex gap-1 mt-2 flex-wrap">
    <button type="button" class="btn btn-sm btn-outline-primary mem-save">Salvează</button>
    <button type="button" class="btn btn-sm btn-outline-danger mem-del">Șterge</button>
  </div>
</div>`;
            })
            .join('');
    } catch (e) {
        console.error('[memory L0]', e);
        list.innerHTML = `<p class="text-danger small mb-0">Nu s-a putut încărca lista: ${escapeHtml(String(e.message || e))}</p>`;
    }
}

export function initChatUserSettingsModal() {
    const modal = document.getElementById('chat-user-settings-modal');
    if (!modal) return;

    modal.addEventListener('show.bs.modal', () => {
        renderMemoryL0List().catch(() => {});
    });

    const list = document.getElementById('memory-l0-list');
    const refreshBtn = document.getElementById('memory-l0-refresh');
    const addBtn = document.getElementById('memory-l0-add-btn');
    const newTitle = document.getElementById('memory-l0-new-title');
    const newContent = document.getElementById('memory-l0-new-content');

    if (refreshBtn) refreshBtn.addEventListener('click', () => renderMemoryL0List());

    if (list) {
        list.addEventListener('click', async (e) => {
            const card = e.target.closest('.memory-l0-card');
            if (!card) return;
            const id = card.dataset.id;
            if (!id) return;

            if (e.target.closest('.mem-del')) {
                if (!confirm('Ștergi această înregistrare din memorie?')) return;
                try {
                    await deleteMemory(id);
                    await renderMemoryL0List();
                } catch (err) {
                    alert(err.message || String(err));
                }
                return;
            }

            if (e.target.closest('.mem-save')) {
                const title = card.querySelector('.mem-title')?.value?.trim() || '';
                const content = card.querySelector('.mem-body')?.value?.trim() || '';
                if (!content) {
                    alert('Conținutul nu poate fi gol.');
                    return;
                }
                try {
                    await patchMemory(id, title, content);
                    await renderMemoryL0List();
                } catch (err) {
                    alert(err.message || String(err));
                }
            }
        });
    }

    if (addBtn && newTitle && newContent) {
        addBtn.addEventListener('click', async () => {
            const title = newTitle.value.trim();
            const content = newContent.value.trim();
            if (!content) {
                alert('Completează conținutul.');
                return;
            }
            try {
                await postMemory(title, content);
                newTitle.value = '';
                newContent.value = '';
                await renderMemoryL0List();
            } catch (err) {
                alert(err.message || String(err));
            }
        });
    }
}
