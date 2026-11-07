# SPDX-License-Identifier: AGPL-3.0-or-later
"""En-têtes MetaTrader 5 dans la langue du terminal → clé canonique anglaise.

MT5 écrit ses rapports (historique de compte, testeur, export CSV) dans la
langue de l'interface ; les valeurs (``buy``/``sell``, ``balance``, ``in``/
``out``) restent anglaises. Les lecteurs MT5 passent chaque en-tête par
``mt5_key`` avant de raisonner : ``Heure`` → ``time``, ``Echange`` → ``swap``,
``Heure d'ouverture`` → ``opentime``…

Langues couvertes : anglais, français, espagnol, allemand, portugais, italien
(alphabet latin ; les accents sont retirés par ``normalise_header``). Une
langue absente tombe sur la porte E1 (correspondance de colonnes), jamais sur
une lecture silencieusement fausse.
"""

from __future__ import annotations

from qaudit.io.readers.common import normalise_header

_ALIASES: dict[str, tuple[str, ...]] = {
    "time": ("time", "heure", "hora", "zeit", "orario", "ora", "uhrzeit"),
    "opentime": (
        "opentime", "heuredouverture", "horadeapertura", "horadeabertura", "eroffnungszeit",
        "orariodiapertura", "openingtime",
    ),
    "closetime": (
        "closetime", "heuredefermeture", "heuredecloture", "horadecierre", "schliesszeit",
        "horadefechamento", "orariodichiusura", "closingtime",
    ),
    "position": ("position", "posicion", "posicao", "posizione"),
    "symbol": ("symbol", "symbole", "simbolo", "item"),
    "type": ("type", "typ", "tipo"),
    "volume": ("volume", "volumen", "size", "taille", "tamano", "grosse", "tamanho", "dimensione"),
    "ticket": ("ticket", "billet", "boleto"),
    "taxes": ("taxes", "taxe", "impuestos", "steuern", "impostos", "tasse"),
    "price": ("price", "prix", "precio", "preis", "preco", "prezzo"),
    "sl": ("sl",),
    "tp": ("tp",),
    "commission": ("commission", "comision", "kommission", "provision", "comissao", "commissione"),
    "swap": ("swap", "echange", "swaps"),
    "profit": ("profit", "beneficio", "gewinn", "lucro", "profitto", "resultado", "ergebnis"),
    "comment": ("comment", "commentaire", "comentario", "kommentar", "commento"),
    "deal": ("deal", "operation", "transaccion", "transaktion", "transacao", "operazione"),
    "direction": ("direction", "direccion", "richtung", "direcao", "direzione"),
    "order": ("order", "ordre", "orden", "auftrag", "ordem", "ordine"),
    "balance": ("balance", "solde", "saldo", "kontostand"),
    "fee": ("fee", "frais", "tarifa", "gebuhr", "taxa", "tassa"),
    "state": ("state", "etat", "estado", "status", "stato"),
    "cost": ("cost", "cout", "coste", "kosten", "custo", "costo"),
}
_LOOKUP: dict[str, str] = {alias: key for key, aliases in _ALIASES.items() for alias in aliases}


def mt5_key(column: str) -> str:
    """Clé canonique d'un en-tête MT5 (suffixe « #n » de désambiguïsation retiré)."""
    normalised = normalise_header(column.split("#")[0])
    return _LOOKUP.get(normalised, normalised)
