/**
 * ui.js – DOM helpers, device card builders, toast notifications
 */

// ── Toast ──────────────────────────────────────────────────────────────────

const Toast = {
  show(msg, type = 'info', duration = 3500) {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    const container = document.getElementById('toast-container');
    container.appendChild(el);
    setTimeout(() => el.remove(), duration);
  },
  success: (m) => Toast.show(m, 'success'),
  error:   (m) => Toast.show(m, 'error', 5000),
  warn:    (m) => Toast.show(m, 'warn'),
};


// ── Helpers ────────────────────────────────────────────────────────────────

function formatValue(device) {
  if (device.value === null || device.value === undefined) return '–';

  const dpt = device.dpt || '';
  const main = dpt.split('.')[0];

  if (main === '1') return device.value ? 'ON' : 'OFF';

  if (typeof device.value === 'boolean') return device.value ? 'ON' : 'OFF';

  const unit = device.unit ? ' ' + device.unit : '';
  if (typeof device.value === 'number') return device.value.toFixed(1) + unit;
  if (Array.isArray(device.value)) return '[' + device.value.join(',') + ']' + unit;
  return String(device.value) + unit;
}

function categoryBadge(cat) {
  return `<span class="badge badge-${cat}">${cat}</span>`;
}

function formatTime(iso) {
  if (!iso) return '–';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString();
  } catch (_) {
    return iso;
  }
}


// ── Light grouping ────────────────────────────────────────────────────────
//
// Strips known German/English KNX suffixes to get a "base name", then groups
// all related group addresses into one tile.

const _GROUP_SUFFIXES = [
  // Longest / most specific first
  ' dimmen tw hell absolute', ' dimmen tw hell rel.',
  ' dimmen h relative',  ' dimmen h rel.',
  ' dimmen s absolute',  ' dimmen s abs.',
  ' dimmen s relative',  ' dimmen s rel.',
  ' dimmen v absolute',  ' dimmen v abs.',
  ' dimmen v relative',  ' dimmen v rel.',
  ' dimmen abs.',        ' dimmen abs',
  ' dimmen rel.',        ' dimmen rel',
  ' hsv color status',   ' hsv colorwert',
  ' rgb color status',   ' rgb colorwert',
  ' sequenz1 schalten',  ' sequenz1 status',
  ' sequenz2 schalten',  ' sequenz2 status',
  ' licht raumschaltung',' raumschaltung',
  ' wandlampen zusammen',' zusammen',
  ' schalten',           ' schalter',
  ' status',
  ' wert',
  ' dimmen',
];

function getBaseName(name) {
  const lower = name.toLowerCase().trim();
  for (var i = 0; i < _GROUP_SUFFIXES.length; i++) {
    if (lower.endsWith(_GROUP_SUFFIXES[i])) {
      return name.slice(0, name.length - _GROUP_SUFFIXES[i].length).trim();
    }
  }
  return name.trim();
}

/**
 * Groups light devices by base name.
 * Returns array of { baseName, switchDev, statusDev, dimLevelDev, extras[] }
 */
function groupLightDevices(devices) {
  var map = {};
  var order = []; // preserve insertion order (IE compat)

  devices.forEach(function(dev) {
    var base = getBaseName(dev.name);
    if (!map[base]) {
      map[base] = { baseName: base, switchDev: null, statusDev: null, dimLevelDev: null, extras: [] };
      order.push(base);
    }
    var g = map[base];
    var lower = dev.name.toLowerCase();

    if (lower.endsWith(' schalten') || lower.endsWith(' schalter')) {
      g.switchDev = dev;
    } else if (lower.endsWith(' status') && (!dev.dpt || dev.dpt.startsWith('1.'))) {
      g.statusDev = dev;
    } else if (
      lower.includes('dimmen abs') || lower.endsWith(' wert') ||
      (dev.dpt === '5.001' && dev.writable)
    ) {
      g.dimLevelDev = dev;
    } else {
      g.extras.push(dev);
    }
  });

  // For groups with no explicit switch, promote a writable boolean or sole device
  order.forEach(function(base) {
    var g = map[base];
    if (!g.switchDev) {
      var candidate = null;
      for (var i = 0; i < g.extras.length; i++) {
        if (g.extras[i].writable && g.extras[i].dpt && g.extras[i].dpt.startsWith('1.')) {
          candidate = g.extras[i]; break;
        }
      }
      if (!candidate && g.extras.length === 1) candidate = g.extras[0];
      if (candidate) {
        g.switchDev = candidate;
        g.extras = g.extras.filter(function(d) { return d !== candidate; });
      }
    }
  });

  return order.map(function(base) { return map[base]; });
}


