#!/bin/bash
# Script de démarrage du serveur Music Server
# Usage: ./start_server.sh [production|development]

MODE=${1:-production}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activer l'environnement virtuel si présent
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Vérifier que Python 3 est installé
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 n'est pas installé"
    exit 1
fi

# Vérifier que les dépendances sont installées
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "⚠️  Les dépendances ne sont pas installées"
    echo "Installation des dépendances..."
    pip3 install -r requirements.txt
fi

# Vérifier que yt-dlp est installé
if ! command -v yt-dlp &> /dev/null; then
    echo "⚠️  yt-dlp n'est pas installé"
    echo "Installation de yt-dlp..."
    pip3 install yt-dlp
fi

# Vérifier que ffmpeg est installé
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  ffmpeg n'est pas installé"
    echo "Installation de ffmpeg..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
    elif command -v yum &> /dev/null; then
        sudo yum install -y ffmpeg
    elif command -v pacman &> /dev/null; then
        sudo pacman -S ffmpeg
    else
        echo "❌ Veuillez installer ffmpeg manuellement"
        exit 1
    fi
fi

# Charger les variables d'environnement
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Déterminer le mode d'exécution
if [ "$MODE" = "production" ]; then
    echo "🚀 Démarrage du serveur en mode PRODUCTION"
    echo "📡 Le serveur sera accessible sur http://0.0.0.0:${API_PORT:-8000}"
    echo "⚠️  Assurez-vous que le firewall est configuré correctement"
    echo ""
    
    # Démarrer avec uvicorn en mode production (sans reload)
    python3 -m uvicorn app.main:app \
        --host "${API_HOST:-0.0.0.0}" \
        --port "${API_PORT:-8000}" \
        --workers 4 \
        --log-level info
else
    echo "🔧 Démarrage du serveur en mode DEVELOPMENT"
    echo "📡 Le serveur sera accessible sur http://localhost:${API_PORT:-8000}"
    echo ""
    
    # Démarrer avec uvicorn en mode développement (avec reload)
    python3 -m uvicorn app.main:app \
        --host "${API_HOST:-127.0.0.1}" \
        --port "${API_PORT:-8000}" \
        --reload \
        --log-level debug
fi

