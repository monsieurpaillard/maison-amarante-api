"""
Maison Amarante - API v4
========================
- Sync Pennylane → Airtable
- Planification des tournées
- Facturation post-livraison
- Plus besoin de Make !
"""

import os
import json
import requests as req
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__, static_folder='static')
CORS(app)

# ==================== CONFIGURATION ====================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")
PENNYLANE_API_KEY = os.environ.get("PENNYLANE_API_KEY")

# Maison Amarante DB (opérationnel)
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "app4EHdsU0Z4hr8Bc")
AIRTABLE_BOUQUETS_TABLE = os.environ.get("AIRTABLE_BOUQUETS_TABLE", "tblIO7x8iR01vO5Bx")
AIRTABLE_CLIENTS_TABLE = os.environ.get("AIRTABLE_CLIENTS_TABLE", "tblOJnWeVjfkA7Cfs")
AIRTABLE_LIVRAISONS_TABLE = os.environ.get("AIRTABLE_LIVRAISONS_TABLE", "tbltyDn0VUIbasYtx")

# Suivi Facturation (pipe commercial)
SUIVI_BASE_ID = "appxlOtjRVYqbW85l"
SUIVI_TABLE_ID = "tblkYF6GxgsrdgBRc"

# Pennylane API base URL
PENNYLANE_API_URL = "https://app.pennylane.com/api/external/v2"

# Valeurs autorisées
COULEURS_VALIDES = ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"]
STYLES_VALIDES = ["Bucolique", "Zen", "Moderne", "Coloré", "Classique"]
TAILLES_VALIDES = ["Petit", "Moyen", "Grand", "Masterpiece"]
PERSONAS_VALIDES = ["Coiffeur", "Bureau", "Hôtel", "Restaurant", "Retail"]
FREQUENCES_VALIDES = ["Hebdomadaire", "Bimensuel", "Mensuel", "Bimestriel", "Trimestriel", "Semestriel"]
CRENEAUX_VALIDES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Matin", "Après-midi"]

# ==================== PENNYLANE HELPERS ====================

def get_pennylane_headers():
    return {
        "Authorization": f"Bearer {PENNYLANE_API_KEY}",
        "Content-Type": "application/json"
    }


def pennylane_get_customers():
    """Récupère tous les clients depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/customers"
    headers = get_pennylane_headers()
    
    all_customers = []
    page = 1
    
    while True:
        response = req.get(url, headers=headers, params={"page": page, "per_page": 100})
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching customers: {response.text}")
            break
        
        data = response.json()
        customers = data.get("items", [])
        all_customers.extend(customers)
        
        if len(customers) < 100:
            break
        page += 1
    
    print(f"[PENNYLANE] Fetched {len(all_customers)} customers")
    return all_customers


def pennylane_get_quotes():
    """Récupère tous les devis depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/quotes"
    headers = get_pennylane_headers()
    
    all_quotes = []
    page = 1
    
    while True:
        response = req.get(url, headers=headers, params={"page": page, "per_page": 100})
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching quotes: {response.text}")
            break
        
        data = response.json()
        quotes = data.get("items", [])
        all_quotes.extend(quotes)
        
        if len(quotes) < 100:
            break
        page += 1
    
    print(f"[PENNYLANE] Fetched {len(all_quotes)} quotes")
    return all_quotes


def pennylane_get_invoices():
    """Récupère toutes les factures depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/customer_invoices"
    headers = get_pennylane_headers()
    
    all_invoices = []
    page = 1
    
    while True:
        response = req.get(url, headers=headers, params={"page": page, "per_page": 100})
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching invoices: {response.text}")
            break
        
        data = response.json()
        invoices = data.get("items", [])
        all_invoices.extend(invoices)
        
        if len(invoices) < 100:
            break
        page += 1
    
    print(f"[PENNYLANE] Fetched {len(all_invoices)} invoices")
    return all_invoices


def pennylane_get_subscriptions():
    """Récupère tous les abonnements depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/billing_subscriptions"
    headers = get_pennylane_headers()
    
    all_subs = []
    page = 1
    
    while True:
        response = req.get(url, headers=headers, params={"page": page, "per_page": 100})
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching subscriptions: {response.text}")
            break
        
        data = response.json()
        subs = data.get("billing_subscriptions", [])
        all_subs.extend(subs)
        
        if len(subs) < 100:
            break
        page += 1
    
    print(f"[PENNYLANE] Fetched {len(all_subs)} subscriptions")
    return all_subs