// ── Merged light card (one tile per base name) ─────────────────────────────

function buildMergedLightCard(group) {
  var ctrl = group.switchDev || group.extras[0];
  if (!ctrl) return null;

  var feedbackDev = group.statusDev || ctrl;
  var isOn = Boolean(feedbackDev.value);
  var dimDev = group.dimLevelDev;
  var dimPct = dimDev && typeof dimDev.value === 'number' ? dimDev.value : null;

  // All devices in this group
  var allDevs = [group.switchDev, group.statusDev, group.dimLevelDev]
    .concat(group.extras)
    .filter(Boolean);

  var card = document.createElement('div');
  card.className = 'device-card ' + (isOn ? 'on' : 'off');
  card.dataset.id       = ctrl.id;
  card.dataset.addr     = ctrl.group_address;
  card.dataset.addrs    = allDevs.map(function(d) { return d.group_address; }).join(',');
  card.dataset.switchId = ctrl.id;
  card.dataset.statusId = group.statusDev ? group.statusDev.id : '';
  card.dataset.dimId    = dimDev ? dimDev.id : '';

  var extraCount = allDevs.length - 1;
  var extraBadge = extraCount > 0
    ? '<span class="card-extra-badge" title="' +
        escHtml(allDevs.slice(1).map(function(d) { return d.group_address; }).join(', ')) +
        '">+' + extraCount + '</span>'
    : '';

  var toggleHtml = ctrl.writable
    ? '<label class="toggle" title="' + (isOn ? 'ON' : 'OFF') + '">' +
        '<input type="checkbox" class="light-toggle"' + (isOn ? ' checked' : '') + ' />' +
        '<span class="toggle-slider"></span>' +
      '</label>'
    : '';

  card.innerHTML =
    '<div class="card-header">' +
      '<div class="card-name-wrap">' +
        '<div class="card-name">' + escHtml(group.baseName) + '</div>' +
        '<div class="card-addr">' + escHtml(ctrl.group_address) + extraBadge + '</div>' +
      '</div>' +
      '<div style="display:flex;gap:.3rem;align-items:center;flex-shrink:0;margin-left:.4rem">' +
        toggleHtml +
      '</div>' +
    '</div>' +
    (dimDev
      ? '<div class="range-wrap" style="margin-top:.4rem">' +
          '<input type="range" class="dim-slider" min="0" max="100" value="' +
            (dimPct !== null ? Math.round(dimPct) : 0) + '" />' +
          '<span class="range-val">' + (dimPct !== null ? Math.round(dimPct) : '–') + '%</span>' +
        '</div>'
      : '');

  // Toggle event
  var toggle = card.querySelector('.light-toggle');
  if (toggle && ctrl.writable) {
    toggle.addEventListener('change', function() {
      var val = toggle.checked;
      var promises = [];

      // Always send to the switch address if it's a real boolean device
      promises.push(
        Api.controlDevice(ctrl.id, { value: val, dpt: ctrl.dpt })
      );

      // Also send 100/0 to the dim address — many KNX dimmers only listen here
      if (dimDev && dimDev.id !== ctrl.id) {
        promises.push(
          Api.controlDevice(dimDev.id, { value: val ? 100 : 0, dpt: dimDev.dpt || '5.001' })
        );
      }

      Promise.all(promises)
        .then(function() {
          card.classList.toggle('on', val);
          card.classList.toggle('off', !val);
        })
        .catch(function(err) {
          Toast.error('Control failed: ' + err.message);
          toggle.checked = !val;
        });
    });
  }

  // Dim slider event
  if (dimDev) {
    var slider = card.querySelector('.dim-slider');
    var valLabel = card.querySelector('.range-val');
    var debounce = null;
    slider.addEventListener('input', function() {
      valLabel.textContent = Math.round(slider.value) + '%';
      clearTimeout(debounce);
      debounce = setTimeout(function() {
        Api.controlDevice(dimDev.id, { value: parseFloat(slider.value), dpt: dimDev.dpt || '5.001' })
          .catch(function(err) { Toast.error('Dim failed: ' + err.message); });
      }, 300);
    });
  }

  return card;
}


// ── Light card ─────────────────────────────────────────────────────────────

