"""
╔══════════════════════════════════════════════════════════════╗
║        CHANA CORPORATE WHATSAPP BOT  v8.0                   ║
║        Render-optimized — stable, non-bloquant              ║
╠══════════════════════════════════════════════════════════════╣
║  Webhook répond en < 200ms (tout le traitement est async)   ║
║  File de travail dédiée (queue) — pas de threads volants    ║
║  TTL mémoire : user_state + history nettoyés toutes 2h      ║
║  Tous les requests.post : timeout=(3, 10)                   ║
║  /ping keep-alive pour Render                               ║
║  Crash gunicorn worker → traceback complet dans les logs    ║
╚══════════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify
import requests
import os
import sys
import traceback
import json
import time
import threading
import queue
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

# TTL mémoire : conversations inactives depuis X secondes → supprimées
MEMORY_TTL_SECONDS = 7_200   # 2 heures
# Max messages en historique par client
HISTORY_MAX_MESSAGES = 20

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM_ONLINE = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_BROCHURE    = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"
LINK_FORM_PDF    = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"

# ═══════════════════════════════════════════════════════════════
# 🗂️  MÉMOIRE — avec horodatage pour TTL
# ═══════════════════════════════════════════════════════════════
# user_state[chat_id] = {
#   "step":       "ai" | "human",
#   "exchanges":  int,
#   "escalated":  bool,
#   "created_at": float (timestamp),
#   "last_seen":  float (timestamp mis à jour à chaque message)
# }
user_state:           dict[str, dict] = {}
conversation_history: dict[str, list] = {}
processed_messages:   set[str]        = set()

# ─────────────────────────────────────────────────────────────
# 📬 FILE DE TRAVAIL ASYNC
# Le webhook dépose un job ici et répond immédiatement.
# Un worker dédié consomme la file en arrière-plan.
# ─────────────────────────────────────────────────────────────
work_queue: queue.Queue = queue.Queue(maxsize=200)


# ═══════════════════════════════════════════════════════════════
# ✅ CHECK VARIABLES AU DÉMARRAGE
# ═══════════════════════════════════════════════════════════════
def check_env():
    required = {
        "GROQ_API_KEY":     GROQ_API_KEY,
        "ID_INSTANCE":      ID_INSTANCE,
        "API_TOKEN":        API_TOKEN,
        "OPERATOR_CHAT_ID": OPERATOR_CHAT_ID,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"\n❌ VARIABLES MANQUANTES : {', '.join(missing)}", flush=True)
        print("   → Render > Environment → ajouter ces variables\n", flush=True)
    else:
        print("✅ Variables d'environnement : OK", flush=True)

    target_type = "GROUPE" if OPERATOR_CHAT_ID.endswith("@g.us") else "NUMÉRO"
    print(f"📢 Alertes → {target_type} : {OPERATOR_CHAT_ID or '⚠️ NON CONFIGURÉ'}", flush=True)


# ═══════════════════════════════════════════════════════════════
# 🧹 NETTOYAGE MÉMOIRE avec TTL (lancé en background)
# Tourne toutes les 30 min, expurge les entrées inactives > 2h
# ═══════════════════════════════════════════════════════════════
def memory_cleanup_loop():
    while True:
        try:
            time.sleep(1_800)   # toutes les 30 minutes
            now        = time.time()
            cutoff     = now - MEMORY_TTL_SECONDS
            expired    = [
                cid for cid, s in user_state.items()
                if s.get("last_seen", s.get("created_at", 0)) < cutoff
            ]
            for cid in expired:
                user_state.pop(cid, None)
                conversation_history.pop(cid, None)

            # Purge processed_messages si trop grand
            if len(processed_messages) > 3_000:
                processed_messages.clear()

            if expired:
                print(
                    f"🧹 Nettoyage mémoire : {len(expired)} session(s) expirée(s) supprimée(s) "
                    f"| user_state={len(user_state)} | history={len(conversation_history)}",
                    flush=True
                )
        except Exception as e:
            print(f"⚠️  Erreur dans memory_cleanup_loop : {e}", flush=True)


threading.Thread(target=memory_cleanup_loop, daemon=True, name="MemoryCleanup").start()


# ═══════════════════════════════════════════════════════════════
# 📤 ENVOI WHATSAPP — timeout (3, 10) — logs complets
#   connect_timeout=3s  /  read_timeout=10s
# ═══════════════════════════════════════════════════════════════
def send_whatsapp(chat_id: str, message: str) -> bool:
    if not chat_id:
        print("❌ SEND BLOCKED : chat_id vide.", flush=True)
        return False
    if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
        print(f"❌ SEND BLOCKED : self-send ({chat_id}).", flush=True)
        return False

    url     = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": message}

    print(f"📤 → {chat_id} | {message[:80]}", flush=True)
    try:
        res = requests.post(url, json=payload, timeout=(3, 10))
        ok  = res.status_code == 200
        print(
            f"   {'✅' if ok else '❌'} status={res.status_code} | {res.text[:150]}",
            flush=True
        )
        return ok
    except requests.exceptions.ConnectTimeout:
        print(f"   ❌ ConnectTimeout → {chat_id}", flush=True)
        return False
    except requests.exceptions.ReadTimeout:
        print(f"   ❌ ReadTimeout → {chat_id}", flush=True)
        return False
    except Exception as e:
        print(f"   ❌ EXCEPTION → {chat_id} : {e}", flush=True)
        return False


# ═══════════════════════════════════════════════════════════════
# 🚨 ALERTES OPÉRATEUR — envoyées directement (dans le worker)
# ═══════════════════════════════════════════════════════════════
def alert_operator_escalation(chat_id: str, last_message: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    send_whatsapp(OPERATOR_CHAT_ID, (
        f"🔔 *CLIENT PRÊT POUR PRISE EN CHARGE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Dernier message : \"{last_message[:250]}\"\n"
        f"📊 Statut : *5 échanges IA complétés*\n"
        f"⏱️  Heure : {ts}\n\n"
        f"👉 Ce client attend qu'un conseiller le recontacte."
    ))


def alert_operator_human_request(chat_id: str, last_message: str):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    send_whatsapp(OPERATOR_CHAT_ID, (
        f"🚨 *DEMANDE HUMAIN EXPLICITE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Message : \"{last_message[:250]}\"\n"
        f"📌 TYPE : *URGENT — CLIENT DEMANDE UN CONSEILLER*\n"
        f"⏱️  Heure : {ts}"
    ))


# ═══════════════════════════════════════════════════════════════
# 🔍 QUALIFICATION PROSPECT — Groq léger, timeout (3, 6)
# Appelé UNIQUEMENT sur le premier message d'un inconnu.
# Fail-open : si Groq timeout → on laisse passer.
# ═══════════════════════════════════════════════════════════════
def is_prospect(message: str) -> bool:
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Classificateur binaire. Réponds UNIQUEMENT OUI ou NON.\n\n"
                            "OUI si le message vient d'un prospect potentiel : "
                            "intérêt commercial, sourcing, importation, Chine, fournisseurs, "
                            "voyage d'affaires, inscription, services professionnels, "
                            "salutations simples (bonjour, bonsoir, allô, salut).\n\n"
                            "NON si clairement hors-sujet : spam, blague, message personnel "
                            "sans lien commercial, message erroné.\n\n"
                            "En cas de doute → OUI."
                        )
                    },
                    {"role": "user", "content": message}
                ],
                "temperature": 0.0,
                "max_tokens":  5
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}"
            },
            timeout=(3, 6)
        )
        if res.status_code != 200:
            print(f"⚠️  Filtre KO ({res.status_code}) — fail-open", flush=True)
            return True
        answer = res.json()["choices"][0]["message"]["content"].strip().upper()
        result = answer.startswith("OUI")
        print(f"🔍 Prospect : {'✅ OUI' if result else '❌ NON'} | '{message[:50]}'", flush=True)
        return result
    except Exception as e:
        print(f"⚠️  Filtre EXCEPTION ({e}) — fail-open", flush=True)
        return True   # fail-open


# ═══════════════════════════════════════════════════════════════
# 🔍 DÉTECTION DEMANDE HUMAIN (mots-clés, pas d'appel réseau)
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
    m = message.lower()
    return any(kw in m for kw in HUMAN_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# 🤖 RÉPONSE IA (Groq) — timeout (3, 12) — historique glissant
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
6. Hors-sujet (politique, religion...) → décline poliment.
7. NE PAS re-saluer à chaque message. Saluer uniquement au premier échange.
8. Si le client est prêt à s'inscrire → partager les liens officiels.

LIENS OFFICIELS :
- Formulaire en ligne : {LINK_FORM_ONLINE}
- Brochure PDF : {LINK_BROCHURE}
- Fiche inscription PDF : {LINK_FORM_PDF}

CHANA CORPORATE :
Entreprise ivoirienne — accompagnement commercial international, sourcing, missions commerciales, logistique, partenariats stratégiques.

MISSION CHINE 2026 :
Dates : 22–31 juillet 2026 (10 jours) | Zhejiang, Chine
Organisateurs : Chana Corporate & African Wind
Partenaires : consortium 1 000+ entreprises chinoises

OBJECTIFS : Achat direct usine · Réduction intermédiaires · Marges améliorées · Fournisseurs fiables · Tarifs préférentiels · Réseau international

ZHEJIANG : Berceau Alibaba & Geely · Marché Yiwu · Ports top · Prix < Guangzhou · Dense en PME

SECTEURS : BTP · Auto · Agriculture · Électroménager · Textile · Fournitures · Mobilier · Médical · Énergies · Commerce général

FORFAIT INCLUS : Visa · Billet A/R · Hôtel 3-4★ · 3 repas/j · B2B · Usines · Yiwu · Transport · Interprètes · Suivi commandes · Contrôle qualité

PROGRAMME : J1-2 Accueil/Briefing | J3 B2B | J4-6 Usines+Yiwu | J7-8 Négos+Commandes | J9-10 Débriefing+Retour

TARIF : 2 500 000 FCFA | Acompte 40% = 1 000 000 FCFA | Solde avant 1er juillet 2026
Paiements : Mobile Money · Espèces · Chèque

CONTACTS : WhatsApp +225 05 00 02 60 72 | Tél +225 27 22 23 66 83 | chanacorporate@gmail.com
Adresses : Cocody Riviera 3, Rue Kloé | Immeuble XL, Rue Dr Crozet"""


