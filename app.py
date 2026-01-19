"""
Maison Amarante - API Analyse Bouquets
======================================
Serveur Flask qui:
1. Reçoit une image de bouquet
2. L'analyse avec Claude Vision
3. Retourne les attributs suggérés (couleurs, style, saison, etc.)
4. Optionnellement crée la fiche dans Airtable
"""

import os
import json
import anthropic
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
# Remove proxy env vars that Railway injects
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(var, None)

app = Flask(__name__)
CORS(app)

# Configuration via variables d'environnement
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")

# Valeurs autorisées
COULEURS_VALIDES = ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"]
STYLES_VALIDES = ["Bucolique", "Zen", "Moderne", "Coloré", "Classique"]
TAILLES_VALIDES = ["Petit", "Moyen", "Grand", "Masterpiece"]
SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver", "Toutes saisons"]
PERSONAS_VALIDES = ["Coiffeur", "Bureau", "Hôtel", "Restaurant", "Retail"]
AMBIANCES_VALIDES = ["Romantique", "Épuré", "Festif", "Corporate", "Champêtre", "Luxe"]


def analyze_image_with_claude(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Analyse une image de bouquet avec Claude Vision"""
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    prompt = f"""Analyse cette photo de bouquet de fleurs en soie pour Maison Amarante (service de location de compositions florales).

Réponds UNIQUEMENT en JSON valide avec cette structure exacte:

{{
    "couleurs": ["couleur1", "couleur2"],
    "style": "style",
    "taille_suggeree": "taille",
    "saison": "saison",
    "personas": ["persona1", "persona2"],
    "ambiance": ["ambiance1"],
    "description": "courte description"
}}

RÈGLES STRICTES:
- "couleurs": 1-4 couleurs dominantes parmi: {COULEURS_VALIDES}
- "style": UN choix parmi: {STYLES_VALIDES}
  (Bucolique=champêtre, Zen=épuré/orchidées, Moderne=graphique, Coloré=vif/multicolore, Classique=roses/pivoines)
- "taille_suggeree": UN choix parmi: {TAILLES_VALIDES} (estime selon les proportions visibles)
- "saison": UN choix parmi: {SAISONS_VALIDES}
- "personas": 1-3 types de clients parmi: {PERSONAS_VALIDES}
- "ambiance": 1-2 ambiances parmi: {AMBIANCES_VALIDES}
- "description": 10-20 mots décrivant le bouquet

Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )
    
    response_text = message.content[0].text.strip()
    
    # Nettoie la réponse si elle contient des backticks
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
    response_text = response_text.strip()
    
    try:
        result = json.loads(response_text)
        
        # Valide et filtre les valeurs
        result["couleurs"] = [c for c in result.get("couleurs", []) if c in COULEURS_VALIDES][:4]
        result["style"] = result.get("style") if result.get("style") in STYLES_VALIDES else "Classique"
        result["taille_suggeree"] = result.get("taille_suggeree") if result.get("taille_suggeree") in TAILLES_VALIDES else "Moyen"
        result["saison"] = result.get("saison") if result.get("saison") in SAISONS_VALIDES else "Toutes saisons"
        result["personas"] = [p for p in result.get("personas", []) if p in PERSONAS_VALIDES][:3]
        result["ambiance"] = [a for a in result.get("ambiance", []) if a in AMBIANCES_VALIDES][:2]
        result["description"] = result.get("description", "")[:200]
        
        return result
        
    except json.JSONDecodeError:
        return {
            "couleurs": ["Blanc"],
            "style": "Classique",
            "taille_suggeree": "Moyen",
            "saison": "Toutes saisons",
            "personas": ["Bureau"],
            "ambiance": ["Épuré"],
            "description": "Analyse automatique échouée",
            "error": "JSON parse error"
        }


