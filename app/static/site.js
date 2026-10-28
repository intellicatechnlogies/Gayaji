(() => {
  const heroes = JSON.parse(document.getElementById('hero-data').textContent);
  const languageToggle = document.getElementById('language-toggle');
  const toast = document.getElementById('toast');
  const bookingBackdrop = document.getElementById('booking-backdrop');
  const adminPanel = document.getElementById('admin-panel');
  const adminScrim = document.getElementById('admin-scrim');
  const isAdminPage = document.body.dataset.adminPage === 'true';
  const loginForm = document.getElementById('admin-login-form');
  const accountArea = document.getElementById('admin-account-area');
  const placeForm = document.getElementById('admin-place-form');
  const placeList = document.getElementById('admin-place-list');
  const stateCities = JSON.parse(document.getElementById('state-city-data').textContent);
  const adminListingData = { hotels: [], restaurants: [], guides: [] };
  document.querySelectorAll('[data-place-image]').forEach((image) => {
    image.addEventListener('error', () => { image.hidden = true; }, { once: true });
  });
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
      listingSaved: 'Listing saved.', listingRemoved: 'Listing removed.',
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
      listingSaved: 'जानकारी सहेजी गई।', listingRemoved: 'जानकारी हटा दी गई।',
    },
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
    if (isAdminPage) {
      adminPanel.hidden = false;
      adminScrim.hidden = true;
      document.body.classList.remove('panel-open');
      if (open) checkAdminSession();
      return;
    }
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
  if (isAdminPage) setAdminOpen(true);

  async function apiRequest(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    const response = await fetch(path, {
      ...options,
      headers,
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
      if (!isAdminPage) {
        window.location.assign('/admin/');
        return;
      }
      await refreshAdminData();
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
      await apiRequest('/api/admin/login', { method: 'POST', body: JSON.stringify(credentials) });
      loginForm.reset();
      window.location.assign('/admin/');
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
      if (isAdminPage) {
        window.location.assign('/');
        return;
      }
      loginForm.hidden = false;
      accountArea.hidden = true;
      placeForm.hidden = true;
      document.querySelectorAll('.listing-form').forEach((form) => { form.hidden = true; });
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
    image.addEventListener('error', () => { image.hidden = true; }, { once: true });
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
    const places = await apiRequest('/api/places');
    placeList.replaceChildren(...places.map(createAdminRow));
  }

  async function refreshStoredCredentials() {
    const list = document.getElementById('admin-credential-list');
    const credentials = await apiRequest('/api/admin/credentials');
    if (!credentials.length) {
      list.classList.add('admin-table-empty');
      list.textContent = 'No credentials stored.';
      return;
    }
    list.classList.remove('admin-table-empty');
    const table = document.createElement('table');
    table.className = 'admin-table';
    const head = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ['Service', 'Credential name', 'Last updated', 'Actions'].forEach((headingText) => {
      const heading = document.createElement('th');
      heading.scope = 'col';
      heading.textContent = headingText;
      headerRow.append(heading);
    });
    head.append(headerRow);
    const body = document.createElement('tbody');
    credentials.forEach((credential) => {
      const row = document.createElement('tr');
      [credential.service, credential.name, new Date(credential.updated_at).toLocaleString()].forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      });
      const actions = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'admin-table-delete';
      remove.textContent = 'Delete';
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Delete ${credential.service} credential "${credential.name}"?`)) return;
        try {
          await apiRequest(`/api/admin/credentials/${credential.id}`, { method: 'DELETE' });
          await refreshStoredCredentials();
          showToast('Credential deleted.');
        } catch (error) {
          showToast(error.message, true);
        }
      });
      actions.append(remove);
      row.append(actions);
      body.append(row);
    });
    table.append(head, body);
    list.replaceChildren(table);
  }

  async function refreshAdminData() {
    await refreshPlaces();
    await Promise.all(['hotels', 'restaurants', 'guides'].map(refreshListings));
  }

  function createListingTable(listingType, listings, searchTerm = '') {
    const columns = {
      hotels: [
        ['name', 'Hotel'], ['website', 'Website'], ['state', 'State'], ['city', 'City'], ['postal_code', 'PIN code'],
        ['contact_info', 'Contact'], ['address', 'Address'], ['air_conditioning', 'AC'],
        ['price_range', 'Price'], ['star_rating', 'Stars'],
      ],
      restaurants: [
        ['name', 'Restaurant'], ['state', 'State'], ['city', 'City'], ['postal_code', 'PIN code'],
        ['contact_info', 'Contact'], ['address', 'Address'], ['food_type', 'Food'], ['price_range', 'Price'],
      ],
      guides: [
        ['name', 'Guide'], ['state', 'State'], ['city', 'City'], ['postal_code', 'PIN code'],
        ['contact_info', 'Contact'], ['languages', 'Languages'], ['price', 'Price'],
      ],
    }[listingType];
    const allRows = listingType === 'hotels'
      ? listings.flatMap((hotel) => hotel.locations.map((location) => ({
        ...hotel,
        ...location,
      })))
      : listings;
    const normalizedSearch = searchTerm.trim().toLocaleLowerCase();
    const rows = normalizedSearch
      ? allRows.filter((item) => Object.values(item).some(
        (value) => String(value ?? '').toLocaleLowerCase().includes(normalizedSearch),
      ))
      : allRows;
    if (listingType === 'hotels') {
      const deleteShownForHotel = new Set();
      rows.forEach((row) => {
        row.showDelete = !deleteShownForHotel.has(row.id);
        deleteShownForHotel.add(row.id);
      });
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'admin-table-wrap';
    if (!rows.length) {
      wrapper.classList.add('admin-table-empty');
      wrapper.textContent = normalizedSearch ? 'No matching listings.' : 'No listings yet.';
      return wrapper;
    }
    const table = document.createElement('table');
    table.className = 'admin-table';
    const head = document.createElement('thead');
    const headingRow = document.createElement('tr');
    columns.forEach(([, label]) => {
      const heading = document.createElement('th');
      heading.scope = 'col';
      heading.textContent = label;
      headingRow.append(heading);
    });
    const actionsHeading = document.createElement('th');
    actionsHeading.scope = 'col';
    actionsHeading.textContent = 'Actions';
    headingRow.append(actionsHeading);
    head.append(headingRow);
    const body = document.createElement('tbody');
    rows.forEach((item) => {
      const row = document.createElement('tr');
      columns.forEach(([field]) => {
        const cell = document.createElement('td');
        cell.textContent = item[field] ?? '';
        row.append(cell);
      });
      const actions = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'admin-table-delete';
      remove.dataset.adminAction = 'delete';
      if (item.showDelete !== false) {
        remove.textContent = text('remove');
        remove.addEventListener('click', () => deleteListing(listingType, item.id));
        actions.append(remove);
      }
      row.append(actions);
      body.append(row);
    });
    table.append(head, body);
    wrapper.append(table);
    return wrapper;
  }

  async function refreshListings(listingType) {
    const listings = await apiRequest(`/api/admin/listings/${listingType}`);
    adminListingData[listingType] = listings;
    renderListings(listingType);
  }

  function renderListings(listingType) {
    const list = document.querySelector(`[data-listing-list="${listingType}"]`);
    const search = document.querySelector(`[data-listing-search="${listingType}"]`);
    list.replaceChildren(createListingTable(listingType, adminListingData[listingType], search.value));
    renderOverallLocationSearch();
  }

  function renderOverallLocationSearch() {
    const search = document.querySelector('[data-overall-location-search]');
    const results = document.querySelector('[data-overall-location-results]');
    const terms = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    document.querySelector('[data-overall-search-controls]').hidden = !terms.length;
    const languageOptions = document.querySelector('[data-guide-search-languages]');
    const selectedLanguages = new Set(
      [...languageOptions.querySelectorAll('input:checked')].map((checkbox) => checkbox.value),
    );
    const selectedTypes = new Set(
      [...document.querySelectorAll('[data-overall-search-type]:checked')].map((checkbox) => checkbox.dataset.overallSearchType),
    );
    document.querySelectorAll('[data-overall-filter-group]').forEach((group) => {
      group.hidden = !selectedTypes.has(group.dataset.overallFilterGroup);
    });
    const availableLanguages = new Map();
    if (terms.length && selectedTypes.has('guides')) {
      adminListingData.guides
        .filter((guide) => {
          const locationText = [guide.state, guide.city, guide.postal_code].join(' ').toLocaleLowerCase();
          return terms.every((term) => locationText.includes(term));
        })
        .forEach((guide) => {
          guide.languages.split(',').map((name) => name.trim()).filter(Boolean).forEach((name) => {
            const key = name.toLocaleLowerCase();
            if (!availableLanguages.has(key)) availableLanguages.set(key, name);
          });
        });
    }
    if (availableLanguages.size) {
      const options = [...availableLanguages.values()].sort((first, second) => first.localeCompare(second));
      languageOptions.replaceChildren(...options.map((name) => {
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = name;
        checkbox.checked = selectedLanguages.has(name);
        label.append(checkbox, ` ${name}`);
        return label;
      }));
    } else {
      const emptyMessage = document.createElement('span');
      emptyMessage.textContent = terms.length
        ? 'No guides with languages found for this location.'
        : 'Search for a location to see available guide languages.';
      languageOptions.replaceChildren(emptyMessage);
    }
    if (!terms.length) {
      results.textContent = 'Enter a location to find matching hotels, restaurants, and guides.';
      return;
    }
    if (!selectedTypes.size) {
      results.textContent = 'Select at least one listing type to search.';
      return;
    }

    const matches = [];
    if (selectedTypes.has('hotels')) adminListingData.hotels.forEach((hotel) => {
      hotel.locations.forEach((location) => {
        const locationText = [location.state, location.city, location.postal_code].join(' ').toLocaleLowerCase();
        if (terms.every((term) => locationText.includes(term))) {
          matches.push({
            type: 'Hotel',
            name: hotel.name,
            city: location.city,
            state: location.state,
            postalCode: location.postal_code,
            contact: location.contact_info,
            airConditioning: hotel.air_conditioning,
            rating: Number(hotel.star_rating),
            priceRange: hotel.price_range,
            website: hotel.website,
            details: [
              ['Address', location.address],
              ['Website', hotel.website],
              ['Air conditioning', hotel.air_conditioning],
              ['Rating', `${hotel.star_rating} stars`],
              ['Price range', hotel.price_range],
            ],
          });
        }
      });
    });
    if (selectedTypes.has('restaurants')) adminListingData.restaurants.forEach((restaurant) => {
      const locationText = [restaurant.state, restaurant.city, restaurant.postal_code].join(' ').toLocaleLowerCase();
      if (terms.every((term) => locationText.includes(term))) {
        matches.push({
          type: 'Restaurant',
          name: restaurant.name,
          city: restaurant.city,
          state: restaurant.state,
          postalCode: restaurant.postal_code,
          contact: restaurant.contact_info,
          foodType: restaurant.food_type,
          priceRange: restaurant.price_range,
          details: [
            ['Address', restaurant.address],
            ['Food type', restaurant.food_type],
            ['Price range', restaurant.price_range],
          ],
        });
      }
    });
    if (selectedTypes.has('guides')) adminListingData.guides.forEach((guide) => {
      const locationText = [guide.state, guide.city, guide.postal_code].join(' ').toLocaleLowerCase();
      if (terms.every((term) => locationText.includes(term))) {
        matches.push({
          type: 'Guide',
          name: guide.name,
          city: guide.city,
          state: guide.state,
          postalCode: guide.postal_code,
          contact: guide.contact_info,
          languages: guide.languages,
          price: Number(guide.price),
          details: [
            ['Languages', guide.languages],
            ['Price', `₹${guide.price}`],
          ],
        });
      }
    });

    const filterValue = (name) => document.querySelector(`[data-overall-filter="${name}"]`).value.trim();
    const minHotelPrice = Number(filterValue('hotel-min-price')) || null;
    const maxHotelPrice = Number(filterValue('hotel-max-price')) || null;
    const minGuidePrice = Number(filterValue('guide-min-price')) || null;
    const maxGuidePrice = Number(filterValue('guide-max-price')) || null;
    const chosenGuideLanguages = new Set(
      [...languageOptions.querySelectorAll('input:checked')].map((checkbox) => checkbox.value.toLocaleLowerCase()),
    );
    const filteredMatches = matches.filter((match) => {
      if (match.type === 'Hotel') {
        if (filterValue('hotel-rating') && match.rating !== Number(filterValue('hotel-rating'))) return false;
        if (filterValue('hotel-ac') && match.airConditioning.toLowerCase() !== filterValue('hotel-ac').toLowerCase()) {
          return false;
        }
        const hotelPriceFilter = filterValue('hotel-price-range').toLowerCase();
        if (hotelPriceFilter && !match.priceRange.toLowerCase().includes(hotelPriceFilter)) return false;
        if (minHotelPrice !== null || maxHotelPrice !== null) {
          const prices = match.priceRange.match(/\d+(?:,\d{3})*(?:\.\d+)?/g)
            ?.map((price) => Number(price.replaceAll(',', ''))) || [];
          if (!prices.length) return false;
          const lowest = Math.min(...prices);
          const highest = Math.max(...prices);
          if (minHotelPrice !== null && highest < minHotelPrice) return false;
          if (maxHotelPrice !== null && lowest > maxHotelPrice) return false;
        }
      } else if (match.type === 'Restaurant') {
        if (filterValue('restaurant-food') && match.foodType.toLowerCase() !== filterValue('restaurant-food').toLowerCase()) {
          return false;
        }
        if (filterValue('restaurant-price') && match.priceRange.toLowerCase() !== filterValue('restaurant-price').toLowerCase()) {
          return false;
        }
      } else {
        if (chosenGuideLanguages.size) {
          const guideLanguages = match.languages.split(',').map((name) => name.trim().toLocaleLowerCase());
          if (![...chosenGuideLanguages].some((name) => guideLanguages.includes(name))) return false;
        }
        if (minGuidePrice !== null && match.price < minGuidePrice) return false;
        if (maxGuidePrice !== null && match.price > maxGuidePrice) return false;
      }
      return true;
    });

    if (!filteredMatches.length) {
      results.textContent = 'No hotels, restaurants, or guides found for that location.';
      return;
    }

    const groups = [
      { type: 'Hotel', records: filteredMatches.filter((match) => match.type === 'Hotel') },
      { type: 'Restaurant', records: filteredMatches.filter((match) => match.type === 'Restaurant') },
      { type: 'Guide', records: filteredMatches.filter((match) => match.type === 'Guide') },
    ];
    const sections = groups.filter((group) => group.records.length).map((group) => {
      const section = document.createElement('details');
      section.className = 'overall-search-group';
      const heading = document.createElement('summary');
      heading.textContent = `${group.type} results (${group.records.length})`;
      section.append(heading);

      const cards = document.createElement('div');
      cards.className = 'overall-search-cards';
      group.records.forEach((match) => {
        const card = document.createElement('article');
        card.className = 'overall-search-card';
        const title = document.createElement('h5');
        title.textContent = match.name;
        card.append(title);
        const fields = [
          ['City', match.city],
          ['State', match.state],
          ['PIN code', match.postalCode],
          ['Contact', match.contact],
          ...match.details,
        ];
        const details = document.createElement('dl');
        details.className = 'overall-search-fields';
        fields.forEach(([label, value]) => {
          if (!value) return;
          const entry = document.createElement('div');
          const term = document.createElement('dt');
          term.textContent = label;
          const description = document.createElement('dd');
          description.textContent = value;
          entry.append(term, description);
          details.append(entry);
        });
        card.append(details);
        cards.append(card);
      });
      section.append(cards);
      return section;
    });
    results.replaceChildren(...sections);
  }

  document.querySelector('[data-overall-location-search]').addEventListener('input', renderOverallLocationSearch);
  document.querySelectorAll('[data-overall-filter]').forEach((filter) => {
    filter.addEventListener('input', renderOverallLocationSearch);
    filter.addEventListener('change', renderOverallLocationSearch);
  });
  document.querySelector('[data-guide-search-languages]').addEventListener('change', renderOverallLocationSearch);
  document.querySelectorAll('[data-overall-search-type]').forEach((checkbox) => {
    checkbox.addEventListener('change', renderOverallLocationSearch);
  });

  document.querySelectorAll('[data-listing-search]').forEach((search) => {
    search.addEventListener('input', () => {
      renderListings(search.dataset.listingSearch);
    });
  });

  document.querySelectorAll('[data-admin-tab]').forEach((button) => {
    button.addEventListener('click', async () => {
      const section = button.dataset.adminTab;
      document.querySelectorAll('[data-admin-tab]').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('[data-admin-section]').forEach((pane) => {
        pane.hidden = pane.dataset.adminSection !== section;
      });
      if (section === 'credentials') {
        try {
          await refreshStoredCredentials();
        } catch (error) {
          showToast(error.message, true);
        }
      }
    });
  });

  document.getElementById('admin-credential-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const payload = Object.fromEntries(new FormData(form));
      await apiRequest('/api/admin/credentials', { method: 'POST', body: JSON.stringify(payload) });
      form.reset();
      await refreshStoredCredentials();
      showToast('Credential encrypted and saved.');
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  document.querySelectorAll('[data-add-listing]').forEach((button) => {
    button.addEventListener('click', () => {
      const form = document.querySelector(`[data-listing-form="${button.dataset.addListing}"]`);
      form.reset();
      form.hidden = false;
      form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  document.querySelectorAll('.listing-cancel').forEach((button) => {
    button.addEventListener('click', () => {
      const form = button.closest('.listing-form');
      form.reset();
      form.hidden = true;
    });
  });

  function initializeLocationFields(scope) {
    const stateSelect = scope.querySelector('[data-location-state]');
    const citySelect = scope.querySelector('[data-location-city]');
    const cityOtherInput = scope.querySelector('[data-location-city-other]');
    const pincodeSelect = scope.querySelector('[data-location-pincode]');
    const pincodeOtherInput = scope.querySelector('[data-location-pincode-other]');
    let lookupSequence = 0;
    if (!stateSelect || !citySelect || !cityOtherInput || !pincodeSelect || !pincodeOtherInput) return;
    Object.keys(stateCities).forEach((state) => {
      stateSelect.add(new Option(state, state));
    });
    stateSelect.addEventListener('change', () => {
      lookupSequence += 1;
      citySelect.replaceChildren(new Option('Select a city', '', true, true));
      (stateCities[stateSelect.value] || []).forEach((city) => {
        citySelect.add(new Option(city, city));
      });
      citySelect.add(new Option('Other', '__other__'));
      citySelect.disabled = false;
      cityOtherInput.value = '';
      cityOtherInput.hidden = true;
      cityOtherInput.disabled = true;
      pincodeSelect.replaceChildren(new Option('Select a city first', '', true, true));
      pincodeSelect.disabled = true;
      pincodeOtherInput.value = '';
      pincodeOtherInput.hidden = true;
      pincodeOtherInput.disabled = true;
    });
    citySelect.addEventListener('change', async () => {
      const requestSequence = ++lookupSequence;
      const isOtherCity = citySelect.value === '__other__';
      cityOtherInput.hidden = !isOtherCity;
      cityOtherInput.disabled = !isOtherCity;
      cityOtherInput.required = isOtherCity;
      if (isOtherCity) {
        pincodeSelect.replaceChildren(new Option('Select a PIN code', '', true, true));
        pincodeSelect.add(new Option('Other', '__other__'));
        pincodeSelect.disabled = false;
        pincodeOtherInput.value = '';
        pincodeOtherInput.hidden = true;
        pincodeOtherInput.disabled = true;
        return;
      }
      pincodeSelect.replaceChildren(new Option('Loading PIN codes…', '', true, true));
      pincodeSelect.disabled = true;
      try {
        const params = new URLSearchParams({ state: stateSelect.value, city: citySelect.value });
        const pincodes = await apiRequest(`/api/location-pincodes?${params}`);
        if (requestSequence !== lookupSequence) return;
        pincodeSelect.replaceChildren(new Option('Select a PIN code', '', true, true));
        pincodes.forEach((pincode) => pincodeSelect.add(new Option(pincode, pincode)));
        pincodeSelect.add(new Option('Other', '__other__'));
        pincodeSelect.disabled = false;
      } catch (error) {
        if (requestSequence !== lookupSequence) return;
        pincodeSelect.replaceChildren(new Option('Select a PIN code', '', true, true));
        pincodeSelect.add(new Option('Other', '__other__'));
        pincodeSelect.disabled = false;
        showToast(error.message || text('saveError'), true);
      }
    });
    pincodeSelect.addEventListener('change', () => {
      const isOtherPincode = pincodeSelect.value === '__other__';
      pincodeOtherInput.hidden = !isOtherPincode;
      pincodeOtherInput.disabled = !isOtherPincode;
      pincodeOtherInput.required = isOtherPincode;
      if (!isOtherPincode) pincodeOtherInput.value = '';
    });
    scope.closest('form').addEventListener('reset', () => {
      if (!scope.isConnected) return;
      lookupSequence += 1;
      stateSelect.value = '';
      citySelect.replaceChildren(new Option('Select a city', '', true, true));
      citySelect.disabled = true;
      cityOtherInput.value = '';
      cityOtherInput.hidden = true;
      cityOtherInput.disabled = true;
      cityOtherInput.required = true;
      pincodeSelect.replaceChildren(new Option('Select a city first', '', true, true));
      pincodeSelect.disabled = true;
      pincodeOtherInput.value = '';
      pincodeOtherInput.hidden = true;
      pincodeOtherInput.disabled = true;
      pincodeOtherInput.required = true;
    });
  }

  document.querySelectorAll('[data-location-fields]').forEach(initializeLocationFields);
  document.querySelectorAll('.listing-form:not([data-listing-form="hotels"])').forEach(initializeLocationFields);

  function updateHotelLocationLabels() {
    document.querySelectorAll('[data-hotel-location]').forEach((card, index) => {
      card.querySelector('legend').textContent = `Branch location ${index + 1}`;
      card.querySelector('[data-remove-hotel-location]').hidden = index === 0;
    });
  }

  document.getElementById('add-hotel-location').addEventListener('click', () => {
    const template = document.getElementById('hotel-location-template');
    const card = template.content.firstElementChild.cloneNode(true);
    document.getElementById('hotel-location-fields').append(card);
    initializeLocationFields(card);
    updateHotelLocationLabels();
  });

  document.getElementById('hotel-location-fields').addEventListener('click', (event) => {
    const removeButton = event.target.closest('[data-remove-hotel-location]');
    if (!removeButton) return;
    removeButton.closest('[data-hotel-location]').remove();
    updateHotelLocationLabels();
  });

  document.querySelector('[data-listing-form="hotels"]').addEventListener('reset', () => {
    window.setTimeout(updateHotelLocationLabels);
  });
  updateHotelLocationLabels();

  function rememberLocation(state, city, pincode) {
    if (!stateCities[state]) stateCities[state] = [];
    if (!stateCities[state].includes(city)) {
      stateCities[state].push(city);
      stateCities[state].sort((first, second) => first.localeCompare(second));
    }
    document.querySelectorAll('[data-location-fields], .listing-form:not([data-listing-form="hotels"])').forEach((scope) => {
      const stateSelect = scope.querySelector('[data-location-state]');
      if (stateSelect.value !== state) return;
      const citySelect = scope.querySelector('[data-location-city]');
      if (![...citySelect.options].some((option) => option.value === city)) {
        citySelect.add(new Option(city, city), citySelect.querySelector('option[value="__other__"]'));
      }
      if (citySelect.value !== city) return;
      const pincodeSelect = scope.querySelector('[data-location-pincode]');
      if (![...pincodeSelect.options].some((option) => option.value === pincode)) {
        pincodeSelect.add(new Option(pincode, pincode), pincodeSelect.querySelector('option[value="__other__"]'));
      }
    });
  }

  function rememberGuideLanguage(form, name) {
    const options = form.querySelector('.guide-language-options');
    const existing = [...options.querySelectorAll('[data-guide-language]')].some(
      (choice) => choice.value.trim().toLowerCase() === name.trim().toLowerCase(),
    );
    if (existing) return;
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.name = 'guide_language';
    checkbox.value = name;
    checkbox.dataset.guideLanguage = '';
    label.append(checkbox, ` ${name}`);
    options.insertBefore(label, options.querySelector('[data-guide-language-other]').parentElement);
    checkbox.addEventListener('change', () => updateGuideLanguageValidity(form));
  }

  function updateGuideLanguageValidity(form) {
    const languageChoices = [...form.querySelectorAll('[data-guide-language]')];
    const otherLanguageChoice = form.querySelector('[data-guide-language-other]');
    const otherLanguageInput = form.querySelector('[data-guide-language-other-text]');
    const hasLanguage = languageChoices.some((choice) => choice.checked) || otherLanguageChoice.checked;
    languageChoices[0].setCustomValidity(hasLanguage ? '' : 'Select at least one language.');
    otherLanguageInput.hidden = !otherLanguageChoice.checked;
    otherLanguageInput.disabled = !otherLanguageChoice.checked;
    otherLanguageInput.required = otherLanguageChoice.checked;
  }

  document.querySelectorAll('.listing-form').forEach((form) => {
    if (form.dataset.listingForm === 'guides') {
      const languageChoices = [...form.querySelectorAll('[data-guide-language]')];
      const otherLanguageChoice = form.querySelector('[data-guide-language-other]');
      languageChoices.forEach((choice) => choice.addEventListener('change', () => updateGuideLanguageValidity(form)));
      otherLanguageChoice.addEventListener('change', () => updateGuideLanguageValidity(form));
      form.addEventListener('reset', () => window.setTimeout(() => updateGuideLanguageValidity(form)));
      updateGuideLanguageValidity(form);
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const listingType = form.dataset.listingForm;
      const payload = Object.fromEntries(new FormData(form));
      if (listingType === 'hotels') {
        payload.locations = [...form.querySelectorAll('[data-hotel-location]')].map((card) => {
          const citySelect = card.querySelector('[data-location-city]');
          const pincodeSelect = card.querySelector('[data-location-pincode]');
          return {
            state: card.querySelector('[data-location-state]').value,
            city: citySelect.value === '__other__'
              ? card.querySelector('[data-location-city-other]').value.trim()
              : citySelect.value,
            postal_code: pincodeSelect.value === '__other__'
              ? card.querySelector('[data-location-pincode-other]').value.trim()
              : pincodeSelect.value,
            contact_info: card.querySelector('[data-location-contact]').value,
            address: card.querySelector('[data-location-address]').value,
            city_is_other: citySelect.value === '__other__',
            postal_code_is_other: pincodeSelect.value === '__other__',
          };
        });
        payload.star_rating = Number(payload.star_rating);
      } else {
        payload.city_is_other = payload.city === '__other__';
        payload.postal_code_is_other = form.querySelector('[data-location-pincode]').value === '__other__';
        if (payload.city === '__other__') payload.city = payload.city_other.trim();
        if (payload.postal_code === '__other__') payload.postal_code = payload.postal_code_other.trim();
        delete payload.city_other;
        delete payload.postal_code_other;
      }
      if (listingType === 'guides') {
        const selectedLanguages = [...form.querySelectorAll('[data-guide-language]:checked')].map((choice) => choice.value);
        const otherLanguage = form.querySelector('[data-guide-language-other-text]').value.trim();
        if (form.querySelector('[data-guide-language-other]').checked && otherLanguage) {
          selectedLanguages.push(otherLanguage);
        }
        payload.languages = selectedLanguages.join(', ');
        delete payload.guide_language;
        delete payload.guide_language_other;
        delete payload.guide_language_other_text;
        payload.price = Number(payload.price);
      }
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const savedListing = await apiRequest(`/api/admin/listings/${listingType}`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        const customLocations = listingType === 'hotels'
          ? payload.locations.filter((location) => location.city_is_other || location.postal_code_is_other)
          : payload.city_is_other || payload.postal_code_is_other
            ? [{ state: savedListing.state, city: savedListing.city, postal_code: savedListing.postal_code }]
            : [];
        if (customLocations.length) {
          customLocations.forEach((location) => rememberLocation(location.state, location.city, location.postal_code));
        }
        if (listingType === 'guides') {
          savedListing.languages.split(',').forEach((name) => rememberGuideLanguage(form, name.trim()));
        }
        form.reset();
        form.hidden = true;
        await refreshListings(listingType);
        showToast(text('listingSaved'));
      } catch (error) {
        showToast(error.message || text('saveError'), true);
      } finally {
        button.disabled = false;
      }
    });
  });

  async function deleteListing(listingType, id) {
    if (!window.confirm(text('deleteConfirm'))) return;
    try {
      await apiRequest(`/api/admin/listings/${listingType}/${id}`, { method: 'DELETE' });
      await refreshListings(listingType);
      showToast(text('listingRemoved'));
    } catch (error) {
      showToast(error.message, true);
    }
  }

  document.getElementById('admin-add-place').addEventListener('click', () => {
    editingId = null;
    placeForm.reset();
    placeForm.elements.image.required = true;
    placeForm.hidden = false;
    document.getElementById('place-region').value = 'Bodh Gaya';
  });

  function startEdit(place) {
    editingId = place.id;
    for (const field of ['name', 'description', 'region', 'category']) {
      placeForm.elements[field].value = place[field];
    }
    placeForm.elements.image.required = false;
    placeForm.hidden = false;
    placeForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  document.getElementById('admin-cancel-edit').addEventListener('click', () => {
    editingId = null;
    placeForm.reset();
    placeForm.elements.image.required = true;
    placeForm.hidden = true;
  });

  placeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const path = editingId ? `/api/places/${editingId}` : '/api/places';
    try {
      await apiRequest(path, { method: editingId ? 'PATCH' : 'POST', body: new FormData(placeForm) });
      editingId = null;
      placeForm.reset();
      placeForm.elements.image.required = true;
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
