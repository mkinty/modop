"""Extraits BAN et parcelles cadastrales d'une commune.

Deux referentiels sont telecharges, commune par commune, au moment du
traitement :

    - la Base Adresse Nationale (BAN), au format BAL :
      https://plateforme.adresse.data.gouv.fr/ban/communes/<insee>/download/csv-bal/adresses
    - les parcelles cadastrales Etalab :
      https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/<dep>/<insee>/...

Chaque fichier ne couvre que la commune demandee (une centaine de Ko) :
aucun fichier departemental a telecharger puis filtrer.

Les deux sont ecrits en CSV dans le repertoire de travail, comme les autres
couches du projet. Ils entrent donc dans l'archive sans traitement
particulier, et le livrable reste lisible hors ligne : c'est un extrait fige
a la date de l'audit, pas un flux qui evoluerait apres coup.

Les parcelles sont publiees en WGS84 (longitude, latitude). Elles sont
projetees ici en Lambert 93, le systeme du projet et de toutes ses couches :
le calcul d'emprise (`qgis_datasource`) ne reprojette pas, et une couche en
degres fausserait un centrage automatique. La projection Lambert 93 est une
conique conforme de Lambert sur l'ellipsoide GRS80 ; ses formules sont
fermees, d'ou une implementation directe plutot qu'une dependance (pyproj).
RGF93 et WGS84 sont confondus a cette echelle, comme le fait QGIS.

Un referentiel indisponible (reseau coupe, commune inconnue du service) ne
fait pas echouer la commune : il est signale par un avertissement, et le
livrable est produit sans la couche concernee.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from xml.etree import ElementTree

from modop.constants import (
    BAN_LAYER_NAME,
    BAN_URL_TEMPLATE,
    PARCELLES_LAYER_NAME,
    PARCELLES_URL_TEMPLATE,
    REFERENTIELS_TIMEOUT,
)
from modop.path_manager import _ban_csv_path, _parcelles_csv_path

#: Identifiant du client envoye aux services. Generique : aucune donnee
#: personnelle.
_USER_AGENT = "modop-audit-sna/0.1 (python-urllib)"

#: Colonne ajoutee en tete de l'extrait BAN : libelle lisible de l'adresse,
#: pratique pour l'etiquetage et la table attributaire.
BAN_LABEL_FIELD = "adresse"

#: Colonne WKT de l'extrait des parcelles.
PARCELLES_WKT_FIELD = "geometrie"

#: Attributs Etalab repris, dans cet ordre, devant la geometrie.
PARCELLES_FIELDS = ("id", "commune", "prefixe", "section", "numero", "contenance")


class ReferentielError(Exception):
    """Referentiel indisponible ou illisible pour la commune demandee."""


# -- Projection Lambert 93 ---------------------------------------------------

_A = 6378137.0                       # demi-grand axe GRS80
_F = 1 / 298.257222101               # aplatissement GRS80
_E = math.sqrt(2 * _F - _F * _F)     # premiere excentricite
_LON0 = math.radians(3.0)
_X0, _Y0 = 700000.0, 6600000.0


def _m(phi: float) -> float:
    return math.cos(phi) / math.sqrt(1 - (_E * math.sin(phi)) ** 2)


def _t(phi: float) -> float:
    sin_phi = _E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - sin_phi) / (1 + sin_phi)) ** (_E / 2)


_PHI1, _PHI2, _PHI0 = (math.radians(v) for v in (44.0, 49.0, 46.5))
_N = (math.log(_m(_PHI1)) - math.log(_m(_PHI2))) / (math.log(_t(_PHI1)) - math.log(_t(_PHI2)))
_AF = _A * _m(_PHI1) / (_N * _t(_PHI1) ** _N)
_RHO0 = _AF * _t(_PHI0) ** _N


def to_lambert93(lon: float, lat: float) -> tuple[float, float]:
    """Projette une position WGS84 (degres) en Lambert 93 (metres).

    >>> x, y = to_lambert93(3.0, 46.5)
    >>> round(x, 3), round(y, 3)
    (700000.0, 6600000.0)
    """
    rho = _AF * _t(math.radians(lat)) ** _N
    theta = _N * (math.radians(lon) - _LON0)
    return _X0 + rho * math.sin(theta), _Y0 + _RHO0 - rho * math.cos(theta)


# -- Telechargement ------------------------------------------------------------


class _NetworkError(ReferentielError):
    """Serveur injoignable par cette methode (reseau, proxy, TLS, delai).

    A distinguer d'une reponse HTTP du serveur (404...) : celle-ci prouve que
    le reseau fonctionne, une autre methode n'y changerait rien.
    """


#: Delai de la tentative directe. Court : sur un poste d'entreprise, elle
#: echoue par expiration, et chaque seconde est perdue avant le repli.
_DIRECT_TIMEOUT = 15

#: Methode ayant reussi en dernier, essayee en premier ensuite : le delai
#: d'echec de l'autre n'est paye qu'une fois par session, pas par fichier.
_preferred_method: str | None = None


def _download_urllib(url: str, timeout: float) -> bytes:
    """Telechargement Python. Lit le proxy des variables d'environnement et
    du registre, mais ni les scripts PAC ni l'authentification Windows."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 407:
            # Reponse du proxy, pas du serveur : il exige l'authentification
            # Windows, que seule la pile du systeme sait fournir.
            raise _NetworkError("connexion directe : proxy, authentification requise") from error
        raise ReferentielError(f"HTTP {error.code} sur {url}") from error
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise _NetworkError(f"connexion directe : {reason}") from error


