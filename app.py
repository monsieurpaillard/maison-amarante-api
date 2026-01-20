"""
Maison Amarante - API Analyse Bouquets + PWA
"""

import os
import json
import requests as req
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
from urllib.parse import quote

app = Flask(__name__, static_folder='static')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")

# Base URL for public pages
BASE_URL = os.environ.get("BASE_URL", "https://web-production-37db3.up.railway.app")

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


def get_bouquet_by_id(bouquet_id: str) -> dict:
    """Fetch bouquet from Airtable by Bouquet_ID"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    
    response = req.get(
        url,
        headers=headers,
        params={"filterByFormula": f"{{Bouquet_ID}}='{bouquet_id}'"}
    )
    
    if response.status_code == 200:
        records = response.json().get("records", [])
        if records:
            return records[0].get("fields", {})
    return None


# Public bouquet page (accessible via QR code)
@app.route("/b/<bouquet_id>")
def bouquet_page(bouquet_id):
    """Public page for a bouquet - accessible without Airtable login"""
    bouquet = get_bouquet_by_id(bouquet_id)
    
    if not bouquet:
        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bouquet non trouvé - Maison Amarante</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                       max-width: 500px; margin: 0 auto; padding: 20px; text-align: center; }}
                h1 {{ color: #8B7355; }}
            </style>
        </head>
        <body>
            <h1>🌸 Maison Amarante</h1>
            <p>Bouquet <strong>{bouquet_id}</strong> non trouvé.</p>
        </body>
        </html>
        """, 404
    
    # Get photo URL
    photo_url = ""
    if bouquet.get("Photo") and len(bouquet["Photo"]) > 0:
        photo_url = bouquet["Photo"][0].get("url", "")
    
    # Build tags HTML
    couleurs = bouquet.get("Couleurs", [])
    fleurs = bouquet.get("Fleurs", [])
    feuillages = bouquet.get("Feuillages", [])
    
    couleurs_html = " ".join([f'<span class="tag couleur">{c}</span>' for c in couleurs])
    fleurs_html = " ".join([f'<span class="tag fleur">{f}</span>' for f in fleurs])
    feuillages_html = " ".join([f'<span class="tag feuillage">{f}</span>' for f in feuillages])
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{bouquet.get('Nom', bouquet_id)} - Maison Amarante</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                max-width: 500px; 
                margin: 0 auto; 
                padding: 20px;
                background: #FDFBF7;
                color: #333;
            }}
            .header {{
                text-align: center;
                margin-bottom: 20px;
            }}
            .header h1 {{
                color: #8B7355;
                font-size: 1.5em;
                margin: 0;
            }}
            .header .subtitle {{
                color: #A99B8D;
                font-size: 0.9em;
            }}
            .photo {{
                width: 100%;
                border-radius: 12px;
                margin-bottom: 20px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            }}
            .info {{
                background: white;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 15px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }}
            .info h2 {{
                margin: 0 0 10px 0;
                color: #8B7355;
                font-size: 1.3em;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px solid #F0EBE3;
            }}
            .info-row:last-child {{
                border-bottom: none;
            }}
            .info-label {{
                color: #A99B8D;
            }}
            .info-value {{
                font-weight: 500;
            }}
            .tags {{
                margin-top: 15px;
            }}
            .tags-title {{
                color: #A99B8D;
                font-size: 0.85em;
                margin-bottom: 8px;
            }}
            .tag {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 0.85em;
                margin: 2px;
            }}
            .tag.couleur {{
                background: #F8E8E0;
                color: #C4846C;
            }}
            .tag.fleur {{
                background: #E8F0E8;
                color: #6B8E6B;
            }}
            .tag.feuillage {{
                background: #E0EBE8;
                color: #5B8B7B;
            }}
            .footer {{
                text-align: center;
                color: #A99B8D;
                font-size: 0.8em;
                margin-top: 30px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🌸 Maison Amarante</h1>
            <div class="subtitle">Fleurs en soie d'exception</div>
        </div>
        
        {"<img class='photo' src='" + photo_url + "' alt='Photo du bouquet'>" if photo_url else ""}
        
        <div class="info">
            <h2>{bouquet.get('Nom', 'Bouquet')}</h2>
            <div class="info-row">
                <span class="info-label">Référence</span>
                <span class="info-value">{bouquet_id}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Style</span>
                <span class="info-value">{bouquet.get('Style', '-')}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Taille</span>
                <span class="info-value">{bouquet.get('Taille', '-')}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Saison</span>
                <span class="info-value">{bouquet.get('Saison', '-')}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Statut</span>
                <span class="info-value">{bouquet.get('Statut', '-')}</span>
            </div>
            
            <div class="tags">
                <div class="tags-title">Couleurs</div>
                {couleurs_html if couleurs_html else '<span class="tag couleur">-</span>'}
            </div>
            
            <div class="tags">
                <div class="tags-title">Fleurs</div>
                {fleurs_html if fleurs_html else '<span class="tag fleur">-</span>'}
            </div>
            
            <div class="tags">
                <div class="tags-title">Feuillages</div>
                {feuillages_html if feuillages_html else '<span class="tag feuillage">-</span>'}
            </div>
        </div>
        
        <div class="footer">
            <p>maisonamarante.fr</p>
        </div>
    </body>
    </html>
    """


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
        
        # Public URL for QR code (accessible without Airtable login)
        public_url = f"{BASE_URL}/b/{bouquet_id}"
        
        # Generate QR code image using free API
        qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(public_url)}"
        
        # Update record with QR code image and URL
        req.patch(
            f"{url}/{record_id}",
            headers=headers,
            json={"fields": {
                "QR_Code_URL": public_url,
                "QR_Code": [{"url": qr_image_url}]
            }}
        )
        
        return {
            "success": True,
            "bouquet_id": bouquet_id,
            "record_id": record_id,
            "public_url": public_url,
            "qr_image": qr_image_url
        }
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
