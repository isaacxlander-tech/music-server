# Commandes utiles pour Music Home

## Nettoyage et organisation

### 1. Nettoyer les artistes en double
```bash
cd /opt/music-home
source venv/bin/activate
python -m app.services.artist_cleanup

# Mode simulation (sans modification)
python -m app.services.artist_cleanup --dry-run
```

### 2. Corriger les métadonnées pour Plex
```bash
cd /opt/music-home
source venv/bin/activate
python -m app.services.plex_metadata_fixer

# Mode simulation
python -m app.services.plex_metadata_fixer --dry-run
```

### 3. Enrichir et trier la bibliothèque (MusicBrainz)
```bash
cd /opt/music-home
source venv/bin/activate
python -m app.services.music_sorter

# Mode simulation
python -m app.services.music_sorter --dry-run
```

## Via l'API (avec authentification)

### Nettoyer les artistes
```bash
curl -X POST "http://localhost:8000/api/music/cleanup-artists?dry_run=false" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Corriger les métadonnées Plex
```bash
curl -X POST "http://localhost:8000/api/music/fix-plex-metadata?dry_run=false" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Enrichir avec MusicBrainz
```bash
curl -X POST "http://localhost:8000/api/music/sort?dry_run=false" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Plex

### Recharger la bibliothèque
```bash
cd /opt/music-home
source venv/bin/activate
python -c "from app.services.plex import PlexService; plex = PlexService(); plex.scan_library()"
```

### Forcer un refresh complet
```bash
python -c "from app.services.plex import PlexService; plex = PlexService(); plex.force_refresh_metadata()"
```

## Statistiques

### Voir les stats de la bibliothèque
```bash
cd /opt/music-home
find music -name "*.flac" | wc -l  # Nombre de fichiers
ls -1 music/ | wc -l               # Nombre d'artistes
du -sh music                        # Taille totale
```

### Vérifier le système
```bash
cd /opt/music-home
source venv/bin/activate
python -c "from app.api.routes import router; print('✅ Système OK')"
```

## Serveur

### Démarrer le serveur
```bash
cd /opt/music-home
./start_server.sh production
```

### Vérifier le statut
```bash
ps aux | grep uvicorn
curl http://localhost:8000/tracks
```

