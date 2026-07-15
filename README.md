# Vaivora Google Merchant feed

Ši repozitorija kasdien sukuria Google Merchant XML iš `https://vaivora.shop/sitemap.xml`.

## Lengviausias įkėlimas: GitHub Desktop

1. Atsisiųskite ir įsidiekite **GitHub Desktop**.
2. GitHub svetainėje atidarykite savo repozitoriją `vaivora-merchant-feed`.
3. Spauskite žalią **Code** mygtuką ir pasirinkite **Open with GitHub Desktop**.
4. Pasirinkite vietą kompiuteryje ir spauskite **Clone**.
5. Atidarykite nuklonuotą aplanką:
   - GitHub Desktop meniu **Repository → Show in Explorer**.
6. Išarchyvuokite šio ZIP turinį tiesiai į tą aplanką.
7. Patvirtinkite failų pakeitimą / perrašymą.
8. Grįžkite į GitHub Desktop.
9. Apačioje kairėje Summary įrašykite: `Add Merchant feed generator`.
10. Spauskite **Commit to main**.
11. Viršuje spauskite **Push origin**.

Tada GitHub svetainėje:

1. Atidarykite **Actions**.
2. Kairėje pasirinkite **Generate Google Merchant feed**.
3. Spauskite **Run workflow**.
4. Sulaukite žalios varnelės.

## GitHub Pages

Po sėkmingo generavimo:

1. **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: **main**
4. Folder: **/public**
5. **Save**

Feed adresas bus:

`https://vaivora-shop.github.io/vaivora-merchant-feed/products.xml`

## Google Merchant Center

Pridėkite naują produktų šaltinį iš URL / Scheduled fetch ir naudokite aukščiau esantį `products.xml` adresą.

## Failų struktūra

```text
.github/workflows/feed.yml
generate_feed.py
requirements.txt
public/.gitkeep
README.md
```
