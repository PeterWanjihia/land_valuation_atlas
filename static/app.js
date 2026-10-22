/* Land Valuation Atlas — Leaflet frontend; all records are stored by the SQLite backend. */
'use strict';

const state = { plots: [], overlays: [], selectedId: null, editingId: null, markers: new Map(), toastTimer: null };
const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const formatNum = (value, decimals = 0) => new Intl.NumberFormat('en-KE', { maximumFractionDigits: decimals }).format(Number(value));
function formatMoney(value) {
  const number = Number(value);
  if (number >= 1_000_000) return `KES ${formatNum(number / 1_000_000, 2)}M`;
  if (number >= 1_000) return `KES ${formatNum(number / 1_000, 1)}K`;
  return `KES ${formatNum(number)}`;
}
function formatMonth(ym) {
  if (!/^\d{4}-\d{2}$/.test(ym || '')) return ym || 'Unknown';
  const [year, month] = ym.split('-').map(Number);
  return new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)));
}
function toast(message, error = false) {
  const el = $('#toast');
  el.textContent = message;
  el.style.background = error ? '#793e37' : '#183a30';
  el.classList.add('show');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch (_) { throw new Error(`Server returned HTTP ${response.status}`); }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
const map = L.map('map', { zoomControl: false, preferCanvas: true }).setView([-1.282, 36.655], 14);
const standardMap = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
});
const satelliteMap = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
  maxZoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics and the GIS User Community'
});
const lightMap = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  maxZoom: 20, attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
});
standardMap.addTo(map);
const markersLayer = L.layerGroup().addTo(map);
L.control.zoom({ position: 'bottomright' }).addTo(map);
const layerControl = L.control.layers({ 'Street map': standardMap, 'Satellite imagery': satelliteMap, 'Light map': lightMap },
  { 'Valuation pins': markersLayer }, { position: 'topright', collapsed: false }).addTo(map);
const layerObjects = new Map();

function pinIcon(selected = false) {
  return L.divIcon({ className: `pin-icon ${selected ? 'is-selected' : ''}`, html: '<div class="pin-body"><span></span></div>', iconSize: [36, 43], iconAnchor: [17, 37] });
}
function popupHTML(p) {
  const sqm = p.area_ha * 10000;
  const lat = Number(p.latitude).toFixed(6);
  const lon = Number(p.longitude).toFixed(6);
  return `<div class="property-popup">
    <div class="popup-kicker">LAND VALUATION RECORD #${p.id}</div>
    <h3>${escapeHTML(p.parcel_number)}</h3>
    <div class="popup-val">${escapeHTML(formatMoney(p.value_kes))} <small>valuation</small></div>
    <div class="popup-grid">
      <div><span>VALUATION DATE</span><strong>${escapeHTML(formatMonth(p.valuation_period))}</strong></div>
      <div><span>LAND SIZE</span><strong>${escapeHTML(p.area_ha)} ha · ${formatNum(sqm, 2)} m²</strong></div>
      <div><span>LATITUDE</span><strong>${lat}</strong></div>
      <div><span>LONGITUDE</span><strong>${lon}</strong></div>
    </div>
    ${p.locality ? `<div class="popup-location">⌖ ${escapeHTML(p.locality)}</div>` : ''}
    ${p.relative_position ? `<div class="popup-location">↗ ${escapeHTML(p.relative_position)}</div>` : ''}
    ${p.notes ? `<div class="popup-location">${escapeHTML(p.notes)}</div>` : ''}
    <div class="popup-actions"><button type="button" data-edit="${p.id}">Edit record</button><a target="_blank" rel="noopener noreferrer" href="https://maps.google.com/?q=${encodeURIComponent(`${lat},${lon}`)}">Google Maps ↗</a></div>
  </div>`;
}

