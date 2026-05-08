# V85 Statistik

Hämtar V85-data från ATG och visar statistik i ett Flask-webbgränssnitt.

## Lokal körning

```bash
pip install -r requirements.txt
python fetch.py      # Hämtar historik
python app.py        # Startar på http://localhost:5000
```

## Deploy till Railway

1. Skapa konto på [railway.app](https://railway.app)
2. Klicka "New Project" → "Deploy from GitHub repo"
3. Pusha detta repo till GitHub (se nedan)
4. Lägg till en **Volume** i Railway för persistent databas:
   - Gå till din service → "Add Volume"
   - Mount path: `/data`
   - Lägg till miljövariabel: `DB_PATH=/data/v85.db`
5. Railway driftsätter automatiskt!

## Pusha till GitHub

```bash
git init
git add .
git commit -m "V85 Statistik"
git branch -M main
git remote add origin https://github.com/DITT-ANVÄNDARNAMN/v85-statistik.git
git push -u origin main
```

## Miljövariabler

| Variabel | Beskrivning | Default |
|----------|-------------|---------|
| `DB_PATH` | Sökväg till SQLite-databas | `./v85.db` |
| `PORT` | Port (sätts automatiskt av Railway) | `5000` |
