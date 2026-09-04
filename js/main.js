/* ==========================================================================
   main.js — gallery rendering, category filtering, entrance animation

   LAYOUT STRATEGY: fixed photos-per-row, justified widths.

   JavaScript chunks the photo list into groups (3 on desktop) and wraps each
   group in a row element. Inside a row, flexbox gives each photo a share of
   the width proportional to its aspect ratio — so a wide panorama takes more
   space than a portrait, and every photo in that row ends up the SAME HEIGHT.
   Row heights then vary from row to row depending on the mix of shapes.

   Why JavaScript is needed: CSS can't do "exactly 3 per row, equal
   heights, filling the width," because that needs a per-row scale
   calculation. CSS wrapping is greedy — it fits whatever it can. Chunking
   the array first is what gives us control over the count.

   Reading order: init() at the bottom starts everything.
   ========================================================================== */

// Pull in the viewer. `import` works because index.html loads this file with
// <script type="module">. The browser fetches lightbox.js automatically — no
// bundler, no build step.
import { initLightbox, openLightbox } from './lightbox.js';

// Note: 'use strict' is unnecessary in a module — modules are always strict.
// Left as a comment so you know why it disappeared.

// Opts into stricter error checking. Without it, a typo'd variable name
// silently creates a global instead of throwing — turning a one-second fix
// into a twenty-minute hunt.


/* --------------------------------------------------------------------------
   CONFIGURATION
   -------------------------------------------------------------------------- */

// How many photos per row at each screen size. Checked largest-first, so the
// first match wins. Change these numbers and the whole gallery re-packs.
const ROW_SIZES = [
  { minWidth: 0, perRow: 3 },
];
// Three per row at every screen size. Because the count never changes, the
// resize handler never triggers a rebuild — CSS rescales widths on its own,
// since flex-grow is proportional rather than fixed.

const STAGGER_MS = 45;    // delay between consecutive photos appearing
const STAGGER_CAP = 11;   // stop increasing after this many, so nothing waits forever


/* --------------------------------------------------------------------------
   STATE
   One object holding everything that can change. Keeping mutable state in a
   single named place makes it obvious what the app knows, and where to look
   when it misbehaves.
   -------------------------------------------------------------------------- */
const state = {
  photos: [],        // every photo from photos.json
  category: 'all',   // active filter
  perRow: 3,         // current packing, recalculated on resize
};

const els = {
  gallery: document.getElementById('gallery'),
  status: document.getElementById('status'),
  filters: document.querySelectorAll('.filter-btn'),
};


/* --------------------------------------------------------------------------
   HOW MANY PER ROW RIGHT NOW
   -------------------------------------------------------------------------- */
function currentPerRow() {
  const width = window.innerWidth;
  // .find returns the first entry whose minWidth we've met. The 0 entry at
  // the end is the catch-all, so this can never return undefined.
  return ROW_SIZES.find((size) => width >= size.minWidth).perRow;
}


/* --------------------------------------------------------------------------
   BUILDING ONE CARD
   -------------------------------------------------------------------------- */
function createCard(photo, index) {
  // A <button>, not a <div>. It's keyboard-focusable, fires on both Enter
  // and Space, and announces itself to screen readers — all for free.
  // Rebuilding that on a div takes real work and is usually done badly.
  const card = document.createElement('button');
  card.className = 'photo';
  card.type = 'button';

  // The variable that drives width distribution within the row. Only the
  // data knows each photo's true shape, which is why this is set here rather
  // than in the stylesheet.
  card.style.setProperty('--aspect', photo.aspect || 1.5);

  card.dataset.id = photo.id;
  card.setAttribute('aria-label', `View ${photo.title || 'photograph'} larger`);

  const img = document.createElement('img');
  img.className = 'photo__img';
  img.src = photo.thumb;
  img.alt = photo.alt || '';

  // Intrinsic dimensions let the browser reserve correct space before the
  // file arrives, so the page doesn't jump as images load.
  img.width = photo.width || 1500;
  img.height = photo.height || 1000;

  // Native lazy loading, no library. The browser downloads an image only
  // when it's near the viewport — what keeps a 105-photo page fast.
  img.loading = 'lazy';
  img.decoding = 'async';

  const overlay = document.createElement('div');
  overlay.className = 'photo__overlay';

  if (photo.title) {
    const title = document.createElement('span');
    title.className = 'photo__title';
    title.textContent = photo.title;
    // textContent, never innerHTML. textContent treats input as plain text;
    // innerHTML parses it as markup. Your captions are your own, but making
    // textContent the default habit is what prevents an injection bug the
    // first time content comes from somewhere you don't control.
    overlay.appendChild(title);
  }

  if (photo.date_display) {
    const meta = document.createElement('span');
    meta.className = 'photo__meta';
    meta.textContent = photo.date_display;
    overlay.appendChild(meta);
  }

  card.append(img, overlay);

  // Open the viewer at this photo's position. We pass photosInView() rather
  // than the whole collection, so prev/next walk only the current category —
  // paging out of "Food" into "Nature" would be surprising.
  card.addEventListener('click', () => {
    openLightbox(photosInView(), index);
  });

  return card;
}


