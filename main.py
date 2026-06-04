"""
╔══════════════════════════════════════════════════════════════╗
║        CHANA CORPORATE WHATSAPP BOT  v12.0                  ║
║        Render stable — threading par requête                ║
╠══════════════════════════════════════════════════════════════╣
║  Start Command Render :                                     ║
║  gunicorn main:app --bind 0.0.0.0:$PORT                    ║
║  --workers 1 --threads 8 --timeout 120                     ║
╚══════════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify
import requests
import os
import time
import signal
import threading
import traceback
from datetime import datetime

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════
# 🔐 CONFIG
# ═══════════════════════════════════════════════════════════════
GROQ_API_KEY     = os.getenv("GROQ_API_KEY",     "")
ID_INSTANCE      = os.getenv("ID_INSTANCE",      "")
API_TOKEN        = os.getenv("API_TOKEN",         "")
OPERATOR_CHAT_ID = os.getenv("OPERATOR_CHAT_ID", "")
BOT_OWN_NUMBER   = os.getenv("BOT_OWN_NUMBER",   "")

GREEN_API_BASE = f"https://api.green-api.com/waInstance{ID_INSTANCE}"

MEMORY_TTL     = 7_200
HISTORY_MAX    = 20
ESCALADE_SEUIL = 5

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM  = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_PDF   = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"
LINK_BROCH = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"

# ═══════════════════════════════════════════════════════════════
# 📊 STATE GLOBAL
# ═══════════════════════════════════════════════════════════════
STATE = {
    "started_at":   time.time(),
    "last_webhook": None,
    "messages":     0,
    "alive":        True,
}

def _sigterm(sig, frame):
    print("🚨 SIGTERM reçu", flush=True)
    STATE["alive"] = False

signal.signal(signal.SIGTERM, _sigterm)

# ═══════════════════════════════════════════════════════════════
# 💓 HEARTBEAT
# ═══════════════════════════════════════════════════════════════
def _heartbeat():
    while True:
        up = int(time.time() - STATE["started_at"])
        print(
            f"💓 alive | up={up}s | msg={STATE['messages']} | last={STATE['last_webhook']}",
            flush=True
        )
        time.sleep(15)

threading.Thread(target=_heartbeat, daemon=True, name="Heartbeat").start()

# ═══════════════════════════════════════════════════════════════
# 🗂️  MÉMOIRE
# ═══════════════════════════════════════════════════════════════
user_state:           dict = {}
conversation_history: dict = {}
processed_messages:   set  = set()
_state_lock = threading.Lock()

stats = {
    "started_at":       datetime.now().isoformat(),
    "jobs_processed":   0,
    "jobs_failed":      0,
    "ignored_offtopic": 0,
}

# ═══════════════════════════════════════════════════════════════
# ✅ CHECK VARIABLES
# ═══════════════════════════════════════════════════════════════
def check_env():
    required = {
        "GROQ_API_KEY": GROQ_API_KEY, "ID_INSTANCE": ID_INSTANCE,
        "API_TOKEN": API_TOKEN, "OPERATOR_CHAT_ID": OPERATOR_CHAT_ID,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"❌ VARIABLES MANQUANTES : {', '.join(missing)}", flush=True)
    else:
        t = "GROUPE" if OPERATOR_CHAT_ID.endswith("@g.us") else "NUMÉRO"
        print(f"✅ Config OK | Alertes → {t} : {OPERATOR_CHAT_ID}", flush=True)

check_env()

# ═══════════════════════════════════════════════════════════════
# 🧹 NETTOYAGE MÉMOIRE
# ═══════════════════════════════════════════════════════════════
def _memory_cleanup():
    while True:
        try:
            time.sleep(1_800)
            cutoff = time.time() - MEMORY_TTL
            with _state_lock:
                expired = [
                    cid for cid, s in list(user_state.items())
                    if s.get("last_seen", s.get("created_at", 0)) < cutoff
                ]
                for cid in expired:
                    user_state.pop(cid, None)
                    conversation_history.pop(cid, None)
                if len(processed_messages) > 3_000:
                    processed_messages.clear()
            if expired:
                print(f"🧹 {len(expired)} session(s) expirée(s)", flush=True)
        except Exception as e:
            print(f"⚠️  cleanup error : {e}", flush=True)

threading.Thread(target=_memory_cleanup, daemon=True, name="MemCleanup").start()

# ═══════════════════════════════════════════════════════════════
# 📤 ENVOI WHATSAPP
# ═══════════════════════════════════════════════════════════════
def send_whatsapp(chat_id: str, message: str) -> bool:
    if not chat_id:
        print("❌ SEND: chat_id vide", flush=True)
        return False
    if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
        print("❌ SEND: self-send bloqué", flush=True)
        return False
    url = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
    try:
        r = requests.post(
            url,
            json={"chatId": chat_id, "message": message},
            timeout=(3, 10)
        )
        ok = r.status_code == 200
        print(
            f"{'✅' if ok else '❌'} SEND → {chat_id} "
            f"status={r.status_code} | {r.text[:100]}",
            flush=True
        )
        return ok
    except requests.exceptions.ConnectTimeout:
        print(f"❌ SEND ConnectTimeout → {chat_id}", flush=True)
    except requests.exceptions.ReadTimeout:
        print(f"❌ SEND ReadTimeout → {chat_id}", flush=True)
    except Exception as e:
        print(f"❌ SEND Exception → {chat_id} : {e}", flush=True)
    return False

# ═══════════════════════════════════════════════════════════════
# 🚨 ALERTES OPÉRATEUR
# ═══════════════════════════════════════════════════════════════
def alert_escalation(chat_id: str, msg: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    send_whatsapp(OPERATOR_CHAT_ID,
        f"🔔 *CLIENT PRÊT POUR PRISE EN CHARGE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Dernier message : \"{msg[:250]}\"\n"
        f"📊 {ESCALADE_SEUIL} échanges IA complétés\n"
        f"⏱️ {ts}\n\n"
        f"👉 Ce client attend un conseiller."
    )

def alert_human_request(chat_id: str, msg: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    send_whatsapp(OPERATOR_CHAT_ID,
        f"🚨 *DEMANDE HUMAIN EXPLICITE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 \"{msg[:250]}\"\n"
        f"📌 URGENT — CLIENT DEMANDE UN CONSEILLER\n"
        f"⏱️ {ts}"
    )

# ═══════════════════════════════════════════════════════════════
# 📨 PARSE_MESSAGE — multi-format Green API
#
# Green API peut envoyer le texte dans plusieurs champs selon
# le type de message. Cette fonction les essaie tous dans l'ordre
# et retourne (texte, source) ou ("", "none") si vide.
#
# Formats supportés :
#   textMessageData.textMessage          → message texte simple
#   extendedTextMessageData.text         → message avec preview/lien
#   quotedMessage.textMessageData.text   → message cité
#   imageMessage.caption                 → légende photo
#   videoMessage.caption                 → légende vidéo
#   documentMessage.caption              → légende document
#   locationMessage.nameLocation         → lieu partagé
# ═══════════════════════════════════════════════════════════════
def parse_message(msg_data: dict) -> tuple[str, str]:
    """
    Extrait le texte d'un messageData Green API.
    Retourne (texte_nettoyé, source_field).
    Retourne ("", "none") si aucun texte trouvé.
    """
    if not msg_data:
        return "", "none"

    # ── 1. Message texte simple ───────────────────────────────
    text = msg_data.get("textMessageData", {}).get("textMessage", "")
    if text and text.strip():
        return text.strip(), "textMessageData"

    # ── 2. Message texte étendu (liens, previews) ─────────────
    text = msg_data.get("extendedTextMessageData", {}).get("text", "")
    if text and text.strip():
        return text.strip(), "extendedTextMessageData"

    # ── 3. Message cité (reply) ───────────────────────────────
    # Le vrai texte du client est dans le champ "caption" ou
    # dans extendedTextMessageData même pour les replies
    quoted = msg_data.get("quotedMessage", {})
    if quoted:
        text = quoted.get("textMessageData", {}).get("textMessage", "")
        if text and text.strip():
            return text.strip(), "quotedMessage"

    # ── 4. Légende image / vidéo / document ──────────────────
    for field in ("imageMessage", "videoMessage", "documentMessage"):
        text = msg_data.get(field, {}).get("caption", "")
        if text and text.strip():
            return text.strip(), field

    # ── 5. Localisation partagée ─────────────────────────────
    text = msg_data.get("locationMessage", {}).get("nameLocation", "")
    if text and text.strip():
        return text.strip(), "locationMessage"

    # ── 6. Aucun texte trouvé — on log le contenu brut ───────
    keys = list(msg_data.keys())
    print(f"⚠️  parse_message: aucun texte trouvé | clés disponibles: {keys}", flush=True)
    return "", "none"


# ═══════════════════════════════════════════════════════════════
# 🔍 FILTRE DE PERTINENCE — 5 niveaux
# ═══════════════════════════════════════════════════════════════

POSITIVE_KEYWORDS = [
    "chine", "chana", "zhejiang", "yiwu", "mission commerciale",
    "voyage", "fournisseur", "usine", "sourcing", "importation",
    "importateur", "exportation", "produit", "commande",
    "inscription", "s'inscrire", "inscrire", "forfait", "tarif",
    "prix", "acompte", "paiement", "visa", "billet", "hôtel",
    "african wind",
    "pub", "publicité", "facebook", "annonce", "instagram",
    "votre annonce", "votre pub", "j'ai vu", "j'ai lu",
    "votre post", "votre publication", "votre page",
    "je viens de voir", "je viens de lire", "je suis tombé",
    "je suis tombée", "vu sur", "lu sur", "seen on",
    "your ad", "your post", "i saw", "i seen", "i just saw",
    "intéressé", "interesse", "interested", "renseignement",
    "information", "plus d'info", "plus d info", "more info",
    "en savoir plus", "savoir plus", "en savoir davantage",
    "tell me more", "learn more", "know more",
    "comment ça marche", "comment ca marche", "how does it work",
    "c'est quoi", "c'est combien", "what is this", "what is it",
    "how much", "combien ça coûte", "combien ca coute",
    "brochure", "fiche", "formulaire",
    "btp", "automobile", "textile", "électroménager",
    "agriculture", "mobilier", "médical", "énergie",
    "à ce sujet", "a ce sujet", "about this", "about that",
    "ce programme", "ce voyage", "cette mission", "cette offre",
    "plus d'informations", "plus d informations",
    "pouvez-vous", "pouvez vous", "can you tell",
    "puis-je", "puis je", "may i", "could you",
    "j'aimerais savoir", "je souhaite savoir", "je voudrais savoir",
    "i would like to know", "i'd like to know",
]

NEGATIVE_KEYWORDS = [
    "météo", "meteo", "foot", "football", "ballon",
    "recette", "cuisine", "restaurant", "match",
    "politique", "élection", "election", "président",
    "religion", "dieu", "prière", "priere", "église",
    "blague", "joke", "lol", "haha", "mdr",
    "amour", "chéri", "cherie", "copine", "copain",
    "appel manqué", "appel manque",
]

GREETINGS_ONLY = {
    "bonjour", "bonsoir", "salut", "allô", "allo",
    "hello", "hi", "hey", "coucou", "bonne journée",
    "bonne journee", "bonne nuit", "bjr", "bsr", "slt",
    "bsr", "bjrs", "bnjr",
}

INTEREST_PATTERNS = [
    "en savoir plus", "savoir plus", "plus d'info", "plus d info",
    "more info", "tell me more", "learn more", "know more",
    "à ce sujet", "a ce sujet", "about this", "about that",
    "puis-je", "puis je", "may i", "pouvez-vous", "pouvez vous",
    "je viens de voir", "je viens de lire", "i just saw", "i saw your",
    "vu sur", "lu sur", "votre pub", "votre annonce", "your ad",
    "ce sujet", "cette offre", "ce programme",
    "interested", "intéressé", "interesse",
    "en savoir davantage", "davantage d'info",
    "could you tell", "can you tell", "can i know",
    "j'aimerais savoir", "je souhaite savoir", "je voudrais savoir",
    "i would like to know", "i'd like to know",
]


def _is_greeting_only(message: str) -> bool:
    clean = message.lower().strip().rstrip("!.,?")
    if clean in GREETINGS_ONLY:
        return True
    msg_lower = message.lower()
    if any(p in msg_lower for p in INTEREST_PATTERNS):
        return False
    for greet in GREETINGS_ONLY:
        if clean.startswith(greet):
            remainder = clean[len(greet):].strip().lstrip(",;-– ")
            if len(remainder) > 3:
                return False
    return False


def is_relevant(message: str) -> bool:
    msg_lower = message.lower()

    if any(kw in msg_lower for kw in NEGATIVE_KEYWORDS):
        print(f"🚫 [FILTRE] Mot-clé négatif → IGNORE", flush=True)
        return False

    if any(kw in msg_lower for kw in POSITIVE_KEYWORDS):
        print(f"✅ [FILTRE] Mot-clé positif → ACCEPT", flush=True)
        return True

    if any(p in msg_lower for p in INTEREST_PATTERNS):
        print(f"✅ [FILTRE] Pattern intérêt → ACCEPT", flush=True)
        return True

    if _is_greeting_only(message):
        print(f"🔕 [FILTRE] Salutation seule → IGNORE", flush=True)
        return False

    # Zone grise → Groq
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Tu es un classificateur strict pour un bot commercial WhatsApp "
                            "d'une entreprise ivoirienne organisant des voyages d'affaires "
                            "en Chine (Chana Corporate).\n\n"
                            "Réponds UNIQUEMENT OUI ou NON.\n\n"
                            "OUI si le message exprime :\n"
                            "- un intérêt pour une mission commerciale, voyage d'affaires, "
                            "sourcing, importation/exportation, fournisseurs chinois\n"
                            "- une question sur les services ou tarifs de l'entreprise\n"
                            "- une demande suite à une publicité Facebook/Instagram\n"
                            "- une intention d'achat ou d'inscription\n"
                            "- une curiosité sur une offre vue en ligne\n\n"
                            "NON dans TOUS les autres cas.\n"
                            "Sois STRICT. En cas de doute → NON."
                        )
                    },
                    {"role": "user", "content": message}
                ],
                "temperature": 0.0,
                "max_tokens": 5
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}"
            },
            timeout=(3, 6)
        )
        if r.status_code != 200:
            print(f"⚠️ [FILTRE] Groq KO ({r.status_code}) → fail-open", flush=True)
            return True
        answer = r.json()["choices"][0]["message"]["content"].strip().upper()
        result = answer.startswith("OUI")
        print(f"🔍 [FILTRE] Groq → {'ACCEPT' if result else 'IGNORE'} | '{message[:50]}'", flush=True)
        return result
    except Exception as e:
        print(f"⚠️ [FILTRE] Exception ({e}) → fail-open", flush=True)
        return True


# ═══════════════════════════════════════════════════════════════
# 🔍 DÉTECTION DEMANDE HUMAIN
# ═══════════════════════════════════════════════════════════════
HUMAN_KEYWORDS = [
    "humain", "conseiller", "opérateur", "operateur", "responsable",
    "agent", "quelqu'un", "quelqu un", "appel", "rappel",
    "rendez-vous", "rendez vous", "parler à", "parler a",
    "je veux parler", "une personne", "vrai personne",
    "pas un robot", "pas un bot", "réclamation", "reclamation",
    "négocier", "negocier", "dossier", "directeur", "gérant", "gerant",
]

def wants_human(message: str) -> bool:
    return any(kw in message.lower() for kw in HUMAN_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# 🤖 RÉPONSE IA
# ═══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.
Tu représentes l'entreprise 24h/24 et 7j/7 sur WhatsApp.

CONTEXTE IMPORTANT :
Certains prospects arrivent via une campagne publicitaire Facebook/Instagram.
Ils peuvent écrire : "j'ai vu votre pub", "votre annonce Facebook", "c'est quoi exactement ?", "puis-je en savoir plus ?".
Traite-les comme n'importe quel prospect — accueil chaleureux, présentation progressive.

OBJECTIF : Accueillir chaleureusement, comprendre le besoin, présenter les services progressivement, répondre à toutes les questions, amener vers l'inscription ou la prise de contact.

RÈGLES :
1. Réponds UNIQUEMENT en français.
2. Ton naturel, chaleureux, professionnel — comme un vrai commercial.
3. Présente les infos progressivement — pas tout d'un coup.
4. Réponds à TOUTES les questions posées sans en omettre aucune.
5. Ne jamais inventer. Si inconnu : "Je transmettrai votre demande à un conseiller."
6. Hors-sujet → décline poliment.
7. NE PAS re-saluer à chaque message. Saluer uniquement au premier échange.
8. Si le client est prêt à s'inscrire → partager les liens officiels.

LIENS OFFICIELS :
- Formulaire en ligne : {LINK_FORM}
- Brochure PDF : {LINK_BROCH}
- Fiche inscription PDF : {LINK_PDF}

CHANA CORPORATE :
Entreprise ivoirienne — accompagnement commercial international, sourcing, missions commerciales, logistique, partenariats stratégiques.

MISSION CHINE 2026 :
Dates : 22–31 juillet 2026 (10 jours) | Province de Zhejiang, Chine
Organisateurs : Chana Corporate & African Wind | Partenaires : 1 000+ entreprises chinoises

OBJECTIFS : Achat direct usine · Réduction intermédiaires · Marges améliorées · Fournisseurs fiables · Tarifs préférentiels

ZHEJIANG : Berceau Alibaba & Geely · Marché Yiwu · Ports top · Prix < Guangzhou · Dense en PME

SECTEURS : BTP · Auto · Agriculture · Électroménager · Textile · Fournitures · Mobilier · Médical · Énergies · Commerce général

FORFAIT INCLUS : Visa · Billet A/R · Hôtel 3-4★ · 3 repas/j · B2B · Usines · Yiwu · Transport · Interprètes · Suivi commandes · Contrôle qualité

PROGRAMME : J1-2 Accueil/Briefing | J3 B2B | J4-6 Usines+Yiwu | J7-8 Négos+Commandes | J9-10 Débriefing+Retour

TARIF : 2 500 000 FCFA | Acompte 40% = 1 000 000 FCFA | Solde avant 1er juillet 2026
Paiements : Mobile Money · Espèces · Chèque

CONTACTS : WhatsApp +225 05 00 02 60 72 | Tél +225 27 22 23 66 83 | chanacorporate@gmail.com
Adresses : Cocody Riviera 3, Rue Kloé | Immeuble XL, Rue Dr Crozet"""