def get_next_bouquet_id() -> str:
    """Génère le prochain ID sérialisé"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    
    params = {"pageSize": 100, "fields[]": "Bouquet_ID"}
    total = 0
    offset = None
    
    while True:
        if offset:
            params["offset"] = offset
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            total += len(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        else:
            break
    
    year = datetime.now().year
    return f"MA-{year}-{total + 1:05d}"


def create_bouquet_in_airtable(data: dict) -> dict:
    """Crée un bouquet dans Airtable et retourne le record"""
    
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    bouquet_id = get_next_bouquet_id()
    
    fields = {
        "Bouquet_ID": bouquet_id,
        "Nom": data.get("nom", f"Bouquet {data.get('style', '')} {data.get('couleurs', [''])[0]}"),
        "Taille": data.get("taille", data.get("taille_suggeree", "Moyen")),
        "Couleurs": data.get("couleurs", []),
        "Style": data.get("style", "Classique"),
        "Statut": "Disponible",
        "Condition": 5,
        "Rotations": 0,
        "Date_Création": datetime.now().strftime("%Y-%m-%d"),
        "Saison": data.get("saison", "Toutes saisons"),
        "Personas_Suggérées": data.get("personas", []),
        "Ambiance": data.get("ambiance", []),
        "Notes": f"Analysé par AI: {data.get('description', '')}"
    }
    
    response = requests.post(url, headers=headers, json={"fields": fields})
    
    if response.status_code == 200:
        record = response.json()
        record_id = record["id"]
        
        # Met à jour le QR_Code_URL
        qr_url = f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}/{record_id}"
        requests.patch(
            f"{url}/{record_id}",
            headers=headers,
            json={"fields": {"QR_Code_URL": qr_url}}
        )
        
        return {
            "success": True,
            "bouquet_id": bouquet_id,
            "record_id": record_id,
            "airtable_url": qr_url
        }
    else:
        return {
            "success": False,
            "error": response.text
        }


@app.route("/", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "service": "Maison Amarante Bouquet Analyzer"})


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Analyse une image de bouquet.
    
    Body JSON:
    {
        "image_base64": "...",
        "media_type": "image/jpeg"  // optionnel
    }
    
    Retourne les attributs suggérés par l'IA.
    """
    data = request.json
    
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    
    image_base64 = data["image_base64"]
    media_type = data.get("media_type", "image/jpeg")
    
    try:
        result = analyze_image_with_claude(image_base64, media_type)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/create", methods=["POST"])
def create():
    """
    Crée un bouquet dans Airtable.
    
    Body JSON:
    {
        "nom": "Mon bouquet",  // optionnel
        "taille": "Grand",
        "couleurs": ["Rouge", "Blanc"],
        "style": "Classique",
        "saison": "Printemps",
        "personas": ["Coiffeur"],
        "ambiance": ["Romantique"],
        "description": "..."
    }
    """
    data = request.json
    
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    
    try:
        result = create_bouquet_in_airtable(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze-and-create", methods=["POST"])
def analyze_and_create():
    """
    Analyse une image ET crée le bouquet dans Airtable.
    
    Body JSON:
    {
        "image_base64": "...",
        "media_type": "image/jpeg",  // optionnel
        "nom": "Mon bouquet",  // optionnel
        "taille": "Grand"  // optionnel, sinon utilise la suggestion AI
    }
    """
    data = request.json
    
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    
    try:
        # Analyse
        analysis = analyze_image_with_claude(
            data["image_base64"],
            data.get("media_type", "image/jpeg")
        )
        
        # Merge avec les données fournies (override AI si spécifié)
        bouquet_data = {**analysis}
        if data.get("nom"):
            bouquet_data["nom"] = data["nom"]
        if data.get("taille"):
            bouquet_data["taille"] = data["taille"]
        
        # Crée dans Airtable
        create_result = create_bouquet_in_airtable(bouquet_data)
        
        return jsonify({
            "analysis": analysis,
            "created": create_result
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
