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

def extract_customer_name_from_label(label, filename=None):
    """Extrait le nom du client depuis le label ou filename Pennylane"""
    # Try label first (factures): "Facture NOM CLIENT - F-2026-xxx (label généré)"
    if label and " - " in label:
        name = label.split(" - ")[0]
        for prefix in ["Facture ", "Devis ", "Avoir "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
        if name.strip() and name.strip() != label:
            return name.strip()
    
    # Try filename (devis): "Devis-NOM CLIENT-MAISON AMARANTE-D-2026-xxx.pdf"
    if filename and "-" in filename:
        parts = filename.replace(".pdf", "").split("-")
        if len(parts) >= 3:
            # parts[0] = "Devis", parts[1] = nom client, etc
            return parts[1].strip() or "Client inconnu"
    
    return "Client inconnu"


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


def pennylane_get_customer_by_id(customer_id: int) -> dict:
    """Récupère les détails d'un customer par son ID"""
    url = f"{PENNYLANE_API_URL}/customers/{customer_id}"
    headers = get_pennylane_headers()

    response = req.get(url, headers=headers)
    if response.status_code != 200:
        print(f"[PENNYLANE] Error fetching customer {customer_id}: {response.text}")
        return {}

    return response.json().get("customer", response.json())


def extract_pennylane_notes(item: dict) -> str:
    """Extrait les commentaires/notes d'un objet Pennylane (devis, facture, abonnement).

    Essaie plusieurs noms de champs possibles dans l'API Pennylane.
    """
    # Liste des champs possibles pour les notes/commentaires
    note_fields = [
        "comments",           # Commentaires
        "notes",              # Notes
        "special_mention",    # Mention spéciale
        "internal_notes",     # Notes internes
        "pdf_invoice_free_text",  # Texte libre sur facture PDF
        "free_text",          # Texte libre
        "customer_note",      # Note client
        "memo",               # Mémo
        "description",        # Description
    ]

    notes_parts = []
    for field in note_fields:
        value = item.get(field)
        if value and isinstance(value, str) and value.strip():
            notes_parts.append(value.strip())
        elif value and isinstance(value, list):
            # Si c'est une liste de commentaires
            for comment in value:
                if isinstance(comment, dict):
                    # Format: {"content": "...", "author": "..."}
                    content = comment.get("content") or comment.get("text") or comment.get("body")
                    if content:
                        notes_parts.append(content.strip())
                elif isinstance(comment, str):
                    notes_parts.append(comment.strip())

    # Debug: log les champs trouvés (à retirer en prod)
    if notes_parts:
        print(f"[PENNYLANE] Found notes: {notes_parts[:100]}...")

    return "\n".join(notes_parts) if notes_parts else ""


def pennylane_get_quotes():
    """Récupère tous les devis depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/quotes"
    headers = get_pennylane_headers()
    
    all_quotes = []
    cursor = None
    
    while True:
        params = {"per_page": 100}
        if cursor:
            params["cursor"] = cursor
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching quotes: {response.text}")
            break
        
        data = response.json()
        quotes = data.get("items", [])
        all_quotes.extend(quotes)
        
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    
    print(f"[PENNYLANE] Fetched {len(all_quotes)} quotes")
    return all_quotes


def pennylane_get_invoices():
    """Récupère toutes les factures depuis Pennylane"""
    url = f"{PENNYLANE_API_URL}/customer_invoices"
    headers = get_pennylane_headers()
    
    all_invoices = []
    cursor = None
    
    while True:
        params = {"per_page": 100}
        if cursor:
            params["cursor"] = cursor
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[PENNYLANE] Error fetching invoices: {response.text}")
            break
        
        data = response.json()
        invoices = data.get("items", [])
        all_invoices.extend(invoices)
        
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    
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

def parse_all_clients_notes_with_claude(clients_data: list) -> dict:
    """Parse les notes de TOUS les clients en batches de 10 pour éviter les timeouts

    Args:
        clients_data: liste de {"name": "...", "notes": "..."}

    Returns:
        dict avec client_name comme clé et infos parsées comme valeur
    """
    if not clients_data:
        return {}

    # Filtrer les clients sans notes
    clients_with_notes = [c for c in clients_data if c.get("notes", "").strip()]
    if not clients_with_notes:
        return {}

    # Batches de 8 clients
    BATCH_SIZE = 8
    all_parsed = {}

    print(f"[PARSE] Total clients to parse: {len(clients_with_notes)} in {(len(clients_with_notes) + BATCH_SIZE - 1) // BATCH_SIZE} batches")

    for i in range(0, len(clients_with_notes), BATCH_SIZE):
        batch = clients_with_notes[i:i + BATCH_SIZE]
        print(f"[PARSE] Starting batch {i // BATCH_SIZE + 1} with {len(batch)} clients")
        batch_result = _parse_batch_with_claude(batch)
        print(f"[PARSE] Batch {i // BATCH_SIZE + 1} result: {len(batch_result)} clients, keys: {list(batch_result.keys())[:3]}...")
        all_parsed.update(batch_result)

    print(f"[PARSE] Total parsed: {len(all_parsed)} clients")
    return all_parsed


def _parse_batch_with_claude(clients_with_notes: list, debug=False) -> dict:
    """Parse un batch de clients (max 10) avec Claude"""
    if not clients_with_notes:
        return {"_debug_error": "No clients with notes"} if debug else {}

    # Construire la liste des clients à parser
    clients_text = "\n\n".join([
        f"### {c['name']}\n{c['notes']}"
        for c in clients_with_notes
    ])

    prompt = f"""Analyse les notes de ces {len(clients_with_notes)} clients et extrais les informations structurées.

{clients_text}

---

Réponds UNIQUEMENT en JSON valide avec le NOM EXACT du client comme clé (garde le nom tel quel, y compris "FAKE", "TEST", etc.):

{{
    "NOM EXACT CLIENT 1": {{
        "persona": "type",
        "frequence": "fréquence",
        "nb_bouquets": nombre,
        "tailles": ["S", "M", "L" ou "XL"],
        "pref_couleurs": ["couleur1"],
        "pref_style": "style",
        "creneau_prefere": "jour/moment",
        "adresse": "adresse complète",
        "instructions_speciales": "autres infos"
    }}
}}

Valeurs:
- persona: Coiffeur, Bureau, Hôtel, Restaurant, Retail, Spa, Galerie, Clinique
- frequence: Hebdomadaire, Bimensuel, Mensuel, Ponctuel
- tailles: S, M, L, XL
- pref_style: Classique, Moderne, Zen, Champêtre, Luxe, Coloré

IMPORTANT: Utilise le NOM EXACT après ### comme clé JSON (ex: si "### FAKE Hôtel Paris" → clé = "FAKE Hôtel Paris")"""

    print(f"[PARSE] Parsing {len(clients_with_notes)} clients en batch...")

    response = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-3-haiku-20240307",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60
    )

    if response.status_code != 200:
        print(f"[PARSE] Error: {response.status_code} - {response.text}")
        return {"_debug_error": f"API error {response.status_code}", "_response": response.text[:300]} if debug else {}

    try:
        text = response.json()["content"][0]["text"].strip()
        print(f"[PARSE] Got response text ({len(text)} chars)")
    except Exception as e:
        print(f"[PARSE] Failed to extract text: {e}")
        return {"_debug_error": f"Extract failed: {e}", "_response": response.text[:300]} if debug else {}

    # Nettoyer le JSON si wrapped dans des backticks
    original_text = text
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
        print(f"[PARSE] Successfully parsed {len(parsed)} clients")
        if debug:
            parsed["_debug_raw"] = original_text[:200]
        return parsed
    except Exception as e:
        print(f"[PARSE] JSON parse failed: {e}")
        return {"_debug_error": f"JSON parse failed: {e}", "_raw_text": text[:500]} if debug else {}


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

    # Récupérer tous les customers pour avoir leurs notes
    all_customers = pennylane_get_customers()
    customers_by_id = {c["id"]: c for c in all_customers}
    print(f"[SYNC] Loaded {len(customers_by_id)} customers for notes lookup")

    # Sync devis
    quotes = pennylane_get_quotes()
    for quote in quotes:
        quote_id = str(quote.get("id", ""))
        if quote_id and quote_id not in existing_by_pennylane_id:
            customer_name = extract_customer_name_from_label(quote.get("label", ""), quote.get("filename", ""))
            amount = quote.get("amount", 0)

            # Extraire les notes du customer associé
            customer_id = quote.get("customer", {}).get("id")
            customer_notes = ""
            if customer_id and customer_id in customers_by_id:
                customer_notes = customers_by_id[customer_id].get("notes") or ""

            # Combiner notes du devis + notes du customer
            quote_notes = extract_pennylane_notes(quote)
            notes = "\n".join(filter(None, [customer_notes, quote_notes]))

            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": quote_id,
                "Montant": float(amount) if amount else 0,
                "Statut": "Devis",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            if notes:
                card_fields["Notes"] = notes

            result = create_suivi_card(card_fields)
            if result["success"]:
                results["quotes_synced"] += 1
                results["details"].append(f"📋 Devis ajouté: {customer_name}")

    # Sync factures
    invoices = pennylane_get_invoices()
    for invoice in invoices:
        invoice_id = str(invoice.get("id", ""))
        if invoice_id and invoice_id not in existing_by_pennylane_id:
            customer_name = extract_customer_name_from_label(invoice.get("label", ""), invoice.get("filename", ""))
            amount = invoice.get("amount", invoice.get("currency_amount", 0))

            # Extraire les notes du customer associé
            customer_id = invoice.get("customer", {}).get("id")
            customer_notes = ""
            if customer_id and customer_id in customers_by_id:
                customer_notes = customers_by_id[customer_id].get("notes") or ""

            # Combiner notes de la facture + notes du customer
            invoice_notes = extract_pennylane_notes(invoice)
            notes = "\n".join(filter(None, [customer_notes, invoice_notes]))

            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": invoice_id,
                "Montant": float(amount) if amount else 0,
                "Statut": "Factures",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            if notes:
                card_fields["Notes"] = notes

            result = create_suivi_card(card_fields)
            if result["success"]:
                results["invoices_synced"] += 1
                results["details"].append(f"🧾 Facture ajoutée: {customer_name}")

    # Sync abonnements
    subscriptions = pennylane_get_subscriptions()
    for sub in subscriptions:
        sub_id = str(sub.get("id", ""))
        if sub_id and sub_id not in existing_by_pennylane_id:
            customer_name = extract_customer_name_from_label(sub.get("label", ""), sub.get("filename", ""))

            # Extraire les notes du customer associé
            customer_id = sub.get("customer", {}).get("id")
            customer_notes = ""
            if customer_id and customer_id in customers_by_id:
                customer_notes = customers_by_id[customer_id].get("notes") or ""

            # Combiner notes de l'abonnement + notes du customer
            sub_notes = extract_pennylane_notes(sub)
            notes = "\n".join(filter(None, [customer_notes, sub_notes]))

            card_fields = {
                "Nom du Client": customer_name,
                "ID Pennylane": sub_id,
                "Statut": "Abonnements",
                "Date": datetime.now().strftime("%Y-%m-%d")
            }
            if notes:
                card_fields["Notes"] = notes

            result = create_suivi_card(card_fields)
            if result["success"]:
                results["subscriptions_synced"] += 1
                results["details"].append(f"🔄 Abonnement ajouté: {customer_name}")

    return results


