// Commandes JavaScript à exécuter dans la console du navigateur (F12)
// Sur https://app.plex.tv après connexion

// Méthode 1: Depuis localStorage (le plus simple)
console.log("🔑 Méthode 1 - Depuis localStorage:");
const token1 = localStorage.getItem('token') || localStorage.getItem('plexToken') || localStorage.getItem('authToken');
if (token1) {
    console.log("✅ Token trouvé:", token1);
    console.log("📋 Copiez cette ligne:");
    console.log(`PLEX_TOKEN=${token1}`);
} else {
    console.log("❌ Token non trouvé dans localStorage");
}

// Méthode 2: Depuis les cookies
console.log("\n🔑 Méthode 2 - Depuis les cookies:");
const cookies = document.cookie.split(';');
const tokenCookie = cookies.find(c => c.includes('token') || c.includes('Token'));
if (tokenCookie) {
    const token2 = tokenCookie.split('=')[1]?.trim();
    console.log("✅ Token trouvé:", token2);
    console.log("📋 Copiez cette ligne:");
    console.log(`PLEX_TOKEN=${token2}`);
} else {
    console.log("❌ Token non trouvé dans les cookies");
}

// Méthode 3: Depuis window.Plex
console.log("\n🔑 Méthode 3 - Depuis window.Plex:");
if (window.Plex && window.Plex.authToken) {
    console.log("✅ Token trouvé:", window.Plex.authToken);
    console.log("📋 Copiez cette ligne:");
    console.log(`PLEX_TOKEN=${window.Plex.authToken}`);
} else {
    console.log("❌ window.Plex.authToken non disponible");
}

// Méthode 4: Chercher dans tous les objets window
console.log("\n🔑 Méthode 4 - Recherche dans window:");
let found = false;
for (let key in window) {
    try {
        if (typeof window[key] === 'object' && window[key] !== null) {
            if (window[key].token || window[key].authToken || window[key].plexToken) {
                const token = window[key].token || window[key].authToken || window[key].plexToken;
                if (token && token.length > 20) {
                    console.log(`✅ Token trouvé dans window.${key}:`, token);
                    console.log("📋 Copiez cette ligne:");
                    console.log(`PLEX_TOKEN=${token}`);
                    found = true;
                    break;
                }
            }
        }
    } catch(e) {}
}
if (!found) {
    console.log("❌ Token non trouvé dans window");
}

// Méthode 5: Depuis les requêtes réseau (nécessite d'ouvrir l'onglet Network)
console.log("\n💡 Méthode 5 - Depuis l'onglet Network:");
console.log("1. Ouvrez l'onglet 'Network' (Réseau) dans les outils de développement");
console.log("2. Rechargez la page (F5)");
console.log("3. Cliquez sur une requête vers 'plex.tv'");
console.log("4. Allez dans l'onglet 'Headers'");
console.log("5. Cherchez 'X-Plex-Token' dans 'Request Headers'");

