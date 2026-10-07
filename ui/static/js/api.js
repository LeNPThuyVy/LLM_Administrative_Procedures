class APIClient {
    constructor() {
        this.sessionId = null;
        this.socket = null;
    }

    async bootstrapSession() {
        try {
            const res = await fetch('/api/session/bootstrap');
            const data = await res.json();
            this.sessionId = data.session_id;
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

    connectWebSocket(onMessage, onError, onClose) {
        if (!this.sessionId) return;
        
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/chat`;
        
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                onMessage(payload);
            } catch (e) {
                console.error("Error parsing WS message", e);
            }
        };
        
        this.socket.onerror = (error) => {
            console.error("WebSocket error", error);
            if (onError) onError(error);
        };
        
        this.socket.onclose = () => {
            console.log("WebSocket closed");
            if (onClose) onClose();
        };
    }

    sendMessage(query, domain) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ query, domain }));
            return true;
        }
        return false;
    }

    disconnect() {
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
    }
}

const api = new APIClient();
window.api = api;
