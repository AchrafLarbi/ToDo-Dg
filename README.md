# Gestion des Taches

Application web hebergee pour gerer des projets, assigner des taches a des collaborateurs,
suivre les echeances/priorites/sensibilite, cloturer les taches et alerter par email (via
Outlook) en cas de retard ou d'echeance proche. Chaque collaborateur peut mettre a jour sa
tache (statut, echeance, commentaire) via un lien securise recu par email, sans avoir de
compte. L'acces a l'interface de gestion (projets, taches, collaborateurs, parametres) est
protege par un mot de passe administrateur.

## Fonctionnement general

- **Collaborateurs** : nom, email, telephone. Ajoutes depuis l'appli, pas de compte/mot de
  passe pour eux.
- **Projets** : nom, description, dates de debut/echeance, statut. Regroupent des taches.
- **Taches** : rattachees a un projet et/ou un collaborateur, avec priorite (Basse / Normale /
  Haute / Urgente) et sensibilite (Faible / Normale / Elevee / Critique). Echeance et statut
  (A faire / En cours / Terminee / Cloturee) completent chaque tache.
- **Alertes visuelles** : une tache devient **orange** ("Echeance proche") X jour(s) avant sa
  date limite (X = parametrable dans Parametres, `reminder_days_before`), puis **rouge**
  ("En retard") une fois la date depassee. Visible sur le tableau de bord, les listes de
  taches et la fiche detail.
- **Emails automatiques** :
  - Creation d'une tache assignee : email de notification immediat avec un lien de suivi.
  - Relances automatiques quotidiennes (si activees) a l'heure choisie, pour les taches en
    retard ou dont l'echeance approche (une seule relance par jour et par tache).
  - Bouton "Verifier les echeances et relancer maintenant" sur le tableau de bord.
  - Relance manuelle disponible sur la fiche de chaque tache.
  - Chaque email envoye (reussi ou en echec) est journalise dans l'historique de la tache.
- **Reponse du collaborateur** : chaque email d'alerte contient un lien unique et secret
  (`/t/<token>`) qui ouvre une page limitee a cette tache : le collaborateur peut changer le
  statut, proposer une nouvelle echeance et expliquer la situation, sans mot de passe.
  L'administrateur recoit un email de notification a chaque mise a jour, et l'historique est
  visible sur la fiche de la tache.
- **Tableau de bord** : totaux (actives / en retard / echeance proche / terminees-cloturees),
  et repartition detaillee par collaborateur.
- **Cloture** : changez le statut d'une tache en "Terminee" ou "Cloturee" avec un commentaire
  optionnel ; la date de cloture est enregistree automatiquement.

## Architecture

- `app.py` : application Flask (routes, authentification admin, page publique collaborateur).
- `database.py` : acces PostgreSQL (via `DATABASE_URL`).
- `email_utils.py` : envoi SMTP (Outlook/Office 365) et construction des liens de suivi.
- `scheduler.py` : relances automatiques quotidiennes (APScheduler).
- `paths.py` : localisation des templates/CSS.
- `*.html`, `style.css` : interface web.

Donnees stockees dans une base **PostgreSQL** (pas de fichier local) : necessaire pour que
plusieurs collaborateurs et l'administrateur utilisent la meme application hebergee sans perte
de donnees au redemarrage.

## Deploiement sur Render (recommande)

1. Poussez ce dossier dans un depot Git (GitHub/GitLab) relie a votre compte Render.
2. Sur [render.com](https://render.com), utilisez **New > Blueprint** et pointez vers ce
   depot : le fichier `render.yaml` cree automatiquement le service web et la base
   PostgreSQL, et relie `DATABASE_URL` entre les deux.
3. Render vous demande la valeur de `ADMIN_PASSWORD` (variable marquee `sync: false`) :
   choisissez un mot de passe fort, c'est celui qui protege toute l'interface de gestion.
4. Une fois deploye, ouvrez l'URL fournie par Render (ex.
   `https://gestion-taches.onrender.com`), connectez-vous avec `ADMIN_PASSWORD`, puis allez
   dans **Parametres** :
   - Renseignez le SMTP Outlook (voir ci-dessous).
   - Renseignez le champ **URL publique de l'application** avec cette meme URL Render : elle
     sert a construire les liens de suivi envoyes aux collaborateurs.