def sync_suivi_to_clients(skip_parsing=False):
    """Synchronise Suivi Facturation → Maison Amarante DB (CLIENTS)

    Args:
        skip_parsing: Si True, ne fait pas le parsing Claude (plus rapide)
    """
    results = {
        "clients_created": 0,
        "clients_updated": 0,
        "clients_deactivated": 0,
        "livraisons_created": 0,
        "notes_parsed": 0,
        "errors": [],
        "details": []
    }

    cards = get_suivi_cards()
    clients_by_name, clients_by_pennylane, _ = get_existing_clients()

    active_statuts = ["Factures", "Abonnements", "Essai gratuit", "À livrer"]
    inactive_statuts = ["Archives", "Abonnement arrêté", "Avoirs"]

    # 1. Collecter tous les clients actifs
    active_cards = []

    for card in cards:
        fields = card.get("fields", {})
        client_name = fields.get("Nom du Client", "").strip()
        statut = fields.get("Statut", "")
        notes = fields.get("Notes", "")
        pennylane_id = str(fields.get("ID Pennylane", ""))

        if not client_name:
            continue

        if statut in active_statuts:
            active_cards.append({
                "card": card,
                "client_name": client_name,
                "statut": statut,
                "notes": notes,
                "pennylane_id": pennylane_id
            })

    # 2. Parsing désactivé par défaut (trop lent pour la sync)
    parsed_data = {}
    if not skip_parsing:
        clients_to_parse = [{"name": c["client_name"], "notes": c["notes"]} for c in active_cards if c["notes"].strip()]
        if clients_to_parse:
            results["details"].append(f"🤖 Parsing IA de {len(clients_to_parse)} notes...")
            parsed_data = parse_all_clients_notes_with_claude(clients_to_parse)
            results["notes_parsed"] = len(parsed_data)
    else:
        results["details"].append("⏭️ Parsing IA désactivé (utilisez /api/parse-clients)")

    # 3. Traiter chaque client avec les infos parsées
    for card_info in active_cards:
        client_name = card_info["client_name"]
        statut = card_info["statut"]
        pennylane_id = card_info["pennylane_id"]

        existing_client = clients_by_pennylane.get(pennylane_id) or clients_by_name.get(client_name.upper())

        # Récupérer les infos parsées pour ce client
        parsed = parsed_data.get(client_name, {})

        client_fields = {
            "Nom": client_name,
            "Actif": True
        }

        if pennylane_id:
            client_fields["ID_Pennylane"] = pennylane_id

        # Ajouter les infos parsées par Claude
        if parsed.get("persona"):
            client_fields["Persona"] = parsed["persona"]
        if parsed.get("frequence"):
            client_fields["Fréquence"] = parsed["frequence"]
        if parsed.get("nb_bouquets"):
            client_fields["Nb_Bouquets"] = parsed["nb_bouquets"]
        if parsed.get("pref_couleurs"):
            # Peut être une liste ou une string
            couleurs = parsed["pref_couleurs"]
            if isinstance(couleurs, list):
                client_fields["Pref_Couleurs"] = ", ".join(couleurs)
            else:
                client_fields["Pref_Couleurs"] = couleurs
        if parsed.get("pref_style"):
            client_fields["Pref_Style"] = parsed["pref_style"]
        if parsed.get("tailles"):
            tailles = parsed["tailles"]
            if isinstance(tailles, list):
                client_fields["Tailles_Demandées"] = ", ".join(tailles)
            else:
                client_fields["Tailles_Demandées"] = tailles
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

    # 4. Traiter les cartes inactives (désactiver les clients existants)
    for card in cards:
        fields = card.get("fields", {})
        client_name = fields.get("Nom du Client", "").strip()
        statut = fields.get("Statut", "")
        pennylane_id = str(fields.get("ID Pennylane", ""))

        if statut in inactive_statuts:
            existing_client = clients_by_pennylane.get(pennylane_id) or clients_by_name.get(client_name.upper())
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

def extract_postal_code(address: str) -> str:
    """Extrait le code postal d'une adresse"""
    import re
    match = re.search(r'\b(75\d{3}|92\d{3}|93\d{3}|94\d{3})\b', address)
    return match.group(1) if match else ""


def get_zone_order(code_postal: str) -> int:
    """Retourne un ordre de zone pour optimiser le parcours géographique.
    Ordre: Paris centre → Paris périphérique → Banlieue proche → Banlieue loin
    """
    if not code_postal:
        return 999

    # Paris par arrondissement (spirale depuis le centre)
    paris_order = {
        "75001": 1, "75002": 2, "75003": 3, "75004": 4,  # Centre
        "75005": 5, "75006": 6, "75007": 7, "75008": 8,  # Rive gauche + ouest
        "75009": 9, "75010": 10, "75011": 11, "75012": 12,  # Est
        "75013": 13, "75014": 14, "75015": 15, "75016": 16,  # Sud-ouest
        "75017": 17, "75018": 18, "75019": 19, "75020": 20,  # Nord-est
    }

    if code_postal in paris_order:
        return paris_order[code_postal]

    # Banlieue par département
    if code_postal.startswith("92"):
        return 30 + int(code_postal[2:]) if code_postal[2:].isdigit() else 35
    if code_postal.startswith("93"):
        return 50 + int(code_postal[2:]) if code_postal[2:].isdigit() else 55
    if code_postal.startswith("94"):
        return 70 + int(code_postal[2:]) if code_postal[2:].isdigit() else 75

    return 999


def optimize_route_order(clients: list) -> list:
    """Optimise l'ordre des clients pour minimiser le temps de trajet.
    Algorithme simple: tri par zone géographique (code postal).
    """
    # Trier par zone géographique
    return sorted(clients, key=lambda c: (
        get_zone_order(c.get("code_postal", "")),
        c.get("code_postal", ""),
        c.get("adresse", "")
    ))


def generate_google_maps_url(clients: list, start_address: str = None) -> str:
    """Génère un lien Google Maps avec l'itinéraire optimisé.

    Format: https://www.google.com/maps/dir/origin/stop1/stop2/.../destination
    """
    import urllib.parse

    if not clients:
        return ""

    addresses = []

    # Point de départ (optionnel)
    if start_address:
        addresses.append(start_address)

    # Ajouter toutes les adresses clients
    for client in clients:
        addr = client.get("adresse", "")
        if addr:
            addresses.append(addr)

    if not addresses:
        return ""

    # Encoder les adresses pour l'URL
    encoded_addresses = [urllib.parse.quote(addr) for addr in addresses]

    # Construire l'URL Google Maps
    url = "https://www.google.com/maps/dir/" + "/".join(encoded_addresses)

    return url


def get_geographic_zone(code_postal: str) -> str:
    """Retourne la zone géographique pour grouper les clients."""
    if not code_postal:
        return "Autre"

    # Paris par zones
    if code_postal in ["75001", "75002", "75003", "75004"]:
        return "Paris Centre"
    if code_postal in ["75005", "75006", "75007"]:
        return "Paris Rive Gauche"
    if code_postal in ["75008", "75009", "75010"]:
        return "Paris Nord-Ouest"
    if code_postal in ["75011", "75012", "75013"]:
        return "Paris Est"
    if code_postal in ["75014", "75015", "75016"]:
        return "Paris Sud-Ouest"
    if code_postal in ["75017", "75018", "75019", "75020"]:
        return "Paris Nord-Est"

    # Banlieue
    if code_postal.startswith("92"):
        return "Hauts-de-Seine (92)"
    if code_postal.startswith("93"):
        return "Seine-St-Denis (93)"
    if code_postal.startswith("94"):
        return "Val-de-Marne (94)"

    return "Autre"


def split_into_tournees(clients: list, max_clients_per_tournee: int = 12) -> list:
    """Divise les clients en plusieurs tournées réalistes.

    Stratégie:
    1. Grouper par zone géographique
    2. Chaque zone devient une tournée si elle a assez de clients
    3. Les petites zones sont fusionnées avec les zones adjacentes
    4. Maximum 12-15 clients par tournée (réaliste pour une journée à Paris)
    """
    if not clients:
        return []

    # Grouper par zone géographique
    zones = defaultdict(list)
    for client in clients:
        zone = get_geographic_zone(client.get("code_postal", ""))
        zones[zone].append(client)

    # Ordre logique des zones (parcours géographique)
    zone_order = [
        "Paris Centre",
        "Paris Rive Gauche",
        "Paris Nord-Ouest",
        "Paris Sud-Ouest",
        "Paris Est",
        "Paris Nord-Est",
        "Hauts-de-Seine (92)",
        "Val-de-Marne (94)",
        "Seine-St-Denis (93)",
        "Autre"
    ]

    # Construire les tournées
    tournees = []
    current_tournee = []

    for zone_name in zone_order:
        zone_clients = zones.get(zone_name, [])
        if not zone_clients:
            continue

        # Trier les clients de la zone par code postal
        zone_clients = sorted(zone_clients, key=lambda c: (c.get("code_postal", ""), c.get("adresse", "")))

        for client in zone_clients:
            current_tournee.append(client)

            # Si on atteint le max, créer une nouvelle tournée
            if len(current_tournee) >= max_clients_per_tournee:
                tournees.append(current_tournee)
                current_tournee = []

    # Ajouter la dernière tournée si elle n'est pas vide
    if current_tournee:
        # Si elle est trop petite et qu'on a d'autres tournées, fusionner avec la précédente si possible
        if len(current_tournee) < 5 and tournees and len(tournees[-1]) + len(current_tournee) <= max_clients_per_tournee + 3:
            tournees[-1].extend(current_tournee)
        else:
            tournees.append(current_tournee)

    return tournees


