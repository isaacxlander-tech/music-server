// API Base URL
const API_BASE = '/api';

// State
let authToken = localStorage.getItem('authToken') || null;
let currentUser = null;
let currentResults = null;
let queueInterval = null;

// DOM Elements
const logoutBtn = document.getElementById('logout-btn');
const searchForm = document.getElementById('search-form');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const resultsTitle = document.getElementById('results-title');
const resultsActions = document.getElementById('results-actions');
const queueContainer = document.getElementById('queue-container');
const clearQueueBtn = document.getElementById('clear-queue-btn');
const queueStatus = document.getElementById('queue-status');
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
    loadAlbums();
    loadQueue();
    
    // Initialize search filters
    initSearchFilters();
    
    // Refresh queue every 2 seconds
    queueInterval = setInterval(loadQueue, 2000);
});

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
logoutBtn.addEventListener('click', logout);

// Search Mode Toggle
let currentSearchMode = 'url';
const urlModeBtn = document.getElementById('url-mode-btn');
const searchModeBtn = document.getElementById('search-mode-btn');
const urlForm = document.getElementById('url-search-form');
const textForm = document.getElementById('text-search-form');

urlModeBtn.addEventListener('click', () => {
    switchSearchMode('url');
});

searchModeBtn.addEventListener('click', () => {
    switchSearchMode('search');
});

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
        // Show filters
        document.getElementById('search-type-filters').style.display = 'flex';
        await searchByTextProgressive(query);
    }
});

// Initialize Search Type Filters (after DOM is loaded)
function initSearchFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (searchInProgress) return;
            
            // Update active filter
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSearchType = btn.dataset.type;
            
            // If we're viewing an artist, reload content
            const currentTitle = resultsTitle.textContent;
            if (currentTitle.includes(' - ')) {
                const artistName = currentTitle.split(' - ')[0].replace('🎵 ', '').trim();
                await loadArtistContent(artistName, currentSearchType);
            }
        });
    });
}

clearQueueBtn.addEventListener('click', async () => {
    if (confirm('Voulez-vous vraiment vider la file d\'attente ?')) {
        await clearQueue();
    }
});

librarySearchBtn.addEventListener('click', () => {
    const query = librarySearchInput.value.trim();
    if (query) {
        searchAlbums(query);
    } else {
        loadAlbums();
    }
});

librarySearchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        librarySearchBtn.click();
    }
});

// Back to albums button
backToAlbumsBtn.addEventListener('click', () => {
    showAlbumsView();
    loadAlbums();
});

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
            messageDiv.textContent = `❌ ${data.detail || 'Erreur lors de la recherche'}`;
            messageDiv.style.display = 'block';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = `❌ Erreur: ${error.message}`;
        messageDiv.style.display = 'block';
    } finally {
        searchBtn.disabled = false;
        btnText.style.display = 'inline';
        btnLoader.style.display = 'none';
    }
}