5. Les collaborateurs n'ont rien a installer : ils recoivent les emails et cliquent sur le
   lien fourni.

**Important - base gratuite PostgreSQL sur Render** : la base PostgreSQL gratuite de Render
expire au bout d'un temps limite (actuellement 30 jours), puis doit passer sur un plan payant
pour continuer a fonctionner sans interruption. Pour un usage en production continu,
prevoyez de passer sur le plan payant de la base avant l'expiration.

**Mise en veille du plan web gratuit** : sur le plan gratuit, le service web se met en veille
apres une periode d'inactivite et met quelques dizaines de secondes a se reveiller au
prochain acces (et les relances automatiques quotidiennes ne se declenchent pas si le service
est endormi a l'heure prevue). Pour un usage fiable en equipe (relances automatiques
garanties, pas de latence de reveil), passez le service web sur un plan payant.

## Deploiement generique (Docker / autre hebergeur)

L'application est une appli Flask standard, lancee en production avec `gunicorn` :

```
pip install -r requirements.txt
export DATABASE_URL=postgresql://...
export SECRET_KEY=...
export ADMIN_PASSWORD=...
gunicorn "app:create_app()"
```

Elle a juste besoin d'une base PostgreSQL accessible via `DATABASE_URL` et d'un `SECRET_KEY`
unique. Le port est lu depuis la variable d'environnement `PORT` (utilise par Render et la
plupart des PaaS).

## Developpement local

1. Lancez une base PostgreSQL locale, par exemple avec Docker :
   ```
   docker run -d --name todo-db -e POSTGRES_USER=todo -e POSTGRES_PASSWORD=todo \
     -e POSTGRES_DB=gestion_taches -p 5432:5432 postgres:16-alpine
   ```
2. Copiez `.env.example` en `.env` et completez `DATABASE_URL`, `SECRET_KEY`,
   `ADMIN_PASSWORD`.
3. Sous Windows : double-cliquez sur `run.bat` (installe les dependances et lance
   `http://127.0.0.1:5000`). Sous Linux/Mac :
   ```
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python3 app.py
   ```

## Configuration de l'envoi d'emails (Outlook)

Dans la page **Parametres** :

- Serveur SMTP : `smtp.office365.com`, port `587` (deja pre-rempli).
- Adresse email : votre adresse Outlook / Office 365.
- Mot de passe : si la double authentification (MFA) est activee sur votre compte Microsoft,
  creez un **mot de passe d'application** :
  1. https://account.microsoft.com/security
  2. "Options de securite avancees" > "Mots de passe d'application"
  3. Creez-le, copiez-le, collez-le dans le champ mot de passe.
  Sans MFA, votre mot de passe Outlook habituel peut suffire (selon la politique de votre
  compte).
- Bouton "Envoyer un email de test" pour verifier que tout fonctionne.

## Securite

- L'interface de gestion (projets, taches, collaborateurs, parametres) est protegee par
  `ADMIN_PASSWORD`. Changez la valeur par defaut avant toute mise en production.
- Le lien envoye a chaque collaborateur (`/t/<token>`) est un jeton aleatoire de 32 octets
  (non devinable) qui ne donne acces qu'a la tache concernee, sans authentification. Ne le
  partagez pas publiquement.
- `SECRET_KEY` doit etre une valeur aleatoire unique et gardee secrete (utilisee pour signer
  les cookies de session).

## Limites a connaitre

- Application concue pour une petite equipe (usage interne). L'administrateur pilote l'outil ;
  les collaborateurs interagissent uniquement via les emails et le lien de suivi de leur
  tache.
- Les relances automatiques quotidiennes necessitent que le service web reste actif a l'heure
  prevue (voir la remarque sur la mise en veille du plan gratuit Render ci-dessus).
