# Méthode qaudit — version 1.0

Ce document décrit intégralement la méthode appliquée par qaudit à un historique de trades : les tests, leurs seuils, les règles de décision, les détecteurs de défauts et leurs paramètres. Il est généré automatiquement depuis le fichier de configuration de la méthode : ce qui est écrit ici est exactement ce qui est calculé.

Trois principes. (1) Le moteur calcule tout ce que les données fournies permettent ; l'offre achetée ne change que ce qui est montré, jamais le verdict. (2) Aucune note globale : chaque test a un seuil fixé à l'avance, un seul test échoué suffit à un NO-GO. (3) Déterminisme : mêmes données, même version de méthode, même graine → même rapport à l'octet près, vérifiable par quiconque dispose du fichier.

## Les cinq barrières

Cinq barrières éliminatoires. Une barrière est « déclenchée » (échouée) quand sa valeur franchit le seuil dans le sens indiqué ; une valeur dans la bande d'indécision rend le verdict mais impose une revue humaine (porte E3) ; une barrière non calculable faute de données devient une condition (jamais un succès).

| Barrière | Question posée | Seuil NO-GO | Bande d'indécision |
|---|---|---|---|
| Sharpe dégonflé (DSR) | Le hasard est-il écarté ? | < 50,0 % | [45,0 % ; 55,0 %] |
| Profit factor, 5ᵉ centile du bootstrap par blocs | Et avec de la malchance ? | < 1,00 | [0,95 ; 1,05] |
| Centile du drawdown observé parmi les permutations d'ordre | Les pertes arrivent-elles groupées ? | < 5,00 | [3,00 ; 8,00] |
| p-value contre la nulle sans edge | Un système sans avantage ferait-il aussi bien ? | ≥ 5,0 % | [3,0 % ; 8,0 %] |
| Efficacité walk-forward hors échantillon | Tient-il hors des périodes où il a été réglé ? | < 40,0 % | [35,0 % ; 50,0 %] |

### Le hasard est-il écarté ?

Sharpe dégonflé (Bailey & López de Prado). Le ratio de Sharpe mesure la régularité des gains. Le PSR est la probabilité que le vrai Sharpe soit positif compte tenu du nombre de trades, de l'asymétrie et des queues de la distribution. Le DSR évalue cette probabilité contre le meilleur Sharpe attendu au hasard après N essais (N déclaré par le demandeur, sinon défaut de la méthode) ; la variance des Sharpe entre variantes, si elle n'est pas fournie, est approchée prudemment (approximation de Lo, signalée). Le rapport imprime la courbe du DSR pour N = 1 à 1 000 et le point de bascule.

### Et avec de la malchance ?

Profit factor au 5ᵉ centile du bootstrap par blocs stationnaires (Politis–Romano, longueur de bloc automatique). Les trades sont rééchantillonnés par blocs pour préserver leur dépendance sérielle ; le profit factor est recalculé sur chaque rééchantillon. La barrière regarde le 5ᵉ centile : ce que donnerait la même stratégie dans les scénarios défavorables. Sous 1,00, elle perd de l'argent dans ces scénarios.

### Les pertes arrivent-elles groupées ?

Centile du drawdown observé parmi les permutations d'ordre. Les mêmes trades sont réordonnés aléatoirement ; le profit total est invariant, seul le drawdown change. Le centile est la part des permutations dont le drawdown est inférieur ou égal à celui observé. Un centile très bas signale une courbe trop régulière pour être crédible (ordre arrangé, sélection) ; un centile très haut n'est pas éliminatoire mais signale des pertes groupées, imprimées comme telles.

### Un système sans avantage ferait-il aussi bien ?

