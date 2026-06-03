"""
╔══════════════════════════════════════════════════════════════╗
║        CHANA CORPORATE WHATSAPP BOT  v10.0                  ║
║        Render stable — threading par requête                ║
╠══════════════════════════════════════════════════════════════╣
║  Commande Start Render :                                    ║
║  gunicorn main:app --bind 0.0.0.0:$PORT --workers 1        ║
║  --threads 8 --timeout 120                                  ║
║  (PAS de --preload — inutile sans queue inter-process)      ║
╚══════════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify
import requests
import os
import time
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

MEMORY_TTL      = 7_200   # 2h
HISTORY_MAX     = 20
ESCALADE_SEUIL  = 5

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM  = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_PDF   = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"
LINK_BROCH = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"

# ═══════════════════════════════════════════════════════════════
# 🗂️  MÉMOIRE (partagée dans le même process — 1 worker Gunicorn)
# ═══════════════════════════════════════════════════════════════
user_state:           dict = {}
conversation_history: dict = {}
processed_messages:   set  = set()
_state_lock = threading.Lock()   # protection multi-thread

stats = {
    "started_at":     datetime.now().isoformat(),
    "jobs_processed": 0,
    "jobs_failed":    0,
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
# 🧹 NETTOYAGE MÉMOIRE — TTL 2h, cycle 30min
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
                print(f"🧹 {len(expired)} session(s) expirée(s) supprimée(s)", flush=True)
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
        print(f"❌ SEND: self-send bloqué", flush=True)
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
# 🔍 QUALIFICATION PROSPECT
# ═══════════════════════════════════════════════════════════════
def is_prospect(message: str) -> bool:
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Classificateur binaire. Réponds UNIQUEMENT OUI ou NON.\n\n"
                            "OUI → prospect potentiel : intérêt commercial, sourcing, "
                            "importation, Chine, fournisseurs, voyage affaires, inscription, "
                            "services pro, ou simple salutation (bonjour, bonsoir, allô).\n\n"
                            "NON → clairement hors-sujet : spam, blague, message perso sans "
                            "rapport commercial, politique, religion.\n\n"
                            "En cas de doute → OUI."
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
            print(f"⚠️ Filtre KO ({r.status_code}) — fail-open", flush=True)
            return True
        answer = r.json()["choices"][0]["message"]["content"].strip().upper()
        result = answer.startswith("OUI")
        print(f"🔍 Prospect : {'✅ OUI' if result else '❌ NON'} | '{message[:50]}'", flush=True)
        return result
    except Exception as e:
        print(f"⚠️ Filtre exception ({e}) — fail-open", flush=True)
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
    "négocier", "negocier", "partenariat", "dossier",
    "directeur", "gérant", "gerant",
]

def wants_human(message: str) -> bool:
    return any(kw in message.lower() for kw in HUMAN_KEYWORDS)

# ═══════════════════════════════════════════════════════════════
# 🤖 RÉPONSE IA
# ═══════════════════════════════════════════════════════════════
SYSTEM_PROMPT = f"""Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.
Tu représentes l'entreprise 24h/24 et 7j/7 sur WhatsApp.

OBJECTIF : Accueillir chaleureusement, comprendre le besoin, présenter les services progressivement, répondre à toutes les questions, amener vers l'inscription ou la prise de contact.