def prepare_tournees():
    """Prépare PLUSIEURS tournées optimisées, réparties sur différents jours."""
    _, _, all_clients = get_existing_clients()

    # Récupérer tous les clients actifs avec une adresse
    clients_to_deliver = []
    for client in all_clients:
        fields = client.get("fields", {})

        if not fields.get("Actif", False):
            continue

        adresse = fields.get("Adresse", "")
        if not adresse:
            continue

        clients_to_deliver.append({
            "id": client["id"],
            "nom": fields.get("Nom", ""),
            "adresse": adresse,
            "code_postal": extract_postal_code(adresse),
            "zone": get_geographic_zone(extract_postal_code(adresse)),
            "nb_bouquets": fields.get("Nb_Bouquets", 1),
            "creneau": fields.get("Créneau_Préféré", ""),
            "pref_couleurs": fields.get("Pref_Couleurs", ""),
            "pref_style": fields.get("Pref_Style", ""),
        })

    if not clients_to_deliver:
        return {
            "total_clients": 0,
            "total_bouquets": 0,
            "tournees": [],
            "message": "Aucun client actif avec adresse"
        }

    # Diviser en plusieurs tournées
    tournees_clients = split_into_tournees(clients_to_deliver, max_clients_per_tournee=12)

    # Jours de livraison possibles (mardi et jeudi)
    delivery_days = get_delivery_days(len(tournees_clients))

    # Construire les tournées avec leurs infos
    tournees = []
    for i, clients in enumerate(tournees_clients):
        # Optimiser l'ordre dans chaque tournée
        optimized = optimize_route_order(clients)

        # Zones couvertes
        zones_couvertes = list(set(c.get("zone", "Autre") for c in optimized))

        tournees.append({
            "numero": i + 1,
            "jour": delivery_days[i] if i < len(delivery_days) else "À planifier",
            "clients": optimized,
            "nb_clients": len(optimized),
            "nb_bouquets": sum(c.get("nb_bouquets", 1) for c in optimized),
            "zones": zones_couvertes,
            "google_maps_url": generate_google_maps_url(optimized),
            "duree_estimee": f"{len(optimized) * 20}min"  # ~20min par client (trajet + livraison)
        })

    return {
        "total_clients": len(clients_to_deliver),
        "total_bouquets": sum(c.get("nb_bouquets", 1) for c in clients_to_deliver),
        "nb_tournees": len(tournees),
        "tournees": tournees,
        "message": f"{len(tournees)} tournées générées pour {len(clients_to_deliver)} clients"
    }


def get_delivery_days(nb_tournees: int) -> list:
    """Retourne une liste de jours de livraison pour N tournées.

    Stratégie:
    - Si 1 tournée: prochain mardi ou jeudi
    - Si 2 tournées: mardi ET jeudi de la même semaine
    - Si 3+ tournées: mardi/jeudi sur plusieurs semaines
    """
    today = datetime.now().date()
    days = []

    # Calculer le prochain mardi et jeudi
    days_until_tuesday = (1 - today.weekday()) % 7
    days_until_thursday = (3 - today.weekday()) % 7

    if days_until_tuesday == 0:
        days_until_tuesday = 7
    if days_until_thursday == 0:
        days_until_thursday = 7

    # Créer une liste ordonnée des prochains jours de livraison
    delivery_slots = []

    # Ajouter les mardis et jeudis des 4 prochaines semaines
    for week in range(4):
        tuesday = today + timedelta(days=days_until_tuesday + 7 * week)
        thursday = today + timedelta(days=days_until_thursday + 7 * week)

        if tuesday < thursday:
            delivery_slots.append(("Mardi", tuesday))
            delivery_slots.append(("Jeudi", thursday))
        else:
            delivery_slots.append(("Jeudi", thursday))
            delivery_slots.append(("Mardi", tuesday))

    # Retourner les N premiers jours
    for i in range(min(nb_tournees, len(delivery_slots))):
        day_name, date = delivery_slots[i]
        days.append(f"{day_name} {date.strftime('%d/%m/%Y')}")

    return days


def get_suggested_delivery_day() -> str:
    """Suggère le meilleur jour de livraison (prochain mardi ou jeudi)."""
    days = get_delivery_days(1)
    return days[0] if days else "À planifier"


# ==================== DISPATCH BOUQUETS ====================

