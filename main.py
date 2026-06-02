from flask import Flask, request, jsonify
import requests
import os
import traceback
import json
import time
import threading
from datetime import datetime

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════
# 🔐 CONFIG — lecture des variables d'environnement
# ═══════════════════════════════════════════════════════════════
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
ID_INSTANCE     = os.getenv("ID_INSTANCE")
API_TOKEN       = os.getenv("API_TOKEN")

# ✅ OPERATOR_CHAT_ID supporte @c.us (numéro) ET @g.us (groupe)
# Exemples :
#   numéro perso  → "22505000XXXXX@c.us"
#   groupe interne → "120363XXXXXXXXXX@g.us"
OPERATOR_CHAT_ID = os.getenv("OPERATOR_CHAT_ID", "")

# Numéro du bot lui-même (pour éviter de s'envoyer des alertes à soi-même)
# Format : "22527XXXXXXXX@c.us"
BOT_OWN_NUMBER = os.getenv("BOT_OWN_NUMBER", "")

GREEN_API_BASE = f"https://api.green-api.com/waInstance{ID_INSTANCE}"

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM_ONLINE = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_BROCHURE    = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"
LINK_FORM_PDF    = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"

# ═══════════════════════════════════════════════════════════════
# ✅ CHECK DES VARIABLES D'ENVIRONNEMENT AU DÉMARRAGE
# ═══════════════════════════════════════════════════════════════
def check_env():
    required = {
        "GROQ_API_KEY":    GROQ_API_KEY,
        "ID_INSTANCE":     ID_INSTANCE,
        "API_TOKEN":       API_TOKEN,
        "OPERATOR_CHAT_ID": OPERATOR_CHAT_ID,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print("\n" + "⚠️ " * 20)
        print(f"❌ VARIABLES MANQUANTES : {', '.join(missing)}")
        print("   → Ajoutez-les dans Render > Environment")
        print("⚠️ " * 20 + "\n")
    else:
        print("✅ Toutes les variables d'environnement sont présentes.")

    if BOT_OWN_NUMBER:
        print(f"🤖 Numéro du bot détecté : {BOT_OWN_NUMBER}")
    else:
        print("⚠️  BOT_OWN_NUMBER non défini — protection self-send désactivée.")

    if OPERATOR_CHAT_ID.endswith("@g.us"):
        print(f"📢 Alertes → GROUPE  : {OPERATOR_CHAT_ID}")
    elif OPERATOR_CHAT_ID.endswith("@c.us"):
        print(f"📢 Alertes → NUMÉRO  : {OPERATOR_CHAT_ID}")
    else:
        print(f"⚠️  OPERATOR_CHAT_ID invalide ou vide : '{OPERATOR_CHAT_ID}'")


# ─────────────────────────────────────────
# 🗂️  ÉTAT EN MÉMOIRE
# ─────────────────────────────────────────
user_state:           dict[str, dict] = {}
processed_messages:   set[str]        = set()
conversation_history: dict[str, list] = {}


# ─────────────────────────────────────────
# 🧹 Nettoyage mémoire périodique
# ─────────────────────────────────────────
def clean_cache():
    while True:
        time.sleep(300)
        if len(processed_messages) > 2000:
            processed_messages.clear()
            print("🧹 Cache processed_messages vidé.")

threading.Thread(target=clean_cache, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
# 📤 ENVOI WHATSAPP — VERSION DEBUGGÉE ET FIABLE
# ═══════════════════════════════════════════════════════════════
def send_whatsapp(chat_id: str, message: str) -> bool:
    """
    Envoie un message WhatsApp via Green API.
    - Logs détaillés : URL, payload, status, response body
    - Garde contre l'envoi au numéro du bot lui-même
    - Retourne True/False fiable
    """

    # ── Guard 1 : chat_id vide ───────────────────────────────
    if not chat_id:
        print("❌ SEND BLOCKED : chat_id vide.")
        return False

    # ── Guard 2 : envoi vers son propre numéro ───────────────
    if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
        print(f"❌ SEND BLOCKED : tentative d'envoi au propre numéro du bot ({chat_id}).")
        return False

    # ── Guard 3 : OPERATOR_CHAT_ID non configuré ────────────
    if not OPERATOR_CHAT_ID and chat_id == "REMPLACE@g.us":
        print("❌ SEND BLOCKED : OPERATOR_CHAT_ID non configuré.")
        return False

    url     = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": message}

    print(f"\n{'─' * 50}")
    print(f"📤 ENVOI WhatsApp")
    print(f"   → Destinataire : {chat_id}")
    print(f"   → URL          : {url}")
    print(f"   → Message      : {message[:120]}")
    print(f"{'─' * 50}")

    try:
        res = requests.post(url, json=payload, timeout=10)

        print(f"   ← Status HTTP  : {res.status_code}")
        print(f"   ← Response     : {res.text[:300]}")

        if res.status_code == 200:
            print(f"   ✅ Envoi réussi → {chat_id}\n")
            return True
        else:
            print(f"   ❌ Échec envoi ({res.status_code}) → {chat_id}\n")
            return False

    except requests.Timeout:
        print(f"   ❌ TIMEOUT lors de l'envoi → {chat_id}\n")
        return False
    except Exception as e:
        print(f"   ❌ EXCEPTION lors de l'envoi → {chat_id} : {e}\n")
        return False


# ═══════════════════════════════════════════════════════════════
# 🧪 FONCTION DE TEST — envoie un message test à l'opérateur
# Appel : GET /test-whatsapp
# ═══════════════════════════════════════════════════════════════
def test_whatsapp():
    """Envoie un message de test à OPERATOR_CHAT_ID et retourne le résultat."""
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    msg = (
        f"🧪 *TEST BOT CHANA CORPORATE*\n\n"
        f"✅ Le bot est opérationnel.\n"
        f"⏱️  Heure : {ts}\n\n"
        f"Si vous recevez ce message, les alertes fonctionnent correctement."
    )
    print(f"\n🧪 Test d'envoi vers OPERATOR_CHAT_ID = '{OPERATOR_CHAT_ID}'")
    ok = send_whatsapp(OPERATOR_CHAT_ID, msg)
    print(f"🧪 Résultat test : {'✅ SUCCÈS' if ok else '❌ ÉCHEC'}\n")
    return ok


@app.route("/test-whatsapp", methods=["GET"])
def route_test_whatsapp():
    ok = test_whatsapp()
    return jsonify({
        "test":            "whatsapp_send",
        "operator_target": OPERATOR_CHAT_ID,
        "success":         ok
    })


# ═══════════════════════════════════════════════════════════════
# 🚨 ALERTES OPÉRATEUR
# ═══════════════════════════════════════════════════════════════
def _safe_alert(chat_id: str, message: str, label: str):
    """Wrapper thread-safe pour les alertes — log le résultat du thread."""
    ok = send_whatsapp(OPERATOR_CHAT_ID, message)
    print(f"{'✅' if ok else '❌'} Alerte [{label}] → {chat_id} | target={OPERATOR_CHAT_ID}")


def alert_operator_escalation(chat_id: str, last_message: str):
    """Alerte après 5 échanges IA — client prêt pour prise en charge humaine."""
    ts    = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🔔 *CLIENT PRÊT POUR PRISE EN CHARGE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Dernier message : \"{last_message[:250]}\"\n"
        f"📊 Statut : *5 échanges IA complétés*\n"
        f"⏱️  Heure : {ts}\n\n"
        f"👉 Ce client attend qu'un conseiller le recontacte."
    )
    threading.Thread(
        target=_safe_alert,
        args=(chat_id, alert, "ESCALADE AUTO"),
        daemon=True
    ).start()


def alert_operator_human_request(chat_id: str, last_message: str):
    """Alerte immédiate — client demande explicitement un humain."""
    ts    = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🚨 *DEMANDE HUMAIN EXPLICITE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Message : \"{last_message[:250]}\"\n"
        f"📌 TYPE : *URGENT — CLIENT DEMANDE UN CONSEILLER*\n"
        f"⏱️  Heure : {ts}"
    )
    threading.Thread(
        target=_safe_alert,
        args=(chat_id, alert, "HUMAIN URGENT"),
        daemon=True
    ).start()


