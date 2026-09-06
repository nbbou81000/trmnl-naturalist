# TRMNL — Natural History Plates

Affiche au hasard une planche des grandes histoires naturelles illustrées :
radiolaires de Haeckel, insectes de Curtis, métamorphoses de Merian, liliacées
de Redouté, coquillages, oiseaux et poissons. Gravé ou lithographié entre le
XVIIᵉ et le XIXᵉ siècle, domaine public.

```
works.json → collect.py → corpus.json → build.py → docs/img/*.png → Pages → plugin
```

## Pourquoi par ouvrages et non par mots-clés

La Biodiversity Heritage Library a versé 363 000 fichiers sur Wikimedia Commons.
Mais chercher « insect » dans ces métadonnées remonte surtout des rapports
phytosanitaires du ministère de l'Agriculture : cartes de répartition et pages
de texte. Un échantillon de 200 fichiers ainsi collectés ne contenait presque
aucune planche exploitable.

Parcourir la catégorie d'un ouvrage connu pour ses planches donne au contraire
un contenu déjà trié par les contributeurs. 15 ouvrages ≈ 12 700 planches.

## Le rendu, à l'inverse des dessins de brevet

Ces planches sont tonales : aquarelle, lithographie coloriée, gravure ombrée.
Une quantification en 4 niveaux les écrase en aplats. On applique donc
autocontraste puis **tramage Floyd-Steinberg** — exactement ce qu'il fallait
bannir pour le trait pur d'un brevet.

**Il n'existe pas de prétraitement unique.** Un scan à fond noir (Haeckel) et une
gravure pâle (Fauna Japonica) demandent des traitements opposés : le réglage qui
sauve l'un détruit l'autre. Chaque ouvrage étant homogène en interne, `works.json`
porte un profil par ouvrage :

```json
"profile": { "bg": "light", "boost": 1.2, "crop": true, "dither": true }
```

- `bg: dark` désactive la neutralisation du papier, qui inverse la logique sur fond noir.
- `boost` relève le contraste des gravures pâles.
- `crop` active le recadrage intérieur, inopérant sur les scans à bord franc.

Quatre profils sont réglés et vérifiés (Haeckel, Curtis, Conchylien, Fauna
Japonica). Les onze autres sont aux valeurs par défaut et devront être ajustés
à la première collecte, en regardant le résultat.

## Filtres qualité

- `is_photograph` — écarte photos de reliures et couvertures, présentes dans les
  catégories d'ouvrages sans que leur nom de fichier le signale.
- `usable` — écarte formats aberrants, scans trop petits, pages de texte
  (détectées par régularité des bandes horizontales).
- `final_check` — juge la planche **après** traitement : certaines gravures sont
  si pâles que le rendu ne laisse qu'une page blanche, ce qu'un filtre d'entrée
  ne peut pas voir.

## Commons

L'API exige un User-Agent identifiant le projet et fournissant un contact.
Un UA générique reçoit un 429 immédiat.

## Rotation

Aucun serveur. Le plugin ne lit que `docs/count.json` et tire un index avec le
filtre natif `random_number` de TRMNL.
