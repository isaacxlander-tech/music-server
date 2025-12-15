// API Base URL
const API_BASE = '/api';

// State
let authToken = localStorage.getItem('authToken') || null;
let currentUser = null;
let currentResults = null;
let downloadStatuses = new Map(); // Track download statuses by URL
let downloadStatusInterval = null;

// DOM Elements
const logoutBtn = document.getElementById('logout-btn');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const resultsTitle = document.getElementById('results-title');
const resultsActions = document.getElementById('results-actions');
const libraryContainer = document.getElementById('library-container');
const albumsView = document.getElementById('albums-view');
const albumsContainer = document.getElementById('albums-container');
const albumDetailView = document.getElementById('album-detail-view');
const albumDetailTitle = document.getElementById('album-detail-title');
const albumTracksContainer = document.getElementById('album-tracks-container');
const backToAlbumsBtn = document.getElementById('back-to-albums-btn');
const librarySearchInput = document.getElementById('library-search-input');
const librarySearchBtn = document.getElementById('library-search-btn');
const usernameDisplay = document.getElementById('username-display');
const searchView = document.getElementById('search-view');
const libraryView = document.getElementById('library-view');
const navItems = document.querySelectorAll('.nav-item');
const allTracksView = document.getElementById('all-tracks-view');
const allTracksContainer = document.getElementById('all-tracks-container');
const libraryTracksBtn = document.getElementById('library-tracks-btn');
const libraryAlbumsBtn = document.getElementById('library-albums-btn');
const downloadsView = document.getElementById('downloads-view');
const downloadsContainer = document.getElementById('downloads-container');
const clearQueueBtn = document.getElementById('clear-queue-btn');

// Simple event handler that works on all devices
function addEventListeners(element, callback) {
    if (!element) return;
    
    // Store touch data on element to avoid sharing between elements
    if (!element._touchData) {
        element._touchData = {
            startTime: 0,
            startX: 0,
            startY: 0,
            moved: false,
            lastTouchTime: 0
        };
    }
    
    const touchData = element._touchData;
    
    // Touch events for mobile
    element.addEventListener('touchstart', (e) => {
        touchData.startTime = Date.now();
        touchData.startX = e.touches[0].clientX;
        touchData.startY = e.touches[0].clientY;
        touchData.moved = false;
        element.style.opacity = '0.7';
    }, { passive: true });
    
    element.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) {
            const xDiff = Math.abs(e.touches[0].clientX - touchData.startX);
            const yDiff = Math.abs(e.touches[0].clientY - touchData.startY);
            if (xDiff > 10 || yDiff > 10) {
                touchData.moved = true;
                element.style.opacity = '';
            }
        }
    }, { passive: true });
    
    element.addEventListener('touchend', (e) => {
        element.style.opacity = '';
        touchData.lastTouchTime = Date.now();
        
        const timeDiff = Date.now() - touchData.startTime;
        const touchEndX = e.changedTouches[0].clientX;
        const touchEndY = e.changedTouches[0].clientY;
        const xDiff = Math.abs(touchEndX - touchData.startX);
        const yDiff = Math.abs(touchEndY - touchData.startY);
        
        // Only trigger if it's a tap (not a swipe)
        if (!touchData.moved && timeDiff < 500 && xDiff < 20 && yDiff < 20) {
            e.preventDefault();
            e.stopPropagation();
            callback(e);
        }
        
        touchData.moved = false;
    }, { passive: false });
    
    // Click for desktop
    element.addEventListener('click', (e) => {
        // Only handle click if no recent touch
        const timeSinceTouch = Date.now() - touchData.lastTouchTime;
        if (timeSinceTouch > 300) {
            callback(e);
        }
    });
}

// Initialize - Check authentication
document.addEventListener('DOMContentLoaded', async () => {
    if (!authToken) {
        window.location.href = '/login';
        return;
    }

    const isValid = await checkAuth();
    if (!isValid) {
        window.location.href = '/login';
        return;
    }

    await loadUserInfo();
    
    // Initialize search filters
    initSearchFilters();
    
    // Initialize navigation
    initNavigation();
    
    // Initialize mobile menu
    initMobileMenu();
    
    // Start polling download statuses
    downloadStatusInterval = setInterval(checkDownloadStatuses, 2000);
});

// Initialize Mobile Menu
function initMobileMenu() {
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const sidebar = document.querySelector('.sidebar');
    
    if (!mobileMenuBtn || !sidebar) return;
    
    // Toggle menu
    const toggleMenu = () => {
        sidebar.classList.toggle('mobile-open');
        document.body.style.overflow = sidebar.classList.contains('mobile-open') ? 'hidden' : '';
    };
    
    addEventListeners(mobileMenuBtn, toggleMenu);
    
    // Close menu when clicking nav item on mobile
    navItems.forEach(item => {
        addEventListeners(item, (e) => {
            if (window.innerWidth <= 768) {
                sidebar.classList.remove('mobile-open');
                document.body.style.overflow = '';
            }
        });
    });
    
    // Close menu on window resize if desktop
    window.addEventListener('resize', () => {
        if (window.innerWidth > 768) {
            sidebar.classList.remove('mobile-open');
            document.body.style.overflow = '';
        }
    });
    
    // Close menu when clicking outside on mobile
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 768 && sidebar.classList.contains('mobile-open')) {
            if (!sidebar.contains(e.target) && !mobileMenuBtn.contains(e.target)) {
                sidebar.classList.remove('mobile-open');
                document.body.style.overflow = '';
            }
        }
    });
}