def ask_groq(chat_id: str, message: str) -> str:
    try:
        history = conversation_history.setdefault(chat_id, [])
        history.append({"role": "user", "content": message})

        # Fenêtre glissante
        if len(history) > HISTORY_MAX_MESSAGES:
            conversation_history[chat_id] = history[-HISTORY_MAX_MESSAGES:]
            history = conversation_history[chat_id]

        t0  = time.time()
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *history
                ],
                "temperature": 0.4,
                "max_tokens":  1024,
                "top_p":       1
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GROQ_API_KEY}"
            },
            timeout=(3, 12)
        )

        if res.status_code != 200:
            print(f"❌ GROQ {res.status_code} : {res.text[:200]}", flush=True)
            return "Désolé, une erreur est survenue. Veuillez réessayer."

        reply = res.json()["choices"][0]["message"]["content"].strip()
        history.append({"role": "assistant", "content": reply})
        print(f"🤖 Groq OK ({time.time()-t0:.2f}s) échanges={len(history)//2}", flush=True)
        return reply

    except requests.exceptions.ConnectTimeout:
        return "Je mets un peu de temps à répondre, merci de patienter et renvoyez votre question. 🙏"
    except requests.exceptions.ReadTimeout:
        return "Je réfléchis encore… merci de patienter puis renvoyez votre question. 🙏"
    except Exception as e:
        print(f"❌ GROQ EXCEPTION : {e}", flush=True)
        return "Le service est momentanément indisponible. Veuillez réessayer."