def get_available_bouquets():
    """Récupère tous les bouquets disponibles depuis Airtable"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()

    all_records = []
    offset = None

    while True:
        params = {"pageSize": 100, "filterByFormula": "{Statut} = 'Disponible'"}
        if offset:
            params["offset"] = offset

        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"[BOUQUETS] Error fetching: {response.text}")
            break

        data = response.json()
        all_records.extend(data.get("records", []))

        offset = data.get("offset")
        if not offset:
            break

    print(f"[BOUQUETS] Fetched {len(all_records)} available bouquets")
    return all_records


def normalize_text(text: str) -> list:
    """Normalise un texte en liste de mots-clés pour la comparaison"""
    if not text:
        return []
    # Convertir en minuscules, remplacer les séparateurs, split
    text = text.lower()
    for sep in [",", "/", ";", "-", "+"]:
        text = text.replace(sep, " ")
    return [w.strip() for w in text.split() if w.strip()]


def calculate_match_score(bouquet: dict, client_prefs: dict) -> dict:
    """Calcule un score de compatibilité entre un bouquet et les préférences d'un client.

    Returns:
        dict avec score (0-100), détails des matchs
    """
    score = 0
    max_score = 0
    details = []

    bouquet_fields = bouquet.get("fields", {})

    # 1. Couleurs (poids: 40 points)
    bouquet_colors = bouquet_fields.get("Couleurs", [])
    if isinstance(bouquet_colors, str):
        bouquet_colors = normalize_text(bouquet_colors)
    else:
        bouquet_colors = [c.lower() for c in bouquet_colors]

    client_colors = normalize_text(client_prefs.get("pref_couleurs", ""))

    if client_colors:
        max_score += 40
        matching_colors = set(bouquet_colors) & set(client_colors)
        if matching_colors:
            color_score = min(40, len(matching_colors) * 20)
            score += color_score
            details.append(f"Couleurs: {', '.join(matching_colors)}")
    else:
        # Pas de préférence = tous les bouquets OK
        score += 20
        max_score += 40

    # 2. Style (poids: 35 points)
    bouquet_style = bouquet_fields.get("Style", "").lower()
    client_styles = normalize_text(client_prefs.get("pref_style", ""))

    if client_styles:
        max_score += 35
        if any(s in bouquet_style or bouquet_style in s for s in client_styles):
            score += 35
            details.append(f"Style: {bouquet_style}")
        elif bouquet_style:
            # Style différent mais pas incompatible
            score += 10
    else:
        score += 17
        max_score += 35

    # 3. Taille (poids: 25 points)
    bouquet_taille = bouquet_fields.get("Taille", "").lower()
    client_tailles = normalize_text(client_prefs.get("tailles", ""))

    # Mapping des tailles
    taille_map = {"s": "petit", "m": "moyen", "l": "grand", "xl": "masterpiece"}

    if client_tailles:
        max_score += 25
        # Normaliser les tailles
        normalized_client = []
        for t in client_tailles:
            normalized_client.append(taille_map.get(t, t))

        if bouquet_taille in normalized_client or any(t in bouquet_taille for t in normalized_client):
            score += 25
            details.append(f"Taille: {bouquet_taille}")
        else:
            # Taille différente mais acceptable
            score += 10
    else:
        score += 12
        max_score += 25

    # Calculer le pourcentage
    final_score = int((score / max_score) * 100) if max_score > 0 else 50

    return {
        "score": final_score,
        "details": details,
        "bouquet_id": bouquet_fields.get("Bouquet_ID", ""),
        "bouquet_nom": bouquet_fields.get("Nom", ""),
        "bouquet_style": bouquet_fields.get("Style", ""),
        "bouquet_taille": bouquet_fields.get("Taille", ""),
        "bouquet_couleurs": bouquet_fields.get("Couleurs", []),
        "bouquet_photo": bouquet_fields.get("Photo", [{}])[0].get("url", "") if bouquet_fields.get("Photo") else "",
        "record_id": bouquet.get("id", "")
    }


def dispatch_for_tournee(tournee_num: int):
    """Génère des suggestions de dispatch pour UNE tournée spécifique.

    Args:
        tournee_num: numéro de la tournée (1, 2, 3...)

    Returns:
        Suggestions pour les clients de cette tournée uniquement
    """
    # D'abord récupérer les tournées
    tournees_data = prepare_tournees()
    tournees = tournees_data.get("tournees", [])

    if not tournees:
        return {"success": False, "message": "Aucune tournée disponible"}

    if tournee_num < 1 or tournee_num > len(tournees):
        return {"success": False, "message": f"Tournée {tournee_num} inexistante (1-{len(tournees)})"}

    # Récupérer la tournée demandée
    tournee = tournees[tournee_num - 1]
    clients_in_tournee = tournee.get("clients", [])

    if not clients_in_tournee:
        return {"success": False, "message": "Aucun client dans cette tournée"}

    # Récupérer les bouquets disponibles
    bouquets = get_available_bouquets()
    if not bouquets:
        return {
            "success": False,
            "message": "Aucun bouquet disponible",
            "tournee": tournee,
            "dispatch": []
        }

    # Pour chaque client de la tournée, calculer les suggestions
    dispatch_results = []
    assigned_bouquets = set()

    for client in clients_in_tournee:
        nb_needed = client.get("nb_bouquets", 1)

        # Calculer le score de chaque bouquet disponible
        scored_bouquets = []
        for bouquet in bouquets:
            if bouquet["id"] in assigned_bouquets:
                continue

            match = calculate_match_score(bouquet, {
                "pref_couleurs": client.get("pref_couleurs", ""),
                "pref_style": client.get("pref_style", ""),
                "tailles": client.get("tailles", "")
            })
            scored_bouquets.append(match)

        # Trier par score décroissant
        scored_bouquets.sort(key=lambda x: x["score"], reverse=True)

        # Prendre les N meilleurs + 2 alternatives
        suggested = scored_bouquets[:nb_needed]
        alternatives = scored_bouquets[nb_needed:nb_needed + 2]

        # Marquer les suggestions principales comme "réservées" (pas les alternatives)
        for s in suggested:
            assigned_bouquets.add(s["record_id"])

        dispatch_results.append({
            "client_id": client.get("id", ""),
            "client_nom": client.get("nom", ""),
            "client_adresse": client.get("adresse", ""),
            "nb_demandes": nb_needed,
            "nb_suggeres": len(suggested),
            "preferences": {
                "couleurs": client.get("pref_couleurs", ""),
                "style": client.get("pref_style", ""),
                "tailles": client.get("tailles", ""),
            },
            "bouquets_suggeres": suggested,
            "alternatives": alternatives,
            "complet": len(suggested) >= nb_needed,
            "valide": False  # À valider par l'utilisateur
        })

    # Stats pour cette tournée
    total_needed = sum(c.get("nb_bouquets", 1) for c in clients_in_tournee)
    total_suggested = sum(len(d["bouquets_suggeres"]) for d in dispatch_results)

    return {
        "success": True,
        "tournee": {
            "numero": tournee.get("numero"),
            "jour": tournee.get("jour"),
            "nb_clients": tournee.get("nb_clients"),
            "nb_bouquets": tournee.get("nb_bouquets"),
            "zones": tournee.get("zones"),
        },
        "stats": {
            "bouquets_disponibles": len(bouquets),
            "bouquets_demandes": total_needed,
            "bouquets_suggeres": total_suggested,
        },
        "dispatch": dispatch_results
    }


def valider_dispatch(client_id: str, bouquet_record_id: str) -> dict:
    """Valide l'assignation d'un bouquet à un client.

    Met à jour le statut du bouquet dans Airtable.
    """
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}/{bouquet_record_id}"
    headers = get_airtable_headers()

    # Mettre à jour le statut du bouquet
    response = req.patch(url, headers=headers, json={
        "fields": {
            "Statut": "Assigné",
            "Client_Assigné": client_id  # Lien vers le client
        }
    })

    if response.status_code == 200:
        return {"success": True, "message": "Bouquet assigné"}
    else:
        return {"success": False, "error": response.text}


def get_tournees_summary():
    """Retourne un résumé des tournées pour l'affichage."""
    tournees_data = prepare_tournees()
    tournees = tournees_data.get("tournees", [])

    return {
        "nb_tournees": len(tournees),
        "total_clients": tournees_data.get("total_clients", 0),
        "total_bouquets": tournees_data.get("total_bouquets", 0),
        "tournees": [
            {
                "numero": t.get("numero"),
                "jour": t.get("jour"),
                "nb_clients": t.get("nb_clients"),
                "nb_bouquets": t.get("nb_bouquets"),
                "zones": t.get("zones"),
                "duree_estimee": t.get("duree_estimee"),
            }
            for t in tournees
        ]
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
    prompt = """Analyse cette photo de bouquet de fleurs en soie.
Réponds UNIQUEMENT en JSON valide avec ces champs (utilise EXACTEMENT les valeurs proposées):
{
  "couleurs": ["Rouge", "Blanc", "Rose", "Vert", "Jaune", "Orange", "Violet", "Bleu", "Noir"],
  "style": "Bucolique | Zen | Moderne | Coloré | Classique",
  "taille_suggeree": "Petit | Moyen | Grand | Masterpiece",
  "saison": "Printemps | Été | Automne | Hiver | Toutes saisons",
  "personas": ["Hôtel", "Restaurant", "Retail"],
  "ambiance": "Romantique | Champêtre | Luxe | Épuré",
  "fleurs": ["Amarante", "Anthurium", "Anémone", "Astilbe", "Chrysanthème", "Dahlia", "Hortensia", "Pivoine", "Rose"],
  "feuillages": ["Asparagus", "Eucalyptus", "Fougère", "Pittosporum", "Ruscus"],
  "description": "courte description du bouquet"
}
IMPORTANT: Pour fleurs, feuillages, personas et ambiance, utilise UNIQUEMENT les valeurs listées ci-dessus."""

    response = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-3-haiku-20240307",
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


def normalize_taille(taille: str) -> str:
    """Normalise la taille pour correspondre aux options Airtable."""
    if not taille:
        return "Moyen"
    taille_lower = taille.lower().strip()
    # Mapping des variations possibles
    if any(x in taille_lower for x in ["petit", "small", "s"]):
        return "Petit"
    if any(x in taille_lower for x in ["moyen", "medium", "m", "normale"]):
        return "Moyen"
    if any(x in taille_lower for x in ["grand", "large", "l", "big"]):
        return "Grand"
    if any(x in taille_lower for x in ["master", "xl", "très grand", "enorme"]):
        return "Masterpiece"
    return "Moyen"  # Défaut


def normalize_style(style: str) -> str:
    """Normalise le style pour correspondre aux options Airtable."""
    if not style:
        return "Classique"
    style_lower = style.lower().strip()
    # Mapping des variations possibles
    if any(x in style_lower for x in ["classique", "classic", "traditionnel"]):
        return "Classique"
    if any(x in style_lower for x in ["moderne", "modern", "contemporain"]):
        return "Moderne"
    if any(x in style_lower for x in ["zen", "minimaliste", "épuré"]):
        return "Zen"
    if any(x in style_lower for x in ["champêtre", "rustique", "campagne", "naturel"]):
        return "Champêtre"
    if any(x in style_lower for x in ["luxe", "luxueux", "premium", "prestige"]):
        return "Luxe"
    if any(x in style_lower for x in ["coloré", "vif", "multicolore"]):
        return "Coloré"
    if any(x in style_lower for x in ["romantique", "romantic", "doux"]):
        return "Romantique"
    if any(x in style_lower for x in ["bohème", "boho", "bohemian"]):
        return "Bohème"
    return "Classique"  # Défaut


def create_bouquet_in_airtable(data: dict, image_url: str = None) -> dict:
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()

    bouquet_id = get_next_bouquet_id()
    # URL fixe (Railway ne change pas)
    base_url = "https://web-production-37db3.up.railway.app"
    public_url = f"{base_url}/b/{bouquet_id}"
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={public_url}"

    # Options valides Airtable (Multiple Select)
    VALID_FLEURS = ["Amarante", "Anthurium", "Anémone", "Astilbe", "Chrysanthème", "Dahlia", "Hortensia", "Pivoine", "Rose"]
    VALID_FEUILLAGES = ["Asparagus", "Eucalyptus", "Fougère", "Pittosporum", "Ruscus"]
    VALID_PERSONAS = ["Hôtel", "Restaurant", "Retail"]
    VALID_AMBIANCES = ["Champêtre", "Luxe", "Romantique", "Épuré"]

    # Convertir en string pour les champs texte
    def to_string(value):
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return value or ""

    # Garder comme liste et filtrer les valeurs valides
    def to_valid_list(value, valid_options):
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",")]
        if not isinstance(value, list):
            return []
        # Filtrer pour ne garder que les options valides (case-insensitive match)
        valid_lower = {v.lower(): v for v in valid_options}
        return [valid_lower[v.lower()] for v in value if v.lower() in valid_lower]

    couleurs = to_string(data.get("couleurs", []))

    # Normaliser taille et style pour correspondre aux options Airtable
    taille_raw = data.get("taille") or data.get("taille_suggeree") or "Moyen"
    style_raw = data.get("style") or "Classique"

    fields = {
        "Bouquet_ID": bouquet_id,
        "Nom": data.get("nom", f"Bouquet {style_raw}"),
        "Taille": normalize_taille(taille_raw),
        "Couleurs": couleurs,
        "Style": normalize_style(style_raw),
        "Statut": "Disponible",
        "QR_Code_URL": public_url,
        "Date_Création": datetime.now().strftime("%Y-%m-%d"),
        "Saison": data.get("saison", "Toutes saisons"),
        "Condition": 5,
        "Rotations": 0,
    }

    # Champs Multiple Select (filtrer les valeurs valides)
    personas = to_valid_list(data.get("personas", []), VALID_PERSONAS)
    if personas:
        fields["Personas_Suggérées"] = personas

    fleurs = to_valid_list(data.get("fleurs", []), VALID_FLEURS)
    if fleurs:
        fields["Fleurs"] = fleurs

    feuillages = to_valid_list(data.get("feuillages", []), VALID_FEUILLAGES)
    if feuillages:
        fields["Feuillages"] = feuillages

    ambiance = data.get("ambiance")
    if ambiance:
        ambiance_list = to_valid_list([ambiance] if isinstance(ambiance, str) else ambiance, VALID_AMBIANCES)
        if ambiance_list:
            fields["Ambiance"] = ambiance_list

    # Ajouter notes/description si présent
    if data.get("description"):
        fields["Notes"] = data.get("description")

    if image_url:
        fields["Photo"] = [{"url": image_url}]
        fields["QR_Code"] = [{"url": qr_image_url}]

    print(f"[BOUQUET] Creating bouquet {bouquet_id}")
    print(f"[BOUQUET] Fields: {fields}")
    response = req.post(url, headers=headers, json={"fields": fields})
    print(f"[BOUQUET] Response status: {response.status_code}")
    print(f"[BOUQUET] Response body: {response.text[:500]}")

    if response.status_code in [200, 201]:
        return {"success": True, "bouquet_id": bouquet_id, "public_url": public_url, "qr_image": qr_image_url}

    # Fallback: si erreur de select option, réessayer sans les champs multiple select
    if "select option" in response.text.lower() or "insufficient permissions" in response.text.lower():
        print("[BOUQUET] Erreur select option détectée, retry sans les champs multiple select...")
        multi_select_fields = ["Fleurs", "Feuillages", "Personas_Suggérées", "Ambiance"]
        for field in multi_select_fields:
            fields.pop(field, None)

        response = req.post(url, headers=headers, json={"fields": fields})
        print(f"[BOUQUET] Retry response status: {response.status_code}")
        print(f"[BOUQUET] Retry response body: {response.text[:500]}")

        if response.status_code in [200, 201]:
            return {"success": True, "bouquet_id": bouquet_id, "public_url": public_url, "qr_image": qr_image_url, "warning": "Créé sans fleurs/feuillages (options manquantes dans Airtable)"}

    # Parse error message
    error_msg = "Erreur Airtable"
    try:
        error_data = response.json()
        if "error" in error_data:
            error_msg = error_data["error"].get("message", response.text)
    except:
        error_msg = response.text[:200]

    return {"success": False, "error": error_msg, "bouquet_id": "ERREUR", "public_url": "#"}


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

    # Gérer couleurs comme string ou array
    couleurs = fields.get("Couleurs", "")
    if isinstance(couleurs, list):
        couleurs = ", ".join(couleurs)

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
    <p>Couleurs: {couleurs}</p>
    </body></html>
    """


# API Routes
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Maison Amarante API v4"})


# Config budget (stockage simple en fichier)
BUDGET_CONFIG_FILE = "/tmp/budget_config.json"
BUDGET_PERCENT = 8  # 8% du CA
COUT_LIVRAISON = 15  # 15€ par livraison

def get_ca_mensuel():
    """Récupère le CA mensuel depuis le fichier config"""
    try:
        with open(BUDGET_CONFIG_FILE, "r") as f:
            config = json.load(f)
            return config.get("ca_mensuel", 12500)
    except (FileNotFoundError, json.JSONDecodeError):
        return 12500  # Valeur par défaut

def set_ca_mensuel(ca):
    """Sauvegarde le CA mensuel dans le fichier config"""
    with open(BUDGET_CONFIG_FILE, "w") as f:
        json.dump({"ca_mensuel": ca}, f)


@app.route("/api/budget", methods=["GET"])
def api_budget():
    """Retourne le budget livraisons du mois en cours"""
    ca_mensuel = get_ca_mensuel()
    budget_max = ca_mensuel * BUDGET_PERCENT / 100

    # Compter les livraisons du mois en cours
    now = datetime.now()
    livraisons = get_livraisons()
    livraisons_mois = 0

    for liv in livraisons:
        created = liv.get("createdTime", "")
        date_liv = liv.get("fields", {}).get("Date", created)

        if date_liv:
            try:
                if "T" in str(date_liv):
                    date_obj = datetime.fromisoformat(date_liv.replace("Z", "+00:00"))
                else:
                    date_obj = datetime.strptime(str(date_liv), "%Y-%m-%d")

                if date_obj.year == now.year and date_obj.month == now.month:
                    livraisons_mois += 1
            except (ValueError, TypeError):
                pass

    budget_utilise = livraisons_mois * COUT_LIVRAISON
    reste = max(0, budget_max - budget_utilise)
    pourcentage = (budget_utilise / budget_max * 100) if budget_max > 0 else 0
    livraisons_max = int(budget_max / COUT_LIVRAISON)
    livraisons_reste = max(0, livraisons_max - livraisons_mois)

    return jsonify({
        "ca_mensuel": ca_mensuel,
        "budget_max": budget_max,
        "budget_utilise": budget_utilise,
        "livraisons_count": livraisons_mois,
        "livraisons_max": livraisons_max,
        "livraisons_reste": livraisons_reste,
        "reste": reste,
        "pourcentage": round(pourcentage, 1),
        "cout_unitaire": COUT_LIVRAISON
    })


@app.route("/api/budget", methods=["POST"])
def api_budget_update():
    """Met à jour le CA mensuel"""
    data = request.get_json() or {}
    ca = data.get("ca_mensuel")

    if ca is None:
        return jsonify({"error": "ca_mensuel requis"}), 400

    try:
        ca = float(ca)
        if ca < 0:
            return jsonify({"error": "CA doit être positif"}), 400
        set_ca_mensuel(ca)
        return jsonify({"success": True, "ca_mensuel": ca})
    except ValueError:
        return jsonify({"error": "CA invalide"}), 400


@app.route("/api/test/cleanup", methods=["POST"])
def api_test_cleanup():
    """Supprime TOUTES les cartes Suivi Facturation + TOUS les clients (Airtable uniquement, ne touche PAS Pennylane)"""
    results = {"suivi_deleted": 0, "clients_deleted": 0, "errors": []}

    # 1. Cleanup Suivi Facturation - TOUTES les cartes
    cards = get_suivi_cards()
    for card in cards:
        record_id = card["id"]
        name = card.get("fields", {}).get("Nom du Client", "inconnu")
        url = f"https://api.airtable.com/v0/{SUIVI_BASE_ID}/{SUIVI_TABLE_ID}/{record_id}"
        response = req.delete(url, headers=get_airtable_headers())
        if response.status_code == 200:
            results["suivi_deleted"] += 1
        else:
            results["errors"].append(f"Erreur suppression suivi {name}: {response.text}")

    # 2. Cleanup Clients (Maison Amarante DB) - TOUS les clients
    _, _, all_clients = get_existing_clients()
    for client in all_clients:
        record_id = client["id"]
        name = client.get("fields", {}).get("Nom", "inconnu")
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}/{record_id}"
        response = req.delete(url, headers=get_airtable_headers())
        if response.status_code == 200:
            results["clients_deleted"] += 1
        else:
            results["errors"].append(f"Erreur suppression client {name}: {response.text}")

    results["deleted"] = results["suivi_deleted"] + results["clients_deleted"]
    return jsonify(results)


@app.route("/api/test/parse-debug", methods=["POST"])
def api_test_parse_debug():
    """Debug endpoint - teste le parsing avec les vrais noms FAKE"""
    # Test avec des noms identiques aux vrais fake clients
    test_clients = [
        {"name": "FAKE Hôtel du Louvre", "notes": "Hebdomadaire. 4 bouquets XL hall + 2 M réception. Style classique luxe. Adresse: 2 place du Palais Royal, 75001 Paris. Livraison lundi 7h"},
        {"name": "FAKE Salon Coiffure Madeleine", "notes": "Hebdomadaire. 2 bouquets S. Chic parisien. Adresse: 15 rue Tronchet, 75008 Paris. Mardi matin uniquement"},
        {"name": "FAKE Restaurant Les Halles", "notes": "3 bouquets M tables. Couleurs chaudes (rouge, orange). Adresse: 15 rue Coquillière, 75001 Paris. Fermé dimanche. Livrer avant 11h"}
    ]

    # Test direct de la fonction _parse_batch_with_claude
    try:
        batch_result = _parse_batch_with_claude(test_clients, debug=True)

        return jsonify({
            "test_clients": [c["name"] for c in test_clients],
            "batch_result_count": len(batch_result),
            "batch_result_keys": list(batch_result.keys()),
            "batch_result": batch_result,
            "match_test": {
                name: name in batch_result
                for name in [c["name"] for c in test_clients]
            }
        })
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@app.route("/api/test/pennylane-comments/<quote_id>", methods=["GET"])
def api_test_pennylane_comments(quote_id):
    """Debug: Essaie de récupérer les commentaires d'un devis Pennylane"""
    headers = get_pennylane_headers()
    results = {}

    # Essayer plusieurs endpoints possibles
    endpoints_to_try = [
        f"{PENNYLANE_API_URL}/quotes/{quote_id}/comments",
        f"{PENNYLANE_API_URL}/quotes/{quote_id}/notes",
        f"{PENNYLANE_API_URL}/comments?quote_id={quote_id}",
        f"{PENNYLANE_API_URL}/document_comments?document_id={quote_id}",
        f"{PENNYLANE_API_URL}/notes?quote_id={quote_id}",
    ]

    for endpoint in endpoints_to_try:
        try:
            response = req.get(endpoint, headers=headers)
            results[endpoint] = {
                "status": response.status_code,
                "body": response.json() if response.status_code == 200 else response.text[:500]
            }
        except Exception as e:
            results[endpoint] = {"error": str(e)}

    return jsonify(results)


