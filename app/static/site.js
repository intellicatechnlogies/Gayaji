(() => {
  const heroes = JSON.parse(document.getElementById('hero-data').textContent);
  const languageToggle = document.getElementById('language-toggle');
  const toast = document.getElementById('toast');
  const bookingBackdrop = document.getElementById('booking-backdrop');
  const adminPanel = document.getElementById('admin-panel');
  const adminScrim = document.getElementById('admin-scrim');
  const loginForm = document.getElementById('admin-login-form');
  const accountArea = document.getElementById('admin-account-area');
  const placeForm = document.getElementById('admin-place-form');
  const placeList = document.getElementById('admin-place-list');
  let language = 'en';
  let slide = 0;
  let toastTimer;
  let editingId = null;

  const translations = {
    en: {
      explore: 'Explore', journey: 'The journey', map: 'The region', contact: 'Get in touch',
      adminError: 'Admin access could not be verified. Please sign in again.',
      saveError: 'Please check your details and try again.',
      contactSuccess: 'Thank you! We’ll be in touch soon.',
      bookingSuccess: 'Your travel request is in. We’ll contact you shortly.',
      loginError: 'Invalid username or password.',
      placeSaved: 'Destination saved.', placeRemoved: 'Destination removed.',
      deleteConfirm: 'Delete this destination?', imageCredit: 'Photo: Wikimedia Commons',
      planVisit: 'Plan a visit　→', edit: 'Edit', remove: 'Delete',
      save: 'Save destination', add: '＋　Add a destination', signIn: 'Sign in',
    },
    hi: {
      explore: 'घूमें', journey: 'यात्रा', map: 'यह क्षेत्र', contact: 'संपर्क करें',
      adminError: 'एडमिन लॉगिन की जाँच नहीं हो सकी। फिर साइन इन करें।',
      saveError: 'कृपया जानकारी जाँचकर फिर कोशिश करें।',
      contactSuccess: 'धन्यवाद! हम जल्द आपसे संपर्क करेंगे।',
      bookingSuccess: 'आपका अनुरोध मिल गया। हम जल्द संपर्क करेंगे।',
      loginError: 'यूज़रनेम या पासवर्ड गलत है।',
      placeSaved: 'गंतव्य सहेजा गया।', placeRemoved: 'गंतव्य हटा दिया गया।',
      deleteConfirm: 'क्या आप यह गंतव्य हटाना चाहते हैं?', imageCredit: 'फ़ोटो: विकिमीडिया कॉमन्स',
      planVisit: 'यात्रा की योजना बनाएं　→', edit: 'बदलें', remove: 'हटाएं',
      save: 'गंतव्य सहेजें', add: '＋　नया गंतव्य जोड़ें', signIn: 'साइन इन करें',
    },
  };
  const destinationImages = {
    'Mahabodhi Temple': heroes[0].image,
    'The Great Buddha Statue': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/b/bf/Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg/1280px-Great_Buddha_Statue%2C_Bodh_Gaya_at_Sunset.jpg',
    'Vishnupad Temple': heroes[3].image,
    'Nalanda Mahavihara': heroes[1].image,
    'Nalanda Archaeological Museum': heroes[1].image,
    'Rajgir Ropeway & Vishwa Shanti Stupa': heroes[2].image,
    'Griddhakuta Hill': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/d/db/Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg/1280px-Cyclopian_wall%2C_Rajgir._%285457385482%29_%28cropped%29.jpg',
    'Barabar Caves': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/2/25/Lomas_Rishi_entrance.jpg/1280px-Lomas_Rishi_entrance.jpg',
  };

  function text(key) {
    return translations[language][key] || translations.en[key] || key;
  }

  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 4000);
  }

  function setLanguage(nextLanguage) {
    language = nextLanguage;
    document.documentElement.lang = language;
    document.title = language === 'hi' ? 'बिहार बियॉन्ड — बिहार की खोज' : 'Bihar Beyond — Find your way to wonder';
    document.querySelectorAll('[data-en][data-hi]').forEach((element) => {
      if (element.tagName === 'OPTION' && element.selected) {
        element.textContent = element.dataset[language];
      } else if (element.tagName !== 'OPTION') {
        element.textContent = element.dataset[language];
      } else {
        element.dataset[`${language}Text`] = element.dataset[language];
      }
    });
    document.querySelectorAll('option[data-en][data-hi]').forEach((option) => {
      option.textContent = option.dataset[language];
    });
    languageToggle.textContent = language === 'en' ? 'हिन्दी' : 'English';
    renderHero();
    if (!loginForm.hidden) document.querySelector('#admin-login-form button[type="submit"]').textContent = text('signIn');
    document.getElementById('admin-add-place').textContent = text('add');
    document.querySelector('#admin-place-form button[type="submit"]').textContent = text('save');
    placeList.querySelectorAll('[data-admin-action="edit"]').forEach((button) => { button.textContent = text('edit'); });
    placeList.querySelectorAll('[data-admin-action="delete"]').forEach((button) => { button.textContent = text('remove'); });
    document.querySelectorAll('[data-open-booking]').forEach((button) => {
      if (button.dataset.en && button.dataset.hi) button.textContent = button.dataset[language];
    });
  }

  function renderHero() {
    const hero = heroes[slide];
    document.getElementById('hero-bg').style.backgroundImage = `url("${hero.image}")`;
    document.getElementById('hero-eyebrow').textContent = language === 'hi' ? 'बिहार के हृदय में, अपनी ही रफ़्तार से' : 'THE HEART OF BIHAR, AT YOUR OWN PACE';
    document.getElementById('hero-title').replaceChildren(
      document.createTextNode(`${language === 'hi' ? hero.titleHi : hero.title} `),
      Object.assign(document.createElement('em'), { textContent: language === 'hi' ? hero.emphasisHi : hero.emphasis }),
    );
    document.getElementById('hero-copy').textContent = language === 'hi' ? hero.copyHi : hero.copy;
    document.getElementById('hero-region').textContent = `⌖　${hero.region}, Bihar`;
    document.getElementById('hero-credit').href = hero.credit;
    document.getElementById('hero-credit').textContent = text('imageCredit');
    document.getElementById('slide-number').textContent = `0${slide + 1}`;
    document.querySelectorAll('.slide-dot').forEach((dot, index) => dot.classList.toggle('active', index === slide));
  }

  heroes.forEach((hero, index) => {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'slide-dot';
    dot.setAttribute('aria-label', `Show ${hero.region}`);
    dot.addEventListener('click', () => { slide = index; renderHero(); });
    document.getElementById('slide-dots').append(dot);
  });
  renderHero();
  window.setInterval(() => { slide = (slide + 1) % heroes.length; renderHero(); }, 6500);

  languageToggle.addEventListener('click', () => setLanguage(language === 'en' ? 'hi' : 'en'));
  document.querySelectorAll('#region-filters [data-region]').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('#region-filters .filter').forEach((filter) => filter.classList.remove('active'));
      button.classList.add('active');
      document.querySelectorAll('[data-place-card]').forEach((card) => {
        card.hidden = button.dataset.region !== 'All' && card.dataset.region !== button.dataset.region;
      });
    });
  });

  const mobileMenu = document.getElementById('mobile-nav');
  document.getElementById('menu-toggle').addEventListener('click', (event) => {
    mobileMenu.hidden = !mobileMenu.hidden;
    event.currentTarget.textContent = mobileMenu.hidden ? '☰' : '×';
  });
  mobileMenu.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
    mobileMenu.hidden = true;
    document.getElementById('menu-toggle').textContent = '☰';
  }));

  function setAdminOpen(open) {
    adminPanel.hidden = !open;
    adminScrim.hidden = !open;
    document.body.classList.toggle('panel-open', open);
    if (open) checkAdminSession();
  }
  document.querySelectorAll('[data-open-admin]').forEach((button) => button.addEventListener('click', () => {
    mobileMenu.hidden = true;
    setAdminOpen(true);
  }));
  document.querySelectorAll('[data-close-admin]').forEach((button) => button.addEventListener('click', () => setAdminOpen(false)));
  adminScrim.addEventListener('click', () => setAdminOpen(false));

  async function apiRequest(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
    });
    if (!response.ok) {
      let detail = '';
      try {
        const body = await response.json();
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || '');
      } catch (_error) {
        detail = '';
      }
      throw new Error(detail || (response.status === 401 ? text('adminError') : text('saveError')));
    }
    return response.status === 204 ? null : response.json();
  }

  async function checkAdminSession() {
    try {
      const response = await fetch('/api/admin/session');
      if (response.status === 401) {
        loginForm.hidden = false;
        accountArea.hidden = true;
        return;
      }
      if (!response.ok) throw new Error(text('adminError'));
      const account = await response.json();
      showAdminAccount(account.username);
      await refreshPlaces();
    } catch (error) {
      showLoginError(error.message);
      loginForm.hidden = false;
      accountArea.hidden = true;
    }
  }

  function showLoginError(message) {
    const error = document.getElementById('admin-login-error');
    error.textContent = message;
    error.hidden = false;
  }

  function showAdminAccount(username) {
    loginForm.hidden = true;
    accountArea.hidden = false;
    document.getElementById('admin-account-name').textContent = `Username: ${username}`;
  }

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = loginForm.querySelector('button[type="submit"]');
    button.disabled = true;
    document.getElementById('admin-login-error').hidden = true;
    try {
      const credentials = Object.fromEntries(new FormData(loginForm));
      const account = await apiRequest('/api/admin/login', { method: 'POST', body: JSON.stringify(credentials) });
      loginForm.reset();
      showAdminAccount(account.username);
      await refreshPlaces();
    } catch (error) {
      showLoginError(error.message || text('loginError'));
    } finally {
      button.disabled = false;
      button.textContent = text('signIn');
    }
  });

  document.getElementById('admin-logout').addEventListener('click', async () => {
    try {
      await apiRequest('/api/admin/logout', { method: 'POST' });
      loginForm.hidden = false;
      accountArea.hidden = true;
      placeForm.hidden = true;
    } catch (error) {
      showToast(error.message, true);
    }
  });

  function createAdminRow(place) {
    const row = document.createElement('div');
    row.className = 'admin-row';
    const image = document.createElement('img');
    image.src = place.image;
    image.alt = '';
    const info = document.createElement('div');
    info.className = 'admin-row-info';
    const name = document.createElement('strong');
    name.textContent = place.name;
    const region = document.createElement('small');
    region.textContent = place.region;
    info.append(name, region);
    const actions = document.createElement('div');
    actions.className = 'admin-actions';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.dataset.adminAction = 'edit';
    edit.textContent = text('edit');
    edit.addEventListener('click', () => startEdit(place));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.dataset.adminAction = 'delete';
    remove.textContent = text('remove');
    remove.addEventListener('click', () => deletePlace(place.id));
    actions.append(edit, remove);
    row.append(image, info, actions);
    return row;
  }

  async function refreshPlaces() {
    const places = (await apiRequest('/api/places')).map((place) => ({
      ...place,
      image: destinationImages[place.name] || place.image,
    }));
    placeList.replaceChildren(...places.map(createAdminRow));
  }

  document.getElementById('admin-add-place').addEventListener('click', () => {
    editingId = null;
    placeForm.reset();
    placeForm.hidden = false;
    document.getElementById('place-region').value = 'Bodh Gaya';
  });

  function startEdit(place) {
    editingId = place.id;
    for (const field of ['name', 'description', 'image', 'region', 'category']) {
      placeForm.elements[field].value = place[field];
    }
    placeForm.hidden = false;
    placeForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  document.getElementById('admin-cancel-edit').addEventListener('click', () => {
    editingId = null;
    placeForm.reset();
    placeForm.hidden = true;
  });

  placeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(placeForm));
    const path = editingId ? `/api/places/${editingId}` : '/api/places';
    try {
      await apiRequest(path, { method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
      editingId = null;
      placeForm.reset();
      placeForm.hidden = true;
      await refreshPlaces();
      showToast(text('placeSaved'));
      window.location.reload();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  async function deletePlace(id) {
    if (!window.confirm(text('deleteConfirm'))) return;
    try {
      await apiRequest(`/api/places/${id}`, { method: 'DELETE' });
      await refreshPlaces();
      showToast(text('placeRemoved'));
      window.location.reload();
    } catch (error) {
      showToast(error.message, true);
    }
  }

  document.querySelectorAll('[data-open-booking]').forEach((button) => {
    button.addEventListener('click', () => {
      document.getElementById('booking-place').textContent = button.dataset.place
        ? `${button.dataset.place} · ${button.dataset.region}`
        : '';
      document.getElementById('booking-destination').value = button.dataset.region || 'Bodh Gaya';
      bookingBackdrop.hidden = false;
    });
  });
  document.querySelectorAll('[data-close-booking]').forEach((button) => button.addEventListener('click', () => {
    bookingBackdrop.hidden = true;
  }));
  bookingBackdrop.addEventListener('click', (event) => {
    if (event.target === bookingBackdrop) bookingBackdrop.hidden = true;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      bookingBackdrop.hidden = true;
      setAdminOpen(false);
    }
  });
  document.getElementById('booking-date').min = new Date().toISOString().slice(0, 10);

  async function submitPublicForm(form, endpoint, successMessage) {
    const payload = Object.fromEntries(new FormData(form));
    if (payload.guests) payload.guests = Number(payload.guests);
    if (payload.service) {
      const serviceLabels = {
        'complete-trip': language === 'hi' ? 'मेरी पूरी यात्रा की योजना' : 'Plan my complete trip',
        accommodation: language === 'hi' ? 'होटल / ठहरने की व्यवस्था' : 'Accommodation / stay',
        'private-van': language === 'hi' ? 'निजी वैन या कैब' : 'Private van or cab',
        'guided-visits': language === 'hi' ? 'गाइडेड विज़िट और टूर' : 'Guided visits and tours',
        custom: language === 'hi' ? 'कुछ और' : 'Something else',
      };
      payload.message = `Requested arrangements: ${serviceLabels[payload.service] || payload.service}\n\n${payload.message}`;
      delete payload.service;
    }
    try {
      await apiRequest(endpoint, { method: 'POST', body: JSON.stringify(payload) });
      form.reset();
      if (form.id === 'booking-form') bookingBackdrop.hidden = true;
      showToast(successMessage);
    } catch (error) {
      showToast(error.message || text('saveError'), true);
    }
  }

  document.getElementById('contact-form').addEventListener('submit', (event) => {
    event.preventDefault();
    submitPublicForm(event.currentTarget, '/api/inquiries', text('contactSuccess'));
  });
  document.getElementById('booking-form').addEventListener('submit', (event) => {
    event.preventDefault();
    submitPublicForm(event.currentTarget, '/api/bookings', text('bookingSuccess'));
  });
})();
