"""
Maison Amarante - API Analyse Bouquets + PWA + Sync
===================================================
v3 - Ajout du système de synchronisation
"""

import os
import json
import requests as req
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta

app = Flask(__name__, static_folder='static')
CORS(app)

# Configuration
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")

# Maison Amarante DB (opérationnel)
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")
AIRTABLE_CLIENTS_TABLE = os.environ.get("AIRTABLE_CLIENTS_TABLE", "tblOJnWeVjfkA7Cfs")
AIRTABLE_LIVRAISONS_TABLE = os.environ.get("AIRTABLE_LIVRAISONS_TABLE", "")  # À remplir

# Suivi Facturation (commercial)
SUIVI_BASE_ID = "appxlOtjRVYqbW85l"
SUIVI_TABLE_ID = "tblkYF6GxgsrdgBRc"

# Valeurs autorisées
COULEURS_VALIDES = ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"]
STYLES_VALIDES = ["Bucolique", "Zen", "Moderne", "Coloré", "Classique"]
TAILLES_VALIDES = ["Petit", "Moyen", "Grand", "Masterpiece"]
SAISONS_VALIDES = ["Printemps", "Été", "Automne", "Hiver", "Toutes saisons"]
PERSONAS_VALIDES = ["Coiffeur", "Bureau", "Hôtel", "Restaurant", "Retail"]
AMBIANCES_VALIDES = ["Romantique", "Épuré", "Festif", "Corporate", "Champêtre", "Luxe"]
FLEURS_VALIDES = ["Rose", "Pivoine", "Hortensia", "Orchidée", "Lys", "Tulipe", "Renoncule", "Dahlia", "Gypsophile", "Lavande", "Anthurium", "Amarante", "Camélia", "Œillet", "Marguerite", "Anémone", "Freesia", "Gerbera", "Iris", "Jasmin", "Jonquille", "Lilas", "Magnolia", "Muguet", "Narcisse", "Pavot", "Protea", "Tournesol", "Zinnia", "Alstroemeria", "Chrysanthème", "Cosmos", "Delphinium", "Gardénia", "Hibiscus", "Jacinthe", "Liseron", "Lotus", "Lisianthus", "Wax flower", "Chardon", "Craspedia", "Statice", "Astilbe", "Agapanthe"]
FEUILLAGES_VALIDES = ["Eucalyptus", "Fougère", "Lierre", "Olivier", "Monstera", "Palmier", "Ruscus", "Asparagus", "Pittosporum", "Saule", "Buis", "Romarin", "Laurier", "Bambou", "Graminées", "Ficus", "Philodendron", "Hosta", "Alocasia", "Calathea", "Cyprès", "Thuya", "Mimosa", "Genêt", "Bruyère", "Salal", "Galax", "Leucadendron", "Viburnum", "Skimmia"]
FREQUENCES_VALIDES = ["Hebdomadaire", "Bimensuel", "Mensuel", "Bimestriel", "Trimestriel", "Semestriel"]
CRENEAUX_VALIDES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Matin", "Après-midi"]

# ==================== HELPERS ====================

