document.addEventListener('DOMContentLoaded', async () => {
    // Elements
    const domainSelect = document.getElementById('domain-select');
    const btnDeleteDomain = document.getElementById('btn-delete-domain');
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
    const historyList = document.getElementById('history-list');

    // State
    let isWaiting = false;
    let currentAssistantMsgBody = null;
    let currentEvidenceMap = {};
    let safetyTimeoutTimer = null;

    // 0. New Chat
    const btnNewChat = document.getElementById('btn-new-chat');
    if (btnNewChat) {
        btnNewChat.addEventListener('click', async () => {
            await startNewSession();
        });
    }

    // 1. Theme toggle
    themeToggle.addEventListener('click', () => {
        const isDark = htmlEl.getAttribute('data-theme') === 'dark';
        htmlEl.setAttribute('data-theme', isDark ? 'light' : 'dark');
    });

    // 2. Load domains with full details
    let allDomainDetails = {};
    async function refreshDomainList(selectedId = null) {
        const details = await api.loadDomainDetails();
        allDomainDetails = {};
        if (details && details.length > 0) {
            domainSelect.innerHTML = '';
            const modalDomainSelect = document.getElementById('modal-domain-select');
            if (modalDomainSelect) modalDomainSelect.innerHTML = '';

            details.forEach(d => {
                allDomainDetails[d.domain_id] = d;

                const opt = document.createElement('option');
                opt.value = d.domain_id;
                opt.textContent = `${d.domain_name} (${d.mode})`;
                if (selectedId && d.domain_id === selectedId) opt.selected = true;
                domainSelect.appendChild(opt);

                if (modalDomainSelect) {
                    const mOpt = document.createElement('option');
                    mOpt.value = d.domain_id;
                    mOpt.textContent = `${d.domain_name} [${d.domain_id}]`;
                    if (selectedId && d.domain_id === selectedId) mOpt.selected = true;
                    modalDomainSelect.appendChild(mOpt);
                }
            });

            if (btnDeleteDomain) {
                btnDeleteDomain.disabled = details.length <= 1;
                btnDeleteDomain.title = details.length <= 1
                    ? "Không thể xóa domain duy nhất còn lại trên hệ thống"
                    : "Xóa lĩnh vực đang chọn";
            }

            applyDomainConfig(selectedId || domainSelect.value);
        }
    }

    function applyDomainConfig(domainId) {
        const d = allDomainDetails[domainId];
        if (!d) return;
        const headerName = document.getElementById('header-domain-name');
        const headerSub = document.getElementById('header-subtitle');
        const modeBadge = document.getElementById('domain-mode-badge');
        if (headerName) headerName.textContent = d.domain_name || d.domain_id;
        if (headerSub) headerSub.textContent = d.description || `Trợ lý chuyên trách ${d.domain_name}`;
        if (modeBadge) {
            const isStrict = d.mode === 'strict';
            modeBadge.textContent = isStrict ? '🛡️ Chế độ: Nghiêm ngặt (Có dẫn chứng)' : '⚡ Chế độ: Thân thiện (Tốc độ cao)';
            htmlEl.setAttribute('data-domain-mode', d.mode);
        }
    }

    domainSelect.addEventListener('change', () => {
        applyDomainConfig(domainSelect.value);
    });

    if (btnDeleteDomain) {
        btnDeleteDomain.addEventListener('click', async () => {
            const targetId = domainSelect.value;
            if (!targetId) return;
            const domainKeys = Object.keys(allDomainDetails);
            if (domainKeys.length <= 1) {
                showToast("Không thể xóa domain duy nhất còn lại trên hệ thống!", true);
                return;
            }
            const dInfo = allDomainDetails[targetId] || {};
            const dName = dInfo.domain_name || targetId;
            const confirmed = confirm(
                `Bạn có chắc chắn muốn xóa lĩnh vực "${dName}" [${targetId}]?\n\n` +
                `Lưu ý: Toàn bộ cấu hình, dữ liệu nguồn và dữ liệu vector trên Qdrant của lĩnh vực này sẽ bị xóa vĩnh viễn!`
            );
            if (!confirmed) return;

            btnDeleteDomain.disabled = true;
            try {
                const res = await api.deleteDomain(targetId);
                showToast(res.message || `Đã xóa lĩnh vực ${dName}`);
                const nextDomain = (res.remaining_domains && res.remaining_domains[0]) || null;
                await refreshDomainList(nextDomain);
            } catch (err) {
                showToast(`Lỗi khi xóa domain: ${err.message}`, true);
                btnDeleteDomain.disabled = Object.keys(allDomainDetails).length <= 1;
            }
        });
    }

    await refreshDomainList();

    // 3. Bootstrap, connect WS & load history
    const sessionId = await api.bootstrapSession();
    if (sessionId) {
        const sessionEl = document.getElementById('current-session-id');
        if (sessionEl) sessionEl.textContent = sessionId.substring(0, 8) + '...';
        api.connectWebSocket(handleWsMessage, handleWsError, handleWsClose);
        
        await Promise.all([
            loadAndRenderMessages(sessionId),
            loadAndRenderHistory(sessionId),
        ]);
    } else {
        showToast("Không thể tạo phiên làm việc", true);
    }

    // 3.1 Check system readiness (Preload & Warmup status)
    const systemReadyBadge = document.getElementById('system-ready-badge');
    async function checkSystemStatus() {
        if (!systemReadyBadge) return false;
        try {
            const resp = await fetch('/api/system/status');
            if (resp.ok) {
                const data = await resp.json();
                if (data.all_ready) {
                    systemReadyBadge.textContent = '⚡ AI sẵn sàng';
                    systemReadyBadge.style.background = 'rgba(16, 185, 129, 0.15)';
                    systemReadyBadge.style.color = '#059669';
                    systemReadyBadge.style.borderColor = 'rgba(16, 185, 129, 0.3)';
                    systemReadyBadge.title = 'Tất cả mô hình (BGE-M3, Qwen 3B, Qwen 1.5B) đã được nạp sẵn!';
                    return true;
                }
            }
        } catch (e) {
            // Server có thể đang khởi động
        }
        return false;
    }

    checkSystemStatus().then(ready => {
        if (!ready) {
            const interval = setInterval(async () => {
                const isReady = await checkSystemStatus();
                if (isReady) clearInterval(interval);
            }, 2000);
        }
    });

    // 4. Input handling - đa sự kiện để tương thích tốt với bộ gõ tiếng Việt (Unikey/EVKey)
    function updateInputState() {
        const len = userInput.value.length;
        charCounter.textContent = `${len}/1000`;
        btnSendMsg.disabled = isWaiting || userInput.value.trim().length === 0;
    }

    ['input', 'change', 'keyup', 'paste'].forEach(evt => {
        userInput.addEventListener(evt, updateInputState);
    });

    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    btnSendMsg.addEventListener('click', () => {
        sendMessage();
    });

    btnStopStream.addEventListener('click', () => {
        resetWaitingState();
        if (currentAssistantMsgBody && !currentAssistantMsgBody.innerHTML.trim()) {
            currentAssistantMsgBody.innerHTML = "<em>[Đã dừng tạo câu trả lời]</em>";
        }
        showToast("Đã dừng câu trả lời");
    });

    function resetWaitingState() {
        isWaiting = false;
        if (safetyTimeoutTimer) {
            clearTimeout(safetyTimeoutTimer);
            safetyTimeoutTimer = null;
        }
        statusContainer.style.display = 'none';
        userInput.disabled = false;
        updateInputState();
    }

    async function sendMessage() {
        if (isWaiting) {
            showToast("Hệ thống đang xử lý câu hỏi trước, bạn có thể bấm [Dừng] nếu muốn hủy.", false);
            return;
        }

        const text = userInput.value.trim();
        if (!text) return;

        btnSendMsg.disabled = true;
        statusText.textContent = 'Đang kết nối & xử lý...';
        statusContainer.style.display = 'block';

        const domain = domainSelect.value;
        const sent = await api.sendMessage(text, domain);

        if (sent) {
            if (welcomeView) welcomeView.style.display = 'none';
            appendUserMessage(text);
            userInput.value = '';
            charCounter.textContent = '0/1000';
            
            isWaiting = true;
            statusText.textContent = 'Đang xử lý...';
            
            currentAssistantMsgBody = appendAssistantMessagePlaceholder();

            // Safety timeout: tự động mở khóa sau 45s nếu server gặp sự cố không trả done
            if (safetyTimeoutTimer) clearTimeout(safetyTimeoutTimer);
            safetyTimeoutTimer = setTimeout(() => {
                if (isWaiting) {
                    console.warn("[TIMEOUT] Safety timeout triggered after 45s.");
                    resetWaitingState();
                    showToast("Thời gian phản hồi quá lâu. Đã mở lại khung chat.", true);
                }
            }, 45000);
        } else {
            resetWaitingState();
            showToast("Không thể gửi tin nhắn. Máy chủ đang kết nối lại, vui lòng thử lại sau giây lát...", true);
        }
    }

    // --- WebSocket Handlers ---
    function handleWsMessage(payload) {
        const type = payload.type;
        const data = payload.data || {};

        if (type === 'connected') {
            console.log("[WS] Session confirmed connected:", data.session_id);
        }
        else if (type === 'clarification') {
            statusText.textContent = 'Cần làm rõ...';
            if (currentAssistantMsgBody) {
                const qText = data.question || "Bạn muốn hỏi về thủ tục hành chính nào?";
                currentAssistantMsgBody.innerHTML = `<div class="clarify-card">${parseMarkdownChunk(qText, true)}</div>`;
                scrollToBottom();
            }
        }
        else if (type === 'evidence') {
            statusText.textContent = 'Đang viết câu trả lời...';
            if (data.evidence_list && data.evidence_list.length > 0) {
                data.evidence_list.forEach(claim => {
                    claim.citations.forEach(cit => {
                        currentEvidenceMap[cit.evidence_id] = cit;
                    });
                });
            }
        }
        else if (type === 'plan') {
            statusText.textContent = 'Đã tìm thấy các thủ tục...';
            if (currentAssistantMsgBody) {
                if (currentAssistantMsgBody.innerHTML === '<span class="pulse-dot"></span>') {
                    currentAssistantMsgBody.innerHTML = '';
                }
                
                let planHtml = `<div class="plan-card" style="margin-bottom: 12px; padding: 12px; background: var(--bg-surface-subtle); border-radius: var(--radius-md); border-left: 4px solid var(--primary);">`;
                planHtml += `<div style="font-weight: 600; margin-bottom: 8px;">Hệ thống đang xử lý các thủ tục:</div>`;
                planHtml += `<ul style="margin: 0; padding-left: 20px;">`;
                
                if (data.found && data.found.length > 0) {
                    data.found.forEach(t => {
                        planHtml += `<li style="color: var(--primary);">✅ ${escapeHtml(t)}</li>`;
                    });
                }
                if (data.missing && data.missing.length > 0) {
                    data.missing.forEach(t => {
                        planHtml += `<li style="color: #b91c1c;">❌ ${escapeHtml(t)} (Không tìm thấy)</li>`;
                    });
                }
                planHtml += `</ul>`;
                if (data.truncated) {
                    planHtml += `<div style="margin-top: 8px; font-size: 13px; color: #b91c1c;">(Đã giới hạn tối đa 8 thủ tục)</div>`;
                }
                planHtml += `</div>`;
                
                currentAssistantMsgBody.innerHTML += planHtml;
                scrollToBottom();
            }
        }
        else if (type === 'section') {
            statusText.textContent = 'Đang trình bày thủ tục...';
            if (currentAssistantMsgBody) {
                let sectionHtml = `<div class="section-card" style="margin-bottom: 16px;">`;
                sectionHtml += `<h4 style="margin: 0 0 8px 0; color: var(--text-primary); border-bottom: 1px solid var(--border-color); padding-bottom: 4px;">${escapeHtml(data.title || '')}</h4>`;
                
                let textHtml = parseMarkdownChunk(data.text || '', true);
                textHtml = textHtml.replace(/\[(EC_\d+)\]/g, (match, p1) => {
                    return `<button class="citation-chip" onclick="showEvidence('${p1}')">${p1.replace('EC_', '')}</button>`;
                });
                
                sectionHtml += `<div style="color: var(--text-secondary);">${textHtml}</div>`;
                sectionHtml += `</div>`;
                
                currentAssistantMsgBody.innerHTML += sectionHtml;
                
                if (data.evidence_list && data.evidence_list.length > 0) {
                    data.evidence_list.forEach(claim => {
                        if (claim.citations) {
                            claim.citations.forEach(cit => {
                                currentEvidenceMap[cit.evidence_id] = cit;
                            });
                        }
                    });
                }
                scrollToBottom();
            }
        }
        else if (type === 'chunk') {
            if (currentAssistantMsgBody) {
                if (currentAssistantMsgBody.innerHTML === '<span class="pulse-dot"></span>') {
                    currentAssistantMsgBody.innerHTML = '';
                }
                currentAssistantMsgBody.innerHTML += parseMarkdownChunk(data.text);
                scrollToBottom();
            }
        }
        else if (type === 'done') {
            resetWaitingState();
            
            if (data.answer && currentAssistantMsgBody) {
                if (data.needs_clarification) {
                    currentAssistantMsgBody.innerHTML = `<div class="clarify-card">${parseMarkdownChunk(data.answer, true)}</div>`;
                } else {
                    let html = parseMarkdownChunk(data.answer, true);
                    html = html.replace(/\[(EC_\d+)\]/g, (match, p1) => {
                        return `<button class="citation-chip" onclick="showEvidence('${p1}')">${p1.replace('EC_', '')}</button>`;
                    });
                    currentAssistantMsgBody.innerHTML = html;
                }
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

            // Cập nhật lại sidebar sau khi backend lưu xong tin nhắn vào DB
            if (api.sessionId) {
                setTimeout(() => {
                    loadAndRenderHistory(api.sessionId);
                }, 800);
            }
        }
        else if (type === 'error') {
            showToast(data.message || "Đã xảy ra lỗi khi xử lý câu hỏi", true);
            resetWaitingState();
        }
    }

    function handleWsError(err) {
        console.warn("[WS] Connection error:", err);
    }
    
    function handleWsClose() {
        console.warn("[WS] Connection closed. Auto-reconnect will trigger.");
        resetWaitingState();
    }

    // --- Session & History Management ---
    async function loadAndRenderHistory(activeSessionId) {
        if (!historyList) return;
        const sessions = await api.loadSessions();
        historyList.innerHTML = '';

        if (!sessions || sessions.length === 0) {
            historyList.innerHTML = '<div class="history-empty-hint">Chưa có lịch sử hội thoại</div>';
            return;
        }

        sessions.forEach(s => {
            const item = document.createElement('div');
            item.className = 'history-item' + (s.id === activeSessionId ? ' active' : '');
            item.dataset.sessionId = s.id;
            item.innerHTML = `
                <span class="history-item-icon">💬</span>
                <div class="history-item-content">
                    <div class="history-item-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</div>
                    <div class="history-item-time">${formatTimeAgo(s.created_at)}</div>
                </div>
                <button class="history-item-delete" title="Xóa cuộc trò chuyện" aria-label="Xóa">&times;</button>
            `;

            item.addEventListener('click', (e) => {
                if (e.target.closest('.history-item-delete')) return;
                if (s.id !== api.sessionId) {
                    switchToSession(s.id);
                }
            });

            const deleteBtn = item.querySelector('.history-item-delete');
            deleteBtn.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (!confirm(`Xóa cuộc trò chuyện "${s.title}"?`)) return;
                const success = await api.deleteSession(s.id);
                if (success) {
                    if (s.id === api.sessionId) {
                        await startNewSession();
                    } else {
                        await loadAndRenderHistory(api.sessionId);
                    }
                    showToast("Đã xóa cuộc trò chuyện");
                } else {
                    showToast("Không thể xóa cuộc trò chuyện", true);
                }
            });

            historyList.appendChild(item);
        });
    }

    function clearMessagesOnly() {
        if (messagesList) {
            messagesList.querySelectorAll('.msg-wrapper').forEach(el => el.remove());
        }
    }

    async function loadAndRenderMessages(sessionId) {
        const data = await api.loadSessionMessages(sessionId);
        clearMessagesOnly();
        currentEvidenceMap = {};

        if (data && data.messages && data.messages.length > 0) {
            if (welcomeView) welcomeView.style.display = 'none';
            data.messages.forEach(msg => {
                if (msg.role === 'user') {
                    appendUserMessage(msg.content);
                } else if (msg.role === 'assistant') {
                    if (msg.citations && Array.isArray(msg.citations)) {
                        msg.citations.forEach(claim => {
                            if (claim.citations) {
                                claim.citations.forEach(cit => {
                                    currentEvidenceMap[cit.evidence_id] = cit;
                                });
                            }
                        });
                    }
                    let html = parseMarkdownChunk(msg.content, true);
                    html = html.replace(/\[(EC_\d+)\]/g, (match, p1) => {
                        return `<button class="citation-chip" onclick="showEvidence('${p1}')">${p1.replace('EC_', '')}</button>`;
                    });
                    appendAssistantMessage(html);
                }
            });
            scrollToBottom();
        } else {
            if (welcomeView) welcomeView.style.display = 'block';
        }
    }

    async function switchToSession(sessionId) {
        if (isWaiting) {
            showToast("Vui lòng đợi câu trả lời hoàn tất trước khi chuyển phiên", true);
            return;
        }
        api.disconnect();
        const ok = await api.switchSession(sessionId);
        if (ok) {
            const sessionEl = document.getElementById('current-session-id');
            if (sessionEl) sessionEl.textContent = sessionId.substring(0, 8) + '...';
            api.connectWebSocket(handleWsMessage, handleWsError, handleWsClose);
            await loadAndRenderMessages(sessionId);
            await loadAndRenderHistory(sessionId);
        } else {
            showToast("Không thể chuyển sang phiên này", true);
        }
    }

    async function startNewSession() {
        if (isWaiting) {
            showToast("Vui lòng đợi câu trả lời hoàn tất", true);
            return;
        }
        api.disconnect();
        const newSession = await api.createNewSession();
        if (newSession) {
            const sessionEl = document.getElementById('current-session-id');
            if (sessionEl) sessionEl.textContent = newSession.session_id.substring(0, 8) + '...';
            api.connectWebSocket(handleWsMessage, handleWsError, handleWsClose);
            clearMessagesOnly();
            if (welcomeView) welcomeView.style.display = 'block';
            await loadAndRenderHistory(newSession.session_id);
        } else {
            showToast("Không thể tạo phiên mới", true);
        }
    }

    function formatTimeAgo(isoString) {
        if (!isoString) return '';
        try {
            const date = new Date(isoString);
            const now = new Date();
            const diffSec = Math.floor((now - date) / 1000);
            if (diffSec < 60) return 'Vừa xong';
            const diffMin = Math.floor(diffSec / 60);
            if (diffMin < 60) return `${diffMin} phút trước`;
            const diffHour = Math.floor(diffMin / 60);
            if (diffHour < 24) return `${diffHour} giờ trước`;
            const diffDay = Math.floor(diffHour / 24);
            if (diffDay < 7) return `${diffDay} ngày trước`;
            return date.toLocaleDateString('vi-VN', { month: 'short', day: 'numeric' });
        } catch (e) {
            return '';
        }
    }

    // --- UI Helpers ---
    function appendUserMessage(text) {
        const div = document.createElement('div');
        div.className = 'msg-wrapper user';
        div.innerHTML = `<div class="msg-bubble">${escapeHtml(text)}</div>`;
        messagesList.appendChild(div);
        scrollToBottom();
    }

    function appendAssistantMessage(htmlContent) {
        const div = document.createElement('div');
        div.className = 'msg-wrapper ai';
        div.innerHTML = `
            <div style="font-size: 24px; margin-top:4px;">🤖</div>
            <div class="msg-bubble ai-content">${htmlContent}</div>
        `;
        messagesList.appendChild(div);
        scrollToBottom();
        return div.querySelector('.ai-content');
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
        if (!toast) return;
        toast.textContent = msg;
        toast.style.background = isError ? '#b91c1c' : '#1e293b';
        toast.style.display = 'block';
        setTimeout(() => toast.style.display = 'none', 3500);
    }

    function parseMarkdownChunk(text, final=false) {
        if (final && window.marked) {
            return window.marked.parse(text);
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function escapeHtml(unsafe) {
        return (unsafe || '')
             .replace(/&/g, "&amp;")
             .replace(/</g, "&lt;")
             .replace(/>/g, "&gt;")
             .replace(/"/g, "&quot;")
             .replace(/'/g, "&#039;");
    }

    // Evidence Panel
    const evidencePanel = document.getElementById('evidence-panel');
    const evidenceContent = document.getElementById('evidence-content');
    const btnCloseEvidence = document.getElementById('btn-close-evidence');
    if (btnCloseEvidence && evidencePanel) {
        btnCloseEvidence.addEventListener('click', () => {
            evidencePanel.classList.remove('open');
        });
    }

    window.showEvidence = function(evidenceId) {
        const evidence = currentEvidenceMap[evidenceId];
        if (!evidence || !evidenceContent || !evidencePanel) return;
        
        evidenceContent.innerHTML = `
            <div style="background:var(--bg-surface-subtle); padding:12px; border-radius:var(--radius-sm); border:1px solid var(--border-color);">
                <div style="font-size:12px; font-weight:700; color:var(--primary); margin-bottom:4px;">[${evidenceId}] ${escapeHtml(evidence.title || '')}</div>
                <div style="font-size:14px; margin-bottom:8px;">Document ID: ${escapeHtml(evidence.document_id || '')}</div>
                ${evidence.source_url ? `<a href="${evidence.source_url}" target="_blank" style="font-size:13px; color:var(--primary);">🔗 Mở liên kết gốc</a>` : ''}
            </div>
        `;
        evidencePanel.classList.add('open');
    };

    // --- Ingest & Domain Onboarding Modal Handlers ---
    const ingestModal = document.getElementById('ingest-modal');
    const btnOpenIngestModal = document.getElementById('btn-open-ingest-modal');
    const btnCloseIngestModal = document.getElementById('btn-close-ingest-modal');
    const tabIngestData = document.getElementById('tab-ingest-data');
    const tabCreateDomain = document.getElementById('tab-create-domain');
    const viewTabIngest = document.getElementById('view-tab-ingest');
    const viewTabCreate = document.getElementById('view-tab-create');
    const radioModeFile = document.getElementById('radio-mode-file');
    const radioModeRaw = document.getElementById('radio-mode-raw');
    const sectionUploadFile = document.getElementById('section-upload-file');
    const sectionRawJson = document.getElementById('section-raw-json');
    const btnSampleData = document.getElementById('btn-sample-data');
    const ingestRawJson = document.getElementById('ingest-raw-json');
    const btnSubmitIngest = document.getElementById('btn-submit-ingest');
    const ingestStatusBox = document.getElementById('ingest-status-box');
    const ingestStatusMsg = document.getElementById('ingest-status-msg');
    const ingestResultDetails = document.getElementById('ingest-result-details');
    const btnSubmitCreateDomain = document.getElementById('btn-submit-create-domain');

    if (btnOpenIngestModal && ingestModal) {
        btnOpenIngestModal.addEventListener('click', () => {
            ingestModal.style.display = 'flex';
        });
    }

    if (btnCloseIngestModal && ingestModal) {
        btnCloseIngestModal.addEventListener('click', () => {
            ingestModal.style.display = 'none';
        });
    }

    if (ingestModal) {
        ingestModal.addEventListener('click', (e) => {
            if (e.target === ingestModal) ingestModal.style.display = 'none';
        });
    }

    // Tab toggling
    if (tabIngestData && tabCreateDomain) {
        tabIngestData.addEventListener('click', () => {
            tabIngestData.classList.add('active');
            tabIngestData.style.borderBottom = '2px solid var(--primary)';
            tabIngestData.style.color = 'var(--primary)';
            tabCreateDomain.classList.remove('active');
            tabCreateDomain.style.borderBottom = 'none';
            tabCreateDomain.style.color = 'var(--text-muted)';
            viewTabIngest.style.display = 'block';
            viewTabCreate.style.display = 'none';
        });

        tabCreateDomain.addEventListener('click', () => {
            tabCreateDomain.classList.add('active');
            tabCreateDomain.style.borderBottom = '2px solid var(--primary)';
            tabCreateDomain.style.color = 'var(--primary)';
            tabIngestData.classList.remove('active');
            tabIngestData.style.borderBottom = 'none';
            tabIngestData.style.color = 'var(--text-muted)';
            viewTabCreate.style.display = 'block';
            viewTabIngest.style.display = 'none';
        });
    }

    // Input mode toggling (File vs Raw JSON)
    if (radioModeFile && radioModeRaw) {
        radioModeFile.addEventListener('change', () => {
            if (radioModeFile.checked) {
                sectionUploadFile.style.display = 'block';
                sectionRawJson.style.display = 'none';
            }
        });
        radioModeRaw.addEventListener('change', () => {
            if (radioModeRaw.checked) {
                sectionUploadFile.style.display = 'none';
                sectionRawJson.style.display = 'block';
            }
        });
    }

    // Sample data button
    if (btnSampleData && ingestRawJson) {
        btnSampleData.addEventListener('click', () => {
            const mDomain = document.getElementById('modal-domain-select')?.value || 'generic';
            let samples = [
                {
                    "id": "1.000001",
                    "so_quyet_dinh": "123/QĐ-UBND",
                    "ten_thu_tuc": "Thủ tục đăng ký khai sinh kết hợp đăng ký thường trú",
                    "co_quan_thuc_hien": "UBND cấp xã",
                    "linh_vuc": "Hộ tịch",
                    "trinh_tu_thuc_hien": "Bước 1: Nộp hồ sơ trực tuyến qua Cổng DVC hoặc trực tiếp tại UBND xã.\nBước 2: Công chức tư pháp - hộ tịch tiếp nhận và thụ lý.\nBước 3: Trả kết quả Giấy khai sinh.",
                    "cach_thuc_thuc_hien": "Trực tiếp hoặc trực tuyến qua Cổng Dịch vụ công Quốc gia",
                    "thanh_phan_ho_so": "Tờ khai đăng ký khai sinh theo mẫu; Giấy chứng sinh do cơ sở y tế cấp.",
                    "thoi_han_giai_quyet": "Ngay trong ngày làm việc",
                    "le_phi": "Miễn phí",
                    "yeu_cau_dieu_kien": "Trẻ em sinh ra tại Việt Nam, có cha hoặc mẹ là công dân Việt Nam."
                }
            ];
            ingestRawJson.value = JSON.stringify(samples, null, 2);
        });
    }

    // Handle Submit Ingest
    if (btnSubmitIngest) {
        btnSubmitIngest.addEventListener('click', async () => {
            const mDomainSelect = document.getElementById('modal-domain-select');
            const targetDomain = mDomainSelect ? mDomainSelect.value : domainSelect.value;
            if (!targetDomain) {
                showToast("Vui lòng chọn domain đích!", true);
                return;
            }

            const formData = new FormData();
            const isFileMode = radioModeFile ? radioModeFile.checked : true;
            const forceReindex = document.getElementById('ingest-force-reindex')?.checked || false;
            formData.append('force_reindex', forceReindex ? 'true' : 'false');

            if (isFileMode) {
                const fileInput = document.getElementById('ingest-file-input');
                if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
                    showToast("Vui lòng chọn một tệp để nạp!", true);
                    return;
                }
                formData.append('file', fileInput.files[0]);
            } else {
                const jsonText = ingestRawJson ? ingestRawJson.value.trim() : '';
                if (!jsonText) {
                    showToast("Vui lòng dán nội dung JSON!", true);
                    return;
                }
                formData.append('raw_json', jsonText);
            }

            btnSubmitIngest.disabled = true;
            if (ingestStatusBox) ingestStatusBox.style.display = 'block';
            if (ingestStatusMsg) ingestStatusMsg.innerHTML = '<span class="pulse-dot"></span> Đang xử lý ETL, chia đoạn và đánh chỉ mục Qdrant...';
            if (ingestResultDetails) ingestResultDetails.style.display = 'none';

            try {
                const res = await api.ingestDomainData(targetDomain, formData);
                if (ingestStatusMsg) {
                    ingestStatusMsg.innerHTML = `✅ <strong>${res.message}</strong>`;
                }
                if (ingestResultDetails) {
                    ingestResultDetails.style.display = 'block';
                    ingestResultDetails.innerHTML = `
                        <div style="margin-top:6px; font-size:12px; color:var(--text-main);">
                            • Số tài liệu đọc được: <strong>${res.total_loaded}</strong><br>
                            • Tài liệu hợp lệ: <strong>${res.total_valid}</strong><br>
                            • Sau khử trùng lặp: <strong>${res.total_after_dedup}</strong><br>
                            • Tổng số chunks đã nạp Qdrant: <strong style="color:var(--primary); font-size:14px;">${res.total_chunks}</strong><br>
                            • Thời gian xử lý: <strong>${res.elapsed_seconds}s</strong>
                        </div>
                    `;
                }
                showToast(`Nạp thành công ${res.total_chunks} chunks vào domain ${targetDomain}!`);
                
                // Đồng bộ và chuyển sang domain vừa nạp
                await refreshDomainList(targetDomain);
                domainSelect.value = targetDomain;
                applyDomainConfig(targetDomain);
            } catch (err) {
                if (ingestStatusMsg) {
                    ingestStatusMsg.innerHTML = `❌ <span style="color:#ef4444;">Lỗi: ${escapeHtml(err.message)}</span>`;
                }
                showToast(`Lỗi: ${err.message}`, true);
            } finally {
                btnSubmitIngest.disabled = false;
            }
        });
    }

    // Handle Submit Create Domain
    if (btnSubmitCreateDomain) {
        btnSubmitCreateDomain.addEventListener('click', async () => {
            const domainId = document.getElementById('create-domain-id')?.value.trim();
            const domainName = document.getElementById('create-domain-name')?.value.trim();
            const desc = document.getElementById('create-domain-desc')?.value.trim() || '';
            const mode = document.getElementById('create-domain-mode')?.value || 'friendly';
            const role = document.getElementById('create-domain-role')?.value.trim() || 'chuyên gia tư vấn';
            const persona = document.getElementById('create-domain-persona')?.value.trim() || '';
            const riskKwStr = document.getElementById('create-domain-risk-kw')?.value.trim() || '';
            const riskKeywords = riskKwStr.split(',').map(s => s.trim()).filter(Boolean);

            if (!domainId || !domainName) {
                showToast("Vui lòng điền Domain ID và Tên hiển thị!", true);
                return;
            }

            btnSubmitCreateDomain.disabled = true;
            try {
                const res = await api.createDomain({
                    domain_id: domainId,
                    domain_name: domainName,
                    description: desc,
                    mode: mode,
                    assistant_role: role,
                    persona: persona,
                    risk_keywords: riskKeywords
                });
                showToast(res.message);
                
                // Refresh list và chuyển sang Tab 1 với domain mới
                await refreshDomainList(domainId);
                const mDomainSelect = document.getElementById('modal-domain-select');
                if (mDomainSelect) mDomainSelect.value = domainId;

                if (tabIngestData) tabIngestData.click();
            } catch (err) {
                showToast(`Lỗi tạo domain: ${err.message}`, true);
            } finally {
                btnSubmitCreateDomain.disabled = false;
            }
        });
    }
});
