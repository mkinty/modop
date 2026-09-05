# Colonnes sur lesquelles le trie par ordre croissant sera appliqué
ZONE1_COL =  "zone 1"
ZONE2_COL =  "zone 2"
SENS_COL =  "sens"


# Couches candidates pour centrer la carte sur la commune, par ordre de
# preference. Correspondance partielle et insensible a la casse. La premiere
# dont l'emprise est calculable est retenue.
ZOOM_LAYER_CANDIDATES = (
    "carto maillage principal",   # zones du maillage : couvre toute la commune
    "carto maillage nom",
    "carto SNA OK",              # adresses validees, emprise plus resserree
)

# -----------------------------------------------------------------------
# ------ GENERATION DES PPT VIERGES (dossier Analyse) --------------------
# -----------------------------------------------------------------------
# Colonne identifiant chaque ligne de l'audit, reprise du programme BPA : un
# PPT est genere par ligne, nomme d'apres cette valeur.
COL_ID_ERR = "ID erreur"

# Colonne de l'audit completee avec le chemin du PPT correspondant.
COL_LINK = "Lien vers le .ppt"

# Nom de fichier d'un PPT, identique a celui produit par BPA
# (services/traitement.py, faire_ppt()) : "cas_analyse_<ID erreur>.pptx".
PPT_NAME_TEMPLATE = "cas_analyse_{id}.pptx"

# Variables injectees dans le template PPT vierge (cle PPT -> colonne Excel).
# Reprises telles quelles du programme BPA (constantes.py) pour que le meme
# template puisse servir aux deux programmes.
VARIABLES = {
    "INSEE": "INSEE",
    "Adresse": "Adresse",
    "Etat id immeuble": "Etat id immeuble",
    "erreur": "erreur",
    "SNA nb log": "SNA nb log",
    "IPE nb log adresse": "IPE nb log adresse",
    "Street View IA": "Street View IA",
}