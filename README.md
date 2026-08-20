# Price Tracker Bot

Bot de suivi de prix : scraping générique (n'importe quelle page produit,
via une URL + un sélecteur CSS), historique versionné dans le repo,
notifications Discord/email en cas de baisse, et un dashboard statique.
Conçu pour tourner sans serveur, via un cron GitHub Actions gratuit.

## Fonctionnalités

- **Scraping générique** : pas de code spécifique à un site — une URL et un
  sélecteur CSS suffisent pour suivre n'importe quelle boutique en ligne.
- **Historique en JSON** : `docs/data/price-history.json`, mis à jour et
  commité automatiquement par le workflow programmé. Pas de base de données.
- **Notifications optionnelles** : Discord (webhook) et email (SMTP), toutes
  deux désactivées par défaut — elles s'activent dès qu'un secret est
  configuré, sans jamais bloquer le run si absent.
- **Dashboard statique** : `docs/index.html`, lit l'historique et affiche un
  mini-graphique par produit. Déployable directement sur GitHub Pages.
- **Exemples préconfigurés** : `products.yaml` pointe par défaut vers
  [books.toscrape.com](https://books.toscrape.com), un site public fait
  exprès pour s'entraîner au scraping (aucune restriction légale) — à
  remplacer par tes propres produits.

## Utilisation en local

```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate sous Windows
pip install -e .

python -m price_tracker            # scrape, met à jour l'historique, notifie
python -m price_tracker --dry-run  # scrape et affiche, sans rien écrire/notifier
```

## Configurer tes propres produits

Édite `products.yaml` :

```yaml
products:
  - id: mon-produit          # clé stable, ne pas changer après coup
    name: "Nom affiché"
    url: "https://boutique.example/produit"
    selector: "span.prix"    # sélecteur CSS de l'élément contenant le prix
    currency: "EUR"
```

Pour trouver le sélecteur : ouvre la page produit dans le navigateur, clic
droit sur le prix → **Inspecter** → clic droit sur la ligne HTML surlignée →
**Copier** → **Copier le sélecteur**.

**Limite connue** : uniquement les sites qui affichent le prix directement
dans le HTML. Les sites qui l'injectent en JavaScript après coup (souvent le
cas sur les gros sites e-commerce avec protection anti-bot) ne sont pas
supportés — ça demanderait un navigateur headless (Selenium/Playwright),
volontairement hors scope pour rester simple à faire tourner sur un cron
GitHub Actions gratuit.

**À savoir** : vérifie le `robots.txt` et les conditions d'utilisation du
site avant de l'ajouter, et n'augmente pas trop la fréquence du cron —
ce projet est pensé pour un usage personnel, respectueux des sites suivis.

## Déploiement

1. Pousse le repo sur GitHub.
2. **Dashboard** : Settings → Pages → Source = "Deploy from a branch",
   branche `main`, dossier `/docs`. L'URL est donnée quelques instants après.
3. **Notifications (optionnel)** : Settings → Secrets and variables →
   Actions → New repository secret :
   - `DISCORD_WEBHOOK_URL` — pour Discord (webhook d'un salon, dans les
     paramètres du salon → Intégrations → Webhooks)
   - `SMTP_HOST`, `SMTP_PORT` (587 par défaut), `SMTP_USER`,
     `SMTP_PASSWORD`, `EMAIL_TO`, `EMAIL_FROM` (optionnel, sinon = `SMTP_USER`)
     — pour l'email (un mot de passe d'application si tu utilises Gmail)
4. Le workflow `track-prices.yml` tourne automatiquement toutes les 6h, et
   peut aussi être lancé manuellement depuis l'onglet **Actions** (bouton
   *Run workflow*) pour tester tout de suite sans attendre.

## Tests

```bash
pip install -e . -r requirements-dev.txt
ruff check .
pytest
```

## Stack

Python 3.11+, `requests` + `BeautifulSoup4` (scraping), `PyYAML` (config),
HTML/JS vanilla (dashboard, aucune dépendance externe), GitHub Actions
(cron + CI), GitHub Pages (hébergement statique).
