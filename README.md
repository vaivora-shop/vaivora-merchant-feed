# Vaivora.shop → Google Merchant XML feed

Šis projektas kasdien:

1. perskaito `https://vaivora.shop/sitemap.xml`;
2. atidaro svetainės puslapius;
3. paima produktų duomenis iš `schema.org Product/Offer` JSON-LD;
4. sukuria `public/products.xml`;
5. pateikia XML viešai per GitHub Pages.

## Svarbi pastaba

Generatorius negali patikimai išgalvoti trūkstamų duomenų. Jeigu produkto puslapyje nėra
GTIN/EAN, MPN, prekės ženklo, kainos arba likučio informacijos, ją reikės sutvarkyti
Hostinger parduotuvėje arba papildyti kitu būdu.

## 1. Įkelkite projektą į GitHub

1. Susikurkite nemokamą GitHub paskyrą.
2. Sukurkite naują **Public** repozitoriją, pvz. `vaivora-merchant-feed`.
3. Įkelkite visus šio aplanko failus, išlaikydami katalogų struktūrą.
4. Atidarykite repozitorijos skiltį **Actions**.
5. Pasirinkite **Generate Google Merchant feed** ir spauskite **Run workflow**.

Pirmas vykdymas gali užtrukti, nes nuskaitoma daugiau kaip 800 puslapių.

## 2. Įjunkite GitHub Pages

Repozitorijoje:

1. **Settings → Pages**
2. **Build and deployment → Source: Deploy from a branch**
3. Branch: **main**
4. Folder: **/public**
5. Spauskite **Save**

Po kelių minučių failas turėtų būti pasiekiamas adresu:

`https://JUSU-GITHUB-VARDAS.github.io/vaivora-merchant-feed/products.xml`

Tikslus adresas bus parodytas GitHub Pages nustatymuose.

## 3. Prijunkite prie Google Merchant Center

Merchant Center:

1. Atidarykite **Settings / Data sources** arba **Products → Add products**.
2. Kurkite naują produktų duomenų šaltinį.
3. Rinkitės įkėlimą iš **URL / Scheduled fetch**.
4. Įklijuokite GitHub Pages `products.xml` adresą.
5. Šalis: **Lithuania**, kalba: **Lithuanian**, valiuta: **EUR**.
6. Nustatykite kasdienį nuskaitymą po GitHub užduoties, pvz. 06:00–08:00 Lietuvos laiku.

Pristatymą ir grąžinimus patogiausia nustatyti pačiame Merchant Center paskyros lygiu.

## 4. Patikrinkite pirmą rezultatą

Po GitHub Action vykdymo atidarykite:

- `public/products.xml` – sugeneruotas feed;
- `feed-report.json` – kiek URL nuskaityta, kiek produktų rasta ir kurie URL nepavyko.

Merchant Center diagnostikoje gali atsirasti pastabų dėl:

- trūkstamo GTIN/EAN;
- prekės ženklo;
- kainos ar likučio neatitikimo;
- per mažų / užblokuotų nuotraukų;
- produktų variantų.

Tai nėra XML generatoriaus klaida, jeigu tų duomenų nėra produkto puslapyje.

## Vietinis bandymas

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Greitas testas su 20 sitemap URL:
python generate_feed.py --limit 20 --verbose

# Pilnas generavimas:
python generate_feed.py
```

Rezultatas: `public/products.xml`.

## Kaip keičiami nustatymai

Pagrindinės komandos reikšmės:

```bash
python generate_feed.py \
  --sitemap "https://vaivora.shop/sitemap.xml" \
  --shop-url "https://vaivora.shop/" \
  --output "public/products.xml" \
  --delay 0.20
```

`--delay` yra pauzė tarp puslapių užklausų. Jos mažinti iki nulio nerekomenduojama.