def upload_to_imgbb(image_base64: str) -> dict:
    """Upload image to imgbb and return URL"""
    if not IMGBB_API_KEY:
        print("[IMGBB] No API key configured")
        return {"error": "IMGBB_API_KEY not configured"}
    
    print(f"[IMGBB] Uploading image, base64 size: {len(image_base64) / 1024 / 1024:.2f} MB")
    
    response = req.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": IMGBB_API_KEY,
            "image": image_base64
        }
    )
    
    print(f"[IMGBB] Response status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            print(f"[IMGBB] SUCCESS: {data['data']['url']}")
            return {
                "url": data["data"]["url"],
                "delete_url": data["data"]["delete_url"],
                "thumb_url": data["data"]["thumb"]["url"]
            }
    
    print(f"[IMGBB] ERROR: {response.text}")
    return {"error": response.text}


def analyze_image_with_claude(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Analyse une image de bouquet avec Claude Vision"""
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


def parse_client_notes_with_claude(client_name: str, notes: str) -> dict:
    """Parse les notes libres d'un client pour extraire les préférences"""
    if not notes or notes.strip() == "":
        return {}
    
    prompt = f"""Analyse ces notes sur le client "{client_name}" et extrais les informations structurées.

Notes:
{notes}

Réponds UNIQUEMENT en JSON valide avec les champs trouvés (omets les champs non mentionnés):

{{
    "persona": "type de client",
    "frequence": "fréquence de livraison",
    "nb_bouquets": nombre,
    "pref_couleurs": ["couleur1", "couleur2"],
    "pref_style": ["style1"],
    "tailles_demandees": ["taille1"],
    "creneau_prefere": "jour ou moment préféré",
    "adresse": "adresse si mentionnée",
    "email": "email si mentionné",
    "telephone": "téléphone si mentionné",
    "instructions_speciales": "autres instructions importantes"
}}

Valeurs possibles:
- persona: {PERSONAS_VALIDES}
- frequence: {FREQUENCES_VALIDES}
- pref_couleurs: {COULEURS_VALIDES}
- pref_style: {STYLES_VALIDES}
- tailles_demandees: {TAILLES_VALIDES}
- creneau_prefere: {CRENEAUX_VALIDES}

Important: 
- Ne devine pas, extrais uniquement ce qui est explicitement mentionné
- Pour nb_bouquets, mets un nombre entier
- Réponds UNIQUEMENT avec le JSON, sans texte avant ou après"""

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
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    
    if response.status_code != 200:
        print(f"[PARSE] Error: {response.text}")
        return {}
    
    text = response.json()["content"][0]["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "").strip()
    
    try:
        result = json.loads(text)
        # Valider les valeurs
        if result.get("persona") and result["persona"] not in PERSONAS_VALIDES:
            del result["persona"]
        if result.get("frequence") and result["frequence"] not in FREQUENCES_VALIDES:
            del result["frequence"]
        if result.get("pref_couleurs"):
            result["pref_couleurs"] = [c for c in result["pref_couleurs"] if c in COULEURS_VALIDES]
        if result.get("pref_style"):
            result["pref_style"] = [s for s in result["pref_style"] if s in STYLES_VALIDES]
        if result.get("tailles_demandees"):
            result["tailles_demandees"] = [t for t in result["tailles_demandees"] if t in TAILLES_VALIDES]
        if result.get("creneau_prefere") and result["creneau_prefere"] not in CRENEAUX_VALIDES:
            del result["creneau_prefere"]
        return result
    except Exception as e:
        print(f"[PARSE] JSON parse failed: {e}, raw: {text}")
        return {}


# ==================== AIRTABLE HELPERS ====================

def get_airtable_headers():
    return {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json"
    }


def get_suivi_cards():
    """Récupère toutes les cards de Suivi Facturation"""
    url = f"https://api.airtable.com/v0/{SUIVI_BASE_ID}/{SUIVI_TABLE_ID}"
    headers = get_airtable_headers()
    
    all_records = []
    offset = None
    
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[SUIVI] Error fetching cards: {response.text}")
            break
        
        data = response.json()
        all_records.extend(data.get("records", []))
        
        offset = data.get("offset")
        if not offset:
            break
    
    print(f"[SUIVI] Fetched {len(all_records)} cards")
    return all_records


def get_existing_clients():
    """Récupère tous les clients existants dans Maison Amarante DB"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}"
    headers = get_airtable_headers()
    
    all_records = []
    offset = None
    
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[CLIENTS] Error fetching: {response.text}")
            break
        
        data = response.json()
        all_records.extend(data.get("records", []))
        
        offset = data.get("offset")
        if not offset:
            break
    
    # Index par nom et par ID Pennylane
    by_name = {}
    by_pennylane_id = {}
    for record in all_records:
        name = record.get("fields", {}).get("Nom", "")
        pennylane_id = record.get("fields", {}).get("ID_Pennylane", "")
        if name:
            by_name[name.upper()] = record
        if pennylane_id:
            by_pennylane_id[pennylane_id] = record
    
    return by_name, by_pennylane_id


def create_client(fields: dict) -> dict:
    """Crée un client dans Maison Amarante DB"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}"
    headers = get_airtable_headers()
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[CLIENTS] Create error: {response.text}")
        return {"success": False, "error": response.text}


def update_client(record_id: str, fields: dict) -> dict:
    """Met à jour un client existant"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}/{record_id}"
    headers = get_airtable_headers()
    
    response = req.patch(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[CLIENTS] Update error: {response.text}")
        return {"success": False, "error": response.text}


def create_livraison(client_record_id: str, livraison_type: str, notes: str = "") -> dict:
    """Crée une livraison à planifier"""
    if not AIRTABLE_LIVRAISONS_TABLE:
        print("[LIVRAISONS] Table ID not configured")
        return {"success": False, "error": "LIVRAISONS table not configured"}
    
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}"
    headers = get_airtable_headers()
    
    fields = {
        "Client": [client_record_id],
        "Statut": "À planifier",
        "Type": livraison_type
    }
    if notes:
        fields["Notes"] = notes
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[LIVRAISONS] Create error: {response.text}")
        return {"success": False, "error": response.text}


def get_pending_livraisons_for_client(client_record_id: str) -> list:
    """Vérifie si le client a déjà des livraisons en attente"""
    if not AIRTABLE_LIVRAISONS_TABLE:
        return []
    
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}"
    headers = get_airtable_headers()
    
    # Filtre sur le client et statut "À planifier"
    params = {
        "filterByFormula": f"AND(FIND('{client_record_id}', ARRAYJOIN(Client)), Statut = 'À planifier')"
    }
    
    response = req.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json().get("records", [])
    return []


# ==================== SYNC LOGIC ====================

def sync_all():
    """Synchronise Suivi Facturation vers Maison Amarante DB"""
    results = {
        "clients_created": 0,
        "clients_updated": 0,
        "clients_deactivated": 0,
        "livraisons_created": 0,
        "errors": [],
        "details": []
    }
    
    # 1. Récupérer les données
    cards = get_suivi_cards()
    clients_by_name, clients_by_pennylane = get_existing_clients()
    
    # 2. Traiter chaque card
    for card in cards:
        fields = card.get("fields", {})
        client_name = fields.get("Nom du Client", "").strip()
        statut = fields.get("Statut", "")
        notes = fields.get("Notes", "")
        pennylane_id = str(fields.get("ID Pennylane", ""))
        montant = fields.get("Montant", "")
        
        if not client_name:
            continue
        
        # Statuts actifs = à traiter
        active_statuts = ["Factures", "Abonnements", "Essai gratuit"]
        inactive_statuts = ["Archives", "Abonnement arrêté", "Avoirs"]
        
        # Chercher le client existant
        existing_client = clients_by_pennylane.get(pennylane_id) or clients_by_name.get(client_name.upper())
        
        if statut in active_statuts:
            # Parser les notes avec Claude
            parsed = parse_client_notes_with_claude(client_name, notes) if notes else {}
            
            # Construire les champs client
            client_fields = {
                "Nom": client_name,
                "Actif": True
            }
            
            if pennylane_id:
                client_fields["ID_Pennylane"] = pennylane_id
            
            # Ajouter les infos parsées
            if parsed.get("persona"):
                client_fields["Persona"] = parsed["persona"]
            if parsed.get("frequence"):
                client_fields["Fréquence"] = parsed["frequence"]
            if parsed.get("nb_bouquets"):
                client_fields["Nb_Bouquets"] = parsed["nb_bouquets"]
            if parsed.get("pref_couleurs"):
                client_fields["Pref_Couleurs"] = parsed["pref_couleurs"]
            if parsed.get("pref_style"):
                client_fields["Pref_Style"] = parsed["pref_style"]
            if parsed.get("tailles_demandees"):
                client_fields["Tailles_Demandées"] = parsed["tailles_demandees"]
            if parsed.get("creneau_prefere"):
                client_fields["Créneau_Préféré"] = parsed["creneau_prefere"]
            if parsed.get("adresse"):
                client_fields["Adresse"] = parsed["adresse"]
            if parsed.get("instructions_speciales"):
                client_fields["Notes_Spéciales"] = parsed["instructions_speciales"]
            
            # Créer ou mettre à jour le client
            if existing_client:
                record_id = existing_client["id"]
                result = update_client(record_id, client_fields)
                if result["success"]:
                    results["clients_updated"] += 1
                    results["details"].append(f"✏️ Client mis à jour: {client_name}")
                else:
                    results["errors"].append(f"Erreur update {client_name}: {result.get('error')}")
            else:
                # Valeurs par défaut pour nouveau client
                if "Fréquence" not in client_fields:
                    client_fields["Fréquence"] = "Mensuel"
                if "Nb_Bouquets" not in client_fields:
                    client_fields["Nb_Bouquets"] = 1
                
                result = create_client(client_fields)
                if result["success"]:
                    results["clients_created"] += 1
                    results["details"].append(f"✅ Client créé: {client_name}")
                    record_id = result["record"]["id"]
                else:
                    results["errors"].append(f"Erreur création {client_name}: {result.get('error')}")
                    continue
            
            # Créer une livraison si pas déjà en attente
            pending = get_pending_livraisons_for_client(record_id)
            if not pending:
                livraison_type = "Essai gratuit" if statut == "Essai gratuit" else ("Abonnement" if statut == "Abonnements" else "One-shot")
                liv_result = create_livraison(record_id, livraison_type, notes)
                if liv_result["success"]:
                    results["livraisons_created"] += 1
                    results["details"].append(f"📦 Livraison créée pour: {client_name} ({livraison_type})")
        
        elif statut in inactive_statuts:
            # Désactiver le client s'il existe
            if existing_client:
                record_id = existing_client["id"]
                result = update_client(record_id, {"Actif": False})
                if result["success"]:
                    results["clients_deactivated"] += 1
                    results["details"].append(f"❌ Client désactivé: {client_name}")
    
    return results


# ==================== BOUQUETS (existing code) ====================

def get_next_bouquet_id():
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()
    response = req.get(url, headers=headers, params={"pageSize": 100})
    count = len(response.json().get("records", [])) if response.status_code == 200 else 0
    return f"MA-{datetime.now().year}-{count + 1:05d}"


def get_bouquet_by_id(bouquet_id: str) -> dict:
    """Récupère un bouquet par son Bouquet_ID"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()
    params = {"filterByFormula": f"{{Bouquet_ID}} = '{bouquet_id}'"}
    
    response = req.get(url, headers=headers, params=params)
    if response.status_code == 200:
        records = response.json().get("records", [])
        if records:
            return records[0]
    return None


def create_bouquet_in_airtable(data: dict, image_url: str = None) -> dict:
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()
    
    bouquet_id = get_next_bouquet_id()
    
    # URL publique pour le QR code
    public_url = f"https://web-production-37db3.up.railway.app/b/{bouquet_id}"
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={public_url}"
    
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
        "Notes": data.get("description", ""),
        "QR_Code_URL": public_url
    }
    
    if image_url:
        fields["Photo"] = [{"url": image_url}]
        fields["QR_Code"] = [{"url": qr_image_url}]
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        record = response.json()
        return {
            "success": True,
            "bouquet_id": bouquet_id,
            "record_id": record["id"],
            "public_url": public_url,
            "qr_image": qr_image_url
        }
    return {"success": False, "error": response.text}


# ==================== ROUTES ====================

# PWA Routes
@app.route("/")
def index():
    return send_from_directory('static', 'index.html')

@app.route("/admin")
def admin():
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


# Page publique bouquet
@app.route("/b/<bouquet_id>")
def bouquet_page(bouquet_id):
    bouquet = get_bouquet_by_id(bouquet_id)
    
    if not bouquet:
        return f"""
        <!DOCTYPE html>
        <html><head><meta charset="UTF-8"><title>Bouquet non trouvé</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>body{{font-family:system-ui;padding:20px;text-align:center;}}h1{{color:#e74c3c;}}</style>
        </head><body><h1>Bouquet non trouvé</h1><p>Le bouquet {bouquet_id} n'existe pas.</p></body></html>
        """, 404
    
    fields = bouquet.get("fields", {})
    nom = fields.get("Nom", bouquet_id)
    photo_url = ""
    if fields.get("Photo"):
        photo_url = fields["Photo"][0].get("url", "")
    
    style = fields.get("Style", "")
    taille = fields.get("Taille", "")
    couleurs = ", ".join(fields.get("Couleurs", []))
    fleurs = ", ".join(fields.get("Fleurs", []))
    feuillages = ", ".join(fields.get("Feuillages", []))
    statut = fields.get("Statut", "")
    condition = fields.get("Condition", "")
    
    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{nom} - Maison Amarante</title>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{ font-family: system-ui, -apple-system, sans-serif; background: #f5f5f5; min-height: 100vh; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; min-height: 100vh; }}
            .photo {{ width: 100%; aspect-ratio: 1; object-fit: cover; background: #eee; }}
            .content {{ padding: 20px; }}
            h1 {{ font-size: 24px; margin-bottom: 5px; color: #2d3436; }}
            .ref {{ color: #636e72; font-size: 14px; margin-bottom: 20px; }}
            .info {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 15px; }}
            .tag {{ background: #dfe6e9; padding: 6px 12px; border-radius: 20px; font-size: 13px; }}
            .tag.style {{ background: #a29bfe; color: white; }}
            .tag.taille {{ background: #74b9ff; color: white; }}
            .section {{ margin-top: 20px; }}
            .section-title {{ font-size: 12px; text-transform: uppercase; color: #636e72; margin-bottom: 8px; }}
            .section-content {{ color: #2d3436; }}
            .statut {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
            .statut.disponible {{ background: #00b894; color: white; }}
            .statut.service {{ background: #fdcb6e; color: #2d3436; }}
            .logo {{ text-align: center; padding: 20px; color: #b2bec3; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            {'<img src="' + photo_url + '" class="photo" alt="' + nom + '">' if photo_url else '<div class="photo"></div>'}
            <div class="content">
                <h1>{nom}</h1>
                <p class="ref">{bouquet_id}</p>
                <div class="info">
                    {f'<span class="tag style">{style}</span>' if style else ''}
                    {f'<span class="tag taille">{taille}</span>' if taille else ''}
                    <span class="statut {'disponible' if statut == 'Disponible' else 'service'}">{statut}</span>
                </div>
                {f'<div class="section"><div class="section-title">Couleurs</div><div class="section-content">{couleurs}</div></div>' if couleurs else ''}
                {f'<div class="section"><div class="section-title">Fleurs</div><div class="section-content">{fleurs}</div></div>' if fleurs else ''}
                {f'<div class="section"><div class="section-title">Feuillages</div><div class="section-content">{feuillages}</div></div>' if feuillages else ''}
                {f'<div class="section"><div class="section-title">Condition</div><div class="section-content">{condition}/5</div></div>' if condition else ''}
            </div>
            <div class="logo">Maison Amarante</div>
        </div>
    </body>
    </html>
    """


# API Routes
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Maison Amarante API v3"})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Endpoint de synchronisation"""
    try:
        results = sync_all()
        return jsonify(results)
    except Exception as e:
        print(f"[SYNC] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    result = analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg"))
    return jsonify(result)


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
