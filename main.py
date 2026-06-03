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
# 🔐 CONFIG
# ═══════════════════════════════════════════════════════════════
GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
ID_INSTANCE      = os.getenv("ID_INSTANCE")
API_TOKEN        = os.getenv("API_TOKEN")
OPERATOR_CHAT_ID = os.getenv("OPERATOR_CHAT_ID", "")
BOT_OWN_NUMBER   = os.getenv("BOT_OWN_NUMBER", "")

GREEN_API_BASE = f"https://api.green-api.com/waInstance{ID_INSTANCE}"

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM_ONLINE = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_BROCHURE    = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"
LINK_FORM_PDF    = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"

# ═══════════════════════════════════════════════════════════════
# 🗂️  ÉTATS EN MÉMOIRE
#
# step:
#   "pending"  → message reçu, en attente de qualification IA
#   "ai"       → prospect qualifié, conversation IA active
#   "human"    → transféré à un humain, bot silencieux
#
# ═══════════════════════════════════════════════════════════════
user_state:           dict[str, dict] = {}
processed_messages:   set[str]        = set()
conversation_history: dict[str, list] = {}


# ─────────────────────────────────────────
# 🧹 Nettoyage mémoire
# ─────────────────────────────────────────
def clean_cache():
    while True:
        time.sleep(300)
        if len(processed_messages) > 2000:
            processed_messages.clear()
            print("🧹 Cache vidé.")

threading.Thread(target=clean_cache, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
# ✅ CHECK VARIABLES AU DÉMARRAGE
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
        print("\n" + "⚠️  " * 15)
        print(f"❌ VARIABLES MANQUANTES : {', '.join(missing)}")
        print("   → Ajoutez-les dans Render > Environment")
        print("⚠️  " * 15 + "\n")
    else:
        print("✅ Toutes les variables d'environnement sont présentes.")

    target_type = "GROUPE" if OPERATOR_CHAT_ID.endswith("@g.us") else "NUMÉRO"
    print(f"📢 Alertes opérateur → {target_type} : {OPERATOR_CHAT_ID or '⚠️ NON CONFIGURÉ'}")
    if BOT_OWN_NUMBER:
        print(f"🤖 Numéro du bot : {BOT_OWN_NUMBER}")


# ═══════════════════════════════════════════════════════════════
# 📤 ENVOI WHATSAPP — logs complets
# ═══════════════════════════════════════════════════════════════
def send_whatsapp(chat_id: str, message: str) -> bool:
    if not chat_id:
        print("❌ SEND BLOCKED : chat_id vide.")
        return False
    if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
        print(f"❌ SEND BLOCKED : envoi vers le propre numéro du bot ({chat_id}).")
        return False

    url     = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": message}

    print(f"\n{'─'*55}")
    print(f"📤 ENVOI → {chat_id}")
    print(f"   Message  : {message[:100]}")

    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"   Status   : {res.status_code}")
        print(f"   Response : {res.text[:200]}")
        ok = res.status_code == 200
        print(f"   {'✅ OK' if ok else '❌ ÉCHEC'}")
        print(f"{'─'*55}\n")
        return ok
    except requests.Timeout:
        print(f"   ❌ TIMEOUT\n{'─'*55}\n")
        return False
    except Exception as e:
        print(f"   ❌ EXCEPTION : {e}\n{'─'*55}\n")
        return False


# ═══════════════════════════════════════════════════════════════
# 🚨 ALERTES OPÉRATEUR
# ═══════════════════════════════════════════════════════════════
def _safe_alert(chat_id: str, message: str, label: str):
    ok = send_whatsapp(OPERATOR_CHAT_ID, message)
    print(f"{'✅' if ok else '❌'} Alerte [{label}] pour {chat_id}")


