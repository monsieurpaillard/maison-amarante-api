"""
Maison Amarante - API Analyse Bouquets
"""

import os
import json
import requests as req
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")

COULEURS_VALIDES = ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"]
STYLES_VALIDES = ["Bucolique", "Zen", "Moderne", "Coloré", "Classique"]
TAILLES_VALIDES = ["Petit", "Moyen", "Grand", "Masterpiece"]
SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver", "Toutes saisons"]
PERSONAS_VALIDES = ["Coiffeur", "Bureau", "Hôtel", "Restaurant", "Retail"]
AMBIANCES_VALIDES = ["Romantique", "Épuré", "Festif", "Corporate", "Champêtre", "Luxe"]


def analyze_image_with_claude(image_base64: str, media_type: str = "image/jpeg") -> dict:
    prompt = f"""Analyse cette photo de bouquet de fleurs en soie.

Réponds UNIQUEMENT en JSON valide:

{{"couleurs": ["couleur1"], "style": "style", "taille_suggeree": "taille", "saison": "saison", "personas": ["persona1"], "ambiance": ["ambiance1"], "description": "courte description"}}

Couleurs possibles: {COULEURS_VALIDES}
Styles: {STYLES_VALIDES}
Tailles: {TAILLES_VALIDES}
Saisons: {SAISONS_VALIDES}
Personas: {PERSONAS_VALIDES}
Ambiances: {AMBIANCES_VALIDES}

Choisis 1-4 couleurs, 1 style, 1 taille, 1 saison, 1-3 personas, 1-2 ambiances."""

    response = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1024,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
                    {"type": "text", "text": prompt}
                ]
            }]
        }
    )
    
    if response.status_code != 200:
        return {"error": response.text}
    
    text = response.json()["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "").strip()
    
    try:
        result = json.loads(text)
        result["couleurs"] = [c for c in result.get("couleurs", []) if c in COULEURS_VALIDES][:4]
        result["style"] = result.get("style") if result.get("style") in STYLES_VALIDES else "Classique"
        result["taille_suggeree"] = result.get("taille_suggeree") if result.get("taille_suggeree") in TAILLES_VALIDES else "Moyen"
        result["saison"] = result.get("saison") if result.get("saison") in SAISONS_VALIDES else "Toutes saisons"
        result["personas"] = [p for p in result.get("personas", []) if p in PERSONAS_VALIDES][:3]
        result["ambiance"] = [a for a in result.get("ambiance", []) if a in AMBIANCES_VALIDES][:2]
        return result
    except:
        return {"error": "JSON parse failed", "raw": text}


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Maison Amarante Bouquet Analyzer"})


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    result = analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg"))
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
