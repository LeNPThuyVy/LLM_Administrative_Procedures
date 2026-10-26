class APIClient {
    constructor() {
        this.sessionId = null;
        this.userId = null;
        this.socket = null;
        this.onMessageCallback = null;
        this.onErrorCallback = null;
        this.onCloseCallback = null;
        this.reconnectTimer = null;
        this.isExplicitDisconnect = false;
    }

    async bootstrapSession() {
        try {
            const res = await fetch('/api/session/bootstrap');
            const data = await res.json();
            this.sessionId = data.session_id;
            this.userId = data.user_id;
            return data.session_id;
        } catch (error) {
            console.error("Failed to bootstrap session", error);
            return null;
        }
    }

    async loadDomains() {
        try {
            const res = await fetch('/api/domains');
            if (res.ok) {
                return await res.json();
            }
        } catch (error) {
            console.error("Failed to load domains", error);
        }
        return [];
    }

    async loadDomainDetails() {
        try {
            const res = await fetch('/api/domains/details');
            if (res.ok) {
                return await res.json();
            }
        } catch (error) {
            console.error("Failed to load domain details", error);
        }
        return [];
    }

    async createDomain(domainData) {
        try {
            const res = await fetch('/api/domains/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(domainData)
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Không thể tạo domain mới");
            }
            return data;
        } catch (error) {
            console.error("Error creating domain", error);
            throw error;
        }
    }

    async ingestDomainData(domainId, formData) {
        try {
            const res = await fetch(`/api/domains/${domainId}/ingest`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Không thể nạp dữ liệu vào domain");
            }
            return data;
        } catch (error) {
            console.error("Error ingesting data", error);
            throw error;
        }
    }

    async deleteDomain(domainId) {
        try {
            const res = await fetch(`/api/domains/${encodeURIComponent(domainId)}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || "Không thể xóa domain");
            }
            return data;
        } catch (error) {
            console.error("Error deleting domain", error);
            throw error;
        }
    }

    async loadSessions() {
        try {
            const res = await fetch('/api/sessions');
            if (res.ok) {
                return await res.json();
            }
        } catch (error) {
            console.error("Failed to load sessions", error);
        }
        return [];
    }

    async loadSessionMessages(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}/messages`);
            if (res.ok) {
                return await res.json();
            }
        } catch (error) {
            console.error("Failed to load session messages", error);
        }
        return null;
    }

    async createNewSession() {
        try {
            const res = await fetch('/api/sessions/new', { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                this.sessionId = data.session_id;
                return data;
            }
        } catch (error) {
            console.error("Failed to create new session", error);
        }
        return null;
    }

    async switchSession(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}/switch`, { method: 'POST' });
            if (res.ok) {
                this.sessionId = sessionId;
                return true;
            }
        } catch (error) {
            console.error("Failed to switch session", error);
        }
        return false;
    }

    async deleteSession(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
            return res.ok;
        } catch (error) {
            console.error("Failed to delete session", error);
            return false;
        }
    }

    connectWebSocket(onMessage, onError, onClose) {
        if (!this.sessionId) return;
        this.isExplicitDisconnect = false;

        if (onMessage) this.onMessageCallback = onMessage;
        if (onError) this.onErrorCallback = onError;
        if (onClose) this.onCloseCallback = onClose;

        if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
            return;
        }

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/chat?session_id=${encodeURIComponent(this.sessionId)}`;

        try {
            this.socket = new WebSocket(wsUrl);

            this.socket.onopen = () => {
                console.log("[WS] Connected successfully to:", wsUrl);
                if (this.reconnectTimer) {
                    clearTimeout(this.reconnectTimer);
                    this.reconnectTimer = null;
                }
                const badge = document.getElementById('session-badge');
                if (badge) badge.style.color = 'var(--primary)';
            };

            this.socket.onmessage = (event) => {
                try {
                    const payload = JSON.parse(event.data);
                    if (this.onMessageCallback) this.onMessageCallback(payload);
                } catch (e) {
                    console.error("Error parsing WS message", e);
                }
            };

            this.socket.onerror = (error) => {
                console.error("WebSocket error", error);
                if (this.onErrorCallback) this.onErrorCallback(error);
            };

            this.socket.onclose = (event) => {
                console.log("[WS] Closed with code:", event.code);
                const badge = document.getElementById('session-badge');
                if (badge) badge.style.color = 'var(--text-muted)';

                if (this.onCloseCallback) this.onCloseCallback(event);

                // Auto-reconnect nếu không phải do người dùng ngắt kết nối chủ động
                if (!this.isExplicitDisconnect) {
                    if (!this.reconnectTimer) {
                        this.reconnectTimer = setTimeout(() => {
                            this.reconnectTimer = null;
                            console.log("[WS] Attempting auto-reconnect...");
                            this.connectWebSocket();
                        }, 2000);
                    }
                }
            };
        } catch (err) {
            console.error("Error creating WebSocket", err);
        }
    }

    async sendMessage(query, domain) {
        // Nếu socket chưa mở hoặc đang đóng, cố gắng kết nối lại
        if (!this.socket || this.socket.readyState === WebSocket.CLOSED || this.socket.readyState === WebSocket.CLOSING) {
            this.connectWebSocket();
        }

        // Đợi socket mở tối đa 3000ms
        if (this.socket && this.socket.readyState === WebSocket.CONNECTING) {
            await new Promise((resolve) => {
                const checkInterval = setInterval(() => {
                    if (!this.socket || this.socket.readyState !== WebSocket.CONNECTING) {
                        clearInterval(checkInterval);
                        resolve();
                    }
                }, 100);
                setTimeout(() => {
                    clearInterval(checkInterval);
                    resolve();
                }, 3000);
            });
        }

        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ query, domain }));
            return true;
        }

        return false;
    }

    disconnect() {
        this.isExplicitDisconnect = true;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.socket) {
            this.socket.onclose = null;
            this.socket.onerror = null;
            this.socket.close();
            this.socket = null;
        }
    }
}

const api = new APIClient();
window.api = api;