def ask_groq(chat_id: str, message: str) -> str:
    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": message})
    if len(history) > HISTORY_MAX:
        conversation_history[chat_id] = history[-HISTORY_MAX:]
        history = conversation_history[chat_id]
    try:
        t0 = time.time()
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *history
                ],
                "temperature": 0.4,
                "max_tokens": 1024,
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}"
            },
            timeout=(3, 12)
        )
        if r.status_code != 200:
            print(f"❌ GROQ {r.status_code} : {r.text[:200]}", flush=True)
            return "Désolé, une erreur est survenue. Veuillez réessayer."
        reply = r.json()["choices"][0]["message"]["content"].strip()
        history.append({"role": "assistant", "content": reply})
        print(f"🤖 Groq OK ({time.time()-t0:.2f}s) | échanges={len(history)//2}", flush=True)
        return reply
    except requests.exceptions.ConnectTimeout:
        return "Je mets un peu de temps, merci de renvoyer votre question. 🙏"
    except requests.exceptions.ReadTimeout:
        return "Je réfléchis encore… merci de patienter puis renvoyez votre question. 🙏"
    except Exception as e:
        print(f"❌ GROQ exception : {e}", flush=True)
        return "Le service est momentanément indisponible. Veuillez réessayer."


# ═══════════════════════════════════════════════════════════════
# 🛡️ ANTI-DOUBLON
# ═══════════════════════════════════════════════════════════════
def is_duplicate(msg_id: str) -> bool:
    with _state_lock:
        if msg_id in processed_messages:
            return True
        processed_messages.add(msg_id)
        return False


