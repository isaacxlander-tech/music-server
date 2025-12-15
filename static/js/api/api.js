// API Base URL
export const API_BASE = '/api';

// Auth token management
export function getAuthToken() {
    return localStorage.getItem('authToken') || null;
}

export function setAuthToken(token) {
    if (token) {
        localStorage.setItem('authToken', token);
    } else {
        localStorage.removeItem('authToken');
    }
}

// API Request helper
export async function apiRequest(endpoint, options = {}) {
    const token = getAuthToken();
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers
    });
    
    if (response.status === 401) {
        setAuthToken(null);
        window.location.href = '/login';
        return null;
    }
    
    return response;
}