def pennylane_create_invoice(customer_id: int, amount: float, label: str, send_email: bool = True) -> dict:
    """Crée et envoie une facture one-shot"""
    url = f"{PENNYLANE_API_URL}/customer_invoices"
    headers = get_pennylane_headers()
    
    payload = {
        "customer_id": customer_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "deadline": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "draft": False,  # Facture finalisée
        "invoice_lines": [
            {
                "label": label,
                "quantity": 1,
                "unit": "piece",
                "raw_currency_unit_price": str(amount),
                "vat_rate": "FR_200"  # TVA 20%
            }
        ]
    }
    
    response = req.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        invoice = response.json()
        print(f"[PENNYLANE] Invoice created: {invoice.get('id')}")
        
        # Envoyer par email si demandé
        if send_email and invoice.get('id'):
            send_url = f"{PENNYLANE_API_URL}/customer_invoices/{invoice['id']}/send_by_email"
            req.post(send_url, headers=headers)
            print(f"[PENNYLANE] Invoice sent by email")
        
        return {"success": True, "invoice": invoice}
    else:
        print(f"[PENNYLANE] Error creating invoice: {response.text}")
        return {"success": False, "error": response.text}


def pennylane_create_subscription(customer_id: int, amount: float, label: str, start_date: str = None) -> dict:
    """Crée un abonnement mensuel"""
    url = f"{PENNYLANE_API_URL}/billing_subscriptions"
    headers = get_pennylane_headers()
    
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    
    payload = {
        "customer_id": customer_id,
        "start": start_date,
        "recurring_rule": "monthly",
        "invoice_lines": [
            {
                "label": label,
                "quantity": 1,
                "unit": "piece",
                "raw_currency_unit_price": str(amount),
                "vat_rate": "FR_200"
            }
        ],
        "send_email": True
    }
    
    response = req.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        subscription = response.json()
        print(f"[PENNYLANE] Subscription created: {subscription.get('id')}")
        return {"success": True, "subscription": subscription}
    else:
        print(f"[PENNYLANE] Error creating subscription: {response.text}")
        return {"success": False, "error": response.text}


def pennylane_create_invoice_from_quote(quote_id: int, send_email: bool = True) -> dict:
    """Crée une facture à partir d'un devis existant"""
    url = f"{PENNYLANE_API_URL}/customer_invoices/create_from_quote"
    headers = get_pennylane_headers()
    
    payload = {
        "quote_id": quote_id,
        "draft": False
    }
    
    response = req.post(url, headers=headers, json=payload)
    if response.status_code in [200, 201]:
        invoice = response.json()
        print(f"[PENNYLANE] Invoice created from quote: {invoice.get('id')}")
        
        if send_email and invoice.get('id'):
            send_url = f"{PENNYLANE_API_URL}/customer_invoices/{invoice['id']}/send_by_email"
            req.post(send_url, headers=headers)
        
        return {"success": True, "invoice": invoice}
    else:
        print(f"[PENNYLANE] Error creating invoice from quote: {response.text}")
        return {"success": False, "error": response.text}


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


def create_suivi_card(fields: dict) -> dict:
    """Crée une card dans Suivi Facturation"""
    url = f"https://api.airtable.com/v0/{SUIVI_BASE_ID}/{SUIVI_TABLE_ID}"
    headers = get_airtable_headers()
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[SUIVI] Create error: {response.text}")
        return {"success": False, "error": response.text}


