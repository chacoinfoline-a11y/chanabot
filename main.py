from flask import Flask, request, jsonify
import requests
import os
import traceback
import json
import time
from threading import Thread

app = Flask(__name__)

# ─────────────────────────────────────────
# 🔐 CONFIG (variables d'environnement)
# ─────────────────────────────────────────
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
ID_INSTANCE       = os.getenv("ID_INSTANCE")
API_TOKEN         = os.getenv("API_TOKEN")
INTERNAL_GROUP_ID = os.getenv("INTERNAL_GROUP_ID", "REMPLACE_PAR_TON_GROUP_ID@g.us")

GREEN_API_BASE = f"https://api.green-api.com/waInstance{ID_INSTANCE}"

# ─────────────────────────────────────────
# 🗂️ ÉTAT EN MÉMOIRE
# ─────────────────────────────────────────
# Etats possibles par chat_id :
#   "menu"    → a reçu le menu 1/2, attend un choix
#   "human"   → a choisi 1, transféré à un humain (bot silencieux)
#   "ai"      → a choisi 2, mode IA actif

user_state: dict[str, str] = {}
processed_messages: set[str] = set()


# ─────────────────────────────────────────
# 🧹 Nettoyage mémoire périodique
# ─────────────────────────────────────────
def clean_cache():
    while True:
        time.sleep(300)
        if len(processed_messages) > 2000:
            processed_messages.clear()

Thread(target=clean_cache, daemon=True).start()


# ─────────────────────────────────────────
# 🧠 LOG
# ─────────────────────────────────────────
def log(title: str, data: dict, force: bool = False):
    if force or os.getenv("DEBUG", "false").lower() == "true":
        print(f"\n{'=' * 60}\n🔥 {title}\n{'=' * 60}")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:600])
        print("=" * 60 + "\n")


# ─────────────────────────────────────────
# 📤 ENVOI WHATSAPP
# ─────────────────────────────────────────
def send_whatsapp(chat_id: str, message: str) -> bool:
    try:
        url     = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
        payload = {"chatId": chat_id, "message": message}
        res     = requests.post(url, json=payload, timeout=8)
        log("SEND", {"to": chat_id, "status": res.status_code, "msg": message[:80]})
        return res.status_code == 200
    except Exception as e:
        print(f"❌ SEND ERROR ({chat_id}): {e}")
        return False


# ─────────────────────────────────────────
# 🚨 ALERTE GROUPE INTERNE
# ─────────────────────────────────────────
def alert_internal_team(chat_id: str, message: str):
    alert = (
        f"🚨 *DEMANDE OPÉRATEUR*\n\n"
        f"👤 Numéro client : {chat_id}\n"
        f"💬 Message : \"{message[:300]}\"\n\n"
        f"✅ Action requise : prise en charge humaine"
    )
    ok = send_whatsapp(INTERNAL_GROUP_ID, alert)
    print(f"{'✅' if ok else '❌'} Alerte interne → {chat_id}")