# ═══════════════════════════════════════════════════════════════
# ⚙️  TRAITEMENT D'UN MESSAGE
# ═══════════════════════════════════════════════════════════════
def handle_message(chat_id: str, message: str):
    try:
        with _state_lock:
            state = user_state.get(chat_id)

        if state is None:
            if not is_relevant(message):
                stats["ignored_offtopic"] += 1
                print(f"🚫 [IGNORE] [{chat_id}] : '{message[:60]}'", flush=True)
                return
            print(f"✅ [NEW PROSPECT] {chat_id}", flush=True)
            now = time.time()
            with _state_lock:
                user_state[chat_id] = {
                    "step":       "ai",
                    "exchanges":  0,
                    "escalated":  False,
                    "created_at": now,
                    "last_seen":  now,
                }
                state = user_state[chat_id]

        with _state_lock:
            state["last_seen"] = time.time()
            step = state["step"]

        if step == "human":
            print(f"🔕 [SILENT] {chat_id}", flush=True)
            return

        if step == "ai":
            if wants_human(message):
                with _state_lock:
                    state["step"]      = "human"
                    state["escalated"] = True
                send_whatsapp(
                    chat_id,
                    "Bien sûr ! 🙏 Je vous mets immédiatement en contact avec un "
                    "conseiller Chana Corporate.\n\n"
                    "Un membre de notre équipe va vous répondre très rapidement.\n"
                    "Vous pouvez aussi nous joindre directement :\n"
                    "📞 +225 27 22 23 66 83\n"
                    "📧 chanacorporate@gmail.com"
                )
                alert_human_request(chat_id, message)
                stats["jobs_processed"] += 1
                return

            reply = ask_groq(chat_id, message)
            with _state_lock:
                state["exchanges"] += 1
                exchanges = state["exchanges"]

            send_whatsapp(chat_id, reply)
            print(f"💬 [EXCHANGE #{exchanges}] {chat_id}", flush=True)

            if exchanges >= ESCALADE_SEUIL and not state.get("escalated"):
                with _state_lock:
                    state["escalated"] = True
                    state["step"]      = "human"
                send_whatsapp(
                    chat_id,
                    "Merci pour cet échange enrichissant ! 😊\n\n"
                    "Afin de mieux vous accompagner, je vous mets maintenant en contact "
                    "avec l'un de nos conseillers Chana Corporate.\n\n"
                    "Il va vous recontacter très prochainement. 🙏\n\n"
                    "En attendant, voici nos documents officiels :\n"
                    f"📄 Brochure : {LINK_BROCH}\n"
                    f"📝 Fiche d'inscription : {LINK_PDF}\n"
                    f"🌐 Inscription en ligne : {LINK_FORM}"
                )
                alert_escalation(chat_id, message)

            stats["jobs_processed"] += 1

    except Exception as e:
        stats["jobs_failed"] += 1
        print(f"❌ [handle_message] [{chat_id}] : {e}", flush=True)
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════
# 📩 WEBHOOK — robuste multi-format Green API
# ═══════════════════════════════════════════════════════════════