def update_suivi_card(record_id: str, fields: dict) -> dict:
    """Met à jour une card dans Suivi Facturation"""
    url = f"https://api.airtable.com/v0/{SUIVI_BASE_ID}/{SUIVI_TABLE_ID}/{record_id}"
    headers = get_airtable_headers()
    
    response = req.patch(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[SUIVI] Update error: {response.text}")
        return {"success": False, "error": response.text}


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
            by_pennylane_id[str(pennylane_id)] = record
    
    return by_name, by_pennylane_id, all_records


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


def get_livraisons():
    """Récupère toutes les livraisons"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}"
    headers = get_airtable_headers()
    
    all_records = []
    offset = None
    
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[LIVRAISONS] Error fetching: {response.text}")
            break
        
        data = response.json()
        all_records.extend(data.get("records", []))
        
        offset = data.get("offset")
        if not offset:
            break
    
    return all_records


def create_livraison(fields: dict) -> dict:
    """Crée une livraison"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}"
    headers = get_airtable_headers()
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[LIVRAISONS] Create error: {response.text}")
        return {"success": False, "error": response.text}


def update_livraison(record_id: str, fields: dict) -> dict:
    """Met à jour une livraison"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}/{record_id}"
    headers = get_airtable_headers()
    
    response = req.patch(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "record": response.json()}
    else:
        print(f"[LIVRAISONS] Update error: {response.text}")
        return {"success": False, "error": response.text}


# ==================== CLAUDE HELPERS ====================

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

Important: Ne devine pas, extrais uniquement ce qui est explicitement mentionné."""

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
        return json.loads(text)
    except Exception as e:
        print(f"[PARSE] JSON parse failed: {e}")
        return {}


# ==================== SYNC LOGIC ====================

def sync_pennylane_to_suivi():
    """Synchronise Pennylane → Suivi Facturation"""
    results = {
        "quotes_synced": 0,
        "invoices_synced": 0,
        "subscriptions_synced": 0,
        "errors": [],
        "details": []
    }
    
    # Récupérer les cards existantes
    existing_cards = get_suivi_cards()
    existing_by_pennylane_id = {}
    for card in existing_cards:
        pid = card.get("fields", {}).get("ID Pennylane", "")
        if pid:
            existing_by_pennylane_id[str(pid)] = card
    
    # Sync devis
    quotes = pennylane_get_quotes()
    for quote in quotes:
        quote_id = str(quote.get("id", ""))
        if quote_id and quote_id not in existing_by_pennylane_id:
            customer_name = quote.get("customer", {}).get("name", "Client inconnu")
            amount = quote.get("amount", 0)
            
            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": quote_id,
                "Montant": f"€{amount}",
                "Statut": "Devis",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            
            result = create_suivi_card(card_fields)
            if result["success"]:
                results["quotes_synced"] += 1
                results["details"].append(f"📋 Devis ajouté: {customer_name}")
    
    # Sync factures
    invoices = pennylane_get_invoices()
    for invoice in invoices:
        invoice_id = str(invoice.get("id", ""))
        if invoice_id and invoice_id not in existing_by_pennylane_id:
            customer_name = invoice.get("customer", {}).get("name", "Client inconnu")
            amount = invoice.get("amount", invoice.get("currency_amount", 0))
            
            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": invoice_id,
                "Montant": f"€{amount}",
                "Statut": "Factures",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            
            result = create_suivi_card(card_fields)
            if result["success"]:
                results["invoices_synced"] += 1
                results["details"].append(f"🧾 Facture ajoutée: {customer_name}")
    
    # Sync abonnements
    subscriptions = pennylane_get_subscriptions()
    for sub in subscriptions:
        sub_id = str(sub.get("id", ""))
        if sub_id and sub_id not in existing_by_pennylane_id:
            customer_name = sub.get("customer", {}).get("name", "Client inconnu")
            
            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": sub_id,
                "Statut": "Abonnements",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            
            result = create_suivi_card(card_fields)
            if result["success"]:
                results["subscriptions_synced"] += 1
                results["details"].append(f"🔄 Abonnement ajouté: {customer_name}")
    
    return results


def sync_suivi_to_clients():
    """Synchronise Suivi Facturation → Maison Amarante DB (CLIENTS)"""
    results = {
        "clients_created": 0,
        "clients_updated": 0,
        "clients_deactivated": 0,
        "livraisons_created": 0,
        "errors": [],
        "details": []
    }
    
    cards = get_suivi_cards()
    clients_by_name, clients_by_pennylane, _ = get_existing_clients()
    
    active_statuts = ["Factures", "Abonnements", "Essai gratuit", "À livrer"]
    inactive_statuts = ["Archives", "Abonnement arrêté", "Avoirs"]
    
    for card in cards:
        fields = card.get("fields", {})
        client_name = fields.get("Nom du Client", "").strip()
        statut = fields.get("Statut", "")
        notes = fields.get("Notes", "")
        pennylane_id = str(fields.get("ID Pennylane", ""))
        
        if not client_name:
            continue
        
        existing_client = clients_by_pennylane.get(pennylane_id) or clients_by_name.get(client_name.upper())
        
        if statut in active_statuts:
            parsed = parse_client_notes_with_claude(client_name, notes) if notes else {}
            
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
            
            if existing_client:
                record_id = existing_client["id"]
                result = update_client(record_id, client_fields)
                if result["success"]:
                    results["clients_updated"] += 1
                    results["details"].append(f"✏️ Client mis à jour: {client_name}")
            else:
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
                    results["errors"].append(f"Erreur création {client_name}")
                    continue
            
            # Créer une livraison si statut "À livrer" ou "Essai gratuit"
            if statut in ["À livrer", "Essai gratuit"]:
                livraison_type = "Essai gratuit" if statut == "Essai gratuit" else "One-shot"
                liv_result = create_livraison({
                    "Client": [record_id],
                    "Statut": "À planifier",
                    "Type": livraison_type
                })
                if liv_result["success"]:
                    results["livraisons_created"] += 1
                    results["details"].append(f"📦 Livraison créée pour: {client_name}")
        
        elif statut in inactive_statuts:
            if existing_client:
                record_id = existing_client["id"]
                result = update_client(record_id, {"Actif": False})
                if result["success"]:
                    results["clients_deactivated"] += 1
                    results["details"].append(f"❌ Client désactivé: {client_name}")
    
    return results


def sync_all():
    """Synchronisation complète"""
    results = {
        "pennylane": {},
        "clients": {},
        "total_details": []
    }
    
    # 1. Sync Pennylane → Suivi Facturation
    pennylane_results = sync_pennylane_to_suivi()
    results["pennylane"] = pennylane_results
    results["total_details"].extend(pennylane_results.get("details", []))
    
    # 2. Sync Suivi Facturation → CLIENTS
    clients_results = sync_suivi_to_clients()
    results["clients"] = clients_results
    results["total_details"].extend(clients_results.get("details", []))
    
    return results


# ==================== PLANNING TOURNÉES ====================

def get_clients_to_deliver():
    """Récupère les clients à livrer (basé sur Prochaine_Livraison et clients actifs)"""
    _, _, all_clients = get_existing_clients()
    
    to_deliver = []
    today = datetime.now().date()
    end_of_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    
    for client in all_clients:
        fields = client.get("fields", {})
        
        # Client actif ?
        if not fields.get("Actif", False):
            continue
        
        # Prochaine livraison dans le mois ?
        prochaine = fields.get("Prochaine_Livraison", "")
        if prochaine:
            try:
                prochaine_date = datetime.strptime(prochaine, "%Y-%m-%d").date()
                if today <= prochaine_date <= end_of_month:
                    to_deliver.append({
                        "id": client["id"],
                        "nom": fields.get("Nom", ""),
                        "adresse": fields.get("Adresse", ""),
                        "persona": fields.get("Persona", ""),
                        "nb_bouquets": fields.get("Nb_Bouquets", 1),
                        "creneau": fields.get("Créneau_Préféré", ""),
                        "prochaine_livraison": prochaine,
                        "code_postal": extract_postal_code(fields.get("Adresse", ""))
                    })
            except ValueError:
                pass
    
    return to_deliver


def extract_postal_code(address: str) -> str:
    """Extrait le code postal d'une adresse"""
    import re
    match = re.search(r'\b(75\d{3}|92\d{3}|93\d{3}|94\d{3})\b', address)
    return match.group(1) if match else ""


def group_deliveries_by_zone_and_persona(clients: list) -> dict:
    """Regroupe les clients par zone et persona pour optimiser les tournées"""
    groups = defaultdict(list)
    
    for client in clients:
        # Grouper par arrondissement (2 premiers chiffres du CP) + persona
        cp = client.get("code_postal", "")
        arrondissement = cp[:4] if cp.startswith("75") else cp[:3]  # 750XX → 750, 92XXX → 92
        persona = client.get("persona", "Autre")
        
        key = f"{arrondissement}_{persona}"
        groups[key].append(client)
    
    return dict(groups)


def suggest_delivery_dates(groups: dict) -> list:
    """Suggère des dates de livraison optimisées"""
    suggestions = []
    
    today = datetime.now().date()
    
    # Trouver le prochain jour ouvré
    def next_weekday(d, weekday):
        days_ahead = weekday - d.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return d + timedelta(days=days_ahead)
    
    day_index = 0
    weekdays = [0, 1, 2, 3, 4]  # Lundi à Vendredi
    
    for group_key, clients in groups.items():
        # Assigner un jour de la semaine prochaine
        delivery_date = next_weekday(today, weekdays[day_index % 5])
        day_index += 1
        
        suggestions.append({
            "group": group_key,
            "date": delivery_date.strftime("%Y-%m-%d"),
            "clients": clients,
            "nb_clients": len(clients),
            "nb_bouquets": sum(c.get("nb_bouquets", 1) for c in clients)
        })
    
    return suggestions


def prepare_tournees():
    """Prépare les tournées du mois"""
    # 1. Récupérer les clients à livrer
    clients = get_clients_to_deliver()
    
    # 2. Ajouter les livraisons "À planifier" existantes
    livraisons = get_livraisons()
    livraisons_a_planifier = [l for l in livraisons if l.get("fields", {}).get("Statut") == "À planifier"]
    
    # Récupérer les infos clients pour ces livraisons
    _, _, all_clients = get_existing_clients()
    clients_by_id = {c["id"]: c for c in all_clients}
    
    for liv in livraisons_a_planifier:
        client_ids = liv.get("fields", {}).get("Client", [])
        if client_ids:
            client_record = clients_by_id.get(client_ids[0])
            if client_record:
                fields = client_record.get("fields", {})
                # Éviter les doublons
                if not any(c["id"] == client_record["id"] for c in clients):
                    clients.append({
                        "id": client_record["id"],
                        "livraison_id": liv["id"],
                        "nom": fields.get("Nom", ""),
                        "adresse": fields.get("Adresse", ""),
                        "persona": fields.get("Persona", ""),
                        "nb_bouquets": fields.get("Nb_Bouquets", 1),
                        "creneau": fields.get("Créneau_Préféré", ""),
                        "code_postal": extract_postal_code(fields.get("Adresse", ""))
                    })
    
    # 3. Grouper par zone/persona
    groups = group_deliveries_by_zone_and_persona(clients)
    
    # 4. Suggérer des dates
    suggestions = suggest_delivery_dates(groups)
    
    return {
        "total_clients": len(clients),
        "total_bouquets": sum(c.get("nb_bouquets", 1) for c in clients),
        "groups": len(groups),
        "suggestions": suggestions
    }


# ==================== FACTURATION ====================

def facturer_livraison(livraison_id: str, invoice_type: str = "one-shot") -> dict:
    """Facture une livraison après qu'elle ait été effectuée"""
    # Récupérer la livraison
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_LIVRAISONS_TABLE}/{livraison_id}"
    headers = get_airtable_headers()
    
    response = req.get(url, headers=headers)
    if response.status_code != 200:
        return {"success": False, "error": "Livraison non trouvée"}
    
    livraison = response.json()
    fields = livraison.get("fields", {})
    
    # Récupérer le client
    client_ids = fields.get("Client", [])
    if not client_ids:
        return {"success": False, "error": "Pas de client associé"}
    
    client_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}/{client_ids[0]}"
    client_response = req.get(client_url, headers=headers)
    if client_response.status_code != 200:
        return {"success": False, "error": "Client non trouvé"}
    
    client = client_response.json()
    client_fields = client.get("fields", {})
    pennylane_id = client_fields.get("ID_Pennylane", "")
    client_name = client_fields.get("Nom", "")
    
    if not pennylane_id:
        return {"success": False, "error": f"Client {client_name} n'a pas d'ID Pennylane"}
    
    # Calculer le montant (à adapter selon ta logique de pricing)
    nb_bouquets = client_fields.get("Nb_Bouquets", 1)
    prix_unitaire = 49.0  # Prix par défaut, à adapter
    montant = nb_bouquets * prix_unitaire
    label = f"Location de {nb_bouquets} bouquet(s) - {client_name}"
    
    if invoice_type == "one-shot":
        result = pennylane_create_invoice(int(pennylane_id), montant, label)
    else:  # abonnement
        result = pennylane_create_subscription(int(pennylane_id), montant, label)
    
    if result["success"]:
        # Mettre à jour la livraison comme facturée
        update_livraison(livraison_id, {"Statut": "Facturée"})
    
    return result


