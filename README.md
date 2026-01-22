# Maison Amarante - API Analyse Bouquets

API Flask pour analyser des photos de bouquets avec Claude Vision et créer des fiches dans Airtable.

## Endpoints

### GET /
Health check

### POST /analyze
Analyse une image et retourne les attributs suggérés.

```json
{
  "image_base64": "...",
  "media_type": "image/jpeg"
}
```

### POST /create
Crée un bouquet dans Airtable.

```json
{
  "nom": "Mon bouquet",
  "taille": "Grand",
  "couleurs": ["Rouge", "Blanc"],
  "style": "Classique",
  "saison": "Printemps",
  "personas": ["Coiffeur"],
  "ambiance": ["Romantique"]
}
```

### POST /analyze-and-create
Analyse une image ET crée le bouquet.

## Variables d'environnement

- `ANTHROPIC_API_KEY` - Clé API Anthropic
- `AIRTABLE_API_KEY` - Token Airtable
- `AIRTABLE_BASE_ID` - ID de la base Airtable
- `AIRTABLE_BOUQUETS_TABLE` - ID de la table BOUQUETS
# Force deploy Thu Jan 22 15:30:22 CET 2026
