# Conditions générales de vente — trame

> **Trame à faire relire et adapter par un juriste de votre juridiction avant
> toute utilisation.** Les crochets `[…]` sont à compléter. Ce texte décrit ce
> que le service fait réellement ; il ne remplace pas un avis juridique
> (statut d'exercice, TVA, droit de la consommation, données personnelles,
> réglementation financière locale).

## 1. Objet

`[Nom commercial]` (« l'Auditeur ») fournit un **audit statistique de résultats
de trading** à partir d'un historique de trades clos remis par le client (« le
Dossier »). L'audit applique la méthode qaudit dans sa version en vigueur à la
date de la commande (document « Méthode qaudit — version `[x.y]` », publié),
au moyen d'un moteur de calcul déterministe.

## 2. Nature du service — ce qu'il n'est pas

L'audit **constate** ; il ne conseille pas. En particulier, l'Auditeur :

- ne fournit aucun conseil en investissement, aucune recommandation d'acheter,
  de vendre, de négocier un système ou de lui allouer un capital ;
- ne recommande aucun paramétrage ni aucune modification du système audité ;
- ne prédit aucune performance future ;
- n'accède ni au code source ni à la logique de la stratégie, et ne l'exécute
  jamais.

Le client reconnaît que le verdict (GO, GO SOUS CONDITIONS, NO-GO) résulte de
seuils fixés à l'avance par la méthode publiée et non d'une appréciation, et
qu'il est **dû et facturé quel qu'il soit**.

## 3. Prestations et prix

| Prestation | Contenu | Prix HT |
|---|---|---|
| Pré-vérification | recevabilité du Dossier (lisibilité, champs, taille d'échantillon) — aucun verdict | gratuit |
| Attestation cessible | audit refait par l'Auditeur sur le Dossier, rapport complet ; si GO, attestation inscrite au registre public, présentable aux tiers acquéreurs | `[390 €]` |
| Portefeuille | audit de plusieurs systèmes avec correction statistique de sélection | sur devis |
| Due diligence | l'ensemble + note de comité | sur devis |
| Licence commerciale | droit d'intégrer le moteur dans un produit ou un service fermé, hors obligations de l'AGPL | sur devis |

Le moteur qaudit lui-même est un logiciel libre (AGPL-3.0-or-later) que le
client peut utiliser gratuitement ; ces conditions ne portent que sur les
prestations ci-dessus. Les prix s'entendent `[hors taxes / TTC]`, payables `[à la commande / à
réception de facture]` par `[moyens de paiement]`.

## 4. Commande et Dossier

La commande est ferme à réception du paiement et d'un Dossier **recevable**
(pré-vérification passée). Le client garantit que le Dossier est un export
complet et non modifié de la plateforme indiquée, et qu'il est autorisé à le
communiquer. Un Dossier tronqué, altéré ou incomplet engage la seule
responsabilité du client ; l'Auditeur signale ce que ses contrôles de cohérence
détectent (trous, doublons, ruine, incohérences de solde) sans pouvoir garantir
l'exhaustivité de ces détections.

## 5. Délai et livraison

Livraison sous `[72 heures]` ouvrées à compter de la réception d'un Dossier
complet et recevable. Les livrables (rapport HTML et PDF, résultats JSON selon
la prestation, attestation le cas échéant) sont remis par `[canal]`.

## 6. Attestation de validation

Une attestation n'est émise que sur verdict **GO**. Elle atteste qu'un fichier
identifié par son empreinte SHA-256 a franchi la méthode dans sa version
indiquée, à une date donnée — et rien d'autre. Elle est inscrite au registre
de l'Auditeur sous une référence unique ; les champs publiés au registre sont
la référence, la date, le nom de système choisi par le client, les versions et
l'empreinte, jamais l'identité du titulaire. Elle devient caduque pour toute
version ultérieure de la méthode. L'attestation « cessible » peut être présentée par le titulaire à des tiers acquéreurs du
système ; toute autre attestation est nominative.

## 7. Nouvel audit

Toute modification du système ou du Dossier donne lieu à un nouvel audit
facturé au tarif en vigueur. Aucune reprise gratuite n'est due au motif que
le verdict déplaît.

## 8. Garantie et remboursement

Si, malgré la pré-vérification, le Dossier se révèle inexploitable après
paiement (porte E1 non résoluble, données invalides), le client est remboursé
intégralement. Aucun autre remboursement n'est dû une fois le rapport livré.

## 9. Confidentialité et données

Le Dossier et les livrables sont confidentiels. Le traitement des données est
décrit dans la « Politique de données » jointe (suppression du fichier source
sous 30 jours, archive sans donnée personnelle, registre sans identité). Le
client autorise `[/ n'autorise pas]` la publication d'une version anonymisée
du rapport à des fins de référence.

## 10. Responsabilité

L'Auditeur est tenu d'une obligation de moyens : appliquer la méthode publiée
au Dossier remis. Sa responsabilité, toutes causes confondues, est limitée au
prix payé pour la prestation concernée. Il ne répond pas des décisions prises
par le client ou par des tiers sur la foi du rapport ou de l'attestation, ni
des pertes de trading, quelle qu'en soit la cause.

## 11. Propriété

Le client est propriétaire de ses données et des livrables qui lui sont remis.
Le moteur, la méthode, les catalogues de textes et la charte des rapports sont
distribués sous licence AGPL-3.0-or-later. Les livrables ne peuvent être
modifiés puis présentés comme émanant de l'Auditeur, et seules les attestations
inscrites à son registre l'engagent.

## 12. Droit applicable et litiges

`[Droit applicable]`, `[juridiction compétente]`, `[médiation le cas échéant]`.

---

Version `[date]`. Ces conditions sont acceptées à la commande.