function filteredPlots() {
  const search = $('#search-input').value.trim().toLowerCase();
  const year = $('#year-filter').value;
  const order = $('#sort-select').value;
  return state.plots.filter(p => {
    const text = [p.parcel_number, p.locality, p.notes, p.relative_position].join(' ').toLowerCase();
    return (!search || text.includes(search)) && (year === 'all' || p.valuation_period.slice(0,4) === year);
  }).sort((a, b) => order === 'value-high' ? b.value_kes - a.value_kes :
    order === 'value-low' ? a.value_kes - b.value_kes :
    order === 'area-high' ? b.area_ha - a.area_ha :
    b.valuation_period.localeCompare(a.valuation_period));
}
function renderStats() {
  const plots = state.plots;
  const sum = plots.reduce((acc, p) => acc + Number(p.value_kes), 0);
  const totalArea = plots.reduce((acc, p) => acc + Number(p.area_ha), 0);
  $('#stat-count').textContent = formatNum(plots.length);
  $('#stat-avg').textContent = plots.length ? formatMoney(sum / plots.length) : '—';
  $('#stat-area').textContent = `${formatNum(totalArea * 10000, 1)} m²`;
  $('#top-total').textContent = `${plots.length} mapped plot${plots.length === 1 ? '' : 's'}`;
  const yearSelect = $('#year-filter');
  const current = yearSelect.value;
  const years = [...new Set(plots.map(p => p.valuation_period.slice(0, 4)))].sort((a,b) => b.localeCompare(a));
  yearSelect.innerHTML = '<option value="all">All years</option>' + years.map(y => `<option value="${y}">${y}</option>`).join('');
  yearSelect.value = years.includes(current) ? current : 'all';
}
function renderPlots() {
  const plots = filteredPlots();
  $('#shown-count').textContent = plots.length;
  const list = $('#property-list');
  list.innerHTML = plots.length ? plots.map(p => `
    <button type="button" class="plot-card ${p.id === state.selectedId ? 'active' : ''}" data-select="${p.id}" role="listitem" aria-label="Open ${escapeHTML(p.parcel_number)}">
      <div class="plot-badge">⌖</div><div class="plot-body">
        <div class="plot-topline"><span class="plot-number" title="${escapeHTML(p.parcel_number)}">${escapeHTML(p.parcel_number)}</span></div>
        <div class="plot-desc">${escapeHTML(p.locality || 'Location recorded')} · ${escapeHTML(p.relative_position || 'GPS located')}</div>
        <div class="plot-footer"><span><b>${escapeHTML(formatMoney(p.value_kes))}</b></span><span>${formatNum(p.area_ha * 10000, 2)} m²</span><span>${escapeHTML(formatMonth(p.valuation_period))}</span></div>
      </div>
    </button>`).join('') : '<div class="empty-state">No plots match these filters.<br>Try another search or add a new property.</div>';
  markersLayer.clearLayers();
  state.markers.clear();
  for (const p of plots) {
    const marker = L.marker([p.latitude, p.longitude], { icon: pinIcon(p.id === state.selectedId) });
    marker.bindPopup(popupHTML(p), { maxWidth: 350, autoPanPadding: [35, 35] });
    marker.bindTooltip(`${p.parcel_number} · ${formatMoney(p.value_kes)}`, { direction: 'top', offset: [0,-28] });
    marker.on('click', () => choose(p.id, false));
    marker.addTo(markersLayer);
    state.markers.set(p.id, marker);
  }
}
function choose(id, animate = true) {
  state.selectedId = id;
  const plot = state.plots.find(p => p.id === id);
  renderPlots();
  const marker = state.markers.get(id);
  if (plot && marker) {
    if (animate) map.flyTo([plot.latitude, plot.longitude], Math.max(map.getZoom(), 16), { duration: 0.6 });
    marker.openPopup();
  }
}
function showAll() {
  const visible = filteredPlots();
  if (!visible.length) return;
  const bounds = L.latLngBounds(visible.map(p => [p.latitude, p.longitude]));
  if (visible.length === 1) map.setView(bounds.getCenter(), 16);
  else map.fitBounds(bounds.pad(0.3), { maxZoom: 16, animate: true });
}

function openEditor(p = null, coords = null) {
  state.editingId = p?.id || null;
  const form = $('#plot-form');
  form.reset();
  for (const key of ['parcel_number','latitude','longitude','coordinate_dms','relative_position','locality','area_ha','value_kes','valuation_period','original_value','original_date','notes']) {
    form.elements[key].value = p ? p[key] ?? '' : '';
  }
  if (coords && !p) {
    form.elements.latitude.value = coords.lat.toFixed(6);
    form.elements.longitude.value = coords.lng.toFixed(6);
  }
  $('#dialog-title').textContent = p ? 'Edit property record' : 'Add a new property';
  $('#save-plot-btn').textContent = p ? 'Save changes →' : 'Save property →';
  $('#delete-plot-btn').hidden = !p;
  $('#map-url-input').value = '';
  updateAreaConversion();
  $('#plot-dialog').showModal();
}
function closeEditor() { $('#plot-dialog').close(); }
function updateAreaConversion() {
  const hectares = Number($('#area_ha').value);
  $('#sqm-output').textContent = hectares > 0 ? `${formatNum(hectares * 10000, 2)} m²` : '— m²';
}
function parseMapsCoordinates(text) {
  // Accept URL ?q=-1.28,36.65, @-1.28,36.65 or a plain "lat, lon" pair.
  const input = String(text).trim();
  const q = input.match(/[?&]q=(-?\d+(?:\.\d+)?)(?:%2C|,)(-?\d+(?:\.\d+)?)/i);
  const at = input.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/);
  const plain = input.match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
  const matched = q || at || plain;
  if (!matched) return null;
  const lat = Number(matched[1]), lng = Number(matched[2]);
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { lat, lng } : null;
}
function showError(ex) { toast(ex.message || 'An unexpected error occurred', true); }
async function refresh() {
  state.plots = await api('/api/plots');
  renderStats();
  renderPlots();
}
async function refreshLayers() {
  const layers = await api('/api/layers');
  for (const [id, entry] of layerObjects.entries()) {
    map.removeLayer(entry.layer);
    layerControl.removeLayer(entry.layer);
  }
  layerObjects.clear();
  state.overlays = layers;
  for (const layerItem of layers) {
    try {
      const layer = L.geoJSON(layerItem.geojson, {
        style: { color: '#d89a48', weight: 2.5, opacity: 0.95, fillColor: '#efd1a0', fillOpacity: 0.19 },
        pointToLayer: (feature, latLng) => L.circleMarker(latLng, { radius: 6, color: '#c7843a', fillColor: '#e6b276', fillOpacity: .8 }),
        onEachFeature: (feature, node) => {
          const properties = feature.properties || {};
          const contents = Object.entries(properties).slice(0, 12).map(([k, v]) => `<div><b>${escapeHTML(k)}</b>: ${escapeHTML(typeof v === 'object' ? JSON.stringify(v) : v)}</div>`).join('');
          if (contents) node.bindPopup(`<div class="property-popup"><strong>${escapeHTML(layerItem.name)}</strong><div class="popup-location">${contents}</div></div>`);
        },
      });
      layerObjects.set(layerItem.id, { layer, name: layerItem.name });
      layerControl.addOverlay(layer, `GIS · ${layerItem.name}`);
      layer.addTo(map);
    } catch (err) { console.warn(`Could not draw overlay ${layerItem.name}`, err); }
  }
}

