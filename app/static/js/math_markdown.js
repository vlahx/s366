/**
 * KaTeX + marked: extrage formulele complete înainte de markdown, astfel încât
 * _, ^, \ din LaTeX să nu fie interpretate de marked ca italic/code etc.
 *
 * Delimitatori acceptați:
 * - $$ ... $$   (display)
 * - $ ... $     (inline; reguli stricte ca la KaTeX auto-render)
 * - \\[ ... \\] (display)
 * - \\( ... \\) (inline)
 *
 * Pentru $ inline: fără spațiu după $ deschis / înainte de $ închis, nu $$,
 * nu \$ escapat; $ urmat de cifră e monedă doar fără pereche sau dacă body e doar numeric ($50$).
 * $10 \\text{ cm}$ este acceptat.
 *
 * La stream, dacă ultima formulă nu e închisă, conținutul de la delimitatorul deschis
 * este omis (nu apare ca text/code); la închidere apare direct KaTeX HTML.
 */

const DELIMS = [
    { open: '$$', close: '$$', display: true },
    { open: '$', close: '$', display: false, inlineDollar: true },
    { open: '\\[', close: '\\]', display: true },
    { open: '\\(', close: '\\)', display: false },
];

function isEscaped(src, idx) {
    return idx > 0 && src[idx - 1] === '\\';
}

/**
 * Deschidere $ inline validă.
 * $ urmat de cifră e monedă doar dacă nu există pereche ($5) sau conținutul e doar numeric ($50$).
 * $10 \\text{ cm}$ trebuie acceptat — altfel marked interpretează \\t ca tab.
 */
function isInlineDollarOpen(src, idx) {
    if (src[idx] !== '$' || isEscaped(src, idx)) return false;
    if (src[idx + 1] === '$') return false;
    const next = src[idx + 1];
    if (next === undefined || /\s/.test(next)) return false;
    if (/\d/.test(next)) {
        const bodyStart = idx + 1;
        const closeIdx = findInlineDollarClose(src, bodyStart);
        if (closeIdx === -1) return false;
        const body = src.slice(bodyStart, closeIdx);
        if (/^[\d\s.,]+$/.test(body)) return false;
        return true;
    }
    return true;
}

/** Închide $ inline: primul $ valid după bodyStart. */
function findInlineDollarClose(src, bodyStart) {
    for (let i = bodyStart; i < src.length; i++) {
        if (src[i] !== '$' || isEscaped(src, i)) continue;
        if (src[i + 1] === '$' || (i > 0 && src[i - 1] === '$')) continue;
        if (i > bodyStart && /\s/.test(src[i - 1])) continue;
        return i;
    }
    return -1;
}

function findCloseIndex(src, bodyStart, hit) {
    if (hit.inlineDollar) return findInlineDollarClose(src, bodyStart);
    return src.indexOf(hit.close, bodyStart);
}

function findNextDelim(src, start) {
    let bestIdx = -1;
    let spec = null;
    for (const d of DELIMS) {
        let i = src.indexOf(d.open, start);
        while (i !== -1) {
            if (d.inlineDollar && !isInlineDollarOpen(src, i)) {
                i = src.indexOf(d.open, i + 1);
                continue;
            }
            break;
        }
        if (i !== -1 && (bestIdx === -1 || i < bestIdx)) {
            bestIdx = i;
            spec = d;
        } else if (i !== -1 && i === bestIdx && spec && d.open.length > spec.open.length) {
            spec = d;
        }
    }
    if (!spec) return null;
    return { idx: bestIdx, ...spec };
}

