# Music Server - Gestionnaire de musique pour Plex

Serveur de gestion de musique compatible avec Plex qui permet de télécharger, organiser et gérer une bibliothèque musicale.

## Fonctionnalités

- 📥 **Téléchargement** : Support YouTube et YouTube Music
- 🎵 **Format FLAC** : Téléchargement en qualité maximale
- 📁 **Organisation automatique** : Structure compatible Plex (`Artiste/Album (Année)/Titre.flac`)
- 🏷️ **Métadonnées** : Extraction et normalisation automatique des tags audio
- 🔍 **Recherche** : API REST pour rechercher dans la bibliothèque
- 📊 **Base de données** : Suivi de tous les morceaux téléchargés

## Prérequis

- Python 3.9+
- ffmpeg (requis pour la conversion audio)
- yt-dlp (pour YouTube)
- spotdl (pour Spotify)

### Installation des outils de téléchargement

```bash
# Installer yt-dlp
pip install yt-dlp

# Installer ffmpeg (macOS)
brew install ffmpeg

# Installer ffmpeg (Ubuntu/Debian)
sudo apt-get install ffmpeg
```

## Installation

1. **Cloner le dépôt** (ou créer le projet)

2. **Installer les dépendances Python** :
```bash
pip install -r requirements.txt
```

3. **Configurer l'environnement** :
```bash
cp .env.example .env
# Éditer .env selon vos besoins
```

4. **Initialiser la base de données** :
La base de données sera créée automatiquement au premier lancement.

## Utilisation

### Démarrer le serveur (développement local)

```bash
python -m app.main
```

Ou avec uvicorn directement :
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Le serveur sera accessible sur `http://localhost:8000`

### Déploiement sur serveur (Kali Linux / Production)

Pour déployer le serveur sur un PC Kali Linux et le rendre accessible depuis l'extérieur, consultez le guide complet : **[DEPLOY.md](DEPLOY.md)**

**Démarrage rapide :**

```bash
# 1. Configurer l'environnement
cp .env.example .env
nano .env  # Modifier API_HOST=0.0.0.0

# 2. Démarrer en mode production
chmod +x start_server.sh
./start_server.sh production

# 3. Configurer le firewall
sudo ufw allow 8000/tcp
```

Le serveur sera accessible sur `http://<IP-DU-SERVEUR>:8000` depuis n'importe quel appareil sur le réseau.

### Documentation API

Une fois le serveur démarré, accédez à la documentation interactive :
- Swagger UI : `http://localhost:8000/docs`
- ReDoc : `http://localhost:8000/redoc`

### Exemples d'utilisation

#### Télécharger depuis YouTube

```bash
curl -X POST "http://localhost:8000/api/download" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID"}'
```

#### Télécharger depuis YouTube Music

```bash
curl -X POST "http://localhost:8000/api/download" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://music.youtube.com/watch?v=VIDEO_ID"}'
```

#### Lister tous les morceaux

```bash
curl "http://localhost:8000/api/tracks"
```

#### Rechercher

```bash
curl "http://localhost:8000/api/search?q=artiste"
```

## Structure des fichiers

Les fichiers sont organisés automatiquement dans la structure Plex :

```
music/
├── Artiste/
│   ├── Album (2023)/
│   │   ├── 01 - Titre.flac
│   │   ├── 02 - Titre.flac
│   │   └── cover.jpg
```

## Configuration Plex

1. Dans Plex Media Server, ajoutez une bibliothèque musicale
2. Pointez vers le dossier `music/` de ce projet
3. Plex détectera automatiquement les fichiers organisés

## API Endpoints

- `POST /api/download` - Télécharger de la musique
- `GET /api/tracks` - Lister tous les morceaux
- `GET /api/tracks/{id}` - Détails d'un morceau
- `DELETE /api/tracks/{id}` - Supprimer un morceau
- `GET /api/search` - Rechercher dans la bibliothèque
- `GET /api/stats` - Statistiques de la bibliothèque

## Configuration

Les paramètres peuvent être configurés via :
- Variables d'environnement (`.env`)
- Fichier de configuration (`config/config.yaml`)
- Paramètres par défaut dans `app/config.py`

## Développement

### Structure du projet

```
music-server/
├── app/
│   ├── main.py              # Application FastAPI
│   ├── config.py            # Configuration
│   ├── models/              # Modèles de données
│   ├── services/            # Services métier
│   ├── api/                 # Routes API
│   └── database/            # Configuration DB
├── music/                   # Bibliothèque musique
├── downloads/               # Téléchargements temporaires
└── config/                  # Fichiers de configuration
```

## Licence

MIT