#: Script PowerShell : .NET applique la configuration reseau de Windows,
#: celle du navigateur (proxy, script PAC, detection automatique), avec
#: l'authentification de la session et les certificats du magasin Windows.
#: URL et fichier passent par l'environnement : aucun echappement a gerer.
_POWERSHELL_SCRIPT = (
    "$ErrorActionPreference = 'Stop';"
    "[Net.ServicePointManager]::SecurityProtocol = "
    "[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12;"
    "$client = New-Object Net.WebClient;"
    "$client.Headers.Add('User-Agent', $env:MODOP_USER_AGENT);"
    "$proxy = [Net.WebRequest]::GetSystemWebProxy();"
    "$proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials;"
    "$client.Proxy = $proxy;"
    "$client.UseDefaultCredentials = $true;"
    "try { $client.DownloadFile($env:MODOP_URL, $env:MODOP_OUT) }"
    "catch { $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException };"
    " [Console]::Error.WriteLine($e.Message); exit 1 }"
)


def _download_windows(url: str, timeout: float) -> bytes:
    """Telechargement par la pile reseau de Windows (via PowerShell).

    Repli pour les postes d'entreprise ou le navigateur passe par un proxy
    que Python ne sait pas utiliser.
    """
    import subprocess
    import tempfile

    handle, target = tempfile.mkstemp(prefix="modop_", suffix=".tmp")
    os.close(handle)
    env = dict(os.environ, MODOP_URL=url, MODOP_OUT=target, MODOP_USER_AGENT=_USER_AGENT)
    try:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", _POWERSHELL_SCRIPT],
                env=env, capture_output=True, timeout=timeout,
                # Pas de fenetre console qui clignote depuis l'interface.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise _NetworkError(f"via Windows : {error}") from error

        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            if not message or "�" in message:
                message = completed.stderr.decode("cp850", errors="replace").strip()
            message = message.splitlines()[-1] if message else f"code {completed.returncode}"
            raise _NetworkError(f"via Windows : {message}")

        with open(target, "rb") as stream:
            return stream.read()
    finally:
        try:
            os.remove(target)
        except OSError:
            pass


def _download(url: str, timeout: float = REFERENTIELS_TIMEOUT) -> bytes:
    """Telecharge une ressource.

    Essaie d'abord le telechargement Python, puis, sous Windows, la pile
    reseau du systeme, qui suit la configuration du navigateur (proxy
    d'entreprise, script PAC, authentification). La methode qui reussit est
    retenue pour les fichiers suivants.

    Raises:
        ReferentielError: reponse HTTP d'erreur, ou toutes les methodes en
            echec (le message les detaille).
    """
    global _preferred_method

    methods = {"direct": lambda: _download_urllib(url, _DIRECT_TIMEOUT)}
    if os.name == "nt":
        methods["windows"] = lambda: _download_windows(url, timeout)

    order = sorted(methods, key=lambda name: name != _preferred_method)
    failures = []
    for name in order:
        try:
            payload = methods[name]()
        except _NetworkError as error:
            failures.append(str(error))
            continue
        _preferred_method = name
        return payload

    raise ReferentielError(f"telechargement impossible ({' ; '.join(failures)}) : {url}")


def ban_url(insee: str) -> str:
    """URL de l'extrait BAN de la commune."""
    return BAN_URL_TEMPLATE.format(insee=str(insee).strip())


def parcelles_url(insee: str) -> str:
    """URL des parcelles de la commune.

    Le dossier departemental compte trois caracteres pour l'outre-mer
    (971 a 976), deux sinon, Corse comprise (2A, 2B).
    """
    insee = str(insee).strip()
    dep = insee[:3] if insee.startswith("97") else insee[:2]
    return PARCELLES_URL_TEMPLATE.format(dep=dep, insee=insee)


# -- BAN -------------------------------------------------------------------