// Initialize Navigation
function initNavigation() {
    navItems.forEach(item => {
        addEventListeners(item, (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            switchView(view);
            
            // Update active state
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

// Switch View
function switchView(view) {
    if (view === 'search') {
        searchView.classList.add('active');
        libraryView.classList.remove('active');
        libraryView.style.display = 'none';
        downloadsView.classList.remove('active');
        downloadsView.style.display = 'none';
    } else if (view === 'library') {
        libraryView.classList.add('active');
        libraryView.style.display = 'block';
        searchView.classList.remove('active');
        downloadsView.classList.remove('active');
        downloadsView.style.display = 'none';
        // Load tracks by default
        switchLibraryMode('tracks');
    } else if (view === 'downloads') {
        downloadsView.classList.add('active');
        downloadsView.style.display = 'block';
        searchView.classList.remove('active');
        libraryView.classList.remove('active');
        libraryView.style.display = 'none';
        loadDownloads();
    }
}

// Check authentication
async function checkAuth() {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const user = await response.json();
            currentUser = user.username;
            return true;
        } else {
            localStorage.removeItem('authToken');
            authToken = null;
            return false;
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        localStorage.removeItem('authToken');
        authToken = null;
        return false;
    }
}

// Load user info
async function loadUserInfo() {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const user = await response.json();
            currentUser = user.username;
            if (usernameDisplay) {
                usernameDisplay.textContent = user.username;
            }
        }
    } catch (error) {
        console.error('Failed to load user info:', error);
    }
}

// Logout
function logout() {
    if (authToken) {
        fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        }).catch(console.error);
    }
    localStorage.removeItem('authToken');
    authToken = null;
    currentUser = null;
    window.location.href = '/login';
}

// Event Listeners
if (logoutBtn) {
    addEventListeners(logoutBtn, (e) => {
        e.preventDefault();
        logout();
    });
}

// Search Mode Toggle
let currentSearchMode = 'url';
const urlModeBtn = document.getElementById('url-mode-btn');
const searchModeBtn = document.getElementById('search-mode-btn');
const urlForm = document.getElementById('url-search-form');
const textForm = document.getElementById('text-search-form');

if (urlModeBtn) {
    addEventListeners(urlModeBtn, (e) => {
        e.preventDefault();
        switchSearchMode('url');
    });
}

if (searchModeBtn) {
    addEventListeners(searchModeBtn, (e) => {
        e.preventDefault();
        switchSearchMode('search');
    });
}

function switchSearchMode(mode) {
    currentSearchMode = mode;
    
    if (mode === 'url') {
        urlModeBtn.classList.add('active');
        searchModeBtn.classList.remove('active');
        urlForm.classList.add('active');
        urlForm.style.display = 'block';
        textForm.classList.remove('active');
        textForm.style.display = 'none';
    } else {
        searchModeBtn.classList.add('active');
        urlModeBtn.classList.remove('active');
        textForm.classList.add('active');
        textForm.style.display = 'block';
        urlForm.classList.remove('active');
        urlForm.style.display = 'none';
    }
    
    // Clear previous results
    resultsSection.style.display = 'none';
    currentResults = null;
}

// URL Search Form
urlForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = document.getElementById('url-input').value.trim();
    if (url) {
        await searchMusic(url);
    }
});

// Text Search Form
let currentSearchType = 'songs';
let searchInProgress = false;

textForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = document.getElementById('text-search-input').value.trim();
    if (query && !searchInProgress) {
        document.getElementById('search-type-filters').style.display = 'flex';
        await searchByTextProgressive(query);
    }
});

// Initialize Search Type Filters
function initSearchFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        addEventListeners(btn, async (e) => {
            e.preventDefault();
            if (searchInProgress) return;
            
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSearchType = btn.dataset.type;
            
            const currentTitle = resultsTitle.textContent;
            if (currentTitle.includes(' - ')) {
                const artistName = currentTitle.split(' - ')[0].trim();
                await loadArtistContent(artistName, currentSearchType);
            }
        });
    });
}

// Library Mode Toggle
let currentLibraryMode = 'tracks';

if (libraryTracksBtn) {
    addEventListeners(libraryTracksBtn, (e) => {
        e.preventDefault();
        switchLibraryMode('tracks');
    });
}

if (libraryAlbumsBtn) {
    addEventListeners(libraryAlbumsBtn, (e) => {
        e.preventDefault();
        switchLibraryMode('albums');
    });
}

function switchLibraryMode(mode) {
    currentLibraryMode = mode;
    
    if (mode === 'tracks') {
        libraryTracksBtn.classList.add('active');
        libraryAlbumsBtn.classList.remove('active');
        allTracksView.style.display = 'block';
        albumsView.style.display = 'none';
        albumDetailView.style.display = 'none';
        loadAllTracks();
    } else {
        libraryAlbumsBtn.classList.add('active');
        libraryTracksBtn.classList.remove('active');
        allTracksView.style.display = 'none';
        albumsView.style.display = 'block';
        albumDetailView.style.display = 'none';
        loadAlbums();
    }
}

if (librarySearchBtn) {
    addEventListeners(librarySearchBtn, (e) => {
        e.preventDefault();
        const query = librarySearchInput.value.trim();
        if (query) {
            if (currentLibraryMode === 'tracks') {
                searchAllTracks(query);
            } else {
                searchAlbums(query);
            }
        } else {
            if (currentLibraryMode === 'tracks') {
                loadAllTracks();
            } else {
                loadAlbums();
            }
        }
    });
}

if (librarySearchInput) {
    librarySearchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            librarySearchBtn.click();
        }
    });
}

if (backToAlbumsBtn) {
    addEventListeners(backToAlbumsBtn, (e) => {
        e.preventDefault();
        showAlbumsView();
        if (currentLibraryMode === 'tracks') {
            loadAllTracks();
        } else {
            loadAlbums();
        }
    });
}