# ==================== BOUQUETS (existing) ====================

def upload_to_imgbb(image_base64: str) -> dict:
    if not IMGBB_API_KEY:
        return {"error": "IMGBB_API_KEY not configured"}
    
    response = req.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_API_KEY, "image": image_base64}
    )
    
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            return {"url": data["data"]["url"]}
    return {"error": response.text}


def analyze_image_with_claude(image_base64: str, media_type: str = "image/jpeg") -> dict:
    prompt = f"""Analyse cette photo de bouquet de fleurs en soie.
Réponds UNIQUEMENT en JSON valide:
{{"couleurs": ["couleur1"], "style": "style", "taille_suggeree": "taille", "saison": "saison", "personas": ["persona1"], "description": "courte description"}}"""

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
        return json.loads(text)
    except:
        return {"error": "JSON parse failed", "raw": text}


def get_next_bouquet_id():
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()
    response = req.get(url, headers=headers, params={"pageSize": 100})
    count = len(response.json().get("records", [])) if response.status_code == 200 else 0
    return f"MA-{datetime.now().year}-{count + 1:05d}"


def get_bouquet_by_id(bouquet_id: str) -> dict:
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
    public_url = f"https://web-production-37db3.up.railway.app/b/{bouquet_id}"
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={public_url}"
    
    fields = {
        "Bouquet_ID": bouquet_id,
        "Nom": data.get("nom", f"Bouquet {data.get('style', '')}"),
        "Taille": data.get("taille", data.get("taille_suggeree", "Moyen")),
        "Couleurs": data.get("couleurs", []),
        "Style": data.get("style", "Classique"),
        "Statut": "Disponible",
        "QR_Code_URL": public_url
    }
    
    if image_url:
        fields["Photo"] = [{"url": image_url}]
        fields["QR_Code"] = [{"url": qr_image_url}]
    
    response = req.post(url, headers=headers, json={"fields": fields})
    if response.status_code == 200:
        return {"success": True, "bouquet_id": bouquet_id, "public_url": public_url, "qr_image": qr_image_url}
    return {"success": False, "error": response.text}


