# SPDX-License-Identifier: AGPL-3.0-or-later
"""Noyau déterministe : numpy, scipy, pandas — rien d'autre.

Règles (voir tests/test_architecture.py) :
- aucun import depuis ``qaudit.io``, ``qaudit.cli`` ou ``qaudit.i18n`` ;
- aucun accès réseau ni disque, aucun modèle de langage ;
- toute fonction est pure ; l'aléatoire passe par un ``numpy.random.Generator``
  reçu en paramètre.
"""
