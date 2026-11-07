# Politique de données — audits qaudit

Ce que l'auditeur reçoit, ce qu'il en fait, ce qu'il garde. Chaque engagement
ci-dessous correspond à un comportement du moteur ou à une pratique de dossier
vérifiable.

## Ce que contient un fichier de trades

Un export de plateforme contient souvent plus que des trades : le rapport
d'historique MetaTrader 5 porte **le nom du titulaire, le numéro de compte, le
courtier et le serveur** dans son en-tête ; un export Deriv porte des
identifiants de contrat. Le moteur n'a besoin d'aucune de ces données : il lit
les trades clos (heures, symbole, sens, volume, prix, stops, profit) et, s'ils
sont présents, la devise et le dépôt initial.

## Ce qui est conservé, et sous quelle forme

| Élément | Conservé ? | Contenu personnel ? |
|---|---|---|
| Fichier source (export de plateforme) | **supprimé après livraison** (voir délai ci-dessous) | oui (nom, compte) |
| Archive JSON de l'audit (`archive/<système>.json`) | conservée | non : nom de système choisi par le client, empreinte SHA-256 du fichier, chiffres calculés ; aucun nom, aucun numéro de compte, aucun trade individuel |
| Livrables (HTML, PDF, attestation) | conservés | seulement le nom de système et, sur l'attestation, le titulaire déclaré par le client |
| Registre des attestations | conservé indéfiniment | référence, date, nom de système, empreinte, versions ; le titulaire n'est **jamais** publié |
| Correspondance de colonnes mémorisée (`~/.qaudit/mappings`) | conservée | non : noms de colonnes et empreinte d'en-tête uniquement |

Délai de suppression du fichier source : **30 jours** après la livraison, sauf
demande contraire écrite du client (par exemple pour une contestation en
cours). Après suppression, l'audit reste reproductible par quiconque détient
le fichier d'origine — c'est le client, pas l'auditeur, qui en garde la
maîtrise.

## Ce que l'empreinte permet et ne permet pas

L'empreinte SHA-256 imprimée dans chaque rapport identifie le fichier audité
sans en révéler le contenu : elle ne permet ni de reconstituer les trades, ni
d'identifier le titulaire. Elle permet à un tiers qui détient le même fichier
de vérifier qu'il s'agit bien de celui qui a été audité.

## Nom de système

Le client choisit le nom sous lequel son système apparaît dans le rapport, dans
l'attestation et au registre public. Recommandation : un nom de stratégie, pas
un nom de personne ni un numéro de compte.

## Transmission

Les fichiers transitent par le canal convenu avec le client (courriel chiffré,
dépôt de fichiers, remise directe). L'auditeur ne téléverse aucun fichier
client vers un service tiers d'analyse : le moteur tourne hors ligne, sur le
poste de l'auditeur, sans appel réseau ni modèle de langage.

## Droits du client

À tout moment, le client peut demander : la suppression anticipée du fichier
source ; la copie de son archive JSON et de ses livrables ; le retrait de son
attestation du registre public (l'entrée est alors marquée retirée, jamais
effacée, pour que la numérotation reste continue et vérifiable).

## Ce que cette politique ne couvre pas

Les obligations légales propres au pays d'exercice (registre des traitements,
mentions d'information, durées légales de conservation des pièces comptables)
s'ajoutent à ce document et doivent être établies avec un conseil juridique
local.