# ═══════════════════════════════════════════════════════════════
# 🛡️ ANTI-DOUBLON
# ═══════════════════════════════════════════════════════════════
def is_duplicate(msg_id: str) -> bool:
    if msg_id in processed_messages:
        return True
    processed_messages.add(msg_id)
    return False


# ═══════════════════════════════════════════════════════════════
# ⚙️  WORKER — traitement async des messages
#
# Le webhook dépose un dict dans work_queue et retourne 202 immédiatement.
# Ce worker tourne en boucle infinie dans son propre thread.
# En cas d'exception non catchée, il log et continue (pas de crash silencieux).
# ═══════════════════════════════════════════════════════════════
def process_job(job: dict):
    """Traite un message entrant : qualification, IA, envoi, alertes."""
    chat_id = job["chat_id"]
    message = job["message"]

    try:
        state = user_state.get(chat_id)

        # ── Porte d'entrée : qualification prospect ───────────
        if state is None:
            if not is_prospect(message):
                print(f"🚫 Non-prospect ignoré : {chat_id} | '{message[:50]}'", flush=True)
                return
            print(f"✅ Nouveau prospect : {chat_id}", flush=True)
            user_state[chat_id] = {
                "step":       "ai",
                "exchanges":  0,
                "escalated":  False,
                "created_at": time.time(),
                "last_seen":  time.time(),
            }
            state = user_state[chat_id]

        # Mise à jour last_seen (pour TTL)
        state["last_seen"] = time.time()
        step = state["step"]

        # ── Mode humain : bot silencieux ──────────────────────
        if step == "human":
            print(f"🔕 Silencieux ({chat_id})", flush=True)
            return

        # ── Mode IA ───────────────────────────────────────────
        if step == "ai":

            # Demande humain explicite
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
                return

            # Réponse IA
            reply = ask_groq(chat_id, message)
            state["exchanges"] += 1
            send_whatsapp(chat_id, reply)

            exchanges = state["exchanges"]
            print(f"💬 Échange #{exchanges} | {chat_id}", flush=True)

            # Escalade auto après 5 échanges
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

    except Exception as e:
        print(f"❌ WORKER EXCEPTION [{chat_id}] : {e}", flush=True)
        traceback.print_exc()