RÈGLES :
1. Réponds UNIQUEMENT en français.
2. Ton naturel, chaleureux, professionnel.
3. Présente les infos progressivement — pas tout d'un coup.
4. Réponds à TOUTES les questions sans en omettre aucune.
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
# Appelé dans un thread dédié par requête webhook
# ═══════════════════════════════════════════════════════════════
def handle_message(chat_id: str, message: str):
    try:
        with _state_lock:
            state = user_state.get(chat_id)

        # ── Qualification prospect (premier message seulement) ─
        if state is None:
            if not is_prospect(message):
                print(f"🚫 Non-prospect : {chat_id} | '{message[:50]}'", flush=True)
                return
            print(f"✅ Nouveau prospect : {chat_id}", flush=True)
            now = time.time()
            new_state = {
                "step":       "ai",
                "exchanges":  0,
                "escalated":  False,
                "created_at": now,
                "last_seen":  now,
            }
            with _state_lock:
                user_state[chat_id] = new_state
                state = user_state[chat_id]

        with _state_lock:
            state["last_seen"] = time.time()
            step = state["step"]

        # ── Bot silencieux ────────────────────────────────────
        if step == "human":
            print(f"🔕 Silencieux {chat_id}", flush=True)
            return

        # ── Mode IA ───────────────────────────────────────────
        if step == "ai":

            # Demande humain explicite
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

            # Réponse IA
            reply = ask_groq(chat_id, message)
            with _state_lock:
                state["exchanges"] += 1
                exchanges = state["exchanges"]

            send_whatsapp(chat_id, reply)
            print(f"💬 Échange #{exchanges} | {chat_id}", flush=True)

            # Escalade après N échanges
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
        print(f"❌ handle_message [{chat_id}] : {e}", flush=True)
        traceback.print_exc()

# ═══════════════════════════════════════════════════════════════
# 📩 WEBHOOK — répond immédiatement, lance un thread par message
# ═══════════════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "invalid_json"}), 400

        if data.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"ignored": True, "reason": "not_a_message"})

        sender   = data.get("senderData", {})
        msg_data = data.get("messageData", {})
        chat_id  = sender.get("chatId", "")
        message  = msg_data.get("textMessageData", {}).get("textMessage", "").strip()
        msg_id   = data.get("idMessage", "")

        # Filtres rapides
        if chat_id.endswith("@g.us"):
            return jsonify({"ignored": True, "reason": "group"})
        if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
            return jsonify({"ignored": True, "reason": "self"})
        if not chat_id or not message:
            return jsonify({"ok": True, "reason": "empty"}), 200
        if msg_id and is_duplicate(msg_id):
            return jsonify({"ignored": True, "reason": "duplicate"})

        print(f"📩 [{chat_id}] '{message[:70]}'", flush=True)

        # Thread dédié — webhook répond immédiatement
        threading.Thread(
            target=handle_message,
            args=(chat_id, message),
            daemon=True,
            name=f"msg-{msg_id[:8]}"
        ).start()

        return jsonify({"ok": True, "processing": True}), 202

    except Exception as e:
        print(f"❌ WEBHOOK : {e}", flush=True)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════════
# 🏓 /ping  🏥 /health  🧪 /test-whatsapp
# ═══════════════════════════════════════════════════════════════
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"pong": True, "ts": time.time()}), 200


@app.route("/health", methods=["GET"])
@app.route("/", methods=["GET"])
def health():
    steps: dict = {}
    for s in user_state.values():
        k = s.get("step", "?")
        steps[k] = steps.get(k, 0) + 1
    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v10",
        "started_at":         stats["started_at"],
        "jobs_processed":     stats["jobs_processed"],
        "jobs_failed":        stats["jobs_failed"],
        "total_users":        len(user_state),
        "processed_messages": len(processed_messages),
        "steps_breakdown":    steps,
        "operator_target":    OPERATOR_CHAT_ID or "⚠️ NON CONFIGURÉ",
    })


@app.route("/test-whatsapp", methods=["GET"])
def test_whatsapp():
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ok = send_whatsapp(
        OPERATOR_CHAT_ID,
        f"🧪 *TEST BOT CHANA CORPORATE v10*\n\n✅ Bot opérationnel.\n⏱️ {ts}"
    )
    return jsonify({"success": ok, "target": OPERATOR_CHAT_ID})

# ═══════════════════════════════════════════════════════════════
# ⚠️  PAS de app.run() — Gunicorn uniquement
#
#  Start Command Render :
#  gunicorn main:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
# ═══════════════════════════════════════════════════════════════