# ─────────────────────────────────────────
# 🤖 RÉPONSE IA (Groq)
# ─────────────────────────────────────────
SYSTEM_PROMPT = """Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.
Tu représentes l'entreprise 24h/24 et 7j/7 sur WhatsApp.

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT en français.
2. Réponds à TOUTES les questions posées dans un même message sans en omettre aucune.
3. Ton professionnel, chaleureux et rassurant.
4. Ne jamais inventer une information. Si inconnue : "Je transmettrai votre demande à un conseiller."
5. Ne jamais discuter de politique, religion ou sujets hors-sujet.
6. NE PAS saluer à nouveau — le client a déjà été accueilli.

PRÉSENTATION CHANA CORPORATE :
Entreprise ivoirienne spécialisée dans l'accompagnement commercial international, mise en relation d'affaires, sourcing international, recherche de fournisseurs fiables, organisation de missions commerciales, accompagnement logistique et développement de partenariats stratégiques.

MISSION COMMERCIALE CHINE 2026 :
- Nom : Mission Commerciale Côte d'Ivoire - Chine 2026
- Dates : 22 au 31 juillet 2026 (10 jours)
- Destination : Province de Zhejiang, Chine
- Organisateurs : Chana Corporate & African Wind
- Partenaire local : consortium de 1 000+ entreprises chinoises

OBJECTIFS :
Achat direct en usine · Réduction des intermédiaires · Marges améliorées · Fournisseurs fiables · Tarifs préférentiels · Réseau d'affaires international · Partenariats durables

POURQUOI LE ZHEJIANG ?
1 000+ entreprises partenaires · Berceau d'Alibaba et Geely · Marché international de Yiwu · Infrastructures portuaires de premier plan · Prix plus compétitifs que Guangzhou · Forte densité de PME industrielles

PROFIL PARTICIPANTS :
Entreprises, PME, commerçants, coopératives, importateurs, distributeurs, entrepreneurs, particuliers

SECTEURS :
BTP · Automobile · Agriculture · Électroménager · Textile · Fournitures scolaires/bureau · Mobilier · Équipements médicaux · Énergies renouvelables · Commerce général

CONTENU DU FORFAIT (tout inclus) :
Visa business · Billet A/R · Hôtel 3-4 étoiles · 3 repas/jour · Rencontres B2B · Visites d'usines · Marché de Yiwu · Transport local · Interprètes français-chinois · Accompagnement commercial & logistique · Suivi commandes · Contrôle qualité · Assistance jusqu'à livraison

PROGRAMME :
J1-J2 : Accueil, installation, briefing, découverte culturelle
J3 : Rencontres B2B et réseautage
J4-J6 : Visites d'usines + marché de Yiwu
J7-J8 : Négociations, commandes, finalisation
J9-J10 : Débriefing, visite portuaire, retour

TARIFICATION :
Total : 2 500 000 FCFA/participant
Acompte (40%) : 1 000 000 FCFA à l'inscription
Solde (60%) : 1 500 000 FCFA avant le 1er juillet 2026
Paiements : Mobile Money, espèces, chèque

GARANTIES :
Fournisseurs identifiés avant le départ · Sourcing personnalisé · Mise en relation ciblée · Suivi logistique & commandes après retour

QUALIFICATION PROSPECT :
Si intérêt détecté, poser : "Quel type de produit recherchez-vous ? Cela nous permettra d'identifier les opportunités adaptées à votre besoin."

COORDONNÉES :
WhatsApp : +225 05 00 02 60 72
Téléphone : +225 27 22 23 66 83
Email : chanacorporate@gmail.com
Adresse 1 : Cocody Riviera 3, Rue Kloé, près de la Clinique Saint Viateur
Adresse 2 : Immeuble XL, Rue Dr Crozet, Boulevard de la République"""


def ask_groq(message: str) -> str:
    try:
        start = time.time()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": message}
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
            "top_p": 1
        }
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=15
        )
        duration = time.time() - start
        if res.status_code != 200:
            log("GROQ ERROR", {"status": res.status_code, "body": res.text[:300]}, force=True)
            return "Désolé, une erreur est survenue. Veuillez réessayer dans quelques instants."
        reply = res.json()["choices"][0]["message"]["content"].strip()
        log("GROQ OK", {"duration": f"{duration:.2f}s", "reply": reply[:200]})
        return reply
    except requests.Timeout:
        return "Je réfléchis encore... merci de patienter quelques secondes puis renvoyez votre question. 🙏"
    except Exception as e:
        print(f"❌ GROQ ERROR: {e}")
        return "Le service est momentanément indisponible. Veuillez réessayer."


# ─────────────────────────────────────────
# 📩 MESSAGES PRÉDÉFINIS
# ─────────────────────────────────────────
WELCOME_MENU = (
    "Bonjour et bienvenue chez Chana Corporate 👋\n\n"
    "Avant de continuer, merci de choisir une option en répondant par un chiffre :\n\n"
    "1️⃣ Vous avez besoin d'un conseiller humain\n"
    "2️⃣ Vous souhaitez découvrir nos services et notre mission commerciale en Chine 🇨🇳\n\n"
    "👉 Répondez simplement par *1* ou *2*."
)

INVALID_CHOICE = (
    "Je n'ai pas compris votre choix. 😊\n\n"
    "Merci de répondre uniquement par :\n"
    "*1* → Parler à un conseiller humain\n"
    "*2* → Découvrir nos services"
)

HUMAN_REPLY = (
    "Merci ! Un conseiller Chana Corporate va vous contacter très rapidement. 🙏\n\n"
    "En attendant, n'hésitez pas à nous joindre directement :\n"
    "📞 +225 27 22 23 66 83\n"
    "📧 chanacorporate@gmail.com"
)

AI_INTRO = (
    "Avec plaisir ! 😊 Je suis CHANA ASSISTANT, votre guide pour tout savoir sur "
    "notre mission commerciale en Chine et nos services.\n\n"
    "Quelle est votre question ?"
)


# ─────────────────────────────────────────
# 🛡️ ANTI-DOUBLON
# ─────────────────────────────────────────
def is_duplicate(msg_id: str) -> bool:
    if msg_id in processed_messages:
        return True
    processed_messages.add(msg_id)
    return False