// Search Music/Album by URL
async function searchMusic(url) {
    const searchBtn = document.getElementById('url-search-btn');
    const btnText = searchBtn.querySelector('.btn-text');
    const btnLoader = searchBtn.querySelector('.btn-loader');
    const messageDiv = document.getElementById('search-message');

    searchBtn.disabled = true;
    btnText.style.display = 'none';
    btnLoader.style.display = 'inline';
    messageDiv.className = 'message';
    messageDiv.textContent = '';
    messageDiv.style.display = 'none';
    resultsSection.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/search`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            currentResults = data;
            displayResults(data);
            resultsSection.style.display = 'block';
        } else {
            messageDiv.className = 'message error';
            messageDiv.textContent = data.detail || 'Erreur lors de la recherche';
            messageDiv.style.display = 'block';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = `Erreur: ${error.message}`;
        messageDiv.style.display = 'block';
    } finally {
        searchBtn.disabled = false;
        btnText.style.display = 'inline';
        btnLoader.style.display = 'none';
    }
}

// Search by Text
async function searchByTextProgressive(query) {
    if (searchInProgress) return;
    
    searchInProgress = true;
    const messageDiv = document.getElementById('search-message');
    const searchBtn = document.getElementById('text-search-btn');
    const btnText = searchBtn.querySelector('.btn-text');
    const btnLoader = searchBtn.querySelector('.btn-loader');

    searchBtn.disabled = true;
    btnText.style.display = 'none';
    btnLoader.style.display = 'inline';
    messageDiv.className = 'message';
    messageDiv.textContent = '';
    messageDiv.style.display = 'none';
    
    resultsSection.style.display = 'block';
    resultsTitle.textContent = `Résultats pour "${escapeHtml(query)}"`;
    resultsContainer.innerHTML = '<div class="search-results-loading">Recherche en cours...</div>';
    
    // Récupérer la plateforme sélectionnée
    const platformSelect = document.getElementById('platform-select');
    const platform = platformSelect ? platformSelect.value : 'youtube';
    
    try {
        const response = await fetch(`${API_BASE}/search/text/quick`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ query, platform, limit: 20 })
        });

        const data = await response.json();

        if (response.ok && data.success && data.type === 'artists') {
            displayArtists(data.artists, query);
        } else {
            messageDiv.className = 'message error';
            messageDiv.textContent = data.detail || 'Erreur lors de la recherche';
            messageDiv.style.display = 'block';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = `Erreur: ${error.message}`;
        messageDiv.style.display = 'block';
    } finally {
        searchInProgress = false;
        searchBtn.disabled = false;
        btnText.style.display = 'inline';
        btnLoader.style.display = 'none';
    }
}

// Display Artists
function displayArtists(artists, query) {
    resultsContainer.innerHTML = '';
    
    if (artists.length === 0) {
        resultsContainer.innerHTML = '<div class="search-results-loading">Aucun artiste trouvé</div>';
        return;
    }
    
    artists.forEach(artist => {
        const artistCard = document.createElement('div');
        artistCard.className = 'artist-result-card';
        addEventListeners(artistCard, (e) => {
            e.preventDefault();
            showArtistContent(artist.name);
        });
        
        const placeholderIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18V5l12-2v13"></path>
            <circle cx="6" cy="18" r="3"></circle>
            <circle cx="18" cy="16" r="3"></circle>
        </svg>`;
        
        artistCard.innerHTML = `
            <div class="artist-result-thumbnail">
                ${artist.thumbnail ? `<img src="${artist.thumbnail}" alt="${escapeHtml(artist.name)}">` : `<div class="artist-placeholder">${placeholderIcon}</div>`}
            </div>
            <div class="artist-result-info">
                <div class="artist-result-name">${escapeHtml(artist.name)}</div>
                <div class="artist-result-meta">${artist.tracks.length} ${artist.tracks.length > 1 ? 'titres' : 'titre'} trouvé${artist.tracks.length > 1 ? 's' : ''}</div>
            </div>
            <div class="artist-result-arrow">→</div>
        `;
        resultsContainer.appendChild(artistCard);
    });
}

// Show Artist Content
async function showArtistContent(artistName) {
    resultsContainer.innerHTML = '<div class="search-results-loading">Chargement du contenu...</div>';
    document.getElementById('search-type-filters').style.display = 'flex';
    await loadArtistContent(artistName, currentSearchType);
}

// Load Artist Content
async function loadArtistContent(artistName, contentType) {
    try {
        // Récupérer la plateforme sélectionnée
        const platformSelect = document.getElementById('platform-select');
        const platform = platformSelect ? platformSelect.value : 'youtube';
        
        const response = await fetch(`${API_BASE}/search/artist`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ artist: artistName, platform, type: contentType, limit: 30 })
        });

        const data = await response.json();

        if (response.ok && data.success) {
            displayArtistContent(artistName, contentType, data.tracks);
        } else {
            resultsContainer.innerHTML = '<div class="search-results-loading">Erreur lors du chargement</div>';
        }
    } catch (error) {
        resultsContainer.innerHTML = `<div class="search-results-loading">Erreur: ${error.message}</div>`;
    }
}

// Display Artist Content
function displayArtistContent(artistName, contentType, tracks) {
    resultsContainer.innerHTML = '';
    const typeLabels = {
        'songs': 'Songs',
        'albums': 'Albums',
        'playlists': 'Playlists'
    };
    resultsTitle.textContent = `${escapeHtml(artistName)} - ${typeLabels[contentType] || contentType}`;
    
    if (tracks.length === 0) {
        resultsContainer.innerHTML = '<div class="search-results-loading">Aucun contenu trouvé</div>';
        return;
    }
    
    const tracksGrid = document.createElement('div');
    tracksGrid.className = 'search-tracks-grid';
    
    tracks.forEach((track, index) => {
        const trackCard = createSongCard(track, index + 1);
        tracksGrid.appendChild(trackCard);
    });
    
    resultsContainer.appendChild(tracksGrid);
}