/* --------------------------------------------------------------------------
   BUILDING ONE ROW
   -------------------------------------------------------------------------- */
function createRow(chunk, perRow, startIndex) {
  const row = document.createElement('div');
  row.className = 'gallery__row';

  // startIndex + offset gives each photo its position in the FULL filtered
  // list, not just within this row — that's what the lightbox needs to know
  // where to begin and how to page.
  chunk.forEach((photo, offset) => {
    row.appendChild(createCard(photo, startIndex + offset));
  });

  // THE PARTIAL LAST ROW PROBLEM
  // Flexbox distributes all available width among the items present. So a
  // final row holding a single photo would stretch it to the full page
  // width — wildly out of scale with everything above it.
  //
  // The fix: an invisible filler claiming the width the missing photos would
  // have taken. Its flex-grow is the row's average aspect ratio times the
  // number of empty slots, so the real photos stay at roughly the same scale
  // as a full row.
  if (chunk.length < perRow) {
    const averageAspect =
      chunk.reduce((sum, p) => sum + (p.aspect || 1.5), 0) / chunk.length;

    const filler = document.createElement('div');
    filler.className = 'gallery__filler';
    filler.style.setProperty(
      '--grow',
      (averageAspect * (perRow - chunk.length)).toFixed(3)
    );
    // aria-hidden because it's pure layout scaffolding — a screen reader
    // announcing an empty box would only be noise.
    filler.setAttribute('aria-hidden', 'true');
    row.appendChild(filler);
  }

  return row;
}


/* --------------------------------------------------------------------------
   LAYOUT — the main rendering pass
   -------------------------------------------------------------------------- */
function photosInView() {
  if (state.category === 'all') return state.photos;
  return state.photos.filter((p) => p.category === state.category);
}

function layout() {
  const list = photosInView();

  // Clear whatever was there. replaceChildren() with no arguments is the
  // modern way to empty an element — clearer than innerHTML = '' and it
  // doesn't invoke the HTML parser.
  els.gallery.replaceChildren();

  if (list.length === 0) {
    setStatus('No photographs in this category yet.');
    return;
  }
  setStatus(null);

  const perRow = state.perRow;

  // A DocumentFragment is an off-screen container. Building every row inside
  // it and appending ONCE means the browser recalculates layout a single
  // time instead of once per row.
  const fragment = document.createDocumentFragment();

  // Step forward `perRow` at a time, slicing off one row's worth each pass.
  for (let i = 0; i < list.length; i += perRow) {
    fragment.appendChild(createRow(list.slice(i, i + perRow), perRow, i));
  }

  els.gallery.appendChild(fragment);

  // Hand every new card to the reveal observer so it animates in on scroll.
  els.gallery.querySelectorAll('.photo').forEach((card) => {
    revealObserver.observe(card);
  });
}


/* --------------------------------------------------------------------------
   FILTERING
   -------------------------------------------------------------------------- */
