# V2 — UX de l'écran « Ajouter un produit »

Ce document définit l'expérience exacte de l'écran **Ajouter un produit**,
conforme à la proposition `proposition-price-tracker.md` : **deux modes
d'utilisation, un seul moteur**.

L'écran est la pièce maîtresse de la V2 : c'est là que la différence entre
un outil technique et un produit agréable se joue. Règle d'or : **l'utilisateur
exprime une intention, le système ose s'en occuper — et montre ce qu'il a
compris avant d'enregistrer.**

---

## 1. Entrée du flux

Depuis le tableau de bord, un bouton unique :

```text
[ + Ajouter un produit ]
```

ouvre un panneau **non modal** (l'utilisateur garde le contexte du dashboard).
Là, trois façons d'exprimer ce qu'on veut surveiller :

```text
┌────────────────────────────────────────────────────────────────────┐
│  Ajouter un produit                                                │
│                                                                    │
│  Qu'est-ce que tu veux surveiller ?                                │
│                                                                    │
│  🔗 Colle un lien           📝 Décris un produit    📸 Capture     │
│  [ https://...            [ "Sony WH-1000XM6"     [ bientôt —     │
│    ████████████████████     "iPhone sous 800 €" ]    planifié ]   │
│    (Méthode Auto)          (Méthode Auto)          │              │
│                                                                    │
│  ──────────────────────────────────────────────────────────────    │
│  Niveau de contrôle                                             ▼  │
│  ○ Automatique        ○ Personnalisé        ● Expert               │
│  « Je m'occupe de     « Je choisis prix    « Je contrôle la       │
│    tout. »              cible et alertes. »   configuration. »    │
│                                                                    │
│                          [ Continuer ]                             │
└────────────────────────────────────────────────────────────────────┘
```

Règles :

- Par défaut, le niveau est **Automatique** — l'utilisateur lambda ne change
  jamais cette valeur.
- Si un lien est collé, le champ « URL » est pré-rempli (mode Expert). Sinon,
  on reste en intention.
- La **Capture** (`📸`) n'est pas livrée en V2 : le bouton existe mais reste
  marqué « bientôt » et désactivé (pas de promesse non tenue).

---

## 2. Résolution de l'intention (le « config generator »)

Quand l'utilisateur clique **Continuer**, le système :

1. **Résout** l'intention → `ProductIntent` (requête, URL éventuelle,
   prix cible s'il s'agit d'une description « sous X € », canal de notif).
2. **Teste réellement** l'extraction sur la page (fetch + auto-détection :
   JSON-LD → OpenGraph → heuristiques de prix → CSS/XPath proposés).
3. Produit une **`TrackingConfig` pré-remplie** + une **confiance**.

L'écran « test » est le cœur du flux :

```text
┌────────────────────────────────────────────────────────────────────┐
│  Ajouter un produit · Vérification                                 │
│                                                                    │
│  📱 iPhone 17                                                      │
│  https://store.example/p/iphone-17                                 │
│                                                                    │
│  ⏱  Extraction du prix…                                           │
│  · JSON-LD          ✅ trouvé : 899,00 €                          │
│  · CSS (auto)       ✅ trouvé : 899,00 €                          │
│  · Regex (défaut)   ✅ trouvé : 899,00 €                          │
│                                                                    │
│  Stratégie retenue :  JSON-LD   (confiance : élevée)               │
│  Prix détecté :      899,00 €   EUR                                │
│                                                                    │
│  🎯 Prix cible :       [ 800 ] €    →  « préviens-moi sous 800 € » │
│                                                                    │
│                    [ Enregistrer ]  [ 🔧 Tester autrement ]        │
└────────────────────────────────────────────────────────────────────┘
```

### 2.1 Réglage du prix cible

- Auto-compris depuis la description (« sous 800 € » pré-remplit `800`).
- Sinon champ vide avec deux choix express :
  `[ < prix saisi ]   [ Dès qu'il baisse ]   [ × % ]`
- Aucun prix cible = alerte uniquement sur toute baisse notable (> 1 %).

### 2.2 Niveaux de détail après la vérification

Selon le niveau choisi à l'entrée, la suite diffère **sans changer le moteur** :

