# Guide de déploiement sur Kali Linux

Ce guide vous explique comment déployer le Music Server sur un serveur Kali Linux pour le rendre accessible depuis l'extérieur.

## Prérequis

- Kali Linux installé et à jour
- Accès root ou sudo
- Connexion Internet
- Python 3.8+ installé

## Installation

### 1. Préparer le système

```bash
# Mettre à jour le système
sudo apt update && sudo apt upgrade -y

# Installer les dépendances système
sudo apt install -y python3 python3-pip python3-venv ffmpeg git

# Installer yt-dlp
pip3 install yt-dlp
```

### 2. Cloner ou copier le projet

```bash
# Option 1: Si vous avez le projet en local, copiez-le
scp -r music-server/ user@kali-server:/opt/

# Option 2: Si vous utilisez git
cd /opt
sudo git clone <votre-repo> music-server
sudo chown -R $USER:$USER /opt/music-server
```

### 3. Configuration

```bash
cd /opt/music-server

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances Python
pip install -r requirements.txt

# Copier le fichier .env.example en .env
cp .env.example .env

# Éditer le fichier .env
nano .env
```

**Configuration du fichier `.env` :**
```env
# Le serveur écoutera sur toutes les interfaces (0.0.0.0)
API_HOST=0.0.0.0
API_PORT=8000

# Configuration Plex (si vous utilisez Plex)
PLEX_SERVER_URL=http://127.0.0.1:32400
PLEX_TOKEN=votre_token_plex
PLEX_LIBRARY_SECTION_ID=1
PLEX_AUTO_SCAN=true
```

### 4. Configuration du firewall

```bash
# Vérifier que le firewall est actif
sudo ufw status

# Autoriser le port 8000 (ou celui que vous avez configuré)
sudo ufw allow 8000/tcp

# Si vous utilisez un reverse proxy (nginx), autorisez aussi le port 80/443
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Activer le firewall si ce n'est pas déjà fait
sudo ufw enable
```

### 5. Démarrage du serveur

#### Option A: Démarrage manuel (pour tester)

```bash
cd /opt/music-server
source venv/bin/activate
chmod +x start_server.sh
./start_server.sh production
```

#### Option B: Service systemd (recommandé pour la production)

```bash
cd /opt/music-server

# Copier le fichier de service
sudo cp music-server.service /etc/systemd/system/

# Modifier le fichier de service pour utiliser votre utilisateur
sudo nano /etc/systemd/system/music-server.service
# Remplacez %i par votre nom d'utilisateur (ex: kali)

# Recharger systemd
sudo systemctl daemon-reload

# Activer le service au démarrage
sudo systemctl enable music-server

# Démarrer le service
sudo systemctl start music-server

# Vérifier le statut
sudo systemctl status music-server

# Voir les logs
sudo journalctl -u music-server -f
```

### 6. Configuration réseau

#### Trouver l'adresse IP du serveur

```bash
# Afficher l'adresse IP
ip addr show | grep "inet " | grep -v 127.0.0.1
# ou
hostname -I
```

#### Accès depuis l'extérieur

Une fois le serveur démarré, vous pouvez y accéder depuis n'importe quel appareil sur le réseau :

- **Depuis le réseau local** : `http://<IP-DU-SERVEUR>:8000`
- **Depuis Internet** : Vous devrez configurer le port forwarding sur votre routeur

#### Configuration du routeur (pour accès Internet)

1. Connectez-vous à l'interface de votre routeur
2. Allez dans les paramètres de port forwarding / NAT
3. Ajoutez une règle :
   - **Port externe** : 8000 (ou un autre port)
   - **Port interne** : 8000
   - **IP interne** : L'adresse IP de votre serveur Kali
   - **Protocole** : TCP

4. Accédez ensuite via : `http://<VOTRE-IP-PUBLIQUE>:8000`

### 7. Sécurité (IMPORTANT)

#### Utiliser HTTPS avec un reverse proxy (recommandé)

Installer et configurer Nginx comme reverse proxy :

```bash
# Installer Nginx
sudo apt install -y nginx certbot python3-certbot-nginx

# Créer la configuration Nginx
sudo nano /etc/nginx/sites-available/music-server
```

**Configuration Nginx :**
```nginx
server {
    listen 80;
    server_name votre-domaine.com;  # Ou votre IP publique

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Activer le site
sudo ln -s /etc/nginx/sites-available/music-server /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Obtenir un certificat SSL (si vous avez un domaine)
sudo certbot --nginx -d votre-domaine.com
```

#### Autres mesures de sécurité

1. **Changer le mot de passe par défaut** de l'utilisateur admin
2. **Utiliser un firewall** (ufw est déjà configuré)
3. **Limiter l'accès SSH** si vous utilisez SSH
4. **Mettre à jour régulièrement** le système
5. **Utiliser des mots de passe forts** pour les utilisateurs

### 8. Vérification

```bash
# Vérifier que le serveur écoute sur le bon port
sudo netstat -tlnp | grep 8000
# ou
sudo ss -tlnp | grep 8000

# Tester depuis le serveur
curl http://localhost:8000/health

# Tester depuis un autre appareil
curl http://<IP-DU-SERVEUR>:8000/health
```

### 9. Maintenance

#### Arrêter le serveur

```bash
# Si service systemd
sudo systemctl stop music-server

# Si démarrage manuel
# Appuyez sur Ctrl+C
```

#### Redémarrer le serveur

```bash
sudo systemctl restart music-server
```

#### Mettre à jour le code

```bash
cd /opt/music-server
source venv/bin/activate
git pull  # Si vous utilisez git
# ou copiez les nouveaux fichiers
pip install -r requirements.txt  # Si de nouvelles dépendances
sudo systemctl restart music-server
```

#### Voir les logs

```bash
# Logs systemd
sudo journalctl -u music-server -f

# Logs de l'application (si configurés)
tail -f /opt/music-server/logs/app.log
```

## Dépannage

### Le serveur ne démarre pas

```bash
# Vérifier les logs
sudo journalctl -u music-server -n 50

# Vérifier que le port n'est pas déjà utilisé
sudo lsof -i :8000

# Vérifier les permissions
ls -la /opt/music-server
```

### Impossible d'accéder depuis l'extérieur

1. Vérifier le firewall : `sudo ufw status`
2. Vérifier que le serveur écoute sur 0.0.0.0 : `sudo netstat -tlnp | grep 8000`
3. Vérifier le port forwarding sur le routeur
4. Vérifier que votre FAI n'a pas bloqué le port

### Erreurs de permissions

```bash
# Donner les bonnes permissions
sudo chown -R $USER:$USER /opt/music-server
chmod +x /opt/music-server/start_server.sh
```

## Support

Pour toute question ou problème, consultez les logs et vérifiez la configuration.

