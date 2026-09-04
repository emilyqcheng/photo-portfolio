/* ==========================================================================
   lightbox.js — the full-screen photo viewer

   This is a SEPARATE FILE from main.js on purpose. main.js owns the gallery;
   this file owns the viewer. They talk through one function, openLightbox().
   Splitting code along the lines of "what is this responsible for?" is how
   you keep a project readable as it grows — a single 800-line main.js is
   where beginner projects go to die.

   The markup lives in index.html rather than being built here, so you can
   restyle the viewer or inspect it in DevTools without reading any
   JavaScript. Structure in HTML, behaviour in JS.
   ========================================================================== */

'use strict';

const SLIDESHOW_MS = 4500;   // how long each photo holds during a slideshow


/* --------------------------------------------------------------------------
   STATE
   -------------------------------------------------------------------------- */
const state = {
  list: [],              // the photos currently viewable (respects the filter)
  index: 0,              // which one we're looking at
  isOpen: false,
  slideshowTimer: null,
  showDetails: false,
  lastFocused: null,     // the gallery card that opened us, so we can restore focus
};


/* --------------------------------------------------------------------------
   ELEMENT REFERENCES
   Looked up once. If any of these are missing, the selectors here and the
   ids in index.html have drifted apart.
   -------------------------------------------------------------------------- */
const els = {};

function cacheElements() {
  els.root = document.getElementById('lightbox');
  els.figure = document.getElementById('lb-figure');
  els.img = document.getElementById('lb-img');
  els.title = document.getElementById('lb-title');
  els.location = document.getElementById('lb-location');
  els.date = document.getElementById('lb-date');
  els.notes = document.getElementById('lb-notes');
  els.counter = document.getElementById('lb-counter');
  els.details = document.getElementById('lb-details');
  els.btnClose = document.getElementById('lb-close');
  els.btnPrev = document.getElementById('lb-prev');
  els.btnNext = document.getElementById('lb-next');
  els.btnFullscreen = document.getElementById('lb-fullscreen');
  els.btnSlideshow = document.getElementById('lb-slideshow');
  els.btnDetails = document.getElementById('lb-toggle-details');
}


/* --------------------------------------------------------------------------
   RENDERING THE CURRENT PHOTO
   -------------------------------------------------------------------------- */
function setText(el, value) {
  // Helper: fill an element, or hide it entirely when there's nothing to say.
  // An empty <p> still occupies space and leaves an awkward gap, so hiding
  // is better than blanking.
  if (value) {
    el.textContent = value;
    el.hidden = false;
  } else {
    el.textContent = '';
    el.hidden = true;
  }
}

function renderDetails(photo) {
  // Build the camera-settings block from whatever EXIF survived. Every field
  // is optional — a photo whose metadata was stripped should still display,
  // just without this panel.
  const rows = [
    ['Camera', photo.camera],
    ['Lens', photo.lens],
    ['Focal length', photo.focal],
    ['Aperture', photo.aperture],
    ['Shutter', photo.shutter],
    ['ISO', photo.iso ? String(photo.iso) : null],
    ['Date taken', photo.datetime_full],
    ['Copyright', photo.copyright],
  ].filter(([, value]) => value);
  // .filter with a destructured, ignored first element — [, value] — is a
  // tidy way to say "I only care about the second item."

  els.details.replaceChildren();

  if (rows.length === 0) {
    const p = document.createElement('p');
    p.className = 'lb-details__empty';
    p.textContent = 'No camera data for this photograph.';
    els.details.appendChild(p);
    return;
  }

  const dl = document.createElement('dl');
  dl.className = 'lb-details__list';

  rows.forEach(([label, value]) => {
    // <dl>/<dt>/<dd> is a description list — the correct semantic element for
    // label-value pairs. A screen reader announces "Aperture, f/5.6" as a
    // related pair, which a pile of <div>s wouldn't convey.
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value;
    dl.append(dt, dd);
  });

  els.details.appendChild(dl);
}