# ==================== ROUTES ====================

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

@app.route("/b/<bouquet_id>")
def bouquet_page(bouquet_id):
    bouquet = get_bouquet_by_id(bouquet_id)
    if not bouquet:
        return f"<h1>Bouquet {bouquet_id} non trouvé</h1>", 404
    
    fields = bouquet.get("fields", {})
    nom = fields.get("Nom", bouquet_id)
    photo_url = fields["Photo"][0].get("url", "") if fields.get("Photo") else ""
    
    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{nom}</title>
    <style>body{{font-family:system-ui;max-width:500px;margin:0 auto;padding:20px;}}
    img{{width:100%;border-radius:12px;}}.tag{{background:#eee;padding:5px 10px;border-radius:20px;margin:5px;display:inline-block;}}</style>
    </head><body>
    {'<img src="' + photo_url + '">' if photo_url else ''}
    <h1>{nom}</h1>
    <p><strong>{bouquet_id}</strong></p>
    <p><span class="tag">{fields.get('Style', '')}</span><span class="tag">{fields.get('Taille', '')}</span></p>
    <p>Couleurs: {', '.join(fields.get('Couleurs', []))}</p>
    </body></html>
    """


# API Routes
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Maison Amarante API v4"})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Synchronisation complète Pennylane → Suivi → Clients"""
    try:
        results = sync_all()
        return jsonify(results)
    except Exception as e:
        print(f"[SYNC] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/pennylane", methods=["POST"])
def api_sync_pennylane():
    """Sync Pennylane → Suivi Facturation uniquement"""
    try:
        results = sync_pennylane_to_suivi()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sync/clients", methods=["POST"])
def api_sync_clients():
    """Sync Suivi Facturation → Clients uniquement"""
    try:
        results = sync_suivi_to_clients()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tournees", methods=["GET"])
def api_tournees():
    """Prépare les tournées"""
    try:
        results = prepare_tournees()
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/facturer", methods=["POST"])
def api_facturer():
    """Facture une livraison"""
    data = request.json
    livraison_id = data.get("livraison_id")
    invoice_type = data.get("type", "one-shot")  # "one-shot" ou "abonnement"
    
    if not livraison_id:
        return jsonify({"error": "livraison_id required"}), 400
    
    try:
        result = facturer_livraison(livraison_id, invoice_type)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    return jsonify(analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg")))


@app.route("/analyze-and-create", methods=["POST"])
def analyze_and_create():
    data = request.json
    if not data or "image_base64" not in data:
        return jsonify({"error": "image_base64 required"}), 400
    
    image_upload = upload_to_imgbb(data["image_base64"])
    image_url = image_upload.get("url")
    
    analysis = analyze_image_with_claude(data["image_base64"], data.get("media_type", "image/jpeg"))
    if "error" in analysis:
        return jsonify(analysis), 500
    
    if data.get("nom"):
        analysis["nom"] = data["nom"]
    
    result = create_bouquet_in_airtable(analysis, image_url)
    
    return jsonify({"analysis": analysis, "created": result, "image_url": image_url})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