function extractMath(md) {
    const blocks = [];
    let out = '';
    let cursor = 0;
    while (cursor < md.length) {
        const hit = findNextDelim(md, cursor);
        if (!hit) {
            out += md.slice(cursor);
            break;
        }
        out += md.slice(cursor, hit.idx);
        const bodyStart = hit.idx + hit.open.length;
        const closeIdx = findCloseIndex(md, bodyStart, hit);
        if (closeIdx === -1) {
            break;
        }
        const latex = md.slice(bodyStart, closeIdx).trim();
        const token = `KATEXSLOT${blocks.length}END`;
        blocks.push({ latex, display: hit.display });
        out += token;
        cursor = closeIdx + hit.close.length;
    }
    return { text: out, blocks };
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function renderKatexHtml(latex, display, katexRef) {
    try {
        return katexRef.renderToString(latex, {
            displayMode: display,
            throwOnError: false,
            strict: 'ignore',
        });
    } catch (e) {
        return `<span class="katex-error text-danger" title="${escapeHtml(String(e.message || e))}">${escapeHtml(latex)}</span>`;
    }
}

/**
 * Markdown complet → HTML cu formule KaTeX (pentru răspunsul în stream).
 */
export function renderMarkdownWithMath(md) {
    const src = typeof md === 'string' ? md : '';
    if (!src) return '';

    if (typeof marked === 'undefined') {
        return `<p>${escapeHtml(src)}</p>`;
    }

    const katexRef = typeof katex !== 'undefined' ? katex : null;
    const { text, blocks } = extractMath(src);

    let html;
    try {
        html = marked.parse(text);
    } catch (e) {
        console.warn('[math_markdown] marked.parse:', e);
        return `<pre>${escapeHtml(src)}</pre>`;
    }

    if (!katexRef || blocks.length === 0) return html;

    let out = html;
    for (let i = 0; i < blocks.length; i++) {
        const token = `KATEXSLOT${i}END`;
        const rendered = renderKatexHtml(blocks[i].latex, blocks[i].display, katexRef);
        out = out.split(token).join(rendered);
    }
    return out;
}

/**
 * Mesaje salvate în SQLite: span.katex-pending (LaTeX în data-latex, setat la salvare).
 */
export function renderKatexPendingInElement(elem) {
    if (!elem || typeof katex === 'undefined') return;
    elem.querySelectorAll('.katex-pending').forEach((span) => {
        const latex = span.getAttribute('data-latex');
        if (latex == null) return;
        const display = span.getAttribute('data-display') === '1';
        span.outerHTML = renderKatexHtml(latex, display, katex);
    });
}

const MATH_IGNORED_TAGS = new Set(['SCRIPT', 'NOSCRIPT', 'STYLE', 'TEXTAREA', 'PRE', 'CODE']);

/** Randează $...$ / \\(...\\) rămase în noduri text (auto-render KaTeX sare $10). */
function typesetRemainingMathInTextNodes(elem) {
    if (!elem || typeof katex === 'undefined') return;

    const walker = document.createTreeWalker(elem, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            const parent = node.parentElement;
            if (!parent || MATH_IGNORED_TAGS.has(parent.tagName)) {
                return NodeFilter.FILTER_REJECT;
            }
            const v = node.nodeValue;
            if (!v || (!v.includes('$') && !v.includes('\\'))) {
                return NodeFilter.FILTER_REJECT;
            }
            return NodeFilter.FILTER_ACCEPT;
        },
    });

    const textNodes = [];
    let n;
    while ((n = walker.nextNode())) textNodes.push(n);

    for (const textNode of textNodes) {
        const src = textNode.nodeValue;
        const { text, blocks } = extractMath(src);
        if (blocks.length === 0) continue;

        const frag = document.createDocumentFragment();
        let rest = text;
        for (let i = 0; i < blocks.length; i++) {
            const token = `KATEXSLOT${i}END`;
            const idx = rest.indexOf(token);
            if (idx === -1) continue;
            if (idx > 0) frag.appendChild(document.createTextNode(rest.slice(0, idx)));
            const span = document.createElement('span');
            span.innerHTML = renderKatexHtml(blocks[i].latex, blocks[i].display, katex);
            while (span.firstChild) frag.appendChild(span.firstChild);
            rest = rest.slice(idx + token.length);
        }
        if (rest) frag.appendChild(document.createTextNode(rest));
        textNode.replaceWith(frag);
    }
}

/**
 * HTML existent (ex. mesaje vechi din SQLite, fără span.katex-pending):
 * caută delimitatori în text și randează KaTeX (nu atinge <pre>/<code>).
 */
export function typesetMathInElement(elem) {
    if (!elem) return;
    renderKatexPendingInElement(elem);

    const renderFn =
        typeof globalThis.renderMathInElement === 'function'
            ? globalThis.renderMathInElement
            : null;
    if (renderFn) {
        try {
            renderFn(elem, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false },
                    { left: '\\[', right: '\\]', display: true },
                    { left: '\\(', right: '\\)', display: false },
                ],
                ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
                strict: false,
            });
        } catch (e) {
            console.warn('[math_markdown] renderMathInElement:', e);
        }
    }

    typesetRemainingMathInTextNodes(elem);
}
