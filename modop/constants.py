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