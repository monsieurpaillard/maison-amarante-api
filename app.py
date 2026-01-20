"""
Maison Amarante - API Analyse Bouquets + PWA
"""

import os
import json
import requests as req
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")

COULEURS_VALIDES = ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"]
STYLES_VALIDES = ["Bucolique", "Zen", "Moderne", "Coloré", "Classique"]
TAILLES_VALIDES = ["Petit", "Moyen", "Grand", "Masterpiece"]
SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver", "Toutes saisons"]
PERSONAS_VALIDES = ["Coiffeur", "Bureau", "Hôtel", "Restaurant", "Retail"]
AMBIANCES_VALIDES = ["Romantique", "Épuré", "Festif", "Corporate", "Champêtre", "Luxe"]
FLEURS_VALIDES = ["Rose", "Pivoine", "Hortensia", "Orchidée", "Lys", "Tulipe", "Renoncule", "Dahlia", "Gypsophile", "Lavande", "Anthurium", "Amarante", "Camélia", "Œillet", "Marguerite", "Anémone", "Freesia", "Gerbera", "Iris", "Jasmin", "Jonquille", "Lilas", "Magnolia", "Muguet", "Narcisse", "Pavot", "Protea", "Tournesol", "Zinnia", "Alstroemeria", "Chrysanthème", "Cosmos", "Delphinium", "Gardénia", "Hibiscus", "Jacinthe", "Liseron", "Lotus", "Lisianthus", "Wax flower", "Chardon", "Craspedia", "Statice", "Astilbe", "Agapanthe"]
FEUILLAGES_VALIDES = ["Eucalyptus", "Fougère", "Lierre", "Olivier", "Monstera", "Palmier", "Ruscus", "Asparagus", "Pittosporum", "Saule", "Buis", "Romarin", "Laurier", "Bambou", "Graminées", "Ficus", "Philodendron", "Hosta", "Alocasia", "Calathea", "Cyprès", "Thuya", "Mimosa", "Genêt", "Bruyère", "Salal", "Galax", "Leucadendron", "Viburnum", "Skimmia"]


def upload_to_imgbb(image_base64: str) -> dict:
    """Upload image to imgbb and return URL"""
    if not IMGBB_API_KEY:
        return {"error": "IMGBB_API_KEY not configured"}
    
    response = req.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": IMGBB_API_KEY,
            "image": image_base64
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            return {
                "url": data["data"]["url"],
                "delete_url": data["data"]["delete_url"],
                "thumb_url": data["data"]["thumb"]["url"]
            }
    return {"error": response.text}


def analyze_image_with_claude(image_base64: str, media_type: str = "image/jpeg") -> dict:
    prompt = f"""Analyse cette photo de bouquet de fleurs en soie.

Réponds UNIQUEMENT en JSON valide:

{{"couleurs": ["couleur1"], "style": "style", "taille_suggeree": "taille", "saison": "saison", "personas": ["persona1"], "ambiance": ["ambiance1"], "fleurs": ["fleur1", "fleur2"], "feuillages": ["feuillage1"], "description": "courte description"}}

Couleurs possibles: {COULEURS_VALIDES}
Styles: {STYLES_VALIDES}
Tailles: {TAILLES_VALIDES}
Saisons: {SAISONS_VALIDES}
Personas: {PERSONAS_VALIDES}
Ambiances: {AMBIANCES_VALIDES}
Fleurs possibles: {FLEURS_VALIDES}
Feuillages possibles: {FEUILLAGES_VALIDES}

Choisis 1-4 couleurs, 1 style, 1 taille, 1 saison, 1-3 personas, 1-2 ambiances.
Liste TOUTES les fleurs et feuillages que tu identifies dans le bouquet."""

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
        result["fleurs"] = [f for f in result.get("fleurs", []) if f in FLEURS_VALIDES]
        result["feuillages"] = [f for f in result.get("feuillages", []) if f in FEUILLAGES_VALIDES]
        return result
    except:
        return {"error": "JSON parse failed", "raw": text}


# PWA Routes
@app.route("/")
def index():
    return send_from_directory('static', 'index.html')

@app.route("/manifest.json")
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route("/sw.js")
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route("/icon-192.png")
def icon_192():
    return send_from_directory('static', 'icon-192.png')

@app.route("/icon-512.png")
def icon_512():
    return send_from_directory('static', 'icon-512.png')


# API Routes
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Maison Amarante Bouquet Analyzer"})


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    result = analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg"))
    return jsonify(result)


def get_next_bouquet_id():
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    response = req.get(url, headers=headers, params={"pageSize": 100})
    count = len(response.json().get("records", [])) if response.status_code == 200 else 0
    return f"MA-{datetime.now().year}-{count + 1:05d}"


def create_bouquet_in_airtable(data: dict, image_url: str = None) -> dict:
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}", "Content-Type": "application/json"}
    
    bouquet_id = get_next_bouquet_id()
    fields = {
        "Bouquet_ID": bouquet_id,
        "Nom": data.get("nom", f"Bouquet {data.get('style', '')}"),
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
        "Fleurs": data.get("fleurs", []),
        "Feuillages": data.get("feuillages", []),
        "Notes": data.get("description", "")
    }
    
    # Add photo if we have an image URL
    if image_url:
        fields["Photo"] = [{"url": image_url}]
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        record = response.json()
        record_id = record["id"]
        
        # Generate QR code URL pointing to Airtable record
        qr_url = f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}/{record_id}"
        
        # Update record with QR code URL
        req.patch(
            f"{url}/{record_id}",
            headers=headers,
            json={"fields": {"QR_Code_URL": qr_url}}
        )
        
        return {"success": True, "bouquet_id": bouquet_id, "record_id": record_id, "qr_url": qr_url}
    return {"success": False, "error": response.text}


@app.route("/analyze-and-create", methods=["POST"])
def analyze_and_create():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    
    # 1. Upload image to imgbb
    image_upload = upload_to_imgbb(data["image_base64"])
    image_url = image_upload.get("url")
    
    # 2. Analyze with Claude
    analysis = analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg"))
    if "error" in analysis:
        return jsonify(analysis), 500
    
    if data.get("nom"):
        analysis["nom"] = data["nom"]
    if data.get("taille"):
        analysis["taille"] = data["taille"]
    
    # 3. Create in Airtable with image URL
    result = create_bouquet_in_airtable(analysis, image_url)
    
    return jsonify({
        "analysis": analysis, 
        "created": result,
        "image_url": image_url
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