// Display Results
function displayResults(data) {
    resultsContainer.innerHTML = '';
    resultsActions.innerHTML = '';

    if (data.type === 'playlist') {
        const header = document.createElement('div');
        header.className = 'playlist-header';
        
        const placeholderIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 18V5l12-2v13"></path>
            <circle cx="6" cy="18" r="3"></circle>
            <circle cx="18" cy="16" r="3"></circle>
        </svg>`;
        
        const thumbnail = data.playlist_info.thumbnail 
            ? `<img src="${data.playlist_info.thumbnail}" alt="Album" class="playlist-thumbnail">`
            : `<div class="playlist-thumbnail" style="background: var(--bg-tertiary); display: flex; align-items: center; justify-content: center; color: var(--text-muted);">${placeholderIcon}</div>`;
        
        header.innerHTML = `
            ${thumbnail}
            <div class="playlist-info">
                <div class="playlist-title">${escapeHtml(data.playlist_info.title)}</div>
                <div class="playlist-artist">${escapeHtml(data.playlist_info.uploader)}</div>
                <div class="playlist-meta">${data.count} musiques</div>
                <div class="playlist-actions">
                    <button class="btn btn-primary" data-action="add-all-queue">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 18px; height: 18px;">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Ajouter tout
                    </button>
                </div>
            </div>
        `;
        const addAllBtn = header.querySelector('[data-action="add-all-queue"]');
        if (addAllBtn) {
            addEventListeners(addAllBtn, (e) => {
                e.preventDefault();
                addAllToQueue();
            });
        }
        resultsContainer.appendChild(header);

        data.tracks.forEach((track, index) => {
            const trackDiv = createTrackResult(track, index + 1);
            resultsContainer.appendChild(trackDiv);
        });

        resultsTitle.textContent = `Album: ${escapeHtml(data.playlist_info.title)}`;
    } else if (data.type === 'search_results') {
        resultsTitle.textContent = `Résultats pour "${escapeHtml(data.query)}"`;
        
        const tracksByArtist = {};
        data.tracks.forEach(track => {
            const artist = track.artist || 'Unknown Artist';
            if (!tracksByArtist[artist]) {
                tracksByArtist[artist] = [];
            }
            tracksByArtist[artist].push(track);
        });
        
        Object.keys(tracksByArtist).forEach(artist => {
            const artistSection = document.createElement('div');
            artistSection.className = 'search-artist-section';
            
            const tracks = tracksByArtist[artist];
            const firstTrack = tracks[0];
            const placeholderIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 18V5l12-2v13"></path>
                <circle cx="6" cy="18" r="3"></circle>
                <circle cx="18" cy="16" r="3"></circle>
            </svg>`;
            
            const artistCard = document.createElement('div');
            artistCard.className = 'search-artist-card';
            artistCard.innerHTML = `
                <div class="search-artist-thumbnail">
                    ${firstTrack.thumbnail ? `<img src="${firstTrack.thumbnail}" alt="${escapeHtml(artist)}">` : `<div class="artist-placeholder">${placeholderIcon}</div>`}
                </div>
                <div class="search-artist-info">
                    <div class="search-artist-name">${escapeHtml(artist)}</div>
                    <div class="search-artist-meta">Artiste • ${tracks.length} ${tracks.length > 1 ? 'titres' : 'titre'}</div>
                </div>
                <div class="search-artist-actions">
                    <button class="btn btn-secondary" data-action="add-all-search" data-urls='${JSON.stringify(tracks.map(t => t.url))}'>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 16px; height: 16px;">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Ajouter tout
                    </button>
                </div>
            `;
            const addAllSearchBtn = artistCard.querySelector('[data-action="add-all-search"]');
            if (addAllSearchBtn) {
                const urls = JSON.parse(addAllSearchBtn.dataset.urls);
                addEventListeners(addAllSearchBtn, (e) => {
                    e.preventDefault();
                    addAllToQueueFromSearch(urls);
                });
            }
            artistSection.appendChild(artistCard);
            
            const tracksList = document.createElement('div');
            tracksList.className = 'search-tracks-list';
            tracksList.innerHTML = `<div class="search-section-title">Les essentiels</div>`;
            
            tracks.forEach((track, index) => {
                const trackDiv = createTrackResult(track, index + 1);
                tracksList.appendChild(trackDiv);
            });
            
            artistSection.appendChild(tracksList);
            resultsContainer.appendChild(artistSection);
        });
    } else {
        const trackDiv = createTrackResult(data.track, null);
        resultsContainer.appendChild(trackDiv);
        resultsTitle.textContent = 'Musique';
    }
}