function buildLightCard(device) {
  const dpt  = device.dpt || '';
  const main = parseInt(dpt.split('.')[0] || '0', 10);
  const isOn = Boolean(device.value);
  const isDimmer = main === 5;

  const card = document.createElement('div');
  card.className = `device-card ${device.writable && isOn ? 'on' : 'off'}`;
  card.dataset.id = device.id;
  card.dataset.addr = device.group_address;

  let controls = '';
  if (device.writable) {
    controls = `
      <label class="toggle" title="${isOn ? 'ON' : 'OFF'}">
        <input type="checkbox" class="light-toggle" ${isOn ? 'checked' : ''} />
        <span class="toggle-slider"></span>
      </label>`;

    if (isDimmer) {
      const pct = typeof device.value === 'number' ? device.value : 0;
      controls += `
        <div class="range-wrap" style="margin-top:.3rem">
          <input type="range" class="dim-slider" min="0" max="100" value="${pct}" />
          <span class="range-val">${Math.round(pct)}%</span>
        </div>`;
    }
  }

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-name">${escHtml(device.name)}</div>
        <div class="card-addr">${escHtml(device.group_address)}</div>
      </div>
      <div style="display:flex;gap:.3rem;align-items:center">
        ${device.dpt ? `<span class="card-dpt">${escHtml(device.dpt)}</span>` : ''}
        ${controls}
      </div>
    </div>`;

  // Toggle listener
  const toggle = card.querySelector('.light-toggle');
  if (toggle) {
    toggle.addEventListener('change', async () => {
      const val = toggle.checked;
      try {
        await Api.controlDevice(device.id, { value: val, dpt: device.dpt });
        card.classList.toggle('on', val);
        card.classList.toggle('off', !val);
      } catch (err) {
        Toast.error('Control failed: ' + err.message);
        toggle.checked = !val;
      }
    });
  }

  // Dimmer slider listener
  const slider = card.querySelector('.dim-slider');
  if (slider) {
    const valLabel = card.querySelector('.range-val');
    let debounce = null;
    slider.addEventListener('input', () => {
      valLabel.textContent = slider.value + '%';
      clearTimeout(debounce);
      debounce = setTimeout(async () => {
        try {
          await Api.controlDevice(device.id, { value: parseFloat(slider.value), dpt: device.dpt });
        } catch (err) {
          Toast.error('Dim failed: ' + err.message);
        }
      }, 300);
    });
  }

  return card;
}


// ── Blind grouping ────────────────────────────────────────────────────────
//
// Strips known suffixes to get a base name, then groups all related group
// addresses (move, step/stop, position, status) into one tile.

const _BLIND_SUFFIXES = [
  ' schritt/stop', ' step/stop',
  ' bewegen', ' fahren', ' fahrt', ' move',
  ' position', ' pos',
  ' status',
  ' auf/ab', ' auf', ' ab',
];

function getBlindBaseName(name) {
  const lower = name.toLowerCase().trim();
  for (let i = 0; i < _BLIND_SUFFIXES.length; i++) {
    if (lower.endsWith(_BLIND_SUFFIXES[i])) {
      return name.slice(0, name.length - _BLIND_SUFFIXES[i].length).trim();
    }
  }
  return name.trim();
}

/**
 * Groups blind move-devices with their sub-addresses by matching base name
 * across ALL devices (sub-addresses may have category=unknown).
 */
function groupBlindDevices(blindDevs, allDevs) {
  const map = {};
  const order = [];

  blindDevs.forEach(dev => {
    const base = getBlindBaseName(dev.name);
    if (!map[base]) {
      map[base] = { baseName: base, moveDev: dev, stepStopDev: null, posDev: null, statusDev: null };
      order.push(base);
    }
  });

  // Pull in related sub-addresses from all devices by matching base name
  allDevs.forEach(dev => {
    const base = getBlindBaseName(dev.name);
    const g = map[base];
    if (!g || dev === g.moveDev) return;
    const lower = dev.name.toLowerCase();
    if (lower.includes('schritt') || lower.includes('step') || lower.includes('stop')) {
      g.stepStopDev = dev;
    } else if (lower.includes('position') || lower.endsWith(' pos')) {
      g.posDev = dev;
    } else if (lower.endsWith(' status') || lower.includes('status')) {
      g.statusDev = dev;
    }
  });

  return order.map(base => map[base]);
}


// ── Merged blind card ─────────────────────────────────────────────────────

function buildMergedBlindCard(group) {
  const moveDev = group.moveDev;
  if (!moveDev) return null;

  // Position feedback: prefer dedicated status device, fall back to position device
  const posFeedback = group.statusDev || group.posDev;
  const pos = posFeedback && typeof posFeedback.value === 'number'
    ? Math.round(posFeedback.value) : null;
  const posLabel = pos !== null ? `${pos}%` : '–';

  const allDevs = [moveDev, group.stepStopDev, group.posDev, group.statusDev].filter(Boolean);
  const extraCount = allDevs.length - 1;
  const extraBadge = extraCount > 0
    ? `<span class="card-extra-badge" title="${escHtml(allDevs.slice(1).map(d => d.group_address).join(', '))}">+${extraCount}</span>`
    : '';

  const card = document.createElement('div');
  card.className = 'device-card';
  card.dataset.id            = moveDev.id;
  card.dataset.addr          = moveDev.group_address;
  card.dataset.addrs         = allDevs.map(d => d.group_address).join(',');
  card.dataset.blindStatusId = group.statusDev ? group.statusDev.id
                             : (group.posDev   ? group.posDev.id : '');
  card.dataset.blindPosId    = group.posDev ? group.posDev.id : '';

  const posSliderHtml = group.posDev && pos !== null ? `
    <div class="range-wrap">
      <input type="range" class="pos-slider" min="0" max="100" value="${pos}" />
      <span class="range-val">${pos}%</span>
    </div>` : '';

  card.innerHTML = `
    <div class="card-header">
      <div class="card-name-wrap">
        <div class="card-name">${escHtml(group.baseName)}</div>
        <div class="card-addr">${escHtml(moveDev.group_address)}${extraBadge}</div>
      </div>
      ${moveDev.dpt ? `<span class="card-dpt">${escHtml(moveDev.dpt)}</span>` : ''}
    </div>
    <div style="font-size:.85rem;color:var(--text-dim)">Position: <strong class="blind-pos-val">${posLabel}</strong></div>
    ${moveDev.writable ? `
    <div class="blind-controls">
      <button class="blind-btn" data-action="up">▲ Up</button>
      <button class="blind-btn stop" data-action="stop">■ Stop</button>
      <button class="blind-btn" data-action="down">▼ Down</button>
    </div>${posSliderHtml}` : ''}`;

  if (moveDev.writable) {
    card.querySelectorAll('.blind-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        try {
          if (action === 'stop') {
            // Use dedicated step/stop address if available, otherwise fall back to move address
            const stopDev = group.stepStopDev || moveDev;
            await Api.controlDevice(stopDev.id, { value: false, dpt: stopDev.dpt || '1.001' });
          } else {
            const val = action === 'down'; // true=1=down, false=0=up
            await Api.controlDevice(moveDev.id, { value: val, dpt: moveDev.dpt || '1.008' });
          }
          Toast.success(`${group.baseName}: ${action}`);
        } catch (err) {
          Toast.error('Blind control failed: ' + err.message);
        }
      });
    });

    const slider = card.querySelector('.pos-slider');
    if (slider && group.posDev) {
      const valLabel = card.querySelector('.range-val');
      let debounce = null;
      slider.addEventListener('input', () => {
        valLabel.textContent = slider.value + '%';
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
          try {
            await Api.controlDevice(group.posDev.id, { value: parseFloat(slider.value), dpt: group.posDev.dpt || '5.001' });
          } catch (err) {
            Toast.error('Position failed: ' + err.message);
          }
        }, 300);
      });
    }
  }

  return card;
}


// ── Blind card ─────────────────────────────────────────────────────────────

function buildBlindCard(device) {
  const card = document.createElement('div');
  card.className = 'device-card';
  card.dataset.id = device.id;
  card.dataset.addr = device.group_address;

  const pos = typeof device.value === 'number' ? Math.round(device.value) : null;
  const posLabel = pos !== null ? `${pos}%` : '–';

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-name">${escHtml(device.name)}</div>
        <div class="card-addr">${escHtml(device.group_address)}</div>
      </div>
      ${device.dpt ? `<span class="card-dpt">${escHtml(device.dpt)}</span>` : ''}
    </div>
    <div style="font-size:.85rem;color:var(--text-dim)">Position: <strong>${posLabel}</strong></div>
    ${device.writable ? `
    <div class="blind-controls">
      <button class="blind-btn" data-action="up">▲ Up</button>
      <button class="blind-btn stop" data-action="stop">■ Stop</button>
      <button class="blind-btn" data-action="down">▼ Down</button>
    </div>
    ${pos !== null ? `
    <div class="range-wrap">
      <input type="range" class="pos-slider" min="0" max="100" value="${pos}" />
      <span class="range-val">${pos}%</span>
    </div>` : ''}
    ` : ''}`;

  if (device.writable) {
    card.querySelectorAll('.blind-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        // down=1, up=0, stop=0 — use the device's own DPT for all three
        const val = action === 'down';   // true(1)=down, false(0)=up/stop

        try {
          await Api.controlDevice(device.id, { value: val, dpt: device.dpt || '1.008' });
          Toast.success(`${device.name}: ${action}`);
        } catch (err) {
          Toast.error('Blind control failed: ' + err.message);
        }
      });
    });

    const slider = card.querySelector('.pos-slider');
    if (slider) {
      const valLabel = card.querySelector('.range-val');
      let debounce = null;
      slider.addEventListener('input', () => {
        valLabel.textContent = slider.value + '%';
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
          try {
            await Api.controlDevice(device.id, { value: parseFloat(slider.value), dpt: '5.001' });
          } catch (err) {
            Toast.error('Position failed: ' + err.message);
          }
        }, 350);
      });
    }
  }

  return card;
}