$('#property-list').addEventListener('click', event => {
  const card = event.target.closest('[data-select]');
  if (card) choose(Number(card.dataset.select));
});
map.on('popupopen', event => {
  const edit = event.popup.getElement()?.querySelector('[data-edit]');
  if (edit) edit.addEventListener('click', () => {
    const record = state.plots.find(p => p.id === Number(edit.dataset.edit));
    if (record) { map.closePopup(); openEditor(record); }
  });
});
// Clicking an empty spot starts a new property at those exact coordinates.
map.on('click', e => openEditor(null, e.latlng));
$('#add-plot-btn').addEventListener('click', () => openEditor());
$('#fit-all-btn').addEventListener('click', showAll);
$('#search-input').addEventListener('input', renderPlots);
$('#year-filter').addEventListener('change', renderPlots);
$('#sort-select').addEventListener('change', renderPlots);
$('#close-dialog-btn').addEventListener('click', closeEditor);
$('#cancel-dialog-btn').addEventListener('click', closeEditor);
$('#area_ha').addEventListener('input', updateAreaConversion);
$('#map-url-input').addEventListener('input', e => {
  const coords = parseMapsCoordinates(e.target.value);
  if (coords) { $('#latitude').value = coords.lat; $('#longitude').value = coords.lng; }
});
$('#plot-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  for (const field of ['latitude','longitude','area_ha','value_kes']) data[field] = Number(data[field]);
  try {
    const record = await api(state.editingId ? `/api/plots/${state.editingId}` : '/api/plots', {
      method: state.editingId ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    closeEditor();
    await refresh();
    choose(record.id);
    toast(state.editingId ? 'Changes saved to the database' : 'Property added to the database');
  } catch (ex) { showError(ex); }
});
$('#delete-plot-btn').addEventListener('click', async () => {
  const p = state.plots.find(p => p.id === state.editingId);
  if (!p || !confirm(`Permanently delete ${p.parcel_number} from the database?`)) return;
  try {
    await api(`/api/plots/${p.id}`, { method: 'DELETE' });
    closeEditor();
    state.selectedId = null;
    await refresh();
    showAll();
    toast('Property deleted');
  } catch (ex) { showError(ex); }
});
$('#export-csv-btn').addEventListener('click', () => window.location.assign('/api/export.csv'));
$('#export-geojson-btn').addEventListener('click', () => window.location.assign('/api/export.geojson'));
$('#import-csv-btn').addEventListener('click', () => $('#csv-file-input').click());
$('#csv-file-input').addEventListener('change', async e => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const result = await api('/api/import.csv', { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: await file.text() });
    await refresh();
    showAll();
    toast(`${result.imported} imported · ${result.duplicates_skipped} existing plot number(s) skipped`);
  } catch (ex) { showError(ex); }
  finally { e.target.value = ''; }
});
$('#add-overlay-btn').addEventListener('click', () => $('#geojson-file-input').click());
$('#geojson-file-input').addEventListener('change', async e => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    const geojson = JSON.parse(await file.text());
    const name = prompt('Name this GIS layer:', file.name.replace(/\.geojson$|\.json$/i, ''));
    if (!name) return;
    await api('/api/layers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, geojson }) });
    await refreshLayers();
    toast(`Map layer “${name}” saved. Use the top-right layers control to toggle it.`);
  } catch (ex) { showError(ex); }
  finally { e.target.value = ''; }
});

(async () => {
  try { await Promise.all([refresh(), refreshLayers()]); showAll(); }
  catch (ex) { showError(ex); $('#property-list').innerHTML = '<div class="empty-state">Could not connect to the local database. Make sure <b>python server.py</b> is running.</div>'; }
})();