// Create Track Result Element with Download Status
function createTrackResult(track, trackNumber) {
    const div = document.createElement('div');
    div.className = 'track-result';
    div.dataset.url = track.url;
    
    const placeholderIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 18V5l12-2v13"></path>
        <circle cx="6" cy="18" r="3"></circle>
        <circle cx="18" cy="16" r="3"></circle>
    </svg>`;
    
    const thumbnail = track.thumbnail 
        ? `<img src="${track.thumbnail}" alt="${escapeHtml(track.title)}" class="track-result-thumbnail">`
        : `<div class="track-result-thumbnail" style="background: var(--bg-tertiary); display: flex; align-items: center; justify-content: center; color: var(--text-muted);">${placeholderIcon}</div>`;
    
    const duration = track.duration ? formatDuration(track.duration) : '';
    const downloadStatus = getDownloadStatusHTML(track.url);
    
    div.innerHTML = `
        ${thumbnail}
        <div class="track-result-info">
            ${trackNumber ? `<div style="color: var(--text-secondary); font-size: 0.85em; margin-bottom: 4px;">#${trackNumber}</div>` : ''}
            <div class="track-result-title">${escapeHtml(track.title)}</div>
            ${track.artist ? `<div class="track-result-artist">${escapeHtml(track.artist)}</div>` : ''}
            ${duration ? `<div class="track-result-duration">${duration}</div>` : ''}
            ${downloadStatus}
            <!-- Mobile download button inside info -->
            <button class="track-result-download-btn-mobile" data-action="download" data-url="${track.url}" title="Télécharger">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
            </button>
        </div>
    `;
    
    // Attach event listeners for download button
    const downloadBtns = div.querySelectorAll('[data-action="download"]');
    downloadBtns.forEach(btn => {
        addEventListeners(btn, (e) => {
            e.preventDefault();
            downloadNow(track.url, track.title);
        });
    });
    
    return div;
}

// Create Song Card Element
function createSongCard(track, trackNumber) {
    const div = document.createElement('div');
    div.className = 'song-card';
    
    const placeholderIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M9 18V5l12-2v13"></path>
        <circle cx="6" cy="18" r="3"></circle>
        <circle cx="18" cy="16" r="3"></circle>
    </svg>`;
    
    const thumbnail = track.thumbnail 
        ? `<img src="${track.thumbnail}" alt="${escapeHtml(track.title)}" class="song-card-thumbnail">`
        : `<div class="song-card-thumbnail" style="background: var(--bg-tertiary); display: flex; align-items: center; justify-content: center; color: var(--text-muted);">${placeholderIcon}</div>`;
    
    const duration = track.duration ? formatDuration(track.duration) : '';
    
    div.innerHTML = `
        <div class="song-card-image-wrapper">
            ${thumbnail}
           
        </div>
        <div class="song-card-info">
            <div class="song-card-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</div>
            ${track.artist ? `<div class="song-card-artist">${escapeHtml(track.artist)}</div>` : ''}
            ${duration ? `<div class="song-card-duration">${duration}</div>` : ''}
            <button class="song-card-download-btn" data-action="download" data-url="${track.url}" title="Télécharger">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
            </button>
        </div>
    `;
    
    // Attach event listeners for all download buttons
    const downloadBtns = div.querySelectorAll('[data-action="download"]');
    downloadBtns.forEach(btn => {
        addEventListeners(btn, (e) => {
            e.preventDefault();
            downloadNow(track.url, track.title);
        });
    });
    
    return div;
}

// Get Download Status HTML
function getDownloadStatusHTML(url) {
    const status = downloadStatuses.get(url);
    if (!status) return '';
    
    let statusHTML = '';
    if (status.status === 'downloading' || status.status === 'processing') {
        const progress = status.progress || 0;
        statusHTML = `
            <div class="track-download-status ${status.status}">
                <div class="download-spinner"></div>
                <span>${status.message || 'Téléchargement...'}</span>
                <div class="download-progress">
                    <div class="download-progress-fill" style="width: ${progress}%"></div>
                </div>
            </div>
        `;
    } else if (status.status === 'completed') {
        statusHTML = `
            <div class="track-download-status completed">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>Téléchargé</span>
            </div>
        `;
    } else if (status.status === 'failed') {
        statusHTML = `
            <div class="track-download-status failed">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span>Échec</span>
            </div>
        `;
    }
    
    return statusHTML;
}

// Check Download Statuses
async function checkDownloadStatuses() {
    try {
        const response = await fetch(`${API_BASE}/queue`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            const newStatuses = new Map();
            
            data.queue.forEach(item => {
                newStatuses.set(item.url, {
                    status: item.status,
                    progress: item.progress || 0,
                    message: item.message || ''
                });
            });
            
            // Update statuses
            downloadStatuses = newStatuses;
            
            // Update downloads view if visible
            if (downloadsView && downloadsView.style.display !== 'none') {
                displayDownloads(data.queue || []);
            }
            
            // Update UI for tracks with status
            document.querySelectorAll('.track-result').forEach(trackEl => {
                const url = trackEl.dataset.url;
                if (url) {
                    const statusEl = trackEl.querySelector('.track-download-status');
                    const statusHTML = getDownloadStatusHTML(url);
                    
                    if (statusHTML && statusEl) {
                        statusEl.outerHTML = statusHTML;
                    } else if (statusHTML && !statusEl) {
                        const infoEl = trackEl.querySelector('.track-result-info');
                        if (infoEl) {
                            infoEl.insertAdjacentHTML('beforeend', statusHTML);
                        }
                    } else if (!statusHTML && statusEl) {
                        statusEl.remove();
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to check download statuses:', error);
    }
}

// Download Now
async function downloadNow(url, title = null) {
    try {
        // Mark as downloading
        downloadStatuses.set(url, {
            status: 'downloading',
            progress: 0,
            message: 'Ajout à la queue...'
        });
        
        // Update UI immediately
        updateTrackStatus(url);
        
        const response = await fetch(`${API_BASE}/queue/add`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ url, title })
        });

        const data = await response.json();
        if (response.ok) {
            showMessage('Téléchargement démarré', 'success');
        } else {
            downloadStatuses.set(url, {
                status: 'failed',
                progress: 0,
                message: data.detail || 'Erreur'
            });
            updateTrackStatus(url);
            showMessage(data.detail || 'Erreur', 'error');
        }
    } catch (error) {
        downloadStatuses.set(url, {
            status: 'failed',
            progress: 0,
            message: error.message
        });
        updateTrackStatus(url);
        showMessage(`Erreur: ${error.message}`, 'error');
    }
}

// Update Track Status in UI
function updateTrackStatus(url) {
    document.querySelectorAll('.track-result').forEach(trackEl => {
        if (trackEl.dataset.url === url) {
            const statusEl = trackEl.querySelector('.track-download-status');
            const statusHTML = getDownloadStatusHTML(url);
            
            if (statusHTML && statusEl) {
                statusEl.outerHTML = statusHTML;
            } else if (statusHTML && !statusEl) {
                const infoEl = trackEl.querySelector('.track-result-info');
                if (infoEl) {
                    infoEl.insertAdjacentHTML('beforeend', statusHTML);
                }
            } else if (!statusHTML && statusEl) {
                statusEl.remove();
            }
        }
    });
}

// Add All to Queue
async function addAllToQueue() {
    if (!currentResults || currentResults.type !== 'playlist') return;
    
    const urls = currentResults.tracks.map(t => t.url);
    const titles = currentResults.tracks.map(t => t.title);
    
    try {
        const response = await fetch(`${API_BASE}/queue/add-multiple`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ urls, titles })
        });

        const data = await response.json();
        if (response.ok) {
            // Mark all as downloading
            urls.forEach(url => {
                downloadStatuses.set(url, {
                    status: 'downloading',
                    progress: 0,
                    message: 'En attente...'
                });
            });
            showMessage(`${urls.length} musiques ajoutées`, 'success');
        } else {
            showMessage(data.detail || 'Erreur', 'error');
        }
    } catch (error) {
        showMessage(`Erreur: ${error.message}`, 'error');
    }
}