# ─────────────────────────────────────────
# 🔍 DÉTECTION DEMANDE HUMAIN
# ─────────────────────────────────────────
HUMAN_KEYWORDS = [
    "humain", "conseiller", "opérateur", "operateur",
    "responsable", "agent", "quelqu'un", "quelqu un",
    "appel", "rappel", "rendez-vous", "rendez vous",
    "parler à", "parler a", "je veux parler",
    "une personne", "vrai personne", "pas un robot",
    "pas un bot", "réclamation", "reclamation",
    "négocier", "negocier", "partenariat", "dossier",
    "directeur", "gérant", "gerant",
]

def wants_human(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in HUMAN_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# 🤖 RÉPONSE IA (Groq) avec historique
# ═══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.
Tu représentes l'entreprise 24h/24 et 7j/7 sur WhatsApp.

OBJECTIF PRINCIPAL :
Accueillir chaleureusement le client, comprendre son besoin, lui présenter les services de manière naturelle et progressive, répondre à toutes ses questions, et l'amener vers l'inscription à la mission commerciale ou la prise de contact.

RÈGLES DE COMMUNICATION :
1. Réponds UNIQUEMENT en français.
2. Ton naturel, chaleureux, professionnel — comme un vrai commercial humain.
3. Ne pas tout déverser d'un coup. Présente les infos progressivement selon le fil de la conversation.
4. Réponds à TOUTES les questions posées sans en omettre aucune.
5. Ne jamais inventer une information. Si inconnue : "Je transmettrai votre demande à un conseiller."
6. Ne jamais discuter de politique, religion ou sujets hors Chana Corporate.
7. NE PAS re-saluer à chaque message. Salue uniquement au tout premier échange.
8. Si le client semble prêt à s'inscrire ou veut aller plus loin, partage les liens d'inscription.

LIENS OFFICIELS :
- Formulaire d'inscription en ligne : {LINK_FORM_ONLINE}
- Brochure Mission Commerciale (PDF) : {LINK_BROCHURE}
- Fiche d'inscription (PDF) : {LINK_FORM_PDF}

PRÉSENTATION CHANA CORPORATE :
Entreprise ivoirienne spécialisée dans l'accompagnement commercial international, mise en relation d'affaires, sourcing international, recherche de fournisseurs fiables, organisation de missions commerciales, accompagnement logistique et développement de partenariats stratégiques.

MISSION COMMERCIALE CHINE 2026 :
- Nom : Mission Commerciale Côte d'Ivoire - Chine 2026
- Dates : 22 au 31 juillet 2026 (10 jours)
- Destination : Province de Zhejiang, Chine
- Organisateurs : Chana Corporate & African Wind
- Partenaire local : consortium de 1 000+ entreprises chinoises

OBJECTIFS :
Achat direct en usine · Réduction des intermédiaires · Marges améliorées · Fournisseurs fiables · Tarifs préférentiels · Réseau international · Partenariats durables

POURQUOI LE ZHEJIANG ?
1 000+ entreprises partenaires · Berceau d'Alibaba et Geely · Marché de Yiwu · Infrastructures portuaires top · Prix plus bas que Guangzhou · Forte densité de PME

PROFIL PARTICIPANTS :
Entreprises, PME, commerçants, coopératives, importateurs, distributeurs, entrepreneurs, particuliers

SECTEURS :
BTP · Automobile · Agriculture · Électroménager · Textile · Fournitures scolaires/bureau · Mobilier · Équipements médicaux · Énergies renouvelables · Commerce général

FORFAIT TOUT INCLUS :
Visa business · Billet A/R · Hôtel 3-4 étoiles · 3 repas/jour · Rencontres B2B · Visites d'usines · Marché de Yiwu · Transport · Interprètes français-chinois · Suivi commandes · Contrôle qualité · Livraison

PROGRAMME :
J1-J2 : Accueil, briefing, découverte
J3 : Rencontres B2B et réseautage
J4-J6 : Visites usines + marché Yiwu
J7-J8 : Négociations et commandes
J9-J10 : Débriefing, visite portuaire, retour

TARIFICATION :
Total : 2 500 000 FCFA/participant
Acompte (40%) : 1 000 000 FCFA à l'inscription
Solde (60%) : 1 500 000 FCFA avant le 1er juillet 2026
Paiements : Mobile Money, espèces, chèque

COORDONNÉES :
WhatsApp : +225 05 00 02 60 72
Téléphone : +225 27 22 23 66 83
Email : chanacorporate@gmail.com
Adresse 1 : Cocody Riviera 3, Rue Kloé, près de la Clinique Saint Viateur
Adresse 2 : Immeuble XL, Rue Dr Crozet, Boulevard de la République"""


def ask_groq(chat_id: str, message: str) -> str:
    try:
        history = conversation_history.setdefault(chat_id, [])
        history.append({"role": "user", "content": message})

        # Fenêtre glissante : max 20 messages (10 échanges)
        if len(history) > 20:
            history = history[-20:]
            conversation_history[chat_id] = history

        start   = time.time()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *history
            ],
            "temperature": 0.4,
            "max_tokens":  1024,
            "top_p":       1
        }
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=15
        )
        duration = time.time() - start

        if res.status_code != 200:
            print(f"❌ GROQ ERROR {res.status_code} : {res.text[:300]}")
            return "Désolé, une erreur est survenue. Veuillez réessayer dans quelques instants."

        reply = res.json()["choices"][0]["message"]["content"].strip()
        history.append({"role": "assistant", "content": reply})

        print(f"🤖 Groq OK ({duration:.2f}s) | échanges={len(history)//2}")
        return reply

    except requests.Timeout:
        return "Je réfléchis encore… merci de patienter puis renvoyez votre question. 🙏"
    except Exception as e:
        print(f"❌ GROQ EXCEPTION: {e}")
        return "Le service est momentanément indisponible. Veuillez réessayer."


# ─────────────────────────────────────────
# 🛡️ ANTI-DOUBLON
# ─────────────────────────────────────────
def is_duplicate(msg_id: str) -> bool:
    if msg_id in processed_messages:
        return True
    processed_messages.add(msg_id)
    return False


# ═══════════════════════════════════════════════════════════════
# 📩 WEBHOOK PRINCIPAL
# ═══════════════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    start_time = time.time()

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        if data.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"ignored": True, "reason": "not_a_message"})

        sender   = data.get("senderData", {})
        msg_data = data.get("messageData", {})

        chat_id = sender.get("chatId", "")
        message = msg_data.get("textMessageData", {}).get("textMessage", "").strip()
        msg_id  = data.get("idMessage", "")

        # Ignorer les groupes externes
        if chat_id.endswith("@g.us"):
            return jsonify({"ignored": True, "reason": "group_message"})

        # Ignorer les messages du bot lui-même
        if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
            return jsonify({"ignored": True, "reason": "self_message"})

        if not chat_id or not message:
            return jsonify({"error": "Missing data"}), 200

        # Anti-doublon
        if msg_id and is_duplicate(msg_id):
            print(f"⛔ Doublon ignoré : {msg_id}")
            return jsonify({"ignored": True, "reason": "duplicate"})

        print(f"\n📩 [{chat_id}] : {message[:100]}")

        # ── Initialisation nouveau client ─────────────────────
        if chat_id not in user_state:
            user_state[chat_id] = {
                "step":       "ai",
                "exchanges":  0,
                "escalated":  False,
                "created_at": time.time(),
            }

        state = user_state[chat_id]
        step  = state["step"]

        # ══════════════════════════════════════════
        # 🔕  MODE HUMAIN — bot silencieux
        # ══════════════════════════════════════════
        if step == "human":
            print(f"🔕 Bot silencieux pour {chat_id}")
            return jsonify({"ignored": True, "reason": "human_mode", "chat_id": chat_id})

        # ══════════════════════════════════════════
        # 🤖  MODE IA
        # ══════════════════════════════════════════
        if step == "ai":

            # ── Demande humain explicite ──────────────────────
            if wants_human(message):
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
                alert_operator_human_request(chat_id, message)
                return jsonify({
                    "success": True,
                    "action":  "human_escalation_explicit",
                    "chat_id": chat_id,
                    "duration": f"{time.time() - start_time:.2f}s"
                })

            # ── Réponse IA normale ────────────────────────────
            reply = ask_groq(chat_id, message)
            state["exchanges"] += 1
            send_whatsapp(chat_id, reply)

            exchanges = state["exchanges"]
            print(f"💬 Échange #{exchanges} | {chat_id}")

            # ── Escalade auto après 5 échanges ───────────────
            if exchanges >= 5 and not state["escalated"]:
                state["escalated"] = True
                state["step"]      = "human"

                escalation_msg = (
                    "Merci pour cet échange enrichissant ! 😊\n\n"
                    "Afin de mieux vous accompagner, je vous mets maintenant en contact "
                    "avec l'un de nos conseillers Chana Corporate.\n\n"
                    "Il va vous recontacter très prochainement pour finaliser votre projet. 🙏\n\n"
                    "En attendant, voici nos documents officiels :\n"
                    f"📄 Brochure : {LINK_BROCHURE}\n"
                    f"📝 Fiche d'inscription : {LINK_FORM_PDF}\n"
                    f"🌐 Inscription en ligne : {LINK_FORM_ONLINE}"
                )
                send_whatsapp(chat_id, escalation_msg)
                alert_operator_escalation(chat_id, message)

                return jsonify({
                    "success":   True,
                    "action":    "ai_reply_then_escalation",
                    "chat_id":   chat_id,
                    "exchanges": exchanges,
                    "duration":  f"{time.time() - start_time:.2f}s"
                })

            return jsonify({
                "success":   True,
                "action":    "ai_reply",
                "chat_id":   chat_id,
                "exchanges": exchanges,
                "duration":  f"{time.time() - start_time:.2f}s"
            })

        return jsonify({"error": "Unknown step", "step": step}), 500

    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        traceback.print_exc()
        return jsonify({
            "error":    str(e),
            "duration": f"{time.time() - start_time:.2f}s"
        }), 500


# ═══════════════════════════════════════════════════════════════
# 🏥 HEALTH CHECK
# ═══════════════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def health():
    steps: dict = {}
    for s in user_state.values():
        k = s.get("step", "unknown")
        steps[k] = steps.get(k, 0) + 1

    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v6",
        "model":              "llama-3.3-70b-versatile",
        "operator_target":    OPERATOR_CHAT_ID or "⚠️ NON CONFIGURÉ",
        "bot_own_number":     BOT_OWN_NUMBER   or "⚠️ NON CONFIGURÉ",
        "total_users":        len(user_state),
        "processed_messages": len(processed_messages),
        "steps_breakdown":    steps
    })


# ═══════════════════════════════════════════════════════════════
# 🚀 DÉMARRAGE
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    check_env()          # ✅ Vérification des variables au boot
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║   🤖  CHANA CORPORATE BOT  v6.0  READY      ║
    ║   Port      : {port}                           ║
    ║   Escalade  : après 5 échanges IA            ║
    ║   Test      : GET /test-whatsapp             ║
    ╚══════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