def worker_loop():
    """Boucle infinie du worker. Résistant aux exceptions."""
    print("⚙️  Worker async démarré.", flush=True)
    while True:
        try:
            job = work_queue.get(timeout=30)   # timeout pour ne pas bloquer indéfiniment
            process_job(job)
            work_queue.task_done()
        except queue.Empty:
            continue   # pas de job, on boucle
        except Exception as e:
            # Log complet, mais le worker ne crashe pas
            print(f"❌ WORKER LOOP ERROR : {e}", flush=True)
            traceback.print_exc()


threading.Thread(target=worker_loop, daemon=True, name="AsyncWorker").start()


# ═══════════════════════════════════════════════════════════════
# 📩 WEBHOOK — répond en < 200ms, délègue au worker
# ═══════════════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
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

        # Filtres système (rapides, pas d'appel réseau)
        if chat_id.endswith("@g.us"):
            return jsonify({"ignored": True, "reason": "group_message"})
        if BOT_OWN_NUMBER and chat_id == BOT_OWN_NUMBER:
            return jsonify({"ignored": True, "reason": "self_message"})
        if not chat_id or not message:
            return jsonify({"ok": True, "reason": "empty"}), 200
        if msg_id and is_duplicate(msg_id):
            return jsonify({"ignored": True, "reason": "duplicate"})

        # Dépôt dans la file (non-bloquant)
        try:
            work_queue.put_nowait({"chat_id": chat_id, "message": message, "msg_id": msg_id})
            print(f"📩 Enqueued [{chat_id}] : {message[:60]}", flush=True)
        except queue.Full:
            # File pleine → log mais on ne crashe pas
            print(f"⚠️  Queue pleine — message de {chat_id} ignoré.", flush=True)
            return jsonify({"error": "queue_full"}), 503

        # Réponse immédiate à Green API (< 200ms garanti)
        return jsonify({"ok": True, "queued": True}), 202

    except Exception as e:
        print(f"❌ WEBHOOK EXCEPTION : {e}", flush=True)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# 🏓 /ping — keep-alive pour Render (à appeler toutes les 14 min)
# ═══════════════════════════════════════════════════════════════
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"pong": True, "ts": time.time()}), 200


# ═══════════════════════════════════════════════════════════════
# 🧪 /test-whatsapp — vérifie que l'envoi WA fonctionne
# ═══════════════════════════════════════════════════════════════
@app.route("/test-whatsapp", methods=["GET"])
def test_whatsapp():
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ok  = send_whatsapp(
        OPERATOR_CHAT_ID,
        f"🧪 *TEST BOT CHANA CORPORATE*\n\n✅ Bot opérationnel.\n⏱️ {ts}"
    )
    return jsonify({"success": ok, "target": OPERATOR_CHAT_ID})


# ═══════════════════════════════════════════════════════════════
# 🏥 / — health check complet
# ═══════════════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def health():
    steps: dict = {}
    for s in user_state.values():
        k = s.get("step", "unknown")
        steps[k] = steps.get(k, 0) + 1

    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v8",
        "model":              "llama-3.3-70b-versatile",
        "operator_target":    OPERATOR_CHAT_ID or "⚠️ NON CONFIGURÉ",
        "queue_size":         work_queue.qsize(),
        "total_users":        len(user_state),
        "processed_messages": len(processed_messages),
        "steps_breakdown":    steps,
        "memory_ttl_hours":   MEMORY_TTL_SECONDS // 3600,
    })


# ═══════════════════════════════════════════════════════════════
# 🚀 DÉMARRAGE
# ═══════════════════════════════════════════════════════════════
check_env()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"""
    ╔══════════════════════════════════════════════════╗
    ║   🤖  CHANA CORPORATE BOT  v8.0  READY          ║
    ║   Port       : {port}                              ║
    ║   Webhook    : async < 200ms (queue)             ║
    ║   Mémoire    : TTL {MEMORY_TTL_SECONDS//3600}h — nettoyage /30min        ║
    ║   Timeouts   : connect=3s / read=10-12s          ║
    ║   Keep-alive : GET /ping                         ║
    ║   Test WA    : GET /test-whatsapp                ║
    ╚══════════════════════════════════════════════════╝
    """, flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
