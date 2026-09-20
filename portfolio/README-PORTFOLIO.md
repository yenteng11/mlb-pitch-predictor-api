# Add MLB Pitch Predictor to a GitHub Pages portfolio

This version is split into two pieces so it works with a static personal website:

1. **Portfolio frontend** — `portfolio/mlb-predictor.html` can live directly in your GitHub Pages repository.
2. **API backend** — `app.py` runs on Render/Railway and retrieves Baseball Savant / MLB data.

## Recommended setup

### 1. Deploy the API
Deploy this repository to Render using `render.yaml`. The backend exposes:

- `/api/pitchers`
- `/api/predict`
- `/health`

After deployment you will get a URL such as:

```text
https://mlb-pitch-predictor.onrender.com
```

### 2. Configure the portfolio page
Open `portfolio/mlb-predictor.html` and change:

```js
window.MLB_PREDICTOR_API_BASE = "https://YOUR-API-URL-HERE";
```

to your deployed backend URL.

### 3. Put it into your GitHub Pages repository
Copy `portfolio/mlb-predictor.html` into your personal website repository. For example:

```text
index.html
projects.html
mlb-predictor.html
assets/
```

Then link to it from your Projects section:

```html
<a href="mlb-predictor.html">Open MLB Pitch Predictor</a>
```

## CORS

The backend supports browser requests from a separate static site. By default it accepts all origins. For production, set the Render environment variable:

```text
ALLOWED_ORIGINS=https://YOUR-USERNAME.github.io,https://your-custom-domain.com
```

## Alternative: embed it as an iframe

If you prefer the full app to remain hosted externally, see `portfolio/iframe-embed.html`. Replace the placeholder URL and paste the iframe into your Projects page.

## Local testing

Start the API:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

For local frontend testing, temporarily set:

```js
window.MLB_PREDICTOR_API_BASE = "http://127.0.0.1:8000";
```

Then serve the portfolio folder with a local static server rather than opening the HTML using `file://`:

```bash
cd portfolio
python3 -m http.server 8080
```

Open `http://127.0.0.1:8080/mlb-predictor.html`.
