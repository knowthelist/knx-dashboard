/**
 * api.js – thin fetch wrapper + WebSocket manager
 */

const API_BASE = '/api';

const Api = {
  async _request(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get:    (p)    => Api._request('GET',    p),
  post:   (p, b) => Api._request('POST',   p, b),
  put:    (p, b) => Api._request('PUT',    p, b),
  delete: (p)    => Api._request('DELETE', p),

  // ── KNX connection ───────────────────────────────────────────────────────
  getStatus:    ()     => Api.get('/status'),
  connect:      (cfg)  => Api.post('/connect', cfg),
  disconnect:   ()     => Api.post('/disconnect'),

  // ── Stats ────────────────────────────────────────────────────────────────
  getStats: () => Api.get('/stats'),

  // ── Devices ─────────────────────────────────────────────────────────────
  getDevices:       (cat)      => Api.get('/devices' + (cat ? `?category=${cat}` : '')),
  createDevice:     (payload)  => Api.post('/devices', payload),
  updateDevice:     (id, upd)  => Api.put(`/devices/${id}`, upd),
  deleteDevice:     (id)       => Api.delete(`/devices/${id}`),
  controlDevice:    (id, req)  => Api.post(`/devices/${id}/control`, req),
  readDevice:       (id)       => Api.post(`/devices/${id}/read`),

  // ── ETS import ───────────────────────────────────────────────────────────
  async importEts(file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(API_BASE + '/import/ets', { method: 'POST', body: form });
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail || msg; } catch (_) {}
      throw new Error(msg);
    }
    return res.json();
  },
};


/**
 * WebSocket manager – auto-reconnects, dispatches typed events.
 */
const WS = {
  _socket: null,
  _handlers: {},
  _reconnectDelay: 3000,

  on(type, handler) {
    if (!this._handlers[type]) this._handlers[type] = [];
    this._handlers[type].push(handler);
  },

  _emit(type, data) {
    (this._handlers[type] || []).forEach(h => h(data));
    (this._handlers['*'] || []).forEach(h => h({ type, data }));
  },

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url   = `${proto}://${location.host}/ws`;

    this._socket = new WebSocket(url);

    this._socket.onopen = () => {
      console.log('[WS] connected');
      this._emit('ws_connected', {});
    };

    this._socket.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        this._emit(msg.type, msg.data);
      } catch (_) {}
    };

    this._socket.onclose = () => {
      console.log('[WS] disconnected, reconnecting…');
      this._emit('ws_disconnected', {});
      setTimeout(() => this.connect(), this._reconnectDelay);
    };

    this._socket.onerror = (err) => {
      console.error('[WS] error', err);
    };
  },

  send(msg) {
    if (this._socket && this._socket.readyState === WebSocket.OPEN) {
      this._socket.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
  },
};