// ── Heating card ────────────────────────────────────────────────────────────

function buildHeatingCard(device) {
  const card = document.createElement('div');
  card.className = 'device-card';
  card.dataset.id = device.id;
  card.dataset.addr = device.group_address;

  const val = typeof device.value === 'number' ? device.value : null;
  const valStr = val !== null ? val.toFixed(1) : '–';
  const unit = device.unit || (device.dpt === '9.001' ? '°C' : '');

  const isSetpoint = device.name.toLowerCase().includes('setpoint') ||
                     device.name.toLowerCase().includes('soll');

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-name">${escHtml(device.name)}</div>
        <div class="card-addr">${escHtml(device.group_address)}</div>
      </div>
      ${device.dpt ? `<span class="card-dpt">${escHtml(device.dpt)}</span>` : ''}
    </div>
    <div class="temp-display">
      <span class="temp-value" id="hval-${device.id}">${escHtml(valStr)}</span>
      <span class="temp-unit">${escHtml(unit)}</span>
    </div>
    ${device.writable && isSetpoint ? `
    <div class="setpoint-row">
      <button class="setpoint-btn" data-delta="-0.5">−</button>
      <span class="setpoint-val" id="sp-${device.id}">${escHtml(valStr)} ${escHtml(unit)}</span>
      <button class="setpoint-btn" data-delta="0.5">+</button>
    </div>` : ''}`;

  if (device.writable && isSetpoint) {
    let current = val !== null ? val : 20;
    card.querySelectorAll('.setpoint-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        current = Math.round((current + parseFloat(btn.dataset.delta)) * 2) / 2;
        card.querySelector(`#sp-${device.id}`).textContent = `${current.toFixed(1)} ${unit}`;
        try {
          await Api.controlDevice(device.id, { value: current, dpt: device.dpt });
        } catch (err) {
          Toast.error('Setpoint failed: ' + err.message);
        }
      });
    });
  }

  return card;
}