function render() {
  const photo = state.list[state.index];
  if (!photo) return;

  // Mark as loading so CSS can fade the old image out. Removed by the load
  // handler below, which gives a smooth swap instead of a hard cut.
  els.figure.classList.add('is-loading');

  els.img.src = photo.full;
  els.img.alt = photo.alt || '';

  setText(els.title, photo.title);
  // Skip the location line when it just repeats the title. For most photos
  // the caption IS the place name, so printing both is redundant — it only
  // differs where the title is something like "A Thousand Ripples".
  setText(els.location, photo.location === photo.title ? '' : photo.location);
  setText(els.date, photo.date_display);
  setText(els.notes, photo.notes);

  els.counter.textContent = `${state.index + 1} / ${state.list.length}`;

  renderDetails(photo);

  // PRELOAD THE NEIGHBOURS. Creating an Image object and setting .src starts
  // the download without displaying anything, so by the time you press the
  // arrow the next photo is already in cache and appears instantly. This is
  // the difference between a viewer that feels snappy and one that stutters
  // on every click — and it's four lines.
  preload(state.index + 1);
  preload(state.index - 1);
}

function preload(index) {
  const photo = state.list[index];
  if (!photo) return;
  const img = new Image();
  img.src = photo.full;
}


/* --------------------------------------------------------------------------
   NAVIGATION
   -------------------------------------------------------------------------- */
function goTo(index, { manual = true } = {}) {
  // Modulo wraps around: from the last photo, next() returns to the first.
  // The `+ length` before the % handles going backwards from index 0, because
  // JavaScript's % keeps the sign of the left operand — (-1 % 42) is -1,
  // not 41. A classic off-by-one trap.
  const count = state.list.length;
  state.index = ((index % count) + count) % count;

  // Any manual navigation stops the slideshow. Nothing is more irritating
  // than a slideshow advancing while you're reading a caption.
  if (manual) stopSlideshow();

  render();
}

function next(options) { goTo(state.index + 1, options); }
function prev(options) { goTo(state.index - 1, options); }


/* --------------------------------------------------------------------------
   SLIDESHOW
   -------------------------------------------------------------------------- */
function startSlideshow() {
  stopSlideshow();
  // manual: false so advancing doesn't immediately stop the slideshow it's
  // running from.
  state.slideshowTimer = setInterval(() => next({ manual: false }), SLIDESHOW_MS);
  els.root.classList.add('is-playing');
  els.btnSlideshow.setAttribute('aria-pressed', 'true');
  els.btnSlideshow.setAttribute('aria-label', 'Pause slideshow');
}

function stopSlideshow() {
  if (state.slideshowTimer) {
    clearInterval(state.slideshowTimer);
    state.slideshowTimer = null;
  }
  els.root.classList.remove('is-playing');
  els.btnSlideshow.setAttribute('aria-pressed', 'false');
  els.btnSlideshow.setAttribute('aria-label', 'Play slideshow');
}

function toggleSlideshow() {
  if (state.slideshowTimer) stopSlideshow();
  else startSlideshow();
}


/* --------------------------------------------------------------------------
   FULLSCREEN
   -------------------------------------------------------------------------- */
function toggleFullscreen() {
  // The Fullscreen API is browser-native — no library. Safari still needs
  // the webkit-prefixed names, hence the fallbacks.
  if (!document.fullscreenElement && !document.webkitFullscreenElement) {
    const request =
      els.root.requestFullscreen || els.root.webkitRequestFullscreen;
    // .call(els.root) because we pulled the function off the object and it
    // needs its `this` put back. Assigning a method to a variable loses the
    // binding — a genuinely confusing corner of JavaScript.
    if (request) request.call(els.root);
  } else {
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (exit) exit.call(document);
  }
}


/* --------------------------------------------------------------------------
   DETAILS PANEL
   -------------------------------------------------------------------------- */
function toggleDetails() {
  state.showDetails = !state.showDetails;
  els.root.classList.toggle('show-details', state.showDetails);
  els.btnDetails.setAttribute('aria-pressed', String(state.showDetails));
  els.details.hidden = !state.showDetails;
}


/* --------------------------------------------------------------------------
   SCROLL LOCK
   -------------------------------------------------------------------------- */