@app.route("/api/test/pennylane-structure", methods=["GET"])
def api_test_pennylane_structure():
    """Debug: Montre la structure des données Pennylane (devis, factures, abonnements, customers)"""
    result = {
        "sample_quote": None,
        "sample_invoice": None,
        "sample_subscription": None,
        "sample_customer": None,
        "quote_fields": [],
        "invoice_fields": [],
        "subscription_fields": [],
        "customer_fields": []
    }

    # Récupérer un devis
    quotes = pennylane_get_quotes()
    if quotes:
        result["sample_quote"] = quotes[0]
        result["quote_fields"] = list(quotes[0].keys())

    # Récupérer une facture
    invoices = pennylane_get_invoices()
    if invoices:
        result["sample_invoice"] = invoices[0]
        result["invoice_fields"] = list(invoices[0].keys())

    # Récupérer un abonnement
    subs = pennylane_get_subscriptions()
    if subs:
        result["sample_subscription"] = subs[0]
        result["subscription_fields"] = list(subs[0].keys())

    # Récupérer un customer (détails complets)
    customers = pennylane_get_customers()
    if customers:
        result["sample_customer"] = customers[0]
        result["customer_fields"] = list(customers[0].keys())

    return jsonify(result)


@app.route("/api/test/sync-all", methods=["POST"])
def api_test_sync_all():
    """Synchronisation complète en mode sandbox (fake Pennylane + vrais clients)
    Note: Le parsing IA est désactivé pour la rapidité. Utilisez /api/parse-clients séparément."""
    results = {
        "pennylane": {},
        "clients": {},
        "total_details": []
    }

    # 1. Fake Pennylane → Suivi Facturation
    fake_response = api_test_fake_pennylane()
    fake_data = fake_response.get_json()
    results["pennylane"] = fake_data
    results["total_details"].extend(fake_data.get("details", []))

    # 2. Sync Suivi Facturation → CLIENTS (sans parsing pour éviter timeout)
    clients_results = sync_suivi_to_clients(skip_parsing=True)
    results["clients"] = clients_results
    results["total_details"].extend(clients_results.get("details", []))

    return jsonify(results)