# ─────────────────────────────────────────
# 📩 WEBHOOK PRINCIPAL
# ─────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # Uniquement les messages entrants
        if data.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"ignored": True, "reason": "not_a_message"})

        sender   = data.get("senderData", {})
        msg_data = data.get("messageData", {})

        chat_id  = sender.get("chatId", "")
        message  = msg_data.get("textMessageData", {}).get("textMessage", "").strip()
        msg_id   = data.get("idMessage", "")

        # Ignorer les groupes externes
        if chat_id.endswith("@g.us"):
            return jsonify({"ignored": True, "reason": "group_message"})

        if not chat_id or not message:
            return jsonify({"error": "Missing data"}), 200

        # Anti-doublon
        if msg_id and is_duplicate(msg_id):
            print(f"⛔ Doublon ignoré: {msg_id}")
            return jsonify({"ignored": True, "reason": "duplicate"})

        log("📩 MESSAGE", {"chat_id": chat_id, "message": message[:100], "msg_id": msg_id})

        state = user_state.get(chat_id)

        # ═══════════════════════════════════════
        # ÉTAPE 1 — Nouveau client : envoi du menu
        # ═══════════════════════════════════════
        if state is None:
            user_state[chat_id] = "menu"
            send_whatsapp(chat_id, WELCOME_MENU)
            return jsonify({
                "success": True,
                "action": "welcome_menu_sent",
                "chat_id": chat_id,
                "duration": f"{time.time() - start_time:.2f}s"
            })

        # ═══════════════════════════════════════
        # ÉTAPE 2 — Client attend choix 1 ou 2
        # ═══════════════════════════════════════
        if state == "menu":

            # Choix 1 : opérateur humain
            if message in ("1", "1️⃣"):
                user_state[chat_id] = "human"
                send_whatsapp(chat_id, HUMAN_REPLY)
                Thread(
                    target=alert_internal_team,
                    args=(chat_id, message),
                    daemon=True
                ).start()
                return jsonify({
                    "success": True,
                    "action": "human_transfer",
                    "chat_id": chat_id,
                    "duration": f"{time.time() - start_time:.2f}s"
                })

            # Choix 2 : mode IA
            if message in ("2", "2️⃣"):
                user_state[chat_id] = "ai"
                send_whatsapp(chat_id, AI_INTRO)
                return jsonify({
                    "success": True,
                    "action": "ai_mode_activated",
                    "chat_id": chat_id,
                    "duration": f"{time.time() - start_time:.2f}s"
                })

            # Choix invalide : on redemande poliment
            send_whatsapp(chat_id, INVALID_CHOICE)
            return jsonify({
                "success": True,
                "action": "invalid_choice_reprompted",
                "chat_id": chat_id,
                "duration": f"{time.time() - start_time:.2f}s"
            })

        # ═══════════════════════════════════════
        # ÉTAPE 3 — Client transféré à un humain
        # Bot silencieux (ne pas interférer)
        # ═══════════════════════════════════════
        if state == "human":
            print(f"🔕 Bot silencieux pour {chat_id} (état: human)")
            return jsonify({
                "ignored": True,
                "reason": "human_mode_active",
                "chat_id": chat_id
            })

        # ═══════════════════════════════════════
        # ÉTAPE 4 — Mode IA actif
        # ═══════════════════════════════════════
        if state == "ai":
            reply = ask_groq(message)
            send_whatsapp(chat_id, reply)
            return jsonify({
                "success": True,
                "action": "ai_reply",
                "chat_id": chat_id,
                "reply": reply,
                "duration": f"{time.time() - start_time:.2f}s"
            })

        # Cas imprévu
        return jsonify({"error": "Unknown state", "state": state}), 500

    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "duration": f"{time.time() - start_time:.2f}s"
        }), 500


# ─────────────────────────────────────────
# 🏥 HEALTH CHECK
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    states_count = {}
    for s in user_state.values():
        states_count[s] = states_count.get(s, 0) + 1
    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v3",
        "model":              "llama-3.3-70b-versatile",
        "total_users":        len(user_state),
        "states_breakdown":   states_count,
        "processed_messages": len(processed_messages)
    })


# ─────────────────────────────────────────
# 🚀 DÉMARRAGE
# ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"""
    ╔══════════════════════════════════════════╗
    ║   🤖  CHANA CORPORATE BOT  v3.0  READY  ║
    ║   Port   : {port}                          ║
    ║   Model  : llama-3.3-70b-versatile       ║
    ║   Groupe : {INTERNAL_GROUP_ID[:35]}  ║
    ╚══════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