// Search by Text - Quick search (artists first)
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
    
    // Show results section
    resultsSection.style.display = 'block';
    resultsTitle.textContent = `🔍 Résultats pour "${escapeHtml(query)}"`;
    resultsContainer.innerHTML = '<div class="search-results-loading">Recherche rapide en cours...</div>';
    
    try {
        // Quick search - get artists first
        const response = await fetch(`${API_BASE}/search/text/quick`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ query, limit: 20 })
        });

        const data = await response.json();

        if (response.ok && data.success && data.type === 'artists') {
            // Display artists
            displayArtists(data.artists, query);
        } else {
            messageDiv.className = 'message error';
            messageDiv.textContent = `❌ ${data.detail || 'Erreur lors de la recherche'}`;
            messageDiv.style.display = 'block';
        }
    } catch (error) {
        messageDiv.className = 'message error';
        messageDiv.textContent = `❌ Erreur: ${error.message}`;
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
        artistCard.onclick = () => showArtistContent(artist.name);
        artistCard.innerHTML = `
            <div class="artist-result-thumbnail">
                ${artist.thumbnail ? `<img src="${artist.thumbnail}" alt="${escapeHtml(artist.name)}">` : '<div class="artist-placeholder">🎵</div>'}
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
    const messageDiv = document.getElementById('search-message');
    resultsContainer.innerHTML = '<div class="search-results-loading">Chargement du contenu...</div>';
    
    // Show filter buttons
    document.getElementById('search-type-filters').style.display = 'flex';
    
    // Load content based on current filter
    await loadArtistContent(artistName, currentSearchType);
}

// Load Artist Content
async function loadArtistContent(artistName, contentType) {
    try {
        const response = await fetch(`${API_BASE}/search/artist`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ artist: artistName, type: contentType, limit: 30 })
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
    resultsTitle.textContent = `🎵 ${escapeHtml(artistName)} - ${contentType === 'songs' ? 'Songs' : contentType === 'albums' ? 'Albums' : 'Playlists'}`;
    
    if (tracks.length === 0) {
        resultsContainer.innerHTML = '<div class="search-results-loading">Aucun contenu trouvé</div>';
        return;
    }
    
    // Display as grid for all content types (songs, albums, playlists)
    const tracksGrid = document.createElement('div');
    tracksGrid.className = 'search-tracks-grid';
    
    tracks.forEach((track, index) => {
        const trackCard = createSongCard(track, index + 1);
        tracksGrid.appendChild(trackCard);
    });
    
    resultsContainer.appendChild(tracksGrid);
}

// Display search results by type
function displaySearchResultsByType(type, data) {
    const section = document.getElementById(`${type}-results`);
    if (!section) return;
    
    const loadingDiv = section.querySelector('.search-results-loading');
    if (loadingDiv) {
        loadingDiv.remove();
    }
    
    if (data.tracks && data.tracks.length > 0) {
        // Group tracks by artist for songs
        if (type === 'songs') {
            const tracksByArtist = {};
            data.tracks.forEach(track => {
                const artist = track.artist || 'Unknown Artist';
                if (!tracksByArtist[artist]) {
                    tracksByArtist[artist] = [];
                }
                tracksByArtist[artist].push(track);
            });
            
            Object.keys(tracksByArtist).forEach(artist => {
                const tracks = tracksByArtist[artist];
                const firstTrack = tracks[0];
                
                // Artist card
                const artistCard = document.createElement('div');
                artistCard.className = 'search-artist-card';
                artistCard.innerHTML = `
                    <div class="search-artist-thumbnail">
                        ${firstTrack.thumbnail ? `<img src="${firstTrack.thumbnail}" alt="${escapeHtml(artist)}">` : '<div class="artist-placeholder">🎵</div>'}
                    </div>
                    <div class="search-artist-info">
                        <div class="search-artist-name">${escapeHtml(artist)}</div>
                        <div class="search-artist-meta">Artiste • ${tracks.length} ${tracks.length > 1 ? 'titres' : 'titre'}</div>
                    </div>
                    <div class="search-artist-actions">
                        <button class="btn btn-secondary" onclick="addAllToQueueFromSearch(['${tracks.map(t => t.url).join("','")}'])">➕ Ajouter tout</button>
                    </div>
                `;
                section.appendChild(artistCard);
                
                // Tracks grid
                const tracksGrid = document.createElement('div');
                tracksGrid.className = 'search-tracks-grid';
                tracksGrid.innerHTML = `<div class="search-section-title">Les essentiels</div>`;
                
                tracks.forEach((track, index) => {
                    const trackCard = createSongCard(track, index + 1);
                    tracksGrid.appendChild(trackCard);
                });
                
                section.appendChild(tracksGrid);
            });
        } else {
            // For albums and playlists, display as grid too
            const tracksGrid = document.createElement('div');
            tracksGrid.className = 'search-tracks-grid';
            
            data.tracks.forEach((track, index) => {
                const trackCard = createSongCard(track, index + 1);
                tracksGrid.appendChild(trackCard);
            });
            
            section.appendChild(tracksGrid);
        }
    } else {
        section.innerHTML += '<div class="search-results-loading">Aucun résultat</div>';
    }
}

// Update visibility of search sections based on active filter
function updateSearchSectionsVisibility() {
    const songsSection = document.getElementById('songs-results');
    const albumsSection = document.getElementById('albums-results');
    const playlistsSection = document.getElementById('playlists-results');
    
    // Hide all
    if (songsSection) songsSection.style.display = 'none';
    if (albumsSection) albumsSection.style.display = 'none';
    if (playlistsSection) playlistsSection.style.display = 'none';
    
    // Show active one
    if (currentSearchType === 'songs' && songsSection) {
        songsSection.style.display = 'block';
    } else if (currentSearchType === 'albums' && albumsSection) {
        albumsSection.style.display = 'block';
    } else if (currentSearchType === 'playlists' && playlistsSection) {
        playlistsSection.style.display = 'block';
    }
}

// Display Results
function displayResults(data) {
    resultsContainer.innerHTML = '';
    resultsActions.innerHTML = '';

    if (data.type === 'playlist') {
        // Display playlist header
        const header = document.createElement('div');
        header.className = 'playlist-header';
        
        const thumbnail = data.playlist_info.thumbnail 
            ? `<img src="${data.playlist_info.thumbnail}" alt="Album" class="playlist-thumbnail">`
            : '<div class="playlist-thumbnail" style="background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 3em;">🎵</div>';
        
        header.innerHTML = `
            ${thumbnail}
            <div class="playlist-info">
                <div class="playlist-title">${escapeHtml(data.playlist_info.title)}</div>
                <div class="playlist-artist">${escapeHtml(data.playlist_info.uploader)}</div>
                <div class="playlist-meta">${data.count} musiques</div>
                <div class="playlist-actions">
                    <button class="btn btn-primary" onclick="addAllToQueue()">➕ Ajouter tout à la queue</button>
                </div>
            </div>
        `;
        resultsContainer.appendChild(header);

        // Display tracks
        data.tracks.forEach((track, index) => {
            const trackDiv = createTrackResult(track, index + 1);
            resultsContainer.appendChild(trackDiv);
        });

        resultsTitle.textContent = `📀 Album: ${escapeHtml(data.playlist_info.title)}`;
    } else if (data.type === 'search_results') {
        // Search results - Display like YouTube Music
        resultsTitle.textContent = `🔍 Résultats pour "${escapeHtml(data.query)}"`;
        
        // Group tracks by artist if possible
        const tracksByArtist = {};
        data.tracks.forEach(track => {
            const artist = track.artist || 'Unknown Artist';
            if (!tracksByArtist[artist]) {
                tracksByArtist[artist] = [];
            }
            tracksByArtist[artist].push(track);
        });
        
        // Display each artist section
        Object.keys(tracksByArtist).forEach(artist => {
            const artistSection = document.createElement('div');
            artistSection.className = 'search-artist-section';
            
            const tracks = tracksByArtist[artist];
            const firstTrack = tracks[0];
            
            // Artist header card
            const artistCard = document.createElement('div');
            artistCard.className = 'search-artist-card';
            artistCard.innerHTML = `
                <div class="search-artist-thumbnail">
                    ${firstTrack.thumbnail ? `<img src="${firstTrack.thumbnail}" alt="${escapeHtml(artist)}">` : '<div class="artist-placeholder">🎵</div>'}
                </div>
                <div class="search-artist-info">
                    <div class="search-artist-name">${escapeHtml(artist)}</div>
                    <div class="search-artist-meta">Artiste • ${tracks.length} ${tracks.length > 1 ? 'titres' : 'titre'}</div>
                </div>
                <div class="search-artist-actions">
                    <button class="btn btn-secondary" onclick="addAllToQueueFromSearch(['${tracks.map(t => t.url).join("','")}'])">➕ Ajouter tout</button>
                </div>
            `;
            artistSection.appendChild(artistCard);
            
            // Tracks list
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
        // Single track
        const trackDiv = createTrackResult(data.track, null);
        resultsContainer.appendChild(trackDiv);
        resultsTitle.textContent = '🎵 Musique';
    }
}

// Create Track Result Element
function createTrackResult(track, trackNumber) {
    const div = document.createElement('div');
    div.className = 'track-result';
    
    const thumbnail = track.thumbnail 
        ? `<img src="${track.thumbnail}" alt="${escapeHtml(track.title)}" class="track-result-thumbnail">`
        : '<div class="track-result-thumbnail" style="background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 2em;">🎵</div>';
    
    const duration = track.duration ? formatDuration(track.duration) : '';
    
    div.innerHTML = `
        ${thumbnail}
        <div class="track-result-info">
            ${trackNumber ? `<div style="color: var(--text-secondary); font-size: 0.85em; margin-bottom: 4px;">#${trackNumber}</div>` : ''}
            <div class="track-result-title">${escapeHtml(track.title)}</div>
            ${track.artist ? `<div class="track-result-artist">${escapeHtml(track.artist)}</div>` : ''}
            ${duration ? `<div class="track-result-duration">⏱️ ${duration}</div>` : ''}
        </div>
        <div class="track-result-actions">
            <button class="song-card-icon-btn" onclick="addToQueue('${track.url}')" title="Ajouter à la queue">
                <span class="icon">➕</span>
            </button>
            <button class="song-card-icon-btn primary" onclick="downloadNow('${track.url}')" title="Télécharger">
                <span class="icon">⬇️</span>
            </button>
        </div>
    `;
    
    return div;
}

// Create Song Card Element (for grid view)
function createSongCard(track, trackNumber) {
    const div = document.createElement('div');
    div.className = 'song-card';
    
    const thumbnail = track.thumbnail 
        ? `<img src="${track.thumbnail}" alt="${escapeHtml(track.title)}" class="song-card-thumbnail">`
        : '<div class="song-card-thumbnail" style="background: var(--border-color); display: flex; align-items: center; justify-content: center; font-size: 3em;">🎵</div>';
    
    const duration = track.duration ? formatDuration(track.duration) : '';
    
    div.innerHTML = `
        <div class="song-card-image-wrapper">
            ${thumbnail}
            <div class="song-card-overlay">
                <button class="song-card-icon-btn" onclick="addToQueue('${track.url}')" title="Ajouter à la queue">
                    <span class="icon">➕</span>
                </button>
                <button class="song-card-icon-btn primary" onclick="downloadNow('${track.url}')" title="Télécharger">
                    <span class="icon">⬇️</span>
                </button>
            </div>
        </div>
        <div class="song-card-info">
            <div class="song-card-title" title="${escapeHtml(track.title)}">${escapeHtml(track.title)}</div>
            ${track.artist ? `<div class="song-card-artist">${escapeHtml(track.artist)}</div>` : ''}
            ${duration ? `<div class="song-card-duration">⏱️ ${duration}</div>` : ''}
        </div>
    `;
    
    return div;
}

// Add to Queue
async function addToQueue(url) {
    try {
        const response = await fetch(`${API_BASE}/queue/add`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ url })
        });

        const data = await response.json();
        if (response.ok) {
            showMessage('✅ Ajouté à la queue', 'success');
            loadQueue();
        } else {
            showMessage(`❌ ${data.detail || 'Erreur'}`, 'error');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
    }
}

// Add All to Queue
async function addAllToQueue() {
    if (!currentResults || currentResults.type !== 'playlist') return;
    
    const urls = currentResults.tracks.map(t => t.url);
    
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
            showMessage(`✅ ${urls.length} musiques ajoutées à la queue`, 'success');
            loadQueue();
        } else {
            showMessage(`❌ ${data.detail || 'Erreur'}`, 'error');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
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
            showMessage(`✅ ${urls.length} musiques ajoutées à la queue`, 'success');
            loadQueue();
        } else {
            showMessage(`❌ ${data.detail || 'Erreur'}`, 'error');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
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
            showMessage(`✅ ${urls.length} musiques ajoutées à la queue`, 'success');
            loadQueue();
        } else {
            showMessage(`❌ ${data.detail || 'Erreur'}`, 'error');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
    }
}

// Download Now (add to queue but with priority - for now just add to queue)
async function downloadNow(url) {
    await addToQueue(url);
    showMessage('✅ Ajouté à la queue (téléchargement en cours...)', 'success');
}

// Load Queue
async function loadQueue() {
    try {
        const response = await fetch(`${API_BASE}/queue`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            displayQueue(data.queue, data.status);
        }
    } catch (error) {
        console.error('Failed to load queue:', error);
    }
}

// Display Queue
function displayQueue(queue, status) {
    if (queue.length === 0) {
        queueContainer.innerHTML = '<div class="loading">Aucun téléchargement en attente</div>';
        queueStatus.textContent = '';
        return;
    }

    queueStatus.textContent = `${status.pending} en attente • ${status.processing} en cours • ${status.completed} terminé${status.failed > 0 ? ` • ${status.failed} échoué` : ''}`;

    queueContainer.innerHTML = '';
    queue.forEach(item => {
        const div = document.createElement('div');
        div.className = 'queue-item';
        
        const statusClass = item.status;
        const statusIcon = {
            'pending': '⏳',
            'processing': '⏳',
            'completed': '✅',
            'failed': '❌'
        }[item.status] || '⏳';
        
        div.innerHTML = `
            <div class="queue-item-status ${statusClass}"></div>
            <div class="queue-item-info">
                <div style="font-weight: 500; margin-bottom: 4px;">${statusIcon} ${item.status === 'processing' ? 'Téléchargement...' : item.status === 'completed' ? 'Terminé' : item.status === 'failed' ? 'Échoué' : 'En attente'}</div>
                <div class="queue-item-url">${escapeHtml(item.url)}</div>
                ${item.error ? `<div style="color: var(--error-color); font-size: 0.85em; margin-top: 4px;">${escapeHtml(item.error)}</div>` : ''}
            </div>
            ${item.status === 'pending' ? `<button class="btn btn-secondary btn-small" onclick="removeFromQueue('${item.url}')">🗑️</button>` : ''}
        `;
        queueContainer.appendChild(div);
    });
}

// Remove from Queue
async function removeFromQueue(url) {
    try {
        const response = await fetch(`${API_BASE}/queue/remove?url=${encodeURIComponent(url)}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            loadQueue();
        }
    } catch (error) {
        console.error('Failed to remove from queue:', error);
    }
}