function lockScroll() {
  // Measure the scrollbar BEFORE hiding it. innerWidth includes the
  // scrollbar; clientWidth doesn't, so the difference is its width.
  const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
  document.body.style.overflow = 'hidden';
  // Without this padding, removing the scrollbar widens the page by ~15px and
  // everything behind the lightbox visibly jumps sideways as it opens.
  document.body.style.paddingRight = `${scrollbarWidth}px`;
}

function unlockScroll() {
  document.body.style.overflow = '';
  document.body.style.paddingRight = '';
}


/* --------------------------------------------------------------------------
   KEYBOARD
   -------------------------------------------------------------------------- */
function onKeyDown(event) {
  if (!state.isOpen) return;

  switch (event.key) {
    case 'Escape':
      close();
      break;
    case 'ArrowRight':
      next();
      break;
    case 'ArrowLeft':
      prev();
      break;
    case ' ':
      // Space would otherwise scroll the page behind the overlay.
      event.preventDefault();
      toggleSlideshow();
      break;
    case 'Tab':
      trapFocus(event);
      break;
    default:
      break;
  }
}

function trapFocus(event) {
  // FOCUS TRAPPING. A modal that lets Tab wander onto the page behind it is
  // broken for keyboard and screen-reader users — focus disappears somewhere
  // invisible and they can't get back. So we cycle focus within the dialog:
  // Tab from the last control returns to the first, Shift+Tab from the first
  // goes to the last.
  const focusable = els.root.querySelectorAll(
    'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
  );
  if (focusable.length === 0) return;

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}


/* --------------------------------------------------------------------------
   OPEN / CLOSE
   -------------------------------------------------------------------------- */
export function openLightbox(list, index) {
  if (!list || list.length === 0) return;

  state.list = list;
  state.index = index;
  state.isOpen = true;
  // Remember what had focus so we can hand it back on close. Dumping the
  // user at the top of the page after they close a modal is disorienting.
  state.lastFocused = document.activeElement;

  els.root.hidden = false;
  lockScroll();

  render();

  // Wait one frame before adding the class that triggers the fade-in.
  // An element that goes from hidden to visible in the same frame has no
  // "before" state for the browser to animate from, so the transition is
  // skipped entirely. requestAnimationFrame gives it that frame.
  requestAnimationFrame(() => els.root.classList.add('is-open'));

  els.btnClose.focus();
}

export function close() {
  state.isOpen = false;
  stopSlideshow();
  els.root.classList.remove('is-open');
  unlockScroll();

  if (document.fullscreenElement || document.webkitFullscreenElement) {
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (exit) exit.call(document);
  }

  // Hide only after the fade-out finishes, otherwise it vanishes instantly.
  setTimeout(() => {
    if (!state.isOpen) els.root.hidden = true;
  }, 300);

  if (state.lastFocused) state.lastFocused.focus();
}


/* --------------------------------------------------------------------------
   SETUP — called once from main.js
   -------------------------------------------------------------------------- */
export function initLightbox() {
  cacheElements();

  els.btnClose.addEventListener('click', close);
  els.btnPrev.addEventListener('click', () => prev());
  els.btnNext.addEventListener('click', () => next());
  els.btnFullscreen.addEventListener('click', toggleFullscreen);
  els.btnSlideshow.addEventListener('click', toggleSlideshow);
  els.btnDetails.addEventListener('click', toggleDetails);

  // No backdrop-click-to-close: Escape and the X button cover it, and with
  // the image now filling its whole box (see the object-fit note in the CSS)
  // there is very little genuine backdrop left to click anyway.

  els.img.addEventListener('load', () => {
    els.figure.classList.remove('is-loading');
  });

  els.img.addEventListener('error', () => {
    els.figure.classList.remove('is-loading');
    console.error('Could not load image:', els.img.src);
  });

  // One keydown listener on the document, rather than one per element. The
  // handler exits immediately when the lightbox is closed, so it costs
  // nothing while you're browsing the gallery.
  document.addEventListener('keydown', onKeyDown);

  els.details.hidden = true;
}