def alert_operator_escalation(chat_id: str, last_message: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🔔 *CLIENT PRÊT POUR PRISE EN CHARGE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Dernier message : \"{last_message[:250]}\"\n"
        f"📊 Statut : *5 échanges IA complétés*\n"
        f"⏱️  Heure : {ts}\n\n"
        f"👉 Ce client attend qu'un conseiller le recontacte."
    )
    threading.Thread(target=_safe_alert, args=(chat_id, alert, "ESCALADE AUTO"), daemon=True).start()


def alert_operator_human_request(chat_id: str, last_message: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🚨 *DEMANDE HUMAIN EXPLICITE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Message : \"{last_message[:250]}\"\n"
        f"📌 TYPE : *URGENT — CLIENT DEMANDE UN CONSEILLER*\n"
        f"⏱️  Heure : {ts}"
    )
    threading.Thread(target=_safe_alert, args=(chat_id, alert, "HUMAIN URGENT"), daemon=True).start()


# ═══════════════════════════════════════════════════════════════
# 🔍 ÉTAPE 1 — QUALIFICATION PROSPECT (appel Groq léger)
#
# Cette fonction est le FILTRE D'ENTRÉE.
# Elle est appelée UNIQUEMENT sur le PREMIER message d'un inconnu.
# Elle répond OUI si le message est lié aux activités de Chana Corporate,
# NON pour tout le reste (bavardage, spam, messages privés hors-sujet...).
#
# ⚠️  Aucune alerte, aucune réponse client, aucun historique
#     n'est créé si cette fonction retourne False.
# ═══════════════════════════════════════════════════════════════
def is_prospect(message: str) -> bool:
    """
    Filtre d'entrée : détermine si le message entrant justifie
    d'engager la conversation commerciale.
    Utilise un appel Groq minimaliste (max_tokens=5, temperature=0).
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Tu es un classificateur binaire. "
                        "Réponds UNIQUEMENT par OUI ou NON, sans ponctuation, sans espace.\n\n"

                        "Réponds OUI si le message indique que la personne est "
                        "potentiellement intéressée par :\n"
                        "- une mission commerciale en Chine\n"
                        "- du sourcing, de l'importation, de l'exportation\n"
                        "- des fournisseurs chinois, des usines, des produits\n"
                        "- Chana Corporate, African Wind, le Zhejiang\n"
                        "- un voyage d'affaires, une inscription, un forfait\n"
                        "- des services commerciaux internationaux\n"
                        "- une demande d'information commerciale ou professionnelle\n"
                        "- une salutation simple (bonjour, bonsoir, allô, salut) "
                        "— car elle peut venir d'un prospect qui commence à écrire\n\n"

                        "Réponds NON si le message est clairement :\n"
                        "- une discussion personnelle sans rapport (météo, blagues, "
                        "politique, religion, sport, santé personnelle)\n"
                        "- du spam ou un message publicitaire non sollicité\n"
                        "- un message adressé à une autre personne par erreur\n"
                        "- un message technique ou de test système\n\n"

                        "En cas de doute, réponds OUI."
                    )
                },
                {"role": "user", "content": message}
            ],
            "temperature": 0.0,
            "max_tokens":  5
        }
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=6
        )
        if res.status_code != 200:
            # Fail-open : si le filtre échoue, on laisse passer
            print(f"⚠️  Filtre prospect KO ({res.status_code}) — fail-open")
            return True

        answer = res.json()["choices"][0]["message"]["content"].strip().upper()
        result = answer.startswith("OUI")
        print(f"🔍 Qualification prospect : {'✅ OUI' if result else '❌ NON'} | msg='{message[:60]}'")
        return result

    except Exception as e:
        # Fail-open : en cas d'erreur réseau ou autre, on laisse passer
        print(f"⚠️  Filtre prospect EXCEPTION ({e}) — fail-open")
        return True


# ═══════════════════════════════════════════════════════════════
# 🔍 DÉTECTION DEMANDE HUMAIN (mots-clés, rapide)
# ═══════════════════════════════════════════════════════════════
HUMAN_KEYWORDS = [
    "humain", "conseiller", "opérateur", "operateur",
    "responsable", "agent", "quelqu'un", "quelqu un",
    "appel", "rappel", "rendez-vous", "rendez vous",
    "parler à", "parler a", "je veux parler",
    "une personne", "vrai personne", "pas un robot", "pas un bot",
    "réclamation", "reclamation", "négocier", "negocier",
    "partenariat", "dossier", "directeur", "gérant", "gerant",
]

def wants_human(message: str) -> bool:
    return any(kw in message.lower() for kw in HUMAN_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# 🤖 RÉPONSE IA (Groq) avec historique de conversation
# ═══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.
Tu représentes l'entreprise 24h/24 et 7j/7 sur WhatsApp.

OBJECTIF PRINCIPAL :
Accueillir chaleureusement le client, comprendre son besoin, présenter les services de manière naturelle et progressive, répondre à toutes ses questions, et l'amener vers l'inscription ou la prise de contact.

RÈGLES :
1. Réponds UNIQUEMENT en français.
2. Ton naturel, chaleureux, professionnel — comme un vrai commercial humain.
3. Présente les infos progressivement selon le fil de la conversation. Pas tout d'un coup.
4. Réponds à TOUTES les questions posées sans en omettre aucune.
5. Ne jamais inventer une information. Si inconnue : "Je transmettrai votre demande à un conseiller."
6. Ne jamais discuter de politique, religion ou sujets hors Chana Corporate.
7. NE PAS re-saluer à chaque message. Salue uniquement au tout premier échange.
8. Si le client est prêt à s'inscrire, partage les liens officiels.

LIENS OFFICIELS :
- Formulaire d'inscription en ligne : {LINK_FORM_ONLINE}
- Brochure Mission Commerciale (PDF) : {LINK_BROCHURE}
- Fiche d'inscription (PDF) : {LINK_FORM_PDF}

PRÉSENTATION CHANA CORPORATE :
Entreprise ivoirienne spécialisée dans l'accompagnement commercial international, mise en relation d'affaires, sourcing international, organisation de missions commerciales, accompagnement logistique et développement de partenariats stratégiques.

MISSION COMMERCIALE CHINE 2026 :
- Dates : 22 au 31 juillet 2026 (10 jours)
- Destination : Province de Zhejiang, Chine
- Organisateurs : Chana Corporate & African Wind
- Partenaire local : consortium de 1 000+ entreprises chinoises

OBJECTIFS :
Achat direct en usine · Réduction des intermédiaires · Marges améliorées · Fournisseurs fiables · Tarifs préférentiels · Réseau international · Partenariats durables

POURQUOI LE ZHEJIANG ?
1 000+ entreprises partenaires · Berceau d'Alibaba et Geely · Marché de Yiwu · Infrastructures portuaires top · Prix plus bas que Guangzhou · Forte densité de PME

SECTEURS :
BTP · Automobile · Agriculture · Électroménager · Textile · Fournitures scolaires/bureau · Mobilier · Équipements médicaux · Énergies renouvelables · Commerce général

FORFAIT TOUT INCLUS :
Visa business · Billet A/R · Hôtel 3-4 étoiles · 3 repas/jour · Rencontres B2B · Visites usines · Marché de Yiwu · Transport · Interprètes · Suivi commandes · Contrôle qualité · Livraison

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
WhatsApp : +225 05 00 02 60 72 | Tél : +225 27 22 23 66 83
Email : chanacorporate@gmail.com
Adresse : Cocody Riviera 3, Rue Kloé / Immeuble XL, Rue Dr Crozet"""


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

        # ── Filtres système ───────────────────────────────────
        if chat_id.endswith("@g.us"):
            return jsonify({"ignored": True, "reason": "group_message"})

        if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
            return jsonify({"ignored": True, "reason": "self_message"})

        if not chat_id or not message:
            return jsonify({"error": "Missing data"}), 200

        if msg_id and is_duplicate(msg_id):
            print(f"⛔ Doublon ignoré : {msg_id}")
            return jsonify({"ignored": True, "reason": "duplicate"})

        print(f"\n📩 [{chat_id}] : {message[:100]}")

        state = user_state.get(chat_id)

        # ══════════════════════════════════════════════════════
        # 🔍 PORTE D'ENTRÉE — QUALIFICATION PROSPECT
        #
        # Si on ne connaît pas encore ce numéro, on qualifie
        # AVANT de faire quoi que ce soit.
        # Aucune réponse, aucune alerte, aucun historique
        # n'est créé si le message ne concerne pas Chana.
        # ══════════════════════════════════════════════════════
        if state is None:
            if not is_prospect(message):
                print(f"🚫 Ignoré (hors-sujet, inconnu) : {chat_id} | '{message[:60]}'")
                return jsonify({
                    "ignored": True,
                    "reason":  "not_a_prospect",
                    "chat_id": chat_id
                })

            # ✅ Prospect qualifié → initialisation
            print(f"✅ Nouveau prospect qualifié : {chat_id}")
            user_state[chat_id] = {
                "step":       "ai",
                "exchanges":  0,
                "escalated":  False,
                "created_at": time.time(),
            }
            state = user_state[chat_id]

        step = state["step"]

        # ══════════════════════════════════════════════════════
        # 🔕 MODE HUMAIN — bot silencieux
        # ══════════════════════════════════════════════════════
        if step == "human":
            print(f"🔕 Bot silencieux pour {chat_id} (pris en charge)")
            return jsonify({"ignored": True, "reason": "human_mode", "chat_id": chat_id})

        # ══════════════════════════════════════════════════════
        # 🤖 MODE IA
        # ══════════════════════════════════════════════════════
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

                send_whatsapp(
                    chat_id,
                    "Merci pour cet échange enrichissant ! 😊\n\n"
                    "Afin de mieux vous accompagner, je vous mets maintenant en contact "
                    "avec l'un de nos conseillers Chana Corporate.\n\n"
                    "Il va vous recontacter très prochainement. 🙏\n\n"
                    "En attendant, voici nos documents officiels :\n"
                    f"📄 Brochure : {LINK_BROCHURE}\n"
                    f"📝 Fiche d'inscription : {LINK_FORM_PDF}\n"
                    f"🌐 Inscription en ligne : {LINK_FORM_ONLINE}"
                )
                alert_operator_escalation(chat_id, message)

                return jsonify({
                    "success":   True,
                    "action":    "ai_reply_then_escalation",
                    "exchanges": exchanges,
                    "chat_id":   chat_id,
                    "duration":  f"{time.time() - start_time:.2f}s"
                })

            return jsonify({
                "success":   True,
                "action":    "ai_reply",
                "exchanges": exchanges,
                "chat_id":   chat_id,
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
# 🧪 TEST ENVOI WHATSAPP
# ═══════════════════════════════════════════════════════════════
@app.route("/test-whatsapp", methods=["GET"])
def route_test_whatsapp():
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    msg = (
        f"🧪 *TEST BOT CHANA CORPORATE*\n\n"
        f"✅ Le bot est opérationnel.\n"
        f"⏱️  Heure : {ts}\n\n"
        f"Si vous recevez ce message, les alertes fonctionnent correctement."
    )
    print(f"\n🧪 Test d'envoi → '{OPERATOR_CHAT_ID}'")
    ok = send_whatsapp(OPERATOR_CHAT_ID, msg)
    return jsonify({
        "test":    "whatsapp_send",
        "target":  OPERATOR_CHAT_ID,
        "success": ok
    })


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
        "service":            "Chana Corporate WhatsApp Bot v7",
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
    check_env()
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║   🤖  CHANA CORPORATE BOT  v7.0  READY      ║
    ║   Port      : {port}                           ║
    ║   Filtre    : qualification prospect active  ║
    ║   Escalade  : après 5 échanges IA            ║
    ║   Test      : GET /test-whatsapp             ║
    ╚══════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