# Types de webhooks Green API que l'on DOIT traiter
INCOMING_TYPES = {"incomingMessageReceived"}

# Types connus à ignorer silencieusement (pas de log d'erreur)
IGNORED_TYPES = {
    "outgoingMessageReceived",    # message envoyé par le bot
    "outgoingAPIMessageReceived", # message API sortant
    "messageDelivered",           # confirmation de livraison
    "messageRead",                # confirmation de lecture
    "deviceInfo",                 # info appareil
    "stateInstanceChanged",       # changement d'état de l'instance
    "statusInstanceChanged",      # changement de statut
    "incomingCall",               # appel entrant
    "outgoingCall",               # appel sortant
    "quotaExceeded",              # quota dépassé
}


@app.route("/webhook", methods=["POST"])
def webhook():
    STATE["last_webhook"] = time.strftime("%H:%M:%S")
    STATE["messages"] += 1

    try:
        # ── Parse du body ─────────────────────────────────────
        raw = request.get_data(as_text=True)
        data = request.get_json(force=True, silent=True)

        if not data:
            print(f"❌ [WEBHOOK] Body invalide | raw='{raw[:200]}'", flush=True)
            return jsonify({"error": "invalid_json"}), 400

        webhook_type = data.get("typeWebhook", "unknown")

        # ── Log RAW systématique ──────────────────────────────
        print(f"\n{'─'*55}", flush=True)
        print(f"📥 [WEBHOOK] type={webhook_type}", flush=True)

        # ── Ignorer les events système connus ─────────────────
        if webhook_type in IGNORED_TYPES:
            print(f"   → SKIP (event système)", flush=True)
            print(f"{'─'*55}\n", flush=True)
            return jsonify({"ignored": True, "reason": webhook_type}), 200

        # ── Traiter uniquement les messages entrants ──────────
        if webhook_type not in INCOMING_TYPES:
            print(f"   → SKIP (type non géré : {webhook_type})", flush=True)
            print(f"{'─'*55}\n", flush=True)
            return jsonify({"ignored": True, "reason": f"unhandled_type:{webhook_type}"}), 200

        # ── Extraction des champs ─────────────────────────────
        sender   = data.get("senderData", {})
        msg_data = data.get("messageData", {})
        chat_id  = sender.get("chatId", "")
        msg_id   = data.get("idMessage", "")

        print(f"   chat_id  = {chat_id}", flush=True)
        print(f"   msg_id   = {msg_id}", flush=True)
        print(f"   msg_data keys = {list(msg_data.keys())}", flush=True)

        # ── Filtres système ───────────────────────────────────
        if chat_id.endswith("@g.us"):
            print(f"   → SKIP (groupe externe)", flush=True)
            print(f"{'─'*55}\n", flush=True)
            return jsonify({"ignored": True, "reason": "group"}), 200

        if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
            print(f"   → SKIP (self)", flush=True)
            print(f"{'─'*55}\n", flush=True)
            return jsonify({"ignored": True, "reason": "self"}), 200

        # ── Anti-doublon ──────────────────────────────────────
        if msg_id and is_duplicate(msg_id):
            print(f"   → SKIP (doublon)", flush=True)
            print(f"{'─'*55}\n", flush=True)
            return jsonify({"ignored": True, "reason": "duplicate"}), 200

        # ── Parse multi-format ────────────────────────────────
        message, source = parse_message(msg_data)

        print(f"   source   = {source}", flush=True)
        print(f"   message  = '{message[:100]}'", flush=True)

        # ── Pas de texte exploitable ──────────────────────────
        if not message:
            print(f"   → SKIP (pas de texte | source={source})", flush=True)
            print(f"{'─'*55}\n", flush=True)
            # On répond quand même 200 pour ne pas faire retry Green API
            return jsonify({"ignored": True, "reason": f"no_text:{source}"}), 200

        print(f"   → ACCEPT → thread lancé", flush=True)
        print(f"{'─'*55}\n", flush=True)

        # ── Traitement async ──────────────────────────────────
        threading.Thread(
            target=handle_message,
            args=(chat_id, message),
            daemon=True,
            name=f"msg-{msg_id[:8] if msg_id else 'noid'}"
        ).start()

        return jsonify({"ok": True, "processing": True, "source": source}), 202

    except Exception as e:
        print(f"❌ [WEBHOOK EXCEPTION] {e}", flush=True)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# 🏓 /ping  /healthz  /health  /test-whatsapp
