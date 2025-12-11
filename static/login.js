// API Base URL
const API_BASE = '/api';

// DOM Elements
const loginForm = document.getElementById('login-form');
const errorDiv = document.getElementById('login-error');

// Check if already logged in
document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('authToken');
    if (token) {
        // Verify token is still valid
        checkAuthAndRedirect(token);
    }
});

// Login function
async function login(username, password) {
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();

        if (response.ok && data.access_token) {
            // Store token
            localStorage.setItem('authToken', data.access_token);
            
            // Redirect to app page
            window.location.href = '/app';
            return true;
        } else {
            const errorMsg = data.detail || 'Erreur de connexion';
            showError(errorMsg);
            return false;
        }
    } catch (error) {
        showError(`Erreur de connexion: ${error.message}`);
        return false;
    }
}

// Check auth and redirect if valid
async function checkAuthAndRedirect(token) {
    try {
        const response = await fetch(`${API_BASE}/auth/me`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            // Token is valid, redirect to app
            window.location.href = '/app';
        } else {
            // Token invalid, clear it
            localStorage.removeItem('authToken');
        }
    } catch (error) {
        localStorage.removeItem('authToken');
    }
}

// Show error message
function showError(message) {
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
}

// Event listener
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    await login(username, password);
});

