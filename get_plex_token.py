#!/usr/bin/env python3
"""
Script pour obtenir le token Plex via l'API
"""
import requests
import sys
import getpass
import xml.etree.ElementTree as ET

def get_plex_token(username: str, password: str) -> str:
    """
    Obtenir le token Plex via l'API
    
    Args:
        username: Nom d'utilisateur Plex
        password: Mot de passe Plex
    
    Returns:
        Le token Plex
    """
    url = "https://plex.tv/users/sign_in.xml"
    
    headers = {
        "X-Plex-Client-Identifier": "music-server",
        "X-Plex-Product": "Music Server",
        "X-Plex-Version": "1.0"
    }
    
    try:
        response = requests.post(
            url,
            headers=headers,
            auth=(username, password),
            timeout=10
        )
        
        if response.status_code == 201:
            # Parser la réponse XML
            root = ET.fromstring(response.text)
            token = root.get("authenticationToken")
            if token:
                return token
            else:
                print("❌ Token non trouvé dans la réponse")
                return None
        else:
            print(f"❌ Erreur HTTP {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return None


def main():
    print("🔑 Obtenir votre token Plex")
    print("=" * 50)
    print()
    
    # Demander les identifiants
    username = input("Nom d'utilisateur Plex: ").strip()
    if not username:
        print("❌ Le nom d'utilisateur est requis")
        sys.exit(1)
    
    password = getpass.getpass("Mot de passe Plex: ")
    if not password:
        print("❌ Le mot de passe est requis")
        sys.exit(1)
    
    print()
    print("⏳ Connexion à Plex...")
    
    token = get_plex_token(username, password)
    
    if token:
        print()
        print("✅ Token obtenu avec succès!")
        print("=" * 50)
        print(f"Token: {token}")
        print()
        print("📝 Ajoutez ceci à votre fichier .env:")
        print(f"PLEX_TOKEN={token}")
        print()
        print("💡 Ou exécutez cette commande pour créer/mettre à jour le fichier .env:")
        print(f'echo "PLEX_TOKEN={token}" >> .env')
    else:
        print()
        print("❌ Impossible d'obtenir le token")
        print()
        print("💡 Méthodes alternatives:")
        print("   1. Via le navigateur: https://www.plex.tv/claim")
        print("   2. Via les outils de développement du navigateur (F12)")
        sys.exit(1)


if __name__ == "__main__":
    main()