# ═══════════════════════════════════════════════════════════════
@app.route("/healthz")
def healthz():
    return "ok", 200

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status":       "alive" if STATE["alive"] else "stopping",
        "uptime":       int(time.time() - STATE["started_at"]),
        "messages":     STATE["messages"],
        "last_webhook": STATE["last_webhook"],
    }), 200

@app.route("/health", methods=["GET"])
@app.route("/", methods=["GET"])
def health():
    steps: dict = {}
    for s in user_state.values():
        k = s.get("step", "?")
        steps[k] = steps.get(k, 0) + 1
    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v12",
        "alive":              STATE["alive"],
        "uptime_s":           int(time.time() - STATE["started_at"]),
        "started_at":         stats["started_at"],
        "jobs_processed":     stats["jobs_processed"],
        "jobs_failed":        stats["jobs_failed"],
        "ignored_offtopic":   stats["ignored_offtopic"],
        "total_users":        len(user_state),
        "processed_messages": len(processed_messages),
        "steps_breakdown":    steps,
        "operator_target":    OPERATOR_CHAT_ID or "⚠️ NON CONFIGURÉ",
        "last_webhook":       STATE["last_webhook"],
    })

@app.route("/test-whatsapp", methods=["GET"])
def test_whatsapp():
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ok = send_whatsapp(
        OPERATOR_CHAT_ID,
        f"🧪 *TEST BOT CHANA CORPORATE v12*\n\n✅ Bot opérationnel.\n⏱️ {ts}"
    )
    return jsonify({"success": ok, "target": OPERATOR_CHAT_ID})

# ═══════════════════════════════════════════════════════════════
# ⚠️  PAS de app.run() — Gunicorn uniquement
#
#  Start Command Render :
#  gunicorn main:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
# ═══════════════════════════════════════════════════════════════
