/**
 * app.js – main application entry point
 * Handles routing, state, WebSocket events, page rendering and user actions.
 */

// ── State ──────────────────────────────────────────────────────────────────

const State = {
  devices: [],             // All Device objects from API
  currentPage: 'dashboard',
  activityLog: [],
  connected: false,

  deviceById(id)   { return this.devices.find(d => d.id === id); },
  deviceByAddr(a)  { return this.devices.find(d => d.group_address === a); },

  upsertDevice(dev) {
    const idx = this.devices.findIndex(d => d.id === dev.id);
    if (idx >= 0) this.devices[idx] = dev;
    else this.devices.push(dev);
  },

  removeDevice(id) {
    this.devices = this.devices.filter(d => d.id !== id);
  },
};


// ── Router ─────────────────────────────────────────────────────────────────

function navigate(page) {
  document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));

  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (navEl) navEl.classList.add('active');

  State.currentPage = page;
  renderPage(page);
}

function renderPage(page) {
  switch (page) {
    case 'dashboard':  renderDashboard(); break;
    case 'lights':     renderCategory('lights',     'light');      break;
    case 'blinds':     renderCategory('blinds',     'blind');      break;
    case 'heating':    renderCategory('heating',    'heating');    break;
    case 'sensors':    renderCategory('sensors',    'sensor');     break;
    case 'sprinkler': renderCategory('sprinkler', 'sprinkler'); break;
    case 'media':     renderCategory('media',     'media');      break;
    case 'devices':    renderDeviceTable(); break;
    case 'settings':   renderSettings(); break;
  }
}


// ── Dashboard ──────────────────────────────────────────────────────────────

async function renderDashboard() {
  try {
    const stats = await Api.getStats();
    document.getElementById('stat-lights').textContent  = stats.by_category.light  || 0;
    document.getElementById('stat-blinds').textContent  = stats.by_category.blind  || 0;
    document.getElementById('stat-sensors').textContent = stats.by_category.sensor || 0;
    document.getElementById('stat-temp').textContent    =
      stats.avg_temperature !== null ? stats.avg_temperature + ' °C' : '–';
  } catch (_) {}
}

function pushActivity(name, addr, value) {
  const entry = { name, addr, value, time: new Date().toLocaleTimeString() };
  State.activityLog.unshift(entry);
  if (State.activityLog.length > 50) State.activityLog.pop();

  const list = document.getElementById('activity-log');
  if (!list) return;

  const empty = list.querySelector('.activity-empty');
  if (empty) empty.remove();

  const li = document.createElement('li');
  li.innerHTML = `
    <span class="act-time">${escHtml(entry.time)}</span>
    <span class="act-name">${escHtml(name)}</span>
    <span>${escHtml(addr)}</span>
    <span style="margin-left:auto;color:var(--text-dim)">${escHtml(String(value))}</span>`;

  list.prepend(li);

  // Keep max 20 visible rows
  while (list.children.length > 20) list.lastChild.remove();
}


// ── Category pages ─────────────────────────────────────────────────────────