// Add All to Queue from Search Results
async function addAllToQueueFromSearch(urls) {
    try {
        const response = await fetch(`${API_BASE}/queue/add-multiple`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ urls })
        });

        const data = await response.json();
        if (response.ok) {
            urls.forEach(url => {
                downloadStatuses.set(url, {
                    status: 'downloading',
                    progress: 0,
                    message: 'En attente...'
                });
            });
            showMessage(`${urls.length} musiques ajoutées`, 'success');
        } else {
            showMessage(data.detail || 'Erreur', 'error');
        }
    } catch (error) {
        showMessage(`Erreur: ${error.message}`, 'error');
    }
}

// Load Albums
// Load All Tracks
async function loadAllTracks() {
    allTracksContainer.innerHTML = '<div class="loading">Chargement...</div>';

    try {
        const response = await fetch(`${API_BASE}/tracks?limit=1000`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const tracks = await response.json();
            displayAllTracks(tracks);
        } else {
            if (response.status === 401) {
                window.location.href = '/login';
            } else {
                allTracksContainer.innerHTML = '<div class="error-message">Erreur lors du chargement</div>';
            }
        }
    } catch (error) {
        allTracksContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

// Display All Tracks
function displayAllTracks(tracks) {
    if (tracks.length === 0) {
        allTracksContainer.innerHTML = '<div class="loading">Aucune musique dans la bibliothèque</div>';
        return;
    }

    allTracksContainer.innerHTML = '';
    tracks.forEach((track, index) => {
        const div = document.createElement('div');
        div.className = 'track-item';
        div.innerHTML = `
            <div class="track-info">
                <div class="track-title">${escapeHtml(track.title)}</div>
                <div class="track-meta">
                    ${track.artist || 'Artiste inconnu'}
                    ${track.album ? ` • ${escapeHtml(track.album)}` : ''}
                    ${track.year ? ` • ${track.year}` : ''}
                    ${track.duration ? ` • ${formatDuration(track.duration)}` : ''}
                </div>
            </div>
            <div class="track-actions">
                <button class="btn-icon" data-action="delete" data-track-id="${track.id}" title="Supprimer">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `;
        // Attach event listeners
        const deleteBtn = div.querySelector('[data-action="delete"]');
        if (deleteBtn) {
            addEventListeners(deleteBtn, (e) => {
                e.preventDefault();
                deleteTrack(track.id);
            });
        }
        allTracksContainer.appendChild(div);
    });
}

// Search All Tracks
async function searchAllTracks(query) {
    allTracksContainer.innerHTML = '<div class="loading">Recherche...</div>';

    try {
        const response = await fetch(`${API_BASE}/tracks/search?q=${encodeURIComponent(query)}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const tracks = await response.json();
            displayAllTracks(tracks);
        } else {
            allTracksContainer.innerHTML = '<div class="error-message">Erreur lors de la recherche</div>';
        }
    } catch (error) {
        allTracksContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

async function loadAlbums() {
    albumsContainer.innerHTML = '<div class="loading">Chargement...</div>';

    try {
        const response = await fetch(`${API_BASE}/albums`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const albums = await response.json();
            displayAlbums(albums);
        } else {
            if (response.status === 401) {
                window.location.href = '/login';
            } else {
                albumsContainer.innerHTML = '<div class="error-message">Erreur lors du chargement</div>';
            }
        }
    } catch (error) {
        albumsContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

// Search Albums
async function searchAlbums(query) {
    albumsContainer.innerHTML = '<div class="loading">Recherche...</div>';

    try {
        const response = await fetch(`${API_BASE}/tracks/search?q=${encodeURIComponent(query)}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const tracks = await response.json();
            const albumsMap = new Map();
            tracks.forEach(track => {
                const key = `${track.artist || 'Unknown Artist'}|${track.album || 'Unknown Album'}|${track.year || ''}`;
                if (!albumsMap.has(key)) {
                    albumsMap.set(key, {
                        artist: track.artist || 'Unknown Artist',
                        album: track.album || 'Unknown Album',
                        year: track.year,
                        track_count: 0
                    });
                }
                albumsMap.get(key).track_count++;
            });
            const albums = Array.from(albumsMap.values());
            displayAlbums(albums);
        } else {
            albumsContainer.innerHTML = '<div class="error-message">Erreur lors de la recherche</div>';
        }
    } catch (error) {
        albumsContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

// Display Albums
function displayAlbums(albums) {
    if (albums.length === 0) {
        albumsContainer.innerHTML = '<div class="loading">Aucun album dans la bibliothèque</div>';
        return;
    }

    albumsContainer.innerHTML = '';
    albums.forEach(album => {
        const div = document.createElement('div');
        div.className = 'album-item';
        div.style.cursor = 'pointer';
        addEventListeners(div, (e) => {
            e.preventDefault();
            showAlbumDetail(album.artist, album.album);
        });
        div.innerHTML = `
            <div class="album-info">
                <div class="album-title">${escapeHtml(album.album)}</div>
                <div class="album-meta">
                    ${escapeHtml(album.artist)}
                    ${album.year ? ` • ${album.year}` : ''}
                    • ${album.track_count} ${album.track_count > 1 ? 'titres' : 'titre'}
                </div>
            </div>
            <div class="album-actions">
                <span class="album-arrow">→</span>
            </div>
        `;
        albumsContainer.appendChild(div);
    });
}

// Show Album Detail
async function showAlbumDetail(artist, album) {
    albumsView.style.display = 'none';
    albumDetailView.style.display = 'block';
    albumDetailTitle.textContent = `${escapeHtml(album)} - ${escapeHtml(artist)}`;
    albumTracksContainer.innerHTML = '<div class="loading">Chargement...</div>';

    try {
        const response = await fetch(`${API_BASE}/albums/${encodeURIComponent(artist)}/${encodeURIComponent(album)}/tracks`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const tracks = await response.json();
            displayAlbumTracks(tracks);
        } else {
            if (response.status === 404) {
                albumTracksContainer.innerHTML = '<div class="error-message">Album non trouvé</div>';
            } else {
                albumTracksContainer.innerHTML = '<div class="error-message">Erreur lors du chargement</div>';
            }
        }
    } catch (error) {
        albumTracksContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

// Display Album Tracks
function displayAlbumTracks(tracks) {
    if (tracks.length === 0) {
        albumTracksContainer.innerHTML = '<div class="loading">Aucune piste dans cet album</div>';
        return;
    }

    albumTracksContainer.innerHTML = '';
    tracks.forEach(track => {
        const div = document.createElement('div');
        div.className = 'track-item';
        div.innerHTML = `
            <div class="track-info">
                <div class="track-title">${escapeHtml(track.title)}</div>
                <div class="track-meta">
                    ${track.duration ? formatDuration(track.duration) : ''}
                </div>
            </div>
            <div class="track-actions">
                <button class="btn-icon" data-action="delete" data-track-id="${track.id}" title="Supprimer">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `;
        // Attach event listeners
        const deleteBtn = div.querySelector('[data-action="delete"]');
        if (deleteBtn) {
            addEventListeners(deleteBtn, (e) => {
                e.preventDefault();
                deleteTrack(track.id);
            });
        }
        albumTracksContainer.appendChild(div);
    });
}

// Show Albums View
function showAlbumsView() {
    albumDetailView.style.display = 'none';
    if (currentLibraryMode === 'albums') {
        albumsView.style.display = 'block';
    } else {
        allTracksView.style.display = 'block';
    }
}

// Load Downloads View
async function loadDownloads() {
    downloadsContainer.innerHTML = '<div class="loading">Chargement...</div>';

    try {
        const response = await fetch(`${API_BASE}/queue`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            displayDownloads(data.queue || []);
        } else {
            if (response.status === 401) {
                window.location.href = '/login';
            } else {
                downloadsContainer.innerHTML = '<div class="error-message">Erreur lors du chargement</div>';
            }
        }
    } catch (error) {
        downloadsContainer.innerHTML = `<div class="error-message">Erreur: ${error.message}</div>`;
    }
}

// Display Downloads
function displayDownloads(queue) {
    console.log('displayDownloads called with queue:', queue);
    if (queue.length === 0) {
        downloadsContainer.innerHTML = '<div class="loading">Aucun téléchargement en cours</div>';
        if (clearQueueBtn) {
            clearQueueBtn.style.display = 'none';
            console.log('Clear queue button hidden (empty queue)');
        }
        return;
    }

    // Show button if there are any items in the queue (regardless of status)
    // This allows clearing completed/failed items too
    if (clearQueueBtn) {
        clearQueueBtn.style.display = 'block';
        console.log('Clear queue button shown (queue has items)');
    }

    downloadsContainer.innerHTML = '';
    queue.forEach((item, index) => {
        const div = document.createElement('div');
        div.className = 'download-item';
        div.dataset.url = item.url;
        
        const statusClass = item.status === 'completed' ? 'completed' : 
                           item.status === 'failed' ? 'failed' : 
                           item.status === 'processing' ? 'processing' : 'downloading';
        
        const statusText = item.status === 'completed' ? 'Terminé' :
                          item.status === 'failed' ? 'Échec' :
                          item.status === 'processing' ? 'Traitement...' :
                          item.status === 'downloading' ? 'Téléchargement...' : 'En attente...';
        
        const progress = item.progress || 0;
        const message = item.message || '';
        
        // Try to extract title from URL or use a default
        let title = 'Téléchargement';
        if (item.title) {
            title = item.title;
        } else if (item.url) {
            // Try to extract from URL
            try {
                const urlObj = new URL(item.url);
                const videoId = urlObj.searchParams.get('v') || urlObj.pathname.split('/').pop();
                title = `Musique ${index + 1}`;
            } catch (e) {
                title = `Téléchargement ${index + 1}`;
            }
        }
        
        div.innerHTML = `
            <div class="download-info">
                <div class="download-title">${escapeHtml(title)}</div>
                <div class="download-meta">
                    <span class="download-status ${statusClass}">${statusText}</span>
                    ${message ? `<span class="download-message">${escapeHtml(message)}</span>` : ''}
                </div>
                ${(item.status === 'downloading' || item.status === 'processing') ? `
                    <div class="download-progress">
                        <div class="download-progress-fill" style="width: ${progress}%"></div>
                    </div>
                    <div class="download-progress-text">${progress}%</div>
                ` : ''}
            </div>
            <div class="download-actions">
                ${item.status !== 'completed' && item.status !== 'failed' ? `
                    <button class="btn-icon" data-action="cancel-download" data-url="${item.url}" title="Annuler">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="15" y1="9" x2="9" y2="15"></line>
                            <line x1="9" y1="9" x2="15" y2="15"></line>
                        </svg>
                    </button>
                ` : ''}
            </div>
        `;
        
        // Attach event listeners for cancel button
        const cancelBtn = div.querySelector('[data-action="cancel-download"]');
        if (cancelBtn) {
            addEventListeners(cancelBtn, (e) => {
                e.preventDefault();
                cancelDownload(item.url);
            });
        }
        
        downloadsContainer.appendChild(div);
    });
}

// Cancel Download
async function cancelDownload(url) {
    if (!confirm('Voulez-vous vraiment annuler ce téléchargement ?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/queue/remove?url=${encodeURIComponent(url)}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            showMessage('Téléchargement annulé', 'success');
            loadDownloads();
            // Also update the status map
            downloadStatuses.delete(url);
        } else {
            showMessage('Erreur lors de l\'annulation', 'error');
        }
    } catch (error) {
        showMessage(`Erreur: ${error.message}`, 'error');
    }
}

// Delete Track
async function deleteTrack(trackId) {
    if (!confirm('Voulez-vous vraiment supprimer cette musique ?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/tracks/${trackId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            if (albumDetailView.style.display !== 'none') {
                const title = albumDetailTitle.textContent;
                const parts = title.split(' - ');
                if (parts.length === 2) {
                    const album = parts[0];
                    const artist = parts[1];
                    showAlbumDetail(artist, album);
                }
            } else if (currentLibraryMode === 'tracks') {
                loadAllTracks();
            } else {
                loadAlbums();
            }
            showMessage('Musique supprimée', 'success');
        } else {
            showMessage('Erreur lors de la suppression', 'error');
        }
    } catch (error) {
        showMessage(`Erreur: ${error.message}`, 'error');
    }
}

// Utility Functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function showMessage(message, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = message;
    messageDiv.style.position = 'fixed';
    messageDiv.style.top = '20px';
    messageDiv.style.right = '20px';
    messageDiv.style.zIndex = '1000';
    messageDiv.style.minWidth = '300px';
    document.body.appendChild(messageDiv);

    setTimeout(() => {
        messageDiv.remove();
    }, 3000);
}

// Clear Queue Button
if (clearQueueBtn) {
    console.log('Clear queue button found, attaching event listener');
    addEventListeners(clearQueueBtn, async (e) => {
        e.preventDefault();
        e.stopPropagation();
        console.log('Clear queue button clicked');
        if (!confirm('Voulez-vous vraiment vider toute la queue de téléchargement ?')) {
            return;
        }
        
        try {
            console.log('Clear queue button clicked');
            const response = await fetch(`${API_BASE}/queue/clear`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });

            console.log('Clear queue response:', response.status, response.statusText);
            const data = await response.json();
            console.log('Clear queue data:', data);

            if (response.ok) {
                showMessage('Queue vidée', 'success');
                downloadStatuses.clear();
                loadDownloads();
            } else {
                showMessage(`Erreur lors du vidage: ${data.detail || 'Erreur inconnue'}`, 'error');
            }
        } catch (error) {
            console.error('Clear queue error:', error);
            showMessage(`Erreur: ${error.message}`, 'error');
        }
    });
} else {
    console.warn('Clear queue button not found in DOM');
}

// Make functions available globally (for backward compatibility with onclick)
window.downloadNow = downloadNow;
window.addAllToQueue = addAllToQueue;
window.addAllToQueueFromSearch = addAllToQueueFromSearch;
window.deleteTrack = deleteTrack;

// Detect touch device
const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

// Event delegation for dynamically created buttons (backup - works on all devices)
let lastActionTime = 0;

// Touch events for mobile
if (isTouchDevice) {
    document.addEventListener('touchend', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        
        const now = Date.now();
        if (now - lastActionTime < 300) return;
        lastActionTime = now;
        
        e.preventDefault();
        e.stopPropagation();
        
        const action = target.dataset.action;
        const url = target.dataset.url;
        const trackId = target.dataset.trackId;
        const urls = target.dataset.urls;
        
        if (action === 'download' && url) {
            downloadNow(url);
        } else if (action === 'delete' && trackId) {
            deleteTrack(parseInt(trackId));
        } else if (action === 'add-all-queue') {
            addAllToQueue();
        } else if (action === 'add-all-search' && urls) {
            try {
                const urlArray = JSON.parse(urls);
                addAllToQueueFromSearch(urlArray);
            } catch (err) {
                console.error('Error parsing URLs:', err);
            }
        }
    }, { passive: false, capture: true });
}

// Click events for desktop and fallback
document.addEventListener('click', (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    
    // On touch devices, ignore click if it happens too soon (to prevent double-firing)
    if (isTouchDevice) {
        const timeSinceTouch = Date.now() - (target._lastTouchTime || 0);
        if (timeSinceTouch < 500) {
            e.preventDefault();
            return;
        }
    }
    
    const action = target.dataset.action;
    const url = target.dataset.url;
    const trackId = target.dataset.trackId;
    const urls = target.dataset.urls;
    
    if (action === 'download' && url) {
        e.preventDefault();
        downloadNow(url);
    } else if (action === 'delete' && trackId) {
        e.preventDefault();
        deleteTrack(parseInt(trackId));
    } else if (action === 'add-all-queue') {
        e.preventDefault();
        addAllToQueue();
    } else if (action === 'add-all-search' && urls) {
        e.preventDefault();
        try {
            const urlArray = JSON.parse(urls);
            addAllToQueueFromSearch(urlArray);
        } catch (err) {
            console.error('Error parsing URLs:', err);
        }
    }
}, true);