// ── Sensor card ─────────────────────────────────────────────────────────────

function buildSensorCard(device) {
  const card = document.createElement('div');
  card.className = 'device-card';
  card.dataset.id = device.id;
  card.dataset.addr = device.group_address;

  const val = device.value;
  const unit = device.unit || '';
  const valStr = val !== null && val !== undefined
    ? (typeof val === 'number' ? val.toFixed(2) : String(val))
    : '–';

  card.innerHTML = `
    <div class="card-header">
      <div>
        <div class="card-name">${escHtml(device.name)}</div>
        <div class="card-addr">${escHtml(device.group_address)}</div>
      </div>
      ${device.dpt ? `<span class="card-dpt">${escHtml(device.dpt)}</span>` : ''}
    </div>
    <div style="display:flex;align-items:baseline;gap:.3rem">
      <span class="sensor-value" id="sval-${device.id}">${escHtml(valStr)}</span>
      <span class="sensor-unit">${escHtml(unit)}</span>
    </div>
    <div style="font-size:.72rem;color:var(--text-muted)">${device.dpt_name || ''}</div>`;

  return card;
}


// ── Find a rendered card by any of its KNX addresses ─────────────────────

function findCardForAddress(addr) {
  var direct = document.querySelector('[data-addr="' + addr + '"]');
  if (direct) return direct;
  // Search merged cards (comma-separated data-addrs)
  var candidates = document.querySelectorAll('[data-addrs]');
  for (var i = 0; i < candidates.length; i++) {
    var list = candidates[i].dataset.addrs.split(',');
    if (list.indexOf(addr) !== -1) return candidates[i];
  }
  return null;
}