def _ban_label(row: dict) -> str:
    """Libelle d'une adresse : "12 bis Rue de la Paix"."""
    numero = " ".join(part for part in (row.get("numero", ""), row.get("suffixe", "")) if part)
    voie = row.get("voie_nom") or row.get("lieudit_complement_nom") or ""
    return " ".join(part for part in (numero, voie) if part and part != "99999").strip()


def convert_ban(payload: bytes, insee: str, target: str) -> int:
    """Ecrit l'extrait BAN au format attendu par la couche QGIS.

    Les colonnes BAL sont conservees telles quelles (x, y en Lambert 93,
    separateur ";", decimales a point), precedees d'un libelle lisible. Seules
    les lignes de la commune sont gardees : un fichier BAL peut contenir des
    communes deleguees ou des lignes parasites.

    Returns:
        Nombre d'adresses ecrites.

    Raises:
        ReferentielError: fichier vide, sans coordonnees, ou sans adresse
            pour cette commune.
    """
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    fields = reader.fieldnames or []

    if "x" not in fields or "y" not in fields:
        raise ReferentielError("extrait BAN sans colonnes x / y")

    insee = str(insee).strip()
    rows = []
    for row in reader:
        if row.get("commune_insee", insee) != insee:
            continue
        if not row.get("x") or not row.get("y"):
            continue
        row[BAN_LABEL_FIELD] = _ban_label(row)
        rows.append(row)

    if not rows:
        raise ReferentielError(f"aucune adresse BAN pour la commune {insee}")

    # uid_adresse est un identifiant technique multiligne, inutile a la
    # carte et source d'ennuis pour le lecteur CSV de QGIS.
    output_fields = [BAN_LABEL_FIELD] + [f for f in fields if f != "uid_adresse"]
    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


# -- Parcelles ----------------------------------------------------------------


def _ring_wkt(ring) -> str:
    points = []
    for position in ring:
        x, y = to_lambert93(position[0], position[1])
        points.append(f"{x:.2f} {y:.2f}")
    return "(" + ", ".join(points) + ")"


def _geometry_wkt(geometry: dict) -> str:
    """Geometrie GeoJSON (WGS84) en WKT MULTIPOLYGON (Lambert 93).

    Tout est ecrit en MULTIPOLYGON : une couche a type de geometrie unique
    evite que QGIS n'ecarte les entites d'un autre type.
    """
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    if kind == "Polygon":
        polygons = [coordinates]
    elif kind == "MultiPolygon":
        polygons = coordinates
    else:
        return ""

    parts = [
        "(" + ", ".join(_ring_wkt(ring) for ring in polygon) + ")"
        for polygon in polygons if polygon
    ]
    return f"MULTIPOLYGON ({', '.join(parts)})" if parts else ""


def convert_parcelles(payload: bytes, target: str) -> int:
    """Ecrit les parcelles en CSV, geometrie WKT en Lambert 93.

    Args:
        payload: GeoJSON Etalab, compresse (gzip) ou non.
        target: fichier CSV a ecrire.

    Returns:
        Nombre de parcelles ecrites.

    Raises:
        ReferentielError: contenu illisible ou sans parcelle.
    """
    try:
        if payload[:2] == b"\x1f\x8b":
            payload = gzip.decompress(payload)
        data = json.loads(payload.decode("utf-8"))
    except (OSError, ValueError) as error:
        raise ReferentielError(f"fichier des parcelles illisible ({error})") from error

    features = data.get("features") if isinstance(data, dict) else None
    if not features:
        raise ReferentielError("aucune parcelle dans le fichier telecharge")

    count = 0
    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([*PARCELLES_FIELDS, PARCELLES_WKT_FIELD])
        for feature in features:
            wkt = _geometry_wkt(feature.get("geometry") or {})
            if not wkt:
                continue
            properties = feature.get("properties") or {}
            writer.writerow([*(properties.get(name, "") for name in PARCELLES_FIELDS), wkt])
            count += 1

    if not count:
        os.remove(target)
        raise ReferentielError("aucune parcelle exploitable dans le fichier telecharge")

    return count


# -- Couches QGIS ---------------------------------------------------------------


def _delimitedtext_uri(filename: str, **geometry: str) -> str:
    """URI delimitedtext relative, au meme format que les couches du modele."""
    from urllib.parse import quote

    options = "&".join(f"{key}={quote(value)}" for key, value in geometry.items())
    return (
        f"file:./{quote(filename)}?type=csv&delimiter=;&maxFields=10000&detectTypes=yes"
        f"&{options}&crs=EPSG:2154&spatialIndex=yes&subsetIndex=no&watchFile=no"
    )


@dataclass(frozen=True)
class LayerSpec:
    """Description d'une couche a ajouter au projet si elle y manque."""

    name: str
    datasource: str
    geometry: str      # "Point" ou "Polygon"
    color: str         # "r,g,b,a"