function renderCategory(gridId, category) {
  const grid = document.getElementById(gridId + '-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const devices = State.devices.filter(d => d.category === category);

  if (!devices.length) {
    grid.innerHTML = '<div class="loading-msg">No ' + category + ' devices discovered yet.<br>Devices appear automatically as KNX telegrams are received.</div>';
    return;
  }

  devices.sort((a, b) => a.name.localeCompare(b.name));

  if (category === 'light' || category === 'sprinkler') {
    // Group related addresses (schalten + Status + dimmen…) into one tile
    const groups = groupLightDevices(devices);
    groups.sort((a, b) => a.baseName.localeCompare(b.baseName));
    groups.forEach(g => {
      const card = buildMergedLightCard(g);
      if (card) grid.appendChild(card);
    });
  } else if (category === 'blind') {
    // Group move + step/stop + position + status addresses into one tile
    const groups = groupBlindDevices(devices, State.devices);
    groups.sort((a, b) => a.baseName.localeCompare(b.baseName));
    groups.forEach(g => {
      const card = buildMergedBlindCard(g);
      if (card) grid.appendChild(card);
    });
  } else {
    devices.forEach(dev => {
      let card;
      if (category === 'heating') card = buildHeatingCard(dev);
      else                         card = buildSensorCard(dev);
      grid.appendChild(card);
    });
  }
}


// ── Device table ───────────────────────────────────────────────────────────

function renderDeviceTable() {
  const tbody = document.getElementById('device-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  // Always read the current filter from the DOM — this prevents WS updates from resetting it
  const searchInput = document.getElementById('device-search');
  const filter = searchInput ? searchInput.value : '';

  let devices = [...State.devices];
  if (filter) {
    const q = filter.toLowerCase();
    devices = devices.filter(d =>
      d.name.toLowerCase().includes(q) || d.group_address.includes(q)
    );
  }

  if (!devices.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading-msg">No devices found.</td></tr>';
    return;
  }

  devices.sort((a, b) => a.group_address.localeCompare(b.group_address, undefined, { numeric: true }));

  devices.forEach(dev => {
    const row = buildTableRow(dev, openEditModal, confirmDelete);
    tbody.appendChild(row);
  });
}


// ── Settings page ──────────────────────────────────────────────────────────

async function renderSettings() {
  try {
    const status = await Api.getStatus();
    if (status.gateway_host) {
      document.getElementById('s-host').value = status.gateway_host;
      document.getElementById('s-port').value = status.gateway_port || 3671;
      document.getElementById('s-type').value = status.connection_type || 'tunneling';
    }
    updateConnectionUI(status.connected);
  } catch (_) {}
}


// ── Connection UI ──────────────────────────────────────────────────────────

function updateConnectionUI(connected) {
  State.connected = connected;
  const dot   = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  if (dot) dot.className = 'dot' + (connected ? ' connected' : '');
  if (label) label.textContent = connected ? 'Connected' : 'Disconnected';
}


// ── Edit / Add Device Modal ─────────────────────────────────────────────────

function openEditModal(device) {
  document.getElementById('modal-title').textContent   = device ? 'Edit Device' : 'Add Device';
  document.getElementById('modal-device-id').value     = device ? device.id : '';
  document.getElementById('modal-name').value           = device ? device.name : '';
  document.getElementById('modal-address').value        = device ? device.group_address : '';
  document.getElementById('modal-address').disabled     = !!device; // can't change addr on edit
  document.getElementById('modal-category').value       = device ? device.category : 'unknown';
  document.getElementById('modal-dpt').value            = device ? (device.dpt || '') : '';
  document.getElementById('modal-writable').checked     = device ? device.writable : true;
  document.getElementById('modal-readable').checked     = device ? device.readable : true;
  document.getElementById('modal-overlay').removeAttribute('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').setAttribute('hidden', '');
}


// ── Delete ──────────────────────────────────────────────────────────────────

async function confirmDelete(device) {
  if (!confirm(`Delete "${device.name}" (${device.group_address})?`)) return;
  try {
    await Api.deleteDevice(device.id);
    State.removeDevice(device.id);
    renderPage(State.currentPage);
    Toast.success('Device deleted');
  } catch (err) {
    Toast.error('Delete failed: ' + err.message);
  }
}


// ── WebSocket events ────────────────────────────────────────────────────────

WS.on('init', (data) => {
  if (data.devices) {
    State.devices = data.devices;
    renderPage(State.currentPage);
  }
  if (data.connection) {
    updateConnectionUI(data.connection.connected);
  }
});

WS.on('device_update', (dev) => {
  const isNew = !State.deviceById(dev.id);   // check BEFORE upsert
  State.upsertDevice(dev);
  updateCard(dev);                            // fast in-place update
  pushActivity(dev.name, dev.group_address, dev.value !== null ? dev.value : '–');

  // Only do a full re-render when a brand-new device appears on the bus
  // (for existing devices updateCard handles all in-place changes)
  const catMap = { light: 'lights', blind: 'blinds', heating: 'heating', sensor: 'sensors', sprinkler: 'sprinkler', media: 'media' };
  if (isNew && catMap[dev.category] === State.currentPage) {
    renderCategory(State.currentPage, dev.category);
  }
  if (State.currentPage === 'devices') renderDeviceTable();
  if (State.currentPage === 'dashboard') renderDashboard();
});

WS.on('full_refresh', (devices) => {
  State.devices = devices;
  renderPage(State.currentPage);
  Toast.success(`Devices refreshed (${devices.length} total)`);
});

WS.on('connection_status', (status) => {
  updateConnectionUI(status.connected);
  Toast[status.connected ? 'success' : 'warn'](
    status.connected ? 'Connected to KNX gateway' : 'Disconnected from KNX gateway'
  );
});

WS.on('ws_disconnected', () => updateConnectionUI(false));


// ── Event listeners ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Navigation
  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      navigate(item.dataset.page);
      // Close sidebar on mobile
      document.getElementById('sidebar').classList.remove('open');
    });
  });

  // Mobile sidebar toggle
  const toggle = document.getElementById('sidebar-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('open');
    });
  }

  // Settings form – connect
  document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const host = document.getElementById('s-host').value.trim();
    const port = parseInt(document.getElementById('s-port').value, 10);
    const type = document.getElementById('s-type').value;
    try {
      await Api.connect({ gateway_host: host, gateway_port: port, connection_type: type });
      Toast.success('Connecting to ' + host + '…');
    } catch (err) {
      Toast.error('Connection failed: ' + err.message);
    }
  });

  // Settings – disconnect
  document.getElementById('btn-disconnect').addEventListener('click', async () => {
    try {
      await Api.disconnect();
    } catch (err) {
      Toast.error(err.message);
    }
  });

  // ETS file picker in settings
  const etsFileInput = document.getElementById('ets-file-input');
  const etsFileName  = document.getElementById('ets-file-name');
  const etsUploadBtn = document.getElementById('btn-ets-upload');

  if (etsFileInput) {
    etsFileInput.addEventListener('change', () => {
      const f = etsFileInput.files[0];
      if (f) {
        etsFileName.textContent = f.name;
        etsUploadBtn.disabled = false;
      }
    });
  }
  if (etsUploadBtn) {
    etsUploadBtn.addEventListener('click', async () => {
      const f = etsFileInput.files[0];
      if (!f) return;
      etsUploadBtn.disabled = true;
      try {
        const res = await Api.importEts(f);
        Toast.success(`ETS import: ${res.imported} devices imported`);
      } catch (err) {
        Toast.error('Import failed: ' + err.message);
      } finally {
        etsUploadBtn.disabled = false;
      }
    });
  }

  // Devices page – import ETS button
  const btnImport = document.getElementById('btn-import-ets');
  if (btnImport) {
    btnImport.addEventListener('click', () => {
      navigate('settings');
    });
  }

  // Devices page – add device button
  const btnAdd = document.getElementById('btn-add-device');
  if (btnAdd) {
    btnAdd.addEventListener('click', () => openEditModal(null));
  }

  // Device search — no need to pass value; renderDeviceTable reads it from DOM
  const searchInput = document.getElementById('device-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => renderDeviceTable());
  }

  // Lights – All Off
  document.getElementById('lights-all-off').addEventListener('click', async () => {
    // Only target writable boolean (switch) devices, not status/dim feedback addresses
    const lights = State.devices.filter(d =>
      d.category === 'light' && d.writable &&
      (!d.dpt || d.dpt.startsWith('1.'))
    );
    const tasks = lights.map(d => Api.controlDevice(d.id, { value: false, dpt: d.dpt }));
    const results = await Promise.allSettled(tasks);
    const failed = results.filter(r => r.status === 'rejected').length;
    if (failed) Toast.warn(`${failed} device(s) failed to turn off`);
    else Toast.success('All lights turned off');
  });

  // Sprinkler – All Off
  document.getElementById('sprinkler-all-off').addEventListener('click', async () => {
    const valves = State.devices.filter(d => d.category === 'sprinkler' && d.writable);
    const tasks = valves.map(d => Api.controlDevice(d.id, { value: false, dpt: d.dpt }));
    const results = await Promise.allSettled(tasks);
    const failed = results.filter(r => r.status === 'rejected').length;
    if (failed) Toast.warn(`${failed} valve(s) failed to close`);
    else Toast.success('All valves closed');
  });

  // Modal – cancel
  document.getElementById('modal-cancel').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  });

  // Modal – submit (create / update)
  document.getElementById('modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id      = document.getElementById('modal-device-id').value;
    const name    = document.getElementById('modal-name').value.trim();
    const address = document.getElementById('modal-address').value.trim();
    const cat     = document.getElementById('modal-category').value;
    const dpt     = document.getElementById('modal-dpt').value.trim() || null;
    const writable= document.getElementById('modal-writable').checked;
    const readable= document.getElementById('modal-readable').checked;

    try {
      if (id) {
        // Update
        const upd = await Api.updateDevice(parseInt(id, 10), {
          name, category: cat, dpt, writable, readable,
        });
        State.upsertDevice(upd);
        Toast.success('Device updated');
      } else {
        // Create
        const dev = await Api.createDevice({
          group_address: address, name, category: cat, dpt, writable, readable,
        });
        State.upsertDevice(dev);
        Toast.success('Device added');
      }
      closeModal();
      renderPage(State.currentPage);
    } catch (err) {
      Toast.error('Save failed: ' + err.message);
    }
  });

  // ── Boot sequence ─────────────────────────────────────────────────────────
  WS.connect();

  // Load initial device list even before WS init event (graceful fallback)
  try {
    const devices = await Api.getDevices();
    if (devices.length && !State.devices.length) {
      State.devices = devices;
      renderPage(State.currentPage);
    }
    const status = await Api.getStatus();
    updateConnectionUI(status.connected);
  } catch (_) {}

  navigate('dashboard');
});