// ── Update an existing card in-place ────────────────────────────────────────

function updateCard(device) {
  var card = findCardForAddress(device.group_address);
  if (!card) return;

  var switchId = parseInt(card.dataset.switchId || '0', 10);
  var statusId = parseInt(card.dataset.statusId || '0', 10);
  var dimId    = parseInt(card.dataset.dimId    || '0', 10);

  // ON/OFF toggle + card class — driven by switch or status device
  if (!dimId || device.id === switchId || device.id === statusId) {
    var toggle = card.querySelector('.light-toggle');
    var isOn = Boolean(device.value);
    if (toggle) {
      toggle.checked = isOn;
      card.classList.toggle('on', isOn);
      card.classList.toggle('off', !isOn);
    }
  }

  // Dim slider — driven by dim device
  if (!dimId || device.id === dimId) {
    var slider = card.querySelector('.dim-slider');
    if (slider && typeof device.value === 'number') {
      slider.value = device.value;
      var lbl = card.querySelector('.range-val');
      if (lbl) lbl.textContent = Math.round(device.value) + '%';
    }
  }

  // Temp / sensor value labels (IDs are per-device)
  var hval = card.querySelector('#hval-' + device.id);
  if (hval && typeof device.value === 'number') hval.textContent = device.value.toFixed(1);

  // Blind merged card: position display + slider
  var blindPosVal = card.querySelector('.blind-pos-val');
  if (blindPosVal) {
    var blindStatusId = parseInt(card.dataset.blindStatusId || '0', 10);
    var blindPosId    = parseInt(card.dataset.blindPosId    || '0', 10);
    if ((blindStatusId && device.id === blindStatusId) || (blindPosId && device.id === blindPosId)) {
      if (typeof device.value === 'number') {
        blindPosVal.textContent = Math.round(device.value) + '%';
        var posSlider = card.querySelector('.pos-slider');
        if (posSlider) {
          posSlider.value = Math.round(device.value);
          var rangeVal = card.querySelector('.range-val');
          if (rangeVal) rangeVal.textContent = Math.round(device.value) + '%';
        }
      }
    }
  }

  var sval = card.querySelector('#sval-' + device.id);
  if (sval && device.value !== null && device.value !== undefined) {
    sval.textContent = typeof device.value === 'number'
      ? device.value.toFixed(2)
      : String(device.value);
  }
}


// ── Device table row ────────────────────────────────────────────────────────

function buildTableRow(device, onEdit, onDelete) {
  const tr = document.createElement('tr');
  tr.dataset.id = device.id;
  tr.dataset.addr = device.group_address;

  const editBtn   = '<button class="btn-icon edit-btn"   title="Edit">✎</button>';
  const deleteBtn = '<button class="btn-icon delete delete-btn" title="Delete">✕</button>';
  const readBtn   = device.readable
    ? '<button class="btn-icon read-btn" title="Read">↻</button>'
    : '';

  tr.innerHTML = `
    <td><code>${escHtml(device.group_address)}</code></td>
    <td>${escHtml(device.name)}</td>
    <td>${categoryBadge(device.category)}</td>
    <td>${device.dpt ? `<code>${escHtml(device.dpt)}</code>` : '–'}</td>
    <td class="val-cell">${escHtml(formatValue(device))}</td>
    <td>${formatTime(device.last_seen)}</td>
    <td style="white-space:nowrap">${readBtn} ${editBtn} ${deleteBtn}</td>`;

  tr.querySelector('.edit-btn').addEventListener('click', () => onEdit(device));
  tr.querySelector('.delete-btn').addEventListener('click', () => onDelete(device));
  if (device.readable) {
    tr.querySelector('.read-btn').addEventListener('click', async () => {
      try {
        await Api.readDevice(device.id);
        Toast.success('Read request sent');
      } catch (err) {
        Toast.error(err.message);
      }
    });
  }
  return tr;
}


// ── Security helper ─────────────────────────────────────────────────────────

function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