BAN_LAYER = LayerSpec(
    name=BAN_LAYER_NAME,
    datasource=_delimitedtext_uri(f"{BAN_LAYER_NAME}.csv", xField="x", yField="y"),
    geometry="Point",
    color="255,0,255,255",
)

PARCELLES_LAYER = LayerSpec(
    name=PARCELLES_LAYER_NAME,
    datasource=_delimitedtext_uri(f"{PARCELLES_LAYER_NAME}.csv",
                                  wktField=PARCELLES_WKT_FIELD),
    geometry="Polygon",
    color="255,170,0,255",
)


# -- Point d'entree --------------------------------------------------------------


@dataclass
class ReferentielsResult:
    """Bilan des extraits produits pour une commune."""

    adresses: int = 0
    parcelles: int = 0
    layers: list[LayerSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def fetch_referentiels(insee: str, verbose: bool = True) -> ReferentielsResult:
    """Telecharge et ecrit les extraits BAN et parcelles de la commune.

    Les fichiers sont ecrits dans le repertoire de travail, aux noms que
    designe path_manager. Chaque referentiel est independant : l'echec de
    l'un n'empeche pas l'autre.

    Returns:
        Le bilan, dont `layers` liste les couches effectivement produites.
    """
    def log(message: str) -> None:
        if verbose:
            print(message)

    result = ReferentielsResult()

    for spec, url, target, convert, unit in (
        (BAN_LAYER, ban_url(insee), _ban_csv_path(),
         lambda data, path: convert_ban(data, insee, path), "adresse(s)"),
        (PARCELLES_LAYER, parcelles_url(insee), _parcelles_csv_path(),
         convert_parcelles, "parcelle(s)"),
    ):
        try:
            count = convert(_download(url), target)
        except ReferentielError as error:
            message = f"Couche '{spec.name}' non produite : {error}"
            result.warnings.append(message)
            log(f"[ref] ⚠ {message}")
            continue

        if spec is BAN_LAYER:
            result.adresses = count
        else:
            result.parcelles = count
        result.layers.append(spec)
        log(f"[ref] {spec.name} : {count} {unit} -> {os.path.basename(target)}")

    return result


# -- Symbologie par defaut ---------------------------------------------------------


def _option(parent, name: str, value: str) -> None:
    ElementTree.SubElement(parent, "Option", {"name": name, "value": value, "type": "QString"})


def renderer_element(spec: LayerSpec) -> ElementTree.Element:
    """Rendu a symbole unique, au format QGIS 3.

    Points BAN : petit disque plein. Parcelles : contour seul, sans
    remplissage, pour laisser voir les couches dessous et le fond satellite.
    """
    renderer = ElementTree.Element("renderer-v2", {
        "type": "singleSymbol", "symbollevels": "0", "forceraster": "0",
        "enableorderby": "0", "referencescale": "-1",
    })
    symbols = ElementTree.SubElement(renderer, "symbols")
    is_point = spec.geometry == "Point"
    symbol = ElementTree.SubElement(symbols, "symbol", {
        "type": "marker" if is_point else "fill", "name": "0", "alpha": "1",
        "clip_to_extent": "1", "force_rhr": "0", "is_animated": "0", "frame_rate": "10",
    })
    layer = ElementTree.SubElement(symbol, "layer", {
        "class": "SimpleMarker" if is_point else "SimpleFill",
        "enabled": "1", "locked": "0", "pass": "0",
    })
    options = ElementTree.SubElement(layer, "Option", {"type": "Map"})

    if is_point:
        for name, value in (
            ("name", "circle"), ("color", spec.color), ("outline_color", "255,255,255,255"),
            ("outline_style", "solid"), ("outline_width", "0.2"), ("outline_width_unit", "MM"),
            ("size", "1.8"), ("size_unit", "MM"), ("scale_method", "diameter"),
        ):
            _option(options, name, value)
    else:
        for name, value in (
            ("color", "0,0,0,0"), ("style", "no"), ("outline_color", spec.color),
            ("outline_style", "solid"), ("outline_width", "0.3"), ("outline_width_unit", "MM"),
            ("joinstyle", "bevel"),
        ):
            _option(options, name, value)

    ElementTree.SubElement(renderer, "rotation")
    ElementTree.SubElement(renderer, "sizescale")
    return renderer


if __name__ == "__main__":
    # Extraits d'une commune, ecrits dans le repertoire de travail :
    #     uv run python -m modop.services.referentiels 73001
    import sys

    from modop.services.config_io import load_and_apply

    load_and_apply()
    bilan = fetch_referentiels(sys.argv[1] if len(sys.argv) > 1 else "45001")
    print(f"[ref] {bilan.adresses} adresse(s), {bilan.parcelles} parcelle(s)")