| Niveau | Après vérification |
| --- | --- |
| 🪄 **Automatique** | Récap minimal + bouton **Enregistrer**. La confiance faible (< 0,55) dégrade le récap en avertissement (voir § 2.3). |
| 🎯 **Personnalisé** | Réglages du prix cible, fréquences (6 h / 12 h / 24 h), multiple vendeurs (même produit, autres offres). |
| 🛠️ **Expert** | Toutes les options du moteur exposées (§ 3). |

Tous les niveaux finissent au même endroit : **une `TrackingConfig`**.

### 2.3 États de confiance

- **Élevée (≥ 0,7)** : vert, bouton `[ Enregistrer ]` proéminent.
- **Moyenne (0,45–0,7)** : le récap liste les stratégies qui concordent et
  invite à « vérifier sur la page » (lien d'aperçu).
- **Faible (< 0,45)** : avertissement explicite :

```text
⚠️  Plusieurs prix ont été repérés (799,99 / 849,99 / 29,99 €).
    Choisis lequel surveiller :
    ○ 799,99 € (JSON-LD, confiance élevée)
    ● 849,99 € (bloc « price », détecté 2 fois)
    ○ 29,99 €  (probablement une suggestion, ignoré par défaut)
```

- **Échec** (`ScrapeError`) : jamais de configuration silencieuse. Écran
  d'erreur avec diagnostic :

```text
⛔  Impossible d'extraire un prix sur cette page.
    · La page a répondu, mais aucun prix n'a été trouvé.
    · Si le prix est chargé en JavaScript, choisis « mode navigateur ».
    · Si le sélecteur a changé, teste une autre méthode ci-dessous.

    [ 🔧 Tester autrement ]   [ Copier le diagnostic ]
```

---

## 3. Mode Expert — le plein contrôle

Tout est exposé sans jargon superflu, mais sans cacher : c'est un **outil de
développement de scraper**.

```text
Product                                          Extraction
──────────────────────────                       ────────────────────────
Name                    [ Sony WH-1000XM6 ]      Stratégie    ○ Auto ● CSS
URL                     [ https://… ]                          ○ JSON-LD
                                                              ○ XPath
Prix cible              [ 300 ] EUR                            ○ Regex
                                                              ○ Navigateur
Valeur minimale         [ 100 ]                                  (Playwright)
Valeur maximale         [ 600 ]
                                                 Selector      [ span.price ]

Parsing
──────────────────────────                       Validation
Décimal        ○ point  ● virgule               Min: [ 100 ]  Max: [ 600 ]
Monnaie uniquement       [■]

Alertes                                              Planification
──────────────────────────                       ────────────────────────
Type          ● < prix cible                     Fréquence   [ 6 h ]
              ○ baisse ≥ 1 %                     Fenêtre     [ 24/7 ]
              ○ stricte (toute variation)

                          [ 🔧 Tester ]   [ Enregistrer ]
```

Règles :

- **Tester** ouvre le panneau **Playground** (§ 4) — c'est le même moteur,
  dans une boucle rapide : on ajuste, on reteste, on enregistre.
- Chaque champ Expert a un **versioneur** non intrusif : « ⚙️ » à droite
  des champs avancés pour voir la `TrackingConfig` YAML générée en direct.

### 3.1 Le mode Navigateur (Playwright)

- Sélection « Navigateur » activée si `playwright` est installé (`extra[.browser]`).
- Si le site semble nécessiter JS (détection heuristique agressive :
  prix absent du HTML statique), le système **propose** le mode navigateur
  plutôt que d'échouer.
- En V2, la stratégie navigateur est **explicite** : jamais de navigateur
  lancé en arrière-plan sans que l'utilisateur l'ait choisi (contrainte de
  coût, pas de surprise).

---

## 4. Playground (mode Debug)

Accessible depuis Expert → **Tester** ou depuis un produit existant →
**⚙️ Configuration avancée** :

```text
┌────────────────────────────────────────────────────────────────────┐
│  Playground · https://example.com/product/123                      │
│                                                                    │
│  ┌────────────────────────────────────────────┐                    │
│  │  🖼  Aperçu de la page (rendu texte)       │                    │
│  │  … 349,99 € · « Casque sans fil premium »  │                    │
│  └────────────────────────────────────────────┘                    │
│                                                                    │
│  Prix détectés :                                                   │
│  ● 349,99 €   ← sélectionné   (JSON-LD)   confiance 0,98          │
│  ○ 389,99 €                     (suggestion « prix barré »)        │
│  ○ 19,99 €                      (abonnement, ignoré)               │
│                                                                    │
│  Extraction utilisée : JSON-LD                                     │
│  ▶  Informations technique : domaine, time, headers, statut        │
│                                                                    │
│                    [ Tester ]   [ Enregistrer ]                    │
└────────────────────────────────────────────────────────────────────┘
```

- La sélection d'un candidat affiche la stratégie qui l'a trouvé.
- **▶ Informations technique** : bloc repliable pour le diagnostic
  (statut HTTP, taille, durée, extrait HTML/résultats XPath, warning). Sans
  jargon pour l'utilisateur lambda, ouvert par défaut pour l'expert.
- Boutons **Tester**/**Enregistrer** : le Playground n'écrit jamais
  automatiquement — seul **Enregistrer** commit la config.

---

## 5. Le dashboard (cohérence)

La carte produit reprend du vocabulaire « surveillance », jamais
« scraping » (proposition § 7) :

```text
┌──────────────────────────────────────────────┐
│  🎧 Sony WH-1000XM6                           │
│                                               │
│  349,99 €                                     │
│  ↓ -12 % depuis le début                      │
│                                               │
│  🎯 Objectif : 300 €   · 83 %  ▓▓▓▓▓▓▓▓░░░░   │
│                                               │
│  👁 Surveillance automatique  (JSON-LD)       │
│  🟢 Dernière vérification : il y a 8 min     │
│                                               │
│  [ Voir historique ]  [ Modifier ]            │
│                        [ ⚙️ Configuration ]   │
└──────────────────────────────────────────────┘
```

Le badge discret `(JSON-LD)` n'apparaît **que** si l'utilisateur est passé
par le niveau Expert — l'Automatique reste épuré.

---

## 6. Cobaye « Ajouter un produit » par niveau — déroulés

### Scénario A — Automatique (utilisateur lambda)

1. `[ + Ajouter un produit ]` → colle `https://store.example/p/iphone-17`.
2. **Continuer** → système teste, affiche « iPhone 17 · 899,00 € » confiance
   **élevée**, prix cible vide.
3. Saisit `800` → **Enregistrer**. Terminé : une `TrackingConfig` (stratégie
   JSON-LD, URL, cible, notif ✉️) a été créée. Le dashboard la montre dans
   « Surveillance automatique ».

### Scénario B — Description + confiance moyenne

1. Saisit « AirPods Pro autour de 200 € ».
2. Le système ne trouve pas de produit unique via URL → il liste 2 offres,
   confiance **moyenne**, demande de choisir.
3. L'utilisateur choisit, valide le réglage « sous 200 € », enregistre.

### Scénario C — Expert avec site JS

1. Expert, colle l'URL (site React), garde Auto → échec « aucun prix dans le
   HTML ».
2. Le diagnostic **propose** le mode Navigateur. Il active `Navigateur`,
   **Tester** → Playground affiche 74,99 € (JSON-LD rendu par JS).
3. **Enregistrer** : config `strategy: browser` + JSON-LD comme extracteur.

### Scénario D — Échec réel

1. Colle une URL 404 ou un site à protection anti-bot.
2. Échec → jamais de config silencieuse. Diagnostic + boutons
   « Tester autrement » / « Copier le diagnostic ». Aucune écriture.

---

## 7. Règles non négociables

1. **Un seul moteur** : Auto, Custom, Expert aboutissent tous à la même
   `TrackingConfig` → `Tracking Engine`. Jamais deux pipelines.
2. **Toujours tester avant d'enregistrer** : aucune config n'est créée sans
   qu'une extraction ait réussi (ou sans un échec explicite assumé par
   l'expert qui force).
3. **Jamais de navigateur silencieux** : Playwright uniquement si choisi
   (ou fortement suggéré face à un constat d'échec JS).
4. **Le confort ne masque pas la complexité** : en cas de confiance faible,
   on laisse choisir, on ne décide pas à la place de l'utilisateur.
5. **Vocabulaire « surveillance »** dans l'interface, « configuration /
   extraction » dans le mode Expert.
6. **Page d'erreur propre** (404 + pages légales) : l'écran fait partie d'un
   site complet, pas d'une démo jetable.