@app.route("/api/test/fake-pennylane", methods=["POST"])
def api_test_fake_pennylane():
    """Simule une sync Pennylane avec des données fake (sans toucher au vrai Pennylane)"""
    import random

    # 40 clients FAKE répartis géographiquement pour tester les tournées
    # Statuts: Factures, Abonnements, Essai gratuit, À livrer (tous actifs)
    fake_clients = [
        # === PARIS CENTRE (75001-75004) - 6 clients ===
        {"id": "FAKE-001", "name": "FAKE Hôtel du Louvre", "statut": "Abonnements", "montant": 450,
         "notes": "Hebdomadaire. 4 bouquets XL hall + 2 M réception. Style classique luxe. Adresse: 2 place du Palais Royal, 75001 Paris. Livraison lundi 7h. Contact: Réception 01 44 58 38 38"},
        {"id": "FAKE-002", "name": "FAKE Bijouterie Vendôme", "statut": "Factures", "montant": 180,
         "notes": "Mensuel. 1 bouquet S vitrine. Tons or/blanc. Style épuré. Adresse: 24 place Vendôme, 75001 Paris. Livraison mardi matin"},
        {"id": "FAKE-003", "name": "FAKE Restaurant Les Halles", "statut": "À livrer", "montant": 220,
         "notes": "3 bouquets M tables. Couleurs chaudes (rouge, orange). Adresse: 15 rue Coquillière, 75001 Paris. Fermé dimanche. Livrer avant 11h"},
        {"id": "FAKE-004", "name": "FAKE Galerie Beaubourg", "statut": "Abonnements", "montant": 380,
         "notes": "Bimensuel. 2 bouquets XL contemporains. Couleurs neutres. Adresse: 8 rue Rambuteau, 75003 Paris. Accès code 4521"},
        {"id": "FAKE-005", "name": "FAKE Café Le Marais", "statut": "Essai gratuit", "montant": 0,
         "notes": "Essai 1 mois. 2 bouquets S comptoir. Style champêtre coloré. Adresse: 38 rue des Archives, 75004 Paris. Contact: Julie 06 12 34 56 78"},
        {"id": "FAKE-006", "name": "FAKE Boutique Saint-Paul", "statut": "Factures", "montant": 95,
         "notes": "1 bouquet M entrée. Roses et pivoines. Adresse: 12 rue Saint-Paul, 75004 Paris. Livraison jeudi après-midi"},

        # === PARIS RIVE GAUCHE (75005-75007) - 5 clients ===
        {"id": "FAKE-007", "name": "FAKE Librairie Quartier Latin", "statut": "Abonnements", "montant": 120,
         "notes": "Mensuel. 1 bouquet M. Style classique, tons bordeaux. Adresse: 34 boulevard Saint-Germain, 75005 Paris. Contact: Pierre 01 42 55 66 77"},
        {"id": "FAKE-008", "name": "FAKE Restaurant Tour Eiffel", "statut": "Factures", "montant": 520,
         "notes": "Hebdomadaire. 5 bouquets L tables. Élégant, blanc/vert. Adresse: 18 avenue de la Bourdonnais, 75007 Paris. Livrer mardi 10h"},
        {"id": "FAKE-009", "name": "FAKE Cabinet Avocat Luxembourg", "statut": "Abonnements", "montant": 150,
         "notes": "Bimensuel. 2 bouquets M. Sobre et élégant. Adresse: 5 rue de Médicis, 75006 Paris. Livraison mercredi matin"},
        {"id": "FAKE-010", "name": "FAKE Spa Saint-Germain", "statut": "À livrer", "montant": 200,
         "notes": "2 bouquets zen L. Blanc/vert apaisant. Pas de fleurs odorantes. Adresse: 42 rue du Bac, 75007 Paris. Livrer jeudi"},
        {"id": "FAKE-011", "name": "FAKE Concept Store Odéon", "statut": "Essai gratuit", "montant": 0,
         "notes": "Test 2 semaines. 1 bouquet M moderne. Couleurs vives. Adresse: 9 carrefour de l'Odéon, 75006 Paris"},

        # === PARIS OPÉRA/GRANDS BOULEVARDS (75008-75009) - 6 clients ===
        {"id": "FAKE-012", "name": "FAKE Salon Coiffure Madeleine", "statut": "Abonnements", "montant": 180,
         "notes": "Hebdomadaire. 2 bouquets S. Chic parisien. Adresse: 15 rue Tronchet, 75008 Paris. Mardi matin uniquement"},
        {"id": "FAKE-013", "name": "FAKE Hôtel Opéra Grand", "statut": "Abonnements", "montant": 650,
         "notes": "Hebdomadaire. 6 bouquets (2XL hall, 4M étages). Luxe classique. Adresse: 5 rue Scribe, 75009 Paris. Lundi 6h30"},
        {"id": "FAKE-014", "name": "FAKE Clinique Esthétique Haussmann", "statut": "Factures", "montant": 175,
         "notes": "3 bouquets S salles. Hypoallergénique. Blanc/rose. Adresse: 99 boulevard Haussmann, 75008 Paris. Avant 8h"},
        {"id": "FAKE-015", "name": "FAKE Bureau Conseil Miromesnil", "statut": "Abonnements", "montant": 140,
         "notes": "Bimensuel. 2 bouquets M. Corporate chic. Adresse: 28 rue de Miromesnil, 75008 Paris. Mercredi"},
        {"id": "FAKE-016", "name": "FAKE Restaurant Pigalle", "statut": "À livrer", "montant": 160,
         "notes": "2 bouquets M ambiance. Rouge/noir. Style moderne. Adresse: 52 rue des Martyrs, 75009 Paris. Fermé lundi"},
        {"id": "FAKE-017", "name": "FAKE Théâtre Mogador", "statut": "Essai gratuit", "montant": 0,
         "notes": "Essai événement. 3 bouquets XL. Spectaculaire. Adresse: 25 rue de Mogador, 75009 Paris. Vendredi 14h"},

        # === PARIS EST (75010-75012) - 6 clients ===
        {"id": "FAKE-018", "name": "FAKE Hôtel Gare du Nord", "statut": "Abonnements", "montant": 320,
         "notes": "Hebdomadaire. 3 bouquets L. Accueillant. Adresse: 12 rue de Dunkerque, 75010 Paris. Lundi matin"},
        {"id": "FAKE-019", "name": "FAKE Salon Coiffure Canal", "statut": "Factures", "montant": 90,
         "notes": "2 bouquets S. Bohème coloré. Adresse: 45 quai de Valmy, 75010 Paris. Mardi après-midi"},
        {"id": "FAKE-020", "name": "FAKE Restaurant République", "statut": "À livrer", "montant": 240,
         "notes": "4 bouquets M. Bistronomique, couleurs terre. Adresse: 3 avenue de la République, 75011 Paris. Jeudi 10h"},
        {"id": "FAKE-021", "name": "FAKE Boutique Oberkampf", "statut": "Abonnements", "montant": 110,
         "notes": "Mensuel. 1 bouquet M. Trendy coloré. Adresse: 78 rue Oberkampf, 75011 Paris. Vendredi"},
        {"id": "FAKE-022", "name": "FAKE Café Bastille", "statut": "Essai gratuit", "montant": 0,
         "notes": "Test. 2 bouquets S comptoir. Champêtre. Adresse: 15 rue de la Roquette, 75011 Paris. Mercredi matin"},
        {"id": "FAKE-023", "name": "FAKE Bureau Bercy", "statut": "Factures", "montant": 200,
         "notes": "2 bouquets M accueil. Corporate. Adresse: 34 rue de Bercy, 75012 Paris. Mardi"},

        # === PARIS RIVE DROITE NORD (75017-75018) - 5 clients ===
        {"id": "FAKE-024", "name": "FAKE Restaurant Batignolles", "statut": "Abonnements", "montant": 180,
         "notes": "Hebdomadaire. 2 bouquets M. Bistrot chic. Adresse: 22 rue des Batignolles, 75017 Paris. Mardi"},
        {"id": "FAKE-025", "name": "FAKE Salon Coiffure Ternes", "statut": "Factures", "montant": 130,
         "notes": "Bimensuel. 2 bouquets S. Élégant. Adresse: 8 avenue des Ternes, 75017 Paris. Lundi matin"},
        {"id": "FAKE-026", "name": "FAKE Hôtel Montmartre", "statut": "À livrer", "montant": 280,
         "notes": "3 bouquets L romantiques. Rose/blanc. Adresse: 5 rue Lepic, 75018 Paris. Livraison urgente"},
        {"id": "FAKE-027", "name": "FAKE Café Abbesses", "statut": "Essai gratuit", "montant": 0,
         "notes": "Essai. 1 bouquet S. Artiste bohème. Adresse: 12 place des Abbesses, 75018 Paris. Jeudi"},
        {"id": "FAKE-028", "name": "FAKE Galerie Art Brut", "statut": "Abonnements", "montant": 220,
         "notes": "Mensuel. 2 bouquets L. Créatif original. Adresse: 45 rue Ordener, 75018 Paris. Mercredi après-midi"},

        # === PARIS OUEST (75015-75016) - 5 clients ===
        {"id": "FAKE-029", "name": "FAKE Clinique Auteuil", "statut": "Abonnements", "montant": 250,
         "notes": "Hebdomadaire. 3 bouquets M. Apaisant. Adresse: 18 rue d'Auteuil, 75016 Paris. Lundi 8h"},
        {"id": "FAKE-030", "name": "FAKE Restaurant Trocadéro", "statut": "Factures", "montant": 380,
         "notes": "4 bouquets L. Gastronomique luxe. Adresse: 2 avenue d'Eylau, 75016 Paris. Mardi 10h"},
        {"id": "FAKE-031", "name": "FAKE Bureau Passy", "statut": "À livrer", "montant": 150,
         "notes": "2 bouquets M. Corporate élégant. Adresse: 35 rue de Passy, 75016 Paris. Cette semaine"},
        {"id": "FAKE-032", "name": "FAKE Salon Institut Vaugirard", "statut": "Abonnements", "montant": 120,
         "notes": "Bimensuel. 2 bouquets S. Cosy. Adresse: 120 rue de Vaugirard, 75015 Paris. Vendredi matin"},
        {"id": "FAKE-033", "name": "FAKE Hôtel Porte Versailles", "statut": "Factures", "montant": 420,
         "notes": "5 bouquets (1XL, 4M). Business. Adresse: 8 boulevard Victor, 75015 Paris. Lundi 7h"},

        # === BANLIEUE OUEST (92) - 5 clients ===
        {"id": "FAKE-034", "name": "FAKE Siège Social La Défense", "statut": "Abonnements", "montant": 580,
         "notes": "Hebdomadaire. 6 bouquets L. Corporate prestige. Adresse: Tour First, 92400 Courbevoie. Lundi 7h30"},
        {"id": "FAKE-035", "name": "FAKE Restaurant Neuilly", "statut": "Factures", "montant": 290,
         "notes": "3 bouquets M. Chic discret. Adresse: 45 avenue Charles de Gaulle, 92200 Neuilly. Mardi"},
        {"id": "FAKE-036", "name": "FAKE Salon Coiffure Boulogne", "statut": "À livrer", "montant": 100,
         "notes": "2 bouquets S. Moderne. Adresse: 78 route de la Reine, 92100 Boulogne. Mercredi"},
        {"id": "FAKE-037", "name": "FAKE Clinique Levallois", "statut": "Essai gratuit", "montant": 0,
         "notes": "Essai. 2 bouquets M. Zen. Adresse: 15 rue Rivay, 92300 Levallois. Jeudi matin"},
        {"id": "FAKE-038", "name": "FAKE Bureau Issy", "statut": "Abonnements", "montant": 160,
         "notes": "Bimensuel. 2 bouquets M. Startup friendly. Adresse: 42 rue Camille Desmoulins, 92130 Issy. Vendredi"},

        # === BANLIEUE EST/NORD (93-94) - 4 clients ===
        {"id": "FAKE-039", "name": "FAKE Studio Photo Montreuil", "statut": "Factures", "montant": 180,
         "notes": "Ponctuel shooting. 4 bouquets variés. Créatif. Adresse: 25 rue de Paris, 93100 Montreuil. Mercredi"},
        {"id": "FAKE-040", "name": "FAKE Restaurant Vincennes", "statut": "À livrer", "montant": 200,
         "notes": "3 bouquets M. Terrasse nature. Vert dominant. Adresse: 8 avenue de Paris, 94300 Vincennes. Jeudi"},
        {"id": "FAKE-041", "name": "FAKE Hôtel Roissy", "statut": "Abonnements", "montant": 350,
         "notes": "Hebdomadaire. 4 bouquets M hall. International. Adresse: 2 allée du Verger, 93290 Tremblay. Lundi 6h"},
        {"id": "FAKE-042", "name": "FAKE Spa Nogent", "statut": "Essai gratuit", "montant": 0,
         "notes": "Test. 2 bouquets L zen. Bambou/orchidées. Adresse: 15 grande rue Charles de Gaulle, 94130 Nogent. Mardi"},
    ]

    # Transformer en format attendu
    direct_cards = [{"id": c["id"], "name": c["name"], "statut": c["statut"], "montant": c["montant"], "notes": c["notes"]} for c in fake_clients]

    # Garder quelques devis (non actifs) pour tester le filtre
    fake_data = {
        "quotes": [
            {"id": "FAKE-Q001", "label": "", "filename": "Devis-FAKE Fleuriste Concurrent-MAISON AMARANTE-D-2026-001.pdf", "amount": 180},
            {"id": "FAKE-Q002", "label": "", "filename": "Devis-FAKE Prospect Indécis-MAISON AMARANTE-D-2026-002.pdf", "amount": 320},
        ],
        "invoices": [],
        "subscriptions": []
    }

    # Notes pour les devis
    fake_notes = {
        "FAKE Fleuriste Concurrent": "Devis en attente de validation. Adresse: 10 rue de la Paix, 75002 Paris",
        "FAKE Prospect Indécis": "En réflexion. Adresse: 5 avenue Montaigne, 75008 Paris",
        "FAKE Clinique Beauté": "Hebdomadaire. 3 bouquets S. Hypoallergénique. Livrer avant 8h. Adresse: 99 avenue des Champs-Élysées, 75008 Paris. Interphone: 4521",
        "FAKE Hôtel Le Marais": "Abonnement premium. 5 bouquets/semaine (2L + 3M). Mix de styles. Adresse: 20 rue des Archives, 75004 Paris. Contact: Réception 01 44 55 66 77",
        "FAKE Boutique Mode Paris": "Mensuel. 2 bouquets M. Roses et pivoines. Fermé dimanche/lundi. Adresse: 67 rue du Faubourg Saint-Honoré, 75008 Paris",
    }

    results = {"quotes_synced": 0, "invoices_synced": 0, "subscriptions_synced": 0, "essais_synced": 0, "a_livrer_synced": 0, "factures_synced": 0, "details": [], "errors": []}

    # Check existing cards to avoid duplicates
    existing_cards = get_suivi_cards()
    existing_ids = {card.get("fields", {}).get("ID Pennylane", "") for card in existing_cards}

    # Sync fake quotes
    for quote in fake_data["quotes"]:
        if quote["id"] in existing_ids:
            continue
        customer_name = extract_customer_name_from_label(quote.get("label", ""), quote.get("filename", ""))
        card_fields = {
            "Nom du Client": customer_name,
            "ID Pennylane": quote["id"],
            "Montant": float(quote["amount"]),
            "Statut": "Devis",
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Notes": fake_notes.get(customer_name, "")
        }
        result = create_suivi_card(card_fields)
        if result["success"]:
            results["quotes_synced"] += 1
            results["details"].append(f"📋 Devis ajouté: {customer_name}")
        else:
            results["errors"].append(f"❌ {customer_name}: {result['error']}")

    # Sync fake invoices
    for invoice in fake_data["invoices"]:
        if invoice["id"] in existing_ids:
            continue
        customer_name = extract_customer_name_from_label(invoice.get("label", ""), invoice.get("filename", ""))
        card_fields = {
            "Nom du Client": customer_name,
            "ID Pennylane": invoice["id"],
            "Montant": float(invoice["amount"]),
            "Statut": "Factures",
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Notes": fake_notes.get(customer_name, "")
        }
        result = create_suivi_card(card_fields)
        if result["success"]:
            results["invoices_synced"] += 1
            results["details"].append(f"🧾 Facture ajoutée: {customer_name}")
        else:
            results["errors"].append(f"❌ {customer_name}: {result['error']}")

    # Sync fake subscriptions
    for sub in fake_data["subscriptions"]:
        if sub["id"] in existing_ids:
            continue
        customer_name = extract_customer_name_from_label(sub.get("label", ""), sub.get("filename", ""))
        card_fields = {
            "Nom du Client": customer_name,
            "ID Pennylane": sub["id"],
            "Statut": "Abonnements",
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Notes": fake_notes.get(customer_name, "")
        }
        result = create_suivi_card(card_fields)
        if result["success"]:
            results["subscriptions_synced"] += 1
            results["details"].append(f"🔄 Abonnement ajouté: {customer_name}")
        else:
            results["errors"].append(f"❌ {customer_name}: {result['error']}")

    # Sync direct cards (Essai gratuit, À livrer)
    for card in direct_cards:
        if card["id"] in existing_ids:
            continue
        card_fields = {
            "Nom du Client": card["name"],
            "ID Pennylane": card["id"],
            "Montant": card["montant"],
            "Statut": card["statut"],
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Notes": card["notes"]
        }
        result = create_suivi_card(card_fields)
        if result["success"]:
            statut = card["statut"]
            if statut == "Essai gratuit":
                results["essais_synced"] += 1
                results["details"].append(f"🎁 Essai: {card['name']}")
            elif statut == "À livrer":
                results["a_livrer_synced"] += 1
                results["details"].append(f"🚚 À livrer: {card['name']}")
            elif statut == "Factures":
                results["factures_synced"] += 1
                results["details"].append(f"🧾 Facture: {card['name']}")
            elif statut == "Abonnements":
                results["subscriptions_synced"] += 1
                results["details"].append(f"🔄 Abo: {card['name']}")
        else:
            results["errors"].append(f"❌ {card['name']}: {result['error']}")

    return jsonify(results)