p-value contre la nulle « sans edge ». Des systèmes sans aucun avantage sont simulés en conservant les distributions empiriques des gains et des pertes et en neutralisant seulement la fréquence de réussite (taux d'équilibre p₀ = |perte moyenne| / (gain moyen + |perte moyenne|)). La p-value est la part de ces systèmes qui atteignent au moins le profit net observé. Ce n'est pas une nulle de marché efficient : la question posée est « le taux de réussite observé est-il explicable par la chance, à profil de gains/pertes donné ? ».

### Tient-il hors des périodes où il a été réglé ?

Efficacité walk-forward. Le demandeur fournit un jeu de résultats par paramètres testés ; la méthode découpe la période en plis (protocole ancré ou glissant), sélectionne sur chaque pli le paramétrage selon le critère fixé, et mesure la performance du paramétrage sélectionné sur le pli suivant, jamais vu. L'efficacité est le rapport de la performance hors échantillon à la performance dans l'échantillon. L'auditeur n'exécute aucune stratégie : il compare des résultats fournis.

## Règles de décision

- 1 constat bloquant ou plus → NO-GO.
- Une barrière déclenchée → NO-GO.
- 3 constats majeurs ou plus → GO SOUS CONDITIONS au mieux.
- Une barrière non évaluée (données manquantes) → condition ; le verdict ne peut pas être GO.
- Une valeur dans la bande d'indécision → verdict rendu, revue humaine requise (porte E3).
- Moins de 30 trades utilisables → constat bloquant « échantillon insuffisant ».

Il n'existe ni pondération ni score composite : les barrières ne se compensent pas.

## Détecteurs structurels

Onze détecteurs structurels examinent la façon de trader. Huit fonctionnent sans série de prix ; trois (géométrie du stop, look-ahead, réalisme d'exécution) exigent les cotations OHLC de l'instrument et sont déclarés « non exécutés » sinon. Chaque détecteur émet un constat de gravité info, mineur, majeur ou bloquant selon les paramètres ci-dessous ; un détecteur qui ne peut pas tourner le dit.

| Détecteur | Ce qu'il détecte | Paramètres |
|---|---|---|
| Mise augmentée après les pertes (`martingale`) | Augmentation du volume après une perte (rapport de volume ≥ ratio_min), sur une part des trades post-perte ; contraste exigé avec le comportement après gain. | ratio_min = 1,5, min_events = 10, major_share = 0,3, blocking_share = 0,6, contrast_min = 0,15 |
| Positions empilées contre le marché (`grid`) | Ajout de positions à une position perdante de même sens à prix pire, refermées ensemble (panier) ; part des trades concernés. | min_depth = 1, major_share = 0,15, blocking_share = 0,35, min_trades = 20, basket_close_seconds = 120 |
| Trades sans stop de protection (`no_stop`) | Part des trades sans stop-loss renseigné. | minor_share = 0,1, major_share = 0,5 |
| Profit porté par quelques trades (`profit_concentration`) | Part du gain brut apportée par les meilleurs trades (top_fraction) ; profit net une fois retirés les meilleurs (remove_fraction). | top_fraction = 0,05, share_major = 0,7, remove_fraction = 0,01, min_trades = 30 |
| Courbe de gains trop régulière (`equity_linearity`) | Courbe d'equity anormalement linéaire : R² contre l'indice du trade au-dessus de r2_major. | r2_major = 0,995, min_trades = 50 |
| Beaucoup de petits gains, quelques grosses pertes (`payoff_asymmetry`) | Taux de réussite très élevé combiné à un ratio gain moyen / perte moyenne très faible. | win_rate_major = 0,85, payoff_major = 0,2, win_rate_blocking = 0,95, payoff_blocking = 0,1, min_trades = 30 |
| Résultat dû à une seule période (`period_dependence`) | Part du profit net apportée par un seul trimestre, sur au moins min_periods trimestres. | min_periods = 4, share_major = 0,8 |
| Durées de position irréalistes (`holding_time`) | Durées de position irréalistes : part des trades de moins de min_seconds, ou de plus de max_days. | min_seconds = 1, short_share_major = 0,1, short_share_blocking = 0,5, max_days = 365, long_share_minor = 0,1 |
| Stop trop sensible (`stop_geometry`) | Avec prix : part du gain brut qui disparaît si le stop est resserré de 10 %, 20 %, 30 %. | collapse_major = 0,5, min_trades = 30, min_aligned_share = 0,5 |
| Entrées trop parfaites (`lookahead`) | Avec prix : part des entrées exactement au plus bas / plus haut de leur barre, testée contre le hasard (p-value). | tick_bps = 1, min_share = 0,05, p_major = 0,01, p_blocking = 0,001, min_aligned_share = 0,5, min_trades = 30 |
| Prix d'exécution impossibles (`execution_realism`) | Avec prix : part des prix d'entrée ou de sortie hors de la fourchette haut–bas de leur barre (tolérance en points de base). | tolerance_bps = 3, minor_share = 0,01, major_share = 0,05, blocking_share = 0,2, min_aligned_share = 0,5 |

Les paramètres sont nommés comme dans le fichier de méthode ; les parts sont des fractions (0,30 = 30 %).

## Simulations et paramètres

- 10 000 itérations pour le bootstrap, la permutation et la nulle, chacune sur un flux aléatoire indépendant dérivé de la graine (rangs fixes).
- Bootstrap : blocs stationnaires (Politis-Romano), longueur automatique.
- Permutation d'ordre : le tableau d'entrée n'est jamais modifié ; le profit total est invariant.
- Nulle sans edge : distributions empiriques des gains et des pertes conservées, fréquence neutralisée.
- Nombre d'essais par défaut : 10 ; grille de sensibilité : 1, 10, 50, 100, 300, 1000.
- Walk-forward : 5 plis, protocole ancré, sélection au profit net.
- Régimes : terciles de volatilité sur 20 trades (sans prix) ou d'ATR sur 14 barres (avec prix).
- Rejeu propfirm : trajectoires de journées de trading rééchantillonnées par blocs ; horizon des phases sans limite : 250 journées.
- Validation : un trou de plus de 30 jours entre deux clôtures est signalé.
- Graine par défaut 0, imprimée dans chaque rapport ; aucune source d'aléa globale.

## Entrées

Entrée obligatoire : les trades clos (heure d'ouverture, heure de clôture, profit net ; utiles : volume, sens, symbole, prix, stop, ticket, commission, swap). Entrées optionnelles : série de prix OHLC (active les trois détecteurs à prix et les régimes par ATR), un jeu de résultats par paramètres testés (active la barrière walk-forward), un règlement propfirm structuré (active le rejeu), le nombre de variantes essayées (N ; défaut de la méthode sinon).

## Ce que la méthode ne teste pas

- Seuls les trades clos sont analysés : le P&L flottant et les positions ouvertes sont inconnus.
- Sans série de prix, la sensibilité du stop, le look-ahead et le réalisme d'exécution ne sont pas testés — le rapport le dit.
- Sans jeu de résultats par paramètres, la robustesse hors échantillon n'est pas établie : le verdict ne peut pas être GO.
- La méthode ne peut pas prouver qu'un historique n'a pas été tronqué au-delà de ses contrôles de cohérence (trous, ruine, doublons).
- Aucune performance future n'est prédite ; un avantage réel peut disparaître.
- Aucun paramétrage n'est recommandé ; l'auditeur constate.

## Versionnement

Version courante : 1.0. Tout changement d'un seuil, d'une bande ou d'un paramètre de détecteur crée une nouvelle version de méthode ; la version est imprimée dans chaque rapport et chaque attestation, qui ne valent que pour elle.

## Reproduire un rapport

Pour reproduire un rapport : le même fichier de trades (son empreinte SHA-256 est imprimée), la même version de qaudit et de méthode, la même graine (imprimée). La commande « qaudit render --from archive.json » régénère les livrables depuis l'archive sans aucun recalcul et produit les mêmes octets que l'audit d'origine.