// Clear Queue
async function clearQueue() {
    try {
        const response = await fetch(`${API_BASE}/queue/clear`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            loadQueue();
            showMessage('✅ Queue vidée', 'success');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
    }
}

// Load Albums
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
        // Search tracks first, then group by album
        const response = await fetch(`${API_BASE}/tracks/search?q=${encodeURIComponent(query)}`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });

        if (response.ok) {
            const tracks = await response.json();
            // Group tracks by album
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
        div.onclick = () => showAlbumDetail(album.artist, album.album);
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
                <button class="btn-icon" onclick="deleteTrack(${track.id})" title="Supprimer">🗑️</button>
            </div>
        `;
        albumTracksContainer.appendChild(div);
    });
}

// Show Albums View
function showAlbumsView() {
    albumsView.style.display = 'block';
    albumDetailView.style.display = 'none';
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
            // If we're in album detail view, reload tracks, otherwise reload albums
            if (albumDetailView.style.display !== 'none') {
                const title = albumDetailTitle.textContent;
                const parts = title.split(' - ');
                if (parts.length === 2) {
                    const album = parts[0];
                    const artist = parts[1];
                    showAlbumDetail(artist, album);
                }
            } else {
                loadAlbums();
            }
            showMessage('✅ Musique supprimée', 'success');
        } else {
            showMessage('❌ Erreur lors de la suppression', 'error');
        }
    } catch (error) {
        showMessage(`❌ Erreur: ${error.message}`, 'error');
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
    // Create temporary message
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

// Make functions available globally for onclick handlers
window.addToQueue = addToQueue;
window.addAllToQueue = addAllToQueue;
window.addAllToQueueFromSearch = addAllToQueueFromSearch;
window.downloadNow = downloadNow;
window.removeFromQueue = removeFromQueue;
window.deleteTrack = deleteTrack;
