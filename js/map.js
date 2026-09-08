/* ==========================================================================
   map.js — the interactive map of where photographs were taken

   Leaflet is loaded from a CDN as a plain <script> in map.html, so it lives
   on window as the global `L`. That's why there's no import for it: plain
   scripts run before deferred modules, so L is guaranteed to exist by the
   time this file executes.

   The lightbox IS imported, because it's our own ES module — and reusing it
   here is the payoff for having put it in its own file. Clicking a photo on
   the map opens the same viewer as clicking one in the gallery, with zero
   duplicated code.
   ========================================================================== */

import { initLightbox, openLightbox } from './lightbox.js';

// CARTO's "Positron" tiles — a pale, low-contrast basemap. Chosen because a
// map is a BACKDROP here: your photographs should carry the colour, and the
// standard OpenStreetMap style is busy enough to compete with them.
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

// Attribution is a LICENCE CONDITION, not a courtesy. OpenStreetMap data is
// ODbL-licensed and CARTO's tiles are free on condition of credit. Removing
// this line would be a licence violation.
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const FIT_PADDING = [60, 60];   // pixels of breathing room around the pins
const MAX_FIT_ZOOM = 12;        // don't zoom to street level for a lone pin

const els = {
  map: document.getElementById('map'),
  status: document.getElementById('map-status'),
};


/* --------------------------------------------------------------------------
   GROUPING
   -------------------------------------------------------------------------- */
function groupByLocation(photos) {
  // A Map, not a plain object, because we're keying on arbitrary strings.
  // Plain objects inherit properties like "constructor" and "toString", so a
  // location genuinely called one of those would collide with the prototype.
  // Map has no such surface, and it preserves insertion order.
  const groups = new Map();

  photos.forEach((photo) => {
    // Skip anything without coordinates. 13 of your photos have no location
    // at all, and that's fine — they live in the gallery, not on the map.
    // == null is deliberate here: it catches both null and undefined, where
    // === null would miss undefined. One of the few places loose equality
    // is the clearer choice.
    if (photo.lat == null || photo.lng == null) return;

    const key = photo.location;

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        lat: photo.lat,
        lng: photo.lng,
        // Prefer the display string; fall back to the geocoder one.
        label: photo.place || photo.location,
        photos: [],
      });
    }

    groups.get(key).photos.push(photo);
  });

  return [...groups.values()];
}


/* --------------------------------------------------------------------------
   MARKERS
   -------------------------------------------------------------------------- */
function createIcon() {
  // Fixed small size, no number. With 61 pins — a dozen of them clustered in
  // southern Iceland — anything larger overlaps into unreadable clumps. The
  // count lives on the cluster bubble and in the popup, where there's room.
  const size = 12;

  return L.divIcon({
    className: 'pin-wrap',
    html: '<span class="pin"></span>',
    iconSize: [size, size],
    // Anchor at the centre so the dot sits ON the coordinate rather than
    // hanging below it, which is Leaflet's default for teardrop pins.
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2 - 2],
  });
}


function createPopup(group) {
  // Built as DOM nodes rather than an HTML string. Leaflet's bindPopup
  // accepts an element, and using textContent for the label means a caption
  // containing < or & can never be parsed as markup.
  const wrap = document.createElement('div');
  wrap.className = 'pin-popup';

  const button = document.createElement('button');
  button.className = 'pin-popup__thumb';
  button.type = 'button';
  const count = group.photos.length;
  button.setAttribute(
    'aria-label',
    `View ${count} photograph${count === 1 ? '' : 's'} from ${group.label}`
  );

  const img = document.createElement('img');
  img.src = group.photos[0].thumb;
  img.alt = group.photos[0].alt || '';
  img.loading = 'lazy';
  button.appendChild(img);

  // Hand off to the shared viewer, scoped to THIS location's photos — so
  // prev/next walks the shots taken here rather than the whole catalogue.
  button.addEventListener('click', () => openLightbox(group.photos, 0));

  const label = document.createElement('p');
  label.className = 'pin-popup__label';
  label.textContent = group.label;

  const meta = document.createElement('p');
  meta.className = 'pin-popup__meta';
  meta.textContent = `${count} photograph${count === 1 ? '' : 's'}`;

  wrap.append(button, label, meta);
  return wrap;
}


/* --------------------------------------------------------------------------
   SETUP
   -------------------------------------------------------------------------- */
function buildMap(groups) {
  const map = L.map(els.map, {
    // Leaflet measures its container on initialisation and renders a blank
    // grey box if that container has no height — the single most common
    // Leaflet problem, and the same definite-height lesson as the lightbox
    // portraits. The CSS gives #map an explicit height for this reason.
    scrollWheelZoom: false,
    // Wheel-zoom off by default: with a full-width map, scrolling the page
    // would hijack into zooming the map and trap the reader. Ctrl+scroll
    // still zooms, and Leaflet shows a hint saying so.
    worldCopyJump: true,
    // Your pins span Iceland to Botswana to Shanghai. This makes markers
    // reappear sensibly when panning across the antimeridian.
  });

  L.tileLayer(TILE_URL, {
    attribution: TILE_ATTRIBUTION,
    maxZoom: 19,
    // Retina tiles on high-DPI screens — {r} in the URL becomes "@2x".
    detectRetina: false,
    // OSM doesn't serve @2x tiles, and detectRetina: true would make Leaflet
    // request four higher-zoom tiles per slot to compensate — quadrupling
    // requests against a volunteer-funded service for no visual gain.
  }).addTo(map);

  const markers = groups.map((group) => {
    const marker = L.marker([group.lat, group.lng], {
      icon: createIcon(),
      title: group.label,     // native browser tooltip on hover
      riseOnHover: true,
    });

    marker.bindPopup(createPopup(group), {
      closeButton: true,
      minWidth: 210,
      maxWidth: 210,
    });

    return marker;
  });

// A feature group so we can ask for the bounding box of everything at once.
  const layer = L.featureGroup(markers).addTo(map);

  map.fitBounds(layer.getBounds(), {
    padding: FIT_PADDING,
    maxZoom: MAX_FIT_ZOOM,
  });

  return map;
}


/* --------------------------------------------------------------------------
   STARTUP
   -------------------------------------------------------------------------- */
async function init() {
  try {
    const response = await fetch('data/photos.json');
    if (!response.ok) {
      throw new Error(`Could not load photos.json (HTTP ${response.status})`);
    }

    const data = await response.json();
    const groups = groupByLocation(data.photos || []);

    if (groups.length === 0) {
      els.status.textContent =
        'No locations yet. Run geocode.py, then build_data.py.';
      return;
    }

    initLightbox();
    buildMap(groups);

    els.status.hidden = true;

    const total = groups.reduce((sum, g) => sum + g.photos.length, 0);
    console.log(`Map: ${total} photographs across ${groups.length} pins.`);
  } catch (error) {
    console.error(error);
    els.status.textContent = 'Could not load the map. See the console for details.';
    console.warn('Tip: fetch() and ES modules both need a server, not file://.');
  }
}

init();