function applyFilter(category) {
  state.category = category;

  els.filters.forEach((btn) => {
    btn.classList.toggle('is-active', btn.dataset.category === category);
  });

  // Full re-layout, because row composition changes completely when the set
  // of photos changes — you can't just hide cards and keep the same rows.
  //
  // Rebuilding the <img> elements is cheap: the browser holds the image files
  // in its HTTP cache, so returning to a category you've already viewed
  // re-downloads nothing. It also replays the entrance animation on every
  // filter change, which is the effect you asked for.
  layout();
}

function wireFilters() {
  els.filters.forEach((btn) => {
    btn.addEventListener('click', () => applyFilter(btn.dataset.category));
  });
}


/* --------------------------------------------------------------------------
   RESIZE
   -------------------------------------------------------------------------- */
function wireResize() {
  let timer;

  window.addEventListener('resize', () => {
    // DEBOUNCE: resize fires continuously while you drag a window edge —
    // potentially hundreds of times a second. Re-laying out 105 photos on
    // each would lock the browser. So we reset a timer on every event and
    // act only once things have been quiet for 150ms.
    clearTimeout(timer);
    timer = setTimeout(() => {
      const perRow = currentPerRow();

      // Only rebuild if the COUNT actually changed. Between breakpoints, CSS
      // handles resizing by itself — flex-grow is proportional, so widths
      // and heights rescale with no JavaScript involved.
      if (perRow !== state.perRow) {
        state.perRow = perRow;
        layout();
      }
    }, 150);
  });
}


/* --------------------------------------------------------------------------
   STAGGERED SCROLL REVEAL
   -------------------------------------------------------------------------- */

// IntersectionObserver reports when an element enters the viewport. The old
// approach — listening to scroll and measuring positions every frame — was a
// well-known performance problem. The browser does this natively now, and
// far more cheaply.
const revealObserver = new IntersectionObserver(handleReveal, {
  // Trigger 80px BEFORE the photo reaches the viewport edge, so it's already
  // fading in by the time you can see it. Revealing exactly at the boundary
  // looks late.
  rootMargin: '0px 0px -80px 0px',
  threshold: 0.01,
});

function handleReveal(entries) {
  // Entries arrive in a batch. Staggering by position WITHIN the batch is
  // what creates the cascade — one shared delay would make them appear as a
  // single block.
  let staggerIndex = 0;

  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;

    const card = entry.target;
    card.style.transitionDelay =
      `${Math.min(staggerIndex, STAGGER_CAP) * STAGGER_MS}ms`;
    card.classList.add('is-visible');
    staggerIndex += 1;

    // Once revealed, stop watching. An observer still firing on every scroll
    // past is wasted work.
    revealObserver.unobserve(card);
  });
}


/* --------------------------------------------------------------------------
   STATUS MESSAGES
   -------------------------------------------------------------------------- */
function setStatus(message) {
  if (message) {
    els.status.textContent = message;
    els.status.hidden = false;
  } else {
    els.status.hidden = true;
  }
}


/* --------------------------------------------------------------------------
   STARTUP
   -------------------------------------------------------------------------- */
async function init() {
  state.perRow = currentPerRow();

  try {
    // fetch() returns a Promise; await pauses until it resolves. Reads
    // top-to-bottom like ordinary code while staying non-blocking.
    const response = await fetch('data/photos.json');

    // fetch does NOT throw on 404 or 500 — it only rejects on network
    // failure. A missing file resolves successfully with ok === false, so
    // this check is required, not optional. Catches many people out.
    if (!response.ok) {
      throw new Error(`Could not load photos.json (HTTP ${response.status})`);
    }

    const data = await response.json();
    state.photos = data.photos || [];

    if (state.photos.length === 0) {
      setStatus('No photographs found. Run build_data.py to generate data/photos.json.');
      return;
    }

    wireFilters();
    wireResize();
    initLightbox();   // attaches the viewer's listeners, once
    layout();

    console.log(`Loaded ${state.photos.length} photographs, ${state.perRow} per row.`);
  } catch (error) {
    console.error(error);
    setStatus('Could not load photographs. See the browser console for details.');
    // fetch() is blocked entirely under the file:// protocol, so opening
    // index.html by double-clicking will always fail here. Serve it instead:
    //   python3 -m http.server 8000
    console.warn('Tip: fetch() does not work over file://. Use a local server.');
  }
}

init();