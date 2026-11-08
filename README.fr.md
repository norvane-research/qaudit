# qaudit 1.0 — audit et validation de systèmes de trading

`qaudit` ingère un historique de trades clos et rend un verdict motivé — **GO**,
**GO SOUS CONDITIONS** ou **NO-GO** — avec les chiffres qui le portent et les
conditions de mise en production.

**Noyau déterministe, coquille intelligente.** Le moteur tourne seul, hors
ligne, sans modèle de langage : mêmes entrées + même version + même graine =
même JSON, à l'octet près. Le verdict découle mécaniquement de barrières
explicites (jamais d'un score composite) ; chaque point est contestable
séparément.

> qaudit constate des faits sur un historique de trades. Ce n'est **pas un
> conseil en investissement** : il ne prédit aucune performance et ne
> recommande aucun réglage. Logiciel libre sous licence AGPL-3.0-or-later
> (voir « Licence » plus bas). *English version: [README.md](README.md).*

**Vous vendez un EA ou des signaux ?** Le moteur est gratuit. Quand vos
acheteurs ont besoin d'un résultat vérifiable, Norvane Research refait l'audit
sur votre fichier et, sur GO, inscrit une attestation numérotée au registre
public :
[attestation cessible, 390 €](https://whop.com/lafabrique/qaudit-attestation),
due quel que soit le verdict · [vérifier une attestation](https://norvane-research.pages.dev/verification.html)
· la pré-vérification de votre fichier est gratuite.

---

## À quoi ressemble un rapport

La démo fournie (`qaudit demo`) audite un système synthétique en martingale.
En surface, tout va bien : +20,5 % en 15 mois, 77,5 % de trades gagnants,
profit factor 1,26, Sharpe annualisé 1,52, drawdown maximal 9 %. Extrait
condensé de son rapport :

```text
NO-GO                    méthode 1.0 · moteur 1.0.0 · graine 0 · 600 trades, USD
SHA-256 des données      ae4badd1047e2753…83394ca19ef5

Bloquant   martingale : après une perte, le volume est multiplié par ≥ 1,5
           dans 96 % des cas (après un gain : 1 %), sur 135 trades post-perte
Majeur     absence de stop : 100 % des trades n'ont aucun stop-loss renseigné

Barrière                               valeur   NO-GO si   zone d'indécision
Sharpe déflaté (10 variantes)          0,54     < 0,50     0,45 – 0,55   limite
profit factor, 5e centile bootstrap    1,03     < 1,00     0,95 – 1,05   limite
centile du drawdown (permutations)     88,0     < 5        3 – 8
p-value, système sans avantage         0,048    ≥ 0,05     0,03 – 0,08   limite
efficacité walk-forward                —        < 0,40     non évaluée (pas de walk-forward)

Ce système cesse d'être significatif au-delà de 12 variantes testées.
```

Sur les seules statistiques, il obtiendrait au mieux un GO sous conditions ;
c'est la gestion des volumes qui en fait un NO-GO. Rapports complets, HTML et
PDF : [martingale → NO-GO](https://norvane-research.pages.dev/exemples/martingale.html)
· [témoin sain → GO](https://norvane-research.pages.dev/exemples/temoin-sain.html).

---

## Produire un rapport client en dix minutes

### 1. Installer (une fois)

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS : source .venv/bin/activate
pip install -e .
```

Dépendances d'exécution : `numpy`, `scipy`, `pandas` — rien d'autre. Une fois
installé, le paquet ne touche ni au réseau ni à une clé d'API.

Vérifier l'installation avec la démonstration embarquée (deux audits hors
ligne : témoin sain attendu GO, martingale attendue NO-GO) :

```bash
qaudit demo --out demo-out
```

### 2. Auditer un dossier

```bash
qaudit audit historique.csv --initial-balance 10000 --out rapport/
```

Le moteur lit le fichier (CSV générique, export CSV MetaTrader 5, rapport HTML
MetaTrader 5, **rapport du Strategy Tester MetaTrader 5** en HTML ou Open XML —
trades clos reconstitués depuis les deals —, **rapport détaillé MetaTrader 4**,
table des profits Deriv ; en-têtes MetaTrader reconnus en fr/en/es/de/pt/it ;
détection automatique, forçable par `--kind`), le valide en nommant toute ligne et colonne fautive, calcule tout ce
que les données permettent, écrit :

- `rapport/archive/<nom>.json` — le document intégral, versionné, toujours
  archivé (schéma publié : `qaudit/io/writers/schema/report-1.0.json`) ;
- `rapport/<nom>.html`, `rapport/<nom>.pdf` (et `<nom>.json` selon l'offre) —
  les livrables du profil de rapport choisi (`--offre`, défaut `audit_complet`).

Le code de sortie **est** le verdict : `0` GO · `1` GO sous conditions · `2`
NO-GO (voir `qaudit --help` pour la liste complète).

Options utiles :

| Option | Effet |
|---|---|
| `--prices ohlc.csv --symbol EURUSD` | série de prix : active les détecteurs de look-ahead, de réalisme d'exécution et la sensibilité du stop ; régimes par ATR |
| `--walkforward dossier/` | un fichier de trades par jeu de paramètres : évalue la barrière walk-forward (sans elle, le verdict est au mieux « sous conditions ») |
| `--ruleset two_step_static` ou `--ruleset mon_reglement.toml` | rejeu propfirm (`qaudit rulesets` liste les modèles embarqués) |
| `--n-trials 50` | nombre de variantes testées déclaré (le DSR est toujours publié sur la grille 1…1000) |
| `--seed 7` | graine des simulations (imprimée dans le rapport) |
| `--lang en` | rapport en anglais |
| `--offre verdict_propfirm` | profil de rapport (`qaudit profils` pour la liste) |

### 3. Si le moteur s'arrête : les trois portes d'escalade

| Code | Situation | Reprise |
|---|---|---|
| **10** (E1) | un en-tête n'est pas reconnu et ne se déduit pas du contenu ; un JSON liste les colonnes vues et les champs manquants | `qaudit mapping-skeleton fichier.csv > mapping.toml`, compléter, relancer avec `--mapping mapping.toml`. La correspondance validée est mémorisée par empreinte d'en-tête : le dossier suivant au même format passe seul. |
| **11** (E2) | règlement propfirm en prose, absent ou incomplet ; le squelette TOML est imprimé | compléter **chaque** clé (une règle absente s'écrit `0`, jamais devinée), `as_of` obligatoire, relancer avec `--ruleset fichier.toml` |
| **E3** | une grandeur de barrière tombe dans sa bande d'indécision | le verdict est rendu normalement, `revue_humaine: true` et la grandeur limite sont imprimés : signaler, ne pas s'arrêter |

Autres codes : `20` données invalides (ligne et colonne nommées), `30` erreur
interne (trace imprimée).

### 4. Régénérer un rapport sans recalculer

```bash
qaudit render --from rapport/archive/<nom>.json --offre audit_prix --out autre/
```

Le rendu depuis l'archive est identique à l'octet au rendu direct (testé).

### 5. Mode lot

```bash
qaudit batch dossier_de_csv/ --jobs 8 --initial-balance 10000 --offre portefeuille --out lot/
```

N systèmes en parallèle, correction de Benjamini-Hochberg sur les p-values du
portefeuille, tableau de synthèse (`lot/portfolio.html`, `lot/portfolio.json`).
Mesuré : 80 systèmes, audit complet à 10 000 itérations, en 22 s sur 8 cœurs.

---

## Ce que le rapport contient

- **En-tête** : version du moteur, version de la méthode, graine, empreinte
  SHA-256 des données (les quatre champs de reproductibilité).
- **En clair** (section présente dans toutes les offres) : l'explication
  destinée au client, en langage courant et sans intervention de l'auditeur —
  ce que veut dire le verdict (feu vert / orange / rouge) et ce qu'il ne veut
  pas dire, les cinq tests reformulés en questions (« le hasard est-il
  écarté ? », « et avec de la malchance ? »…) avec le chiffre du dossier et le
  seuil, chaque défaut grave titré et expliqué (« retirez quelques trades
  exceptionnels et le résultat s'effondre »), puis ce qu'il reste à faire.
  Chaque section porte en outre un encadré « Comment lire cette section ».
  Ces textes sont des gabarits du catalogue (`qaudit/i18n/explain_<lang>.toml`)
  remplis avec les nombres du document archivé : rien n'est calculé ni
  interprété au rendu, et aucun réglage n'est recommandé.
- **Verdict** et barrières : Sharpe dégonflé, profit factor au 5ᵉ centile du
  bootstrap par blocs, centile du drawdown parmi les permutations d'ordre,
  p-value contre la nulle sans edge, efficacité walk-forward — chacune avec son
  seuil et sa bande d'indécision.
- **Constats** : validation (ruine, trous…), détecteurs structurels
  (martingale, grille, absence de stop, concentration du profit, linéarité de
  l'equity, asymétrie réussite/ratio, dépendance à une période, durée de
  position) et, avec prix, look-ahead, réalisme d'exécution, sensibilité du stop
  (±10/20/30 %). Un détecteur qui n'a pas pu tourner le dit (constat « info »).
- **Statistiques** : PSR, DSR et sa courbe de sensibilité au nombre d'essais
  avec le point de bascule (« ce système cesse d'être significatif au-delà de N
  variantes ») ; quand la variance des Sharpe entre variantes est inconnue, la
  correction de Lo est signalée comme prudente.
- **Rééchantillonnage** : bootstrap par blocs stationnaire (Politis–Romano,
  longueur de bloc automatique), permutation d'ordre, nulle sans edge (qui
  conserve les distributions empiriques — ce n'est pas une nulle de marché
  efficient, le rapport le dit).
- **Régimes** (terciles de volatilité ou ATR, classificateur nommé), trimestres,
  walk-forward (protocole nommé), rejeu propfirm (probabilité par phase, causes
  d'échec, ruine du compte financé, gain médian, espérance nette ; horizon des
  phases sans limite imprimé).

### Présentation (HTML, PDF, fenêtre)

Une seule charte pour les trois supports : encre marine, filet or, titres en
serif, corps en sans-serif système ; couleurs sémantiques fixes — GO vert,
GO sous conditions ambre, NO-GO rouge ; gravités bloquant / majeur / mineur /
info et statuts de barrière portés par des pastilles de même palette. Le
rapport HTML est autonome (CSS en ligne, aucune police ni ressource
téléchargée, imprimable) : en-tête de marque, bandeau de verdict avec
compteurs, bandeau de faits (période, trades, solde, N), sommaire, cartes
d'indicateurs, tableaux zébrés à colonnes numériques alignées, fiches de
constats, graphique SVG de la sensibilité au nombre d'essais avec la ligne de
seuil. Le PDF reproduit la même structure sans dépendance (PDF 1.4 généré à la
main, polices standard, pied de page numéroté). La fenêtre est « DPI-aware »
(rendu net aux échelles 125–300 %). Le rendu ne calcule rien : il ne fait que
présenter le document JSON archivé, ce qui garantit qu'un `render --from`
reste identique à l'octet à l'audit direct.

## Conventions d'ingestion (à connaître avant de lire un rapport)

- Champs obligatoires : heure d'ouverture, heure de clôture, profit. Les autres
  (volume, sens, symbole, prix, stop, ticket, commission, swap, devise) sont
  optionnels ; leur absence désactive proprement les analyses concernées.
- Si `commission` et/ou `swap` sont fournis, `profit` est réputé brut et le
  net vaut `profit + commission + swap` (convention MetaTrader) ; sinon
  `profit` est réputé net.
- Horodatages naïfs, interprétés tels quels (heure du serveur) ; un décalage
  explicite est converti en UTC.
- Ordre canonique : clôture croissante. Les doublons, les clôtures antérieures
  aux ouvertures, les devises mêlées sont des erreurs (code 20).
- Ruine : dès que `solde initial + cumul` ≤ 0, constat bloquant ; aucun ratio
  n'est calculé sur une base négative. Sans `--initial-balance` (ni dépôt lu
  dans un rapport MT5), la ruine et les métriques relatives ne sont pas
  évaluables et le rapport le dit.
- Toutes les grandeurs de décision sont calculées sur le P&L par trade en
  devise du compte : le verdict est exactement invariant par changement
  d'échelle des profits.

## Méthode versionnée

Les seuils vivent dans `qaudit/io/methods/method-1.0.toml`, jamais dans le
code. Changer un seuil impose d'incrémenter `version` : la version de la
méthode est imprimée dans chaque rapport et invalide les rapports antérieurs.
Un autre fichier de méthode se passe par `--method`.

| Barrière | NO-GO | Bande d'indécision |
|---|---|---|
| constat structurel bloquant | ≥ 1 | — |
| Sharpe dégonflé | < 0,50 | 0,45 – 0,55 |
| profit factor, 5ᵉ centile bootstrap par blocs | < 1,00 | 0,95 – 1,05 |
| centile du drawdown dans les permutations | < 5 | 3 – 8 |
| p-value contre la nulle sans edge | ≥ 0,05 | 0,03 – 0,08 |
| efficacité walk-forward hors échantillon | < 0,40 | 0,35 – 0,50 |
| constats majeurs cumulés | — | ≥ 3 → conditionnel |

Une barrière non évaluable (walk-forward non fourni, nulle non calculable)
n'est jamais réputée franchie : elle devient une condition nommée.

## Attestation, registre, vérification

Une **attestation de validation** n'est émise que sur verdict **GO**, par les
profils qui la livrent (`audit_complet`, `audit_prix`, `attestation_cessible`
— cessible —, `portefeuille`, `due_diligence`). Elle est inscrite au
**registre** (`~/.qaudit/registre.jsonl`, `--registry` pour un autre chemin)
sous une référence `AUD-<année>-<NNN>` ; la même empreinte auditée avec les
mêmes versions reçoit toujours la même référence (pas de doublon), et une
ré-émission produit les mêmes octets. L'attestation reprend la déclaration,
l'objet (référence, date, titulaire, système, période, trades, N, capital,
versions, empreinte SHA-256, portée), les barrières franchies, ce qu'elle ne
dit pas, et comment la vérifier.

```bash
qaudit audit dossier.html --offre attestation_cessible --holder "Studio X" --issuer "Nom"
qaudit attest --from qaudit-out/archive/dossier.json --offre audit_complet   # ré-émission
qaudit verify AUD-2026-001                  # l'entrée du registre, code 20 si inconnue
qaudit badge AUD-2026-001 --site https://exemple.org   # badge SVG + extraits HTML/Markdown à coller
qaudit registre --html site/verification.html   # page publique : jamais le titulaire
qaudit methode --write docs/methode-1.0.md  # méthode publiée, générée depuis la configuration
```

`docs/methode-1.0.md` (et `method-1.0.en.md`) sont **générés** par
`qaudit methode` ; un test échoue s'ils divergent de la configuration chargée.

Tout le monde peut lancer le moteur, refaire n'importe quel rapport et émettre
des attestations dans son propre registre, sous son propre nom. Les
attestations inscrites au **registre public du mainteneur** ne sont émises
qu'après qu'il a refait l'audit sur le fichier du client : c'est le service
payant décrit plus bas.

## Site de l'offre

`python packaging/build_site.py` assemble `site/` (français à la racine,
anglais sous `en/`) : page de vente, « Préparer votre audit », méthode,
politique de données (`docs/politique-donnees.md`), trame de CGV
(`docs/cgv-modele.md`, à faire relire par un juriste), page de vérification
(registre public) et deux rapports d'exemple rendus par le moteur (témoin sain
GO, martingale NO-GO). L'offre commerciale (prestations, prix, ordre),
les coordonnées, le formulaire de commande, les liens de paiement et l'adresse
du dépôt viennent de `site.toml` ; le moteur, lui, ne connaît aucun prix.
Statique, sans dépendance, hébergeable tel quel — mais pas sur GitHub Pages,
que les conditions de GitHub excluent pour un site à vocation commerciale.

## Profils de rapport

Sections canoniques : en-tête, verdict, `en_clair` (explication client, placée
après `verdict` et incluse dans les sept profils embarqués, mais pas
obligatoire : un profil TOML qui l'omet reste valide), indicateurs, barrières,
constats, statistiques, simulations, régimes, walk-forward, détecteurs à prix,
propfirm, seuil d'arrêt, conditions, portefeuille, note de comité, portée et
limites, pied.

`qaudit profils` liste les sept profils (`qaudit/io/profils/*.toml`). Un profil
choisit les sections livrées et les formats ; il ne touche jamais au calcul ni
au verdict, ne peut retirer ni l'en-tête, ni le verdict, ni les constats
critiques, ni la portée et les limites, ni le pied ; le JSON intégral est
toujours archivé. Aucune notion de profil ni de prix n'existe sous
`qaudit/core/` (testé).

| Profil | Contenu |
|---|---|
| `pre_verification` | le fichier est-il exploitable ? (`qaudit validate`, aucun verdict) |
| `verdict_propfirm` | verdict, indicateurs, rejeu du règlement propfirm |
| `audit_complet` | le rapport intégral ; attestation si GO |
| `audit_prix` | rapport intégral + détecteurs à prix + walk-forward |
| `attestation_cessible` | rapport intégral + attestation présentable aux acquéreurs du système |
| `portefeuille` | plusieurs systèmes, correction de sélection multiple |
| `due_diligence` | tout, plus une note de comité d'investissement |

## Application PC (interface graphique)

Trois façons de l'ouvrir :

- le raccourci **qaudit** sur le Bureau (créé par la construction ; il lance
  `dist\qaudit\qaudit.exe gui`) ou `Lancer qaudit.cmd` à la racine du dépôt ;
- `dist\qaudit\qaudit.exe gui` — **déposer un fichier de trades sur
  l'icône** de `qaudit-gui.exe` l'ouvre avec ce fichier déjà chargé (même
  fenêtre : `qaudit-gui.exe` est le binaire fenêtré, `qaudit.exe gui` passe
  par le binaire console et masque sa console — voir *Exécutables Windows*) ;
- `qaudit gui`, `qaudit-gui` ou `python -m qaudit.gui.app` depuis
  l'environnement Python.

Premier essai : bouton **Charger l'exemple** (témoin sain embarqué, solde
10 000 USD, walk-forward et règlement `two_step_static`) puis **Lancer
l'audit** → verdict GO en quelques secondes, **Ouvrir le HTML** montre le
rapport. Le journal de la fenêtre est aussi écrit dans
`%USERPROFILE%\qaudit-out\qaudit-gui.log` ; un plantage est journalisé et
affiché, jamais silencieux.

Arguments de lancement (automatisation) : `qaudit.exe gui fichier.csv
--initial-balance 10000 --out dossier --run --exit-after` (ou `qaudit-gui.exe`
avec les mêmes arguments) lance l'audit et se ferme en rendant le code de
sortie du verdict (0 / 1 / 2, 10 pour E1).

Même noyau, mêmes rapports que la ligne de commande — un audit lancé depuis la
fenêtre et un audit lancé en console produisent le même JSON (testé octet à
octet). La fenêtre : formulaire (fichier de trades, lecteur, solde initial,
série de prix, dossier walk-forward, règlement, offre, langue, graine,
itérations, dossier de sortie), verdict et barrières, constats, journal,
historique des archives du dossier de sortie (double-clic : rendu à nouveau
avec le profil choisi). Les portes d'escalade y sont traitées sans quitter la
fenêtre : E1 ouvre l'éditeur de correspondance de colonnes et relance ; E2
propose d'enregistrer le squelette de règlement ; E3 affiche « revue humaine
requise » avec la grandeur limite. Interface en tkinter (livré avec Python :
aucune dépendance ajoutée).

### Exécutables Windows

```powershell
.\packaging\build.ps1      # -> dist\qaudit\qaudit.exe et dist\qaudit\qaudit-gui.exe
```

Le dossier `dist\qaudit\` est autonome (Python et dépendances embarqués,
≈ 140 Mo) : le copier tel quel sur un poste sans Python suffit ;
`qaudit.exe demo` y produit les deux rapports attendus hors ligne. Les
binaires ne sont pas signés. Constaté sous **Smart App Control** (Windows 11
en mode « activé ») : le binaire fenêtré `qaudit-gui.exe` est refusé
(« une stratégie de contrôle d'application a bloqué ce fichier »,
événement Code Integrity 3077) alors que le binaire console `qaudit.exe`
est admis après ses premiers lancements. Constaté ensuite : le binaire console lui-même
peut rester bloqué après une reconstruction (nouveau hachage, réputation
inconnue). Sur le poste de l'auditeur, le raccourci Bureau et `Lancer
qaudit.cmd` lancent donc la fenêtre par le Python signé de l'environnement
(`.venv\Scripts\pythonw.exe -m qaudit gui`), jamais bloqué ; `qaudit.exe gui`
masque sa console au double-clic et reste la voie pour un poste sans Python
(sans Smart App Control, ou après confirmation). La vraie solution pour
distribuer les binaires est un certificat de signature de code.

## Bibliothèque

```python
import pandas as pd
from qaudit.core.audit import AuditOptions, run_audit
from qaudit.core.validate import validate
from qaudit.io.method import load_method
from qaudit.io.readers.common import infer_mapping
from qaudit.io.readers.dataframe import from_dataframe

table = from_dataframe(df, initial_balance=10_000.0, currency="USD")
config = load_method()
validation = validate(table, infer_mapping(table.columns), max_gap_days=config.max_gap_days)
result = run_audit(validation, config, AuditOptions(seed=0))
print(result.verdict.decision, [b.name for b in result.verdict.barriers if b.triggered])
```

Un classificateur de régimes externe s'injecte par `run_audit(..., classifier=…)`
(protocole `qaudit.core.regimes.RegimeClassifier`).

## Développement

```bash
pip install -e ".[dev]"
pytest                    # ~520 tests : unitaires, propriétés (hypothesis), dorés, non-régression D-01…D-09 et R-01…R-08
mypy --strict             # 0 erreur, stubs locaux pour scipy/pandas dans stubs/
ruff check .              # complexité cyclomatique ≤ 10, aléatoire global interdit (NPY002)
pytest --cov              # couverture de core/ ≥ 90 %
```

Règles d'architecture (vérifiées par `tests/test_architecture.py`) : `core/`
n'importe ni `io/`, ni `cli/`, ni `i18n/` ; aucun accès disque ou réseau dans
le noyau (un test coupe les sockets) ; l'aléatoire passe exclusivement par un
`numpy.random.Generator` reçu en paramètre ; aucune chaîne utilisateur dans le
code (clés i18n, catalogues `fr.toml` / `en.toml` à clés identiques).

Fixtures dorées (`tests/fixtures/`, régénérées par `tests/fixtures/generate.py`,
identiques à l'octet) : témoin sain, martingale, grille, sans stop + asymétrie,
bruit sans edge, ruine, look-ahead. **Le témoin sain est le garde-fou : s'il
ressort NO-GO, c'est le moteur qui est cassé.**

Budgets mesurés : audit complet 1 000 trades × 10 000 itérations en ≈ 2,8 s
(N-03 < 8 s) ; 80 systèmes en parallèle en ≈ 22 s (N-04 < 3 min).

Contributions : voir [CONTRIBUTING.md](CONTRIBUTING.md).

## Offre

Le moteur est gratuit. Ce que vend le mainteneur, c'est ce qu'une copie du
code ne donne pas : un audit refait par un tiers et inscrit à un registre
public.

| Prestation | Prix | |
|---|---|---|
| Moteur open source | gratuit | tout le moteur, tous les rapports, AGPL-3.0-or-later |
| Pré-vérification | gratuit | votre fichier est-il exploitable ? Réponse avant tout paiement |
| Attestation cessible | 390 € | nous refaisons l'audit sur votre fichier ; si GO, attestation numérotée au registre public, vérifiable par vos acquéreurs ; due quel que soit le verdict |
| Portefeuille de systèmes | sur devis | plusieurs systèmes, correction de sélection multiple |
| Due diligence | sur devis | tout, plus une note de comité d'investissement |
| Licence commerciale | sur devis | intégrer le moteur dans un produit ou un service fermé, sans les obligations de l'AGPL |

## Licence

Copyright © 2026 — voir [NOTICE](NOTICE).

qaudit est un logiciel libre sous **GNU Affero General Public License v3.0 ou
ultérieure** ([LICENSE](LICENSE)). Qui fait tourner une version modifiée comme
service en ligne doit en proposer le code source à ses utilisateurs. Une
**licence commerciale** est disponible pour un usage fermé.

## Ce que qaudit ne fait pas

Il n'exécute jamais de code de stratégie (il constate, il ne rejoue pas) ; il ne
recommande jamais un paramétrage ; il ne devine jamais une règle propfirm ; il
ne fait appel à aucun modèle de langage dans le calcul ni dans le verdict. Ce
n'est pas un conseil en investissement.