@app.route("/api/test/fake-bouquets", methods=["POST"])
def api_test_fake_bouquets():
    """Génère des bouquets fake pour tester le dispatch.

    Crée ~60 bouquets variés avec différentes couleurs, styles et tailles
    pour permettre de tester les matchs avec les préférences clients.
    """
    import random

    # Définition des variations possibles
    styles = ["Classique", "Moderne", "Zen", "Champêtre", "Luxe", "Coloré", "Romantique", "Bohème"]
    tailles = ["Petit", "Moyen", "Grand", "Masterpiece"]
    couleurs_possibles = [
        ["Rouge", "Blanc"],
        ["Rose", "Blanc"],
        ["Blanc", "Vert"],
        ["Rouge", "Orange"],
        ["Violet", "Rose"],
        ["Jaune", "Orange"],
        ["Blanc", "Rose", "Vert"],
        ["Rouge", "Bordeaux"],
        ["Bleu", "Blanc"],
        ["Rose", "Pêche"],
        ["Vert", "Blanc", "Jaune"],
        ["Rouge", "Blanc", "Rose"],
        ["Orange", "Jaune", "Rouge"],
        ["Violet", "Blanc"],
        ["Rose", "Rouge"],
    ]

    # Noms de bouquets
    noms_base = [
        "Élégance", "Harmonie", "Sérénité", "Passion", "Douceur",
        "Éclat", "Charme", "Prestige", "Nature", "Rêverie",
        "Aurore", "Crépuscule", "Soleil", "Lune", "Étoile",
        "Jardin", "Forêt", "Prairie", "Océan", "Montagne"
    ]

    # Générer les bouquets
    fake_bouquets = []
    for i in range(60):
        style = random.choice(styles)
        taille = random.choice(tailles)
        couleurs = random.choice(couleurs_possibles)
        nom_base = random.choice(noms_base)

        fake_bouquets.append({
            "nom": f"FAKE {nom_base} {style}",
            "style": style,
            "taille": taille,
            "couleurs": couleurs
        })

    # Créer les bouquets dans Airtable
    results = {"created": 0, "errors": [], "details": []}

    # Vérifier les bouquets existants pour éviter les doublons
    existing = get_available_bouquets()
    existing_ids = {b.get("fields", {}).get("Bouquet_ID", "") for b in existing}

    # Compter combien de FAKE bouquets existent déjà
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()
    response = req.get(url, headers=headers, params={"pageSize": 100})
    all_bouquets = response.json().get("records", []) if response.status_code == 200 else []
    fake_count = sum(1 for b in all_bouquets if b.get("fields", {}).get("Nom", "").startswith("FAKE"))

    if fake_count >= 50:
        return jsonify({
            "message": f"Déjà {fake_count} bouquets FAKE existants. Utilisez cleanup d'abord.",
            "created": 0
        })

    # Créer les nouveaux bouquets
    for bouquet in fake_bouquets[:60 - fake_count]:  # Ne pas dépasser 60 au total
        result = create_bouquet_in_airtable(bouquet)
        if result.get("success"):
            results["created"] += 1
            results["details"].append(f"💐 {bouquet['nom']} ({bouquet['style']}, {bouquet['taille']})")
        else:
            results["errors"].append(result.get("error", "Unknown error")[:100])

    results["message"] = f"{results['created']} bouquets créés"
    return jsonify(results)


@app.route("/api/test/cleanup-bouquets", methods=["POST"])
def api_test_cleanup_bouquets():
    """Supprime tous les bouquets FAKE"""
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_BOUQUETS_TABLE}"
    headers = get_airtable_headers()

    # Récupérer tous les bouquets
    all_records = []
    offset = None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        response = req.get(url, headers=headers, params=params)
        if response.status_code != 200:
            break
        data = response.json()
        all_records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    # Supprimer les FAKE
    deleted = 0
    for record in all_records:
        nom = record.get("fields", {}).get("Nom", "")
        if nom.startswith("FAKE "):
            delete_url = f"{url}/{record['id']}"
            resp = req.delete(delete_url, headers=headers)
            if resp.status_code == 200:
                deleted += 1

    return jsonify({"deleted": deleted, "message": f"{deleted} bouquets FAKE supprimés"})


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
    """Sync Suivi Facturation → Clients (sans parsing IA pour la rapidité)"""
    try:
        results = sync_suivi_to_clients(skip_parsing=True)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/parse-clients", methods=["POST"])
