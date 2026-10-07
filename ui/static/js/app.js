document.addEventListener('DOMContentLoaded', async () => {
    // Elements
    const domainSelect = document.getElementById('domain-select');
    const userInput = document.getElementById('user-input');
    const btnSendMsg = document.getElementById('btn-send-msg');
    const messagesList = document.getElementById('messages-list');
    const welcomeView = document.getElementById('welcome-view');
    const statusContainer = document.getElementById('status-container');
    const statusText = document.getElementById('status-text');
    const btnStopStream = document.getElementById('btn-stop-stream');
    const charCounter = document.getElementById('char-counter');
    const themeToggle = document.getElementById('theme-toggle');
    const htmlEl = document.documentElement;

    // State
    let isWaiting = false;
    let currentAssistantMsgBody = null;
    let currentEvidenceMap = {};

    // 1. Theme toggle
    themeToggle.addEventListener('click', () => {
        const isDark = htmlEl.getAttribute('data-theme') === 'dark';
        htmlEl.setAttribute('data-theme', isDark ? 'light' : 'dark');
    });

    // 2. Load domains
    const domains = await api.loadDomains();
    if (domains && domains.length > 0) {
        domainSelect.innerHTML = '';
        domains.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            domainSelect.appendChild(opt);
        });
    }

    // 3. Bootstrap and connect WS
    const sessionId = await api.bootstrapSession();
    if (sessionId) {
        api.connectWebSocket(handleWsMessage, handleWsError, handleWsClose);
    } else {
        showToast("Không thể tạo phiên làm việc", true);
    }

    // 4. Input handling
    userInput.addEventListener('input', () => {
        charCounter.textContent = `${userInput.value.length}/1000`;
        btnSendMsg.disabled = userInput.value.trim().length === 0;
    });

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    btnSendMsg.addEventListener('click', sendMessage);

    btnStopStream.addEventListener('click', () => {
        // Mock stop behavior
        isWaiting = false;
        statusContainer.style.display = 'none';
        userInput.disabled = false;
        btnSendMsg.disabled = false;
        if (currentAssistantMsgBody && !currentAssistantMsgBody.innerHTML.trim()) {
            currentAssistantMsgBody.innerHTML = "<em>[Đã dừng tạo câu trả lời]</em>";
        }
    });

    function sendMessage() {
        if (isWaiting) return;
        const text = userInput.value.trim();
        if (!text) return;

        const domain = domainSelect.value;
        const sent = api.sendMessage(text, domain);
        if (sent) {
            if (welcomeView) welcomeView.style.display = 'none';
            appendUserMessage(text);
            userInput.value = '';
            charCounter.textContent = '0/1000';
            btnSendMsg.disabled = true;
            
            isWaiting = true;
            statusText.textContent = 'Đang xử lý...';
            statusContainer.style.display = 'block';
            
            // Prepare assistant bubble
            currentAssistantMsgBody = appendAssistantMessagePlaceholder();
        }
    }

    // --- WebSocket Handlers ---
    function handleWsMessage(payload) {
        const type = payload.type;
        const data = payload.data || {};

        if (type === 'connected') {
            console.log("Connected with session:", data.session_id);
        }
        else if (type === 'clarification') {
            statusText.textContent = 'Cần làm rõ...';
            if (currentAssistantMsgBody) {
                currentAssistantMsgBody.innerHTML = `<div class="clarify-card">${data.question}</div>`;
            }
        }
        else if (type === 'evidence') {
            statusText.textContent = 'Đang viết câu trả lời...';
            // Save evidence list for later citation clicking
            if (data.evidence_list && data.evidence_list.length > 0) {
                data.evidence_list.forEach(claim => {
                    claim.citations.forEach(cit => {
                        currentEvidenceMap[cit.evidence_id] = cit;
                    });
                });
            }
        }
        else if (type === 'chunk') {
            if (currentAssistantMsgBody) {
                // If this is the first chunk, replace placeholder text
                if (currentAssistantMsgBody.innerHTML === '<span class="pulse-dot"></span>') {
                    currentAssistantMsgBody.innerHTML = '';
                }
                
                // Append text and parse markdown roughly
                currentAssistantMsgBody.innerHTML += parseMarkdownChunk(data.text);
                scrollToBottom();
            }
        }
        else if (type === 'done') {
            isWaiting = false;
            statusContainer.style.display = 'none';
            btnSendMsg.disabled = false;
            
            if (data.answer && currentAssistantMsgBody) {
                // Replace citations with buttons
                let html = parseMarkdownChunk(data.answer, true);
                html = html.replace(/\[(EC_\d+)\]/g, (match, p1) => {
                    return `<button class="citation-chip" onclick="showEvidence('${p1}')">${p1.replace('EC_', '')}</button>`;
                });
                currentAssistantMsgBody.innerHTML = html;
            }
            
            if (data.domain) {
                domainSelect.value = data.domain;
            }
            if (data.mode) {
                htmlEl.setAttribute('data-domain-mode', data.mode);
                const badge = document.getElementById('domain-mode-badge');
                if (badge) badge.textContent = `Chế độ: ${data.mode}`;
            }
            
            scrollToBottom();
        }
        else if (type === 'error') {
            showToast(data.message || "Đã xảy ra lỗi", true);
            isWaiting = false;
            statusContainer.style.display = 'none';
            btnSendMsg.disabled = false;
        }
    }

    function handleWsError(err) {
        showToast("Lỗi kết nối máy chủ", true);
    }
    
    function handleWsClose() {
        showToast("Đã mất kết nối", true);
        isWaiting = false;
        statusContainer.style.display = 'none';
        btnSendMsg.disabled = false;
    }

    // --- UI Helpers ---
    function appendUserMessage(text) {
        const div = document.createElement('div');
        div.className = 'msg-wrapper user';
        div.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
        messagesList.appendChild(div);
        scrollToBottom();
    }

    function appendAssistantMessagePlaceholder() {
        const div = document.createElement('div');
        div.className = 'msg-wrapper ai';
        div.innerHTML = `
            <div style="font-size: 24px; margin-top:4px;">🤖</div>
            <div class="msg-bubble ai-content"><span class="pulse-dot"></span></div>
        `;
        messagesList.appendChild(div);
        scrollToBottom();
        return div.querySelector('.ai-content');
    }

    function scrollToBottom() {
        messagesList.scrollTop = messagesList.scrollHeight;
    }

    function showToast(msg, isError=false) {
        const toast = document.getElementById('toast-banner');
        toast.textContent = msg;
        toast.style.background = isError ? '#b91c1c' : '#1e293b';
        toast.style.display = 'block';
        setTimeout(() => toast.style.display = 'none', 3000);
    }

    // Simple markdown parsing
    function parseMarkdownChunk(text, final=false) {
        // If marked is available, use it on final text
        if (final && window.marked) {
            return window.marked.parse(text);
        }
        // Fallback simple parsing for streaming
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function escapeHtml(unsafe) {
        return unsafe
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }

    // Evidence Panel
    const evidencePanel = document.getElementById('evidence-panel');
    const evidenceContent = document.getElementById('evidence-content');
    document.getElementById('btn-close-evidence').addEventListener('click', () => {
        evidencePanel.classList.remove('open');
    });

    window.showEvidence = function(evidenceId) {
        const evidence = currentEvidenceMap[evidenceId];
        if (!evidence) return;
        
        evidenceContent.innerHTML = `
            <div style="background:var(--bg-surface-subtle); padding:12px; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                <div style="font-size:12px; font-weight:700; color:var(--primary); margin-bottom:4px;">[${evidenceId}] ${evidence.title}</div>
                <div style="font-size:14px; margin-bottom:8px;">Document ID: ${evidence.document_id}</div>
                ${evidence.source_url ? `<a href="${evidence.source_url}" target="_blank" style="font-size:13px; color:var(--primary);">🔗 Mở liên kết gốc</a>` : ''}
            </div>
        `;
        evidencePanel.classList.add('open');
    };
});