def api_parse_clients():
    """Parse les notes des clients avec Claude IA (endpoint séparé car lent)

    Params optionnels (query string):
        limit: nombre max de clients à parser (défaut: 10)
        offset: ignorer les N premiers clients (pour pagination)
    """
    try:
        limit = request.args.get("limit", 10, type=int)
        offset = request.args.get("offset", 0, type=int)

        cards = get_suivi_cards()
        clients_by_name, clients_by_pennylane, all_clients = get_existing_clients()

        active_statuts = ["Factures", "Abonnements", "Essai gratuit", "À livrer"]

        # Collecter les clients actifs avec notes
        all_clients_to_parse = []
        client_records = {}  # Pour retrouver le record à mettre à jour

        for card in cards:
            fields = card.get("fields", {})
            client_name = fields.get("Nom du Client", "").strip()
            statut = fields.get("Statut", "")
            notes = fields.get("Notes", "")
            pennylane_id = str(fields.get("ID Pennylane", ""))

            if not client_name or statut not in active_statuts or not notes.strip():
                continue

            all_clients_to_parse.append({"name": client_name, "notes": notes})

            # Trouver le client dans Airtable
            existing = clients_by_pennylane.get(pennylane_id) or clients_by_name.get(client_name.upper())
            if existing:
                client_records[client_name] = existing["id"]

        total_clients = len(all_clients_to_parse)
        if not all_clients_to_parse:
            return jsonify({"message": "Aucun client à parser", "parsed": 0, "total": 0})

        # Appliquer pagination
        clients_to_parse = all_clients_to_parse[offset:offset + limit]
        if not clients_to_parse:
            return jsonify({"message": "Plus de clients à parser", "parsed": 0, "total": total_clients, "offset": offset})

        # Parser avec Claude (seulement le batch demandé)
        parsed_data = parse_all_clients_notes_with_claude(clients_to_parse)

        # Mettre à jour les clients
        updated = 0
        errors = []
        for client_name, parsed in parsed_data.items():
            if client_name.startswith("_"):  # Skip debug keys
                continue
            record_id = client_records.get(client_name)
            if not record_id:
                errors.append(f"{client_name}: no record_id")
                continue

            update_fields = {}
            # Champs texte libres
            if parsed.get("adresse"):
                update_fields["Adresse"] = parsed["adresse"]
            if parsed.get("creneau_prefere"):
                update_fields["Créneau_Préféré"] = str(parsed["creneau_prefere"])
            if parsed.get("instructions_speciales"):
                update_fields["Notes_Spéciales"] = parsed["instructions_speciales"]
            if parsed.get("nb_bouquets"):
                update_fields["Nb_Bouquets"] = int(parsed["nb_bouquets"])

            # Fréquence - doit matcher les options Airtable
            if parsed.get("frequence"):
                freq = parsed["frequence"]
                # Normaliser pour matcher les options Single Select
                freq_map = {
                    "hebdomadaire": "Hebdomadaire",
                    "bimensuel": "Bimensuel",
                    "mensuel": "Mensuel",
                    "ponctuel": "Ponctuel",
                    "bimestriel": "Bimestriel",
                    "trimestriel": "Trimestriel",
                }
                freq_normalized = freq_map.get(freq.lower().strip(), freq)
                update_fields["Fréquence"] = freq_normalized

            if parsed.get("persona"):
                update_fields["Persona"] = parsed["persona"]

            # Couleurs et Style - texte libre
            if parsed.get("pref_couleurs"):
                couleurs = parsed["pref_couleurs"]
                if isinstance(couleurs, list):
                    update_fields["Pref_Couleurs"] = ", ".join(couleurs)
                else:
                    update_fields["Pref_Couleurs"] = str(couleurs)

            if parsed.get("pref_style"):
                update_fields["Pref_Style"] = str(parsed["pref_style"])

            if not update_fields:
                errors.append(f"{client_name}: no fields to update")
                continue

            result = update_client(record_id, update_fields)
            if result["success"]:
                updated += 1
            else:
                errors.append(f"{client_name}: {result.get('error', 'unknown')[:100]}")

        # Debug info
        parsed_names = [k for k in parsed_data.keys() if not k.startswith("_")]
        records_found = {name: name in client_records for name in parsed_names}

        return jsonify({
            "version": "v2",  # Pour vérifier le déploiement
            "total_clients": total_clients,
            "batch_size": len(clients_to_parse),
            "offset": offset,
            "parsed": len(parsed_names),
            "updated": updated,
            "errors": errors[:5] if errors else [],
            "next_offset": offset + limit if offset + limit < total_clients else None
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# ==================== INBOX - CLIENTS À PLACER ====================

@app.route("/api/inbox", methods=["GET"])
def api_inbox():
    """Récupère les clients à placer (essais gratuits + devis acceptés)"""
    try:
        # 1. Récupérer les cartes Suivi Facturation avec statut "À livrer" ou "Essai gratuit"
        cards = get_suivi_cards()
        inbox_statuts = ["À livrer", "Essai gratuit"]

        # 2. Récupérer tous les clients existants pour avoir leurs infos
        _, _, all_clients = get_existing_clients()
        clients_by_name = {c.get("fields", {}).get("Nom", "").upper(): c for c in all_clients}

        # 3. Préparer les tournées existantes pour calculer les options de greffe
        tournees_data = prepare_tournees()
        tournees = tournees_data.get("tournees", [])

        # 4. Grouper les clients en attente par zone pour les mini-tournées
        clients_par_zone = defaultdict(list)

        inbox_clients = []
        for card in cards:
            fields = card.get("fields", {})
            statut = fields.get("Statut", "")

            if statut not in inbox_statuts:
                continue

            # Exclure les clients déjà assignés à une tournée
            tournee_assignee = fields.get("Tournée_assignée", "")
            if tournee_assignee:
                continue

            client_name = fields.get("Nom du Client", "").strip()
            date_creation = fields.get("Date", "")
            notes = fields.get("Notes", "")
            montant = fields.get("Montant", 0)

            # Récupérer les infos du client depuis la table Clients
            client_record = clients_by_name.get(client_name.upper())
            adresse = ""
            zone = "Autre"
            nb_bouquets = 1
            code_postal = ""

            if client_record:
                client_fields = client_record.get("fields", {})
                adresse = client_fields.get("Adresse", "")
                code_postal = extract_postal_code(adresse)
                zone = get_geographic_zone(code_postal)
                nb_bouquets = client_fields.get("Nb_Bouquets", 1)

            # Calculer jours d'attente
            jours_attente = 0
            if date_creation:
                try:
                    date_obj = datetime.strptime(date_creation, "%Y-%m-%d")
                    jours_attente = (datetime.now() - date_obj).days
                except:
                    pass

            client_info = {
                "card_id": card["id"],
                "client_id": client_record["id"] if client_record else None,
                "nom": client_name,
                "statut": statut,
                "adresse": adresse,
                "zone": zone,
                "code_postal": code_postal,
                "nb_bouquets": nb_bouquets,
                "montant": montant,
                "notes": notes,
                "jours_attente": jours_attente,
                "alerte": jours_attente > 4,
                "date_creation": date_creation
            }

            inbox_clients.append(client_info)
            clients_par_zone[zone].append(client_info)

        # 5. Calculer les options de placement pour chaque client
        for client in inbox_clients:
            options = []
            zone = client["zone"]

            # Option 1: Greffe - existe-t-il une tournée cette semaine dans la même zone?
            for tournee in tournees:
                tournee_zones = tournee.get("zones", [])
                if zone in tournee_zones or zone == "Autre":
                    # Vérifier s'il reste de la place (< 12 clients)
                    if tournee.get("nb_clients", 0) < 12:
                        temps_ajoute = 20  # ~20 min par client
                        options.append({
                            "type": "greffe",
                            "tournee_id": tournee.get("numero"),
                            "tournee_nom": f"Tournée {tournee.get('numero')} - {tournee.get('jour', 'À planifier')}",
                            "tournee_jour": tournee.get("jour", "À planifier"),
                            "temps_ajoute": temps_ajoute,
                            "nb_clients_tournee": tournee.get("nb_clients", 0)
                        })

            # Option 2: Mini-tournée - y a-t-il 2+ autres clients en attente dans la même zone?
            autres_clients_zone = [c for c in clients_par_zone.get(zone, []) if c["card_id"] != client["card_id"]]
            if len(autres_clients_zone) >= 2:
                options.append({
                    "type": "mini",
                    "clients_groupables": [{"nom": c["nom"], "adresse": c["adresse"]} for c in autres_clients_zone[:5]],
                    "nb_clients_groupables": len(autres_clients_zone)
                })

            # Option 3: Filet - toujours disponible
            options.append({
                "type": "filet",
                "description": "Livraison individuelle"
            })

            client["options"] = options

        # Trier par urgence (alerte d'abord, puis par jours d'attente)
        inbox_clients.sort(key=lambda c: (-c["alerte"], -c["jours_attente"]))

        return jsonify({
            "success": True,
            "total": len(inbox_clients),
            "alertes": sum(1 for c in inbox_clients if c["alerte"]),
            "clients": inbox_clients
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/api/inbox/placer", methods=["POST"])
def api_inbox_placer():
    """Place un client dans une tournée"""
    data = request.json
    client_id = data.get("client_id")
    card_id = data.get("card_id")
    option = data.get("option")  # "greffe", "mini", "filet"
    tournee_id = data.get("tournee_id")  # requis si greffe

    if not card_id or not option:
        return jsonify({"error": "card_id et option requis"}), 400

    try:
        result = {"success": True, "action": option}

        if option == "greffe":
            if not tournee_id:
                return jsonify({"error": "tournee_id requis pour greffe"}), 400

            # Marquer le client comme planifié
            if client_id:
                update_client(client_id, {"Actif": True})

            # Créer une livraison liée à cette tournée
            if client_id:
                livraison_data = {
                    "Client": [client_id],
                    "Statut": "Planifiée",
                    "Type": "Greffe",
                    "Notes": f"Greffé sur Tournée {tournee_id}"
                }
                liv_result = create_livraison(livraison_data)
                result["livraison"] = liv_result

            result["message"] = f"Client greffé sur la tournée {tournee_id}"

        elif option == "mini":
            # Créer une nouvelle mini-tournée
            if client_id:
                update_client(client_id, {"Actif": True})

                livraison_data = {
                    "Client": [client_id],
                    "Statut": "À planifier",
                    "Type": "Mini-tournée"
                }
                liv_result = create_livraison(livraison_data)
                result["livraison"] = liv_result

            result["message"] = "Client ajouté à une nouvelle mini-tournée"

        elif option == "filet":
            # Livraison individuelle
            if client_id:
                update_client(client_id, {"Actif": True})

                livraison_data = {
                    "Client": [client_id],
                    "Statut": "À planifier",
                    "Type": "Filet"
                }
                liv_result = create_livraison(livraison_data)
                result["livraison"] = liv_result

            result["message"] = "Client placé en livraison filet"

        # Marquer la carte comme assignée à une tournée (sans changer le statut commercial)
        tournee_label = f"Tournée {tournee_id}" if option == "greffe" else ("Mini-tournée" if option == "mini" else "Filet")
        update_suivi_card(card_id, {"Tournée_assignée": tournee_label})

        return jsonify(result)

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# TEMPORAIREMENT DÉSACTIVÉ - Tournées et dispatch (on y reviendra plus tard)
# @app.route("/api/tournees", methods=["GET"])
# def api_tournees():
#     """Prépare la tournée optimisée de la semaine"""
#     try:
#         results = prepare_tournees()
#         return jsonify(results)
#     except Exception as e:
#         import traceback
#         return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# @app.route("/api/dispatch/tournees", methods=["GET"])
# def api_dispatch_tournees():
#     """Retourne la liste des tournées pour le dispatch"""
#     try:
#         results = get_tournees_summary()
#         return jsonify(results)
#     except Exception as e:
#         import traceback
#         return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# @app.route("/api/dispatch/<int:tournee_num>", methods=["GET"])
# def api_dispatch_tournee(tournee_num):
#     """Génère des suggestions de dispatch pour une tournée spécifique"""
#     try:
#         results = dispatch_for_tournee(tournee_num)
#         return jsonify(results)
#     except Exception as e:
#         import traceback
#         return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


# @app.route("/api/dispatch/valider", methods=["POST"])
# def api_dispatch_valider():
#     """Valide l'assignation d'un bouquet à un client"""
#     data = request.json
#     client_id = data.get("client_id")
#     bouquet_record_id = data.get("bouquet_record_id")

#     if not client_id or not bouquet_record_id:
#         return jsonify({"error": "client_id et bouquet_record_id requis"}), 400

#     try:
#         result = valider_dispatch(client_id, bouquet_record_id)
#         return jsonify(result)
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


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
