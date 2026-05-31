from flask import Flask, request, jsonify
import requests
import os
import traceback
import json
import time
from threading import Thread

app = Flask(__name__)

# 🔐 CONFIG
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN = os.getenv("API_TOKEN")
GREEN_API_URL = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"

# ⚡ Cache pour éviter les doublons (messages traités)
processed_messages = set()


# 🧹 Nettoyage périodique du cache
def clean_cache():
    while True:
        time.sleep(60)
        if len(processed_messages) > 1000:
            processed_messages.clear()


Thread(target=clean_cache, daemon=True).start()


# 🧠 LOG UTILITAIRE
def log(title, data, force=False):
    if force or os.getenv("DEBUG", "false").lower() == "true":
        print(f"\n{'=' * 60}\n🔥 {title}\n{'=' * 60}")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
        print("=" * 60 + "\n")


# ────────────────────────────────────────────────────────────
# 🤖  ÉTAPE 1 — FILTRE DE PERTINENCE (modèle léger, rapide)
# ────────────────────────────────────────────────────────────
def is_relevant(message: str) -> bool:
    """
    Appelle Groq avec un mini-prompt de classification.
    Retourne True si le message concerne Chana Corporate,
    False sinon. Timeout court (5 s) car c'est juste un filtre.
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
                        "Réponds UNIQUEMENT par le mot OUI ou le mot NON, sans ponctuation, sans espace.\n\n"
                        "Réponds OUI si le message parle de : Chana Corporate, mission commerciale, "
                        "voyage en Chine, Zhejiang, Yiwu, fournisseurs, importation, exportation, "
                        "sourcing, visa Chine, inscription, paiement, usines, produits chinois, "
                        "logistique, commandes, livraison, BTP, automobile, textile, électroménager, "
                        "agriculture, mobilier, équipements médicaux, énergies renouvelables, "
                        "tarifs, acompte, African Wind, partenaires chinois.\n\n"
                        "Réponds NON pour tout le reste (météo, politique, cuisine, sport, blagues, "
                        "santé générale, religion, salutations sans contexte business, etc.)."
                    )
                },
                {"role": "user", "content": message}
            ],
            "temperature": 0.0,
            "max_tokens": 5
        }
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=5
        )
        if res.status_code != 200:
            # En cas d'erreur du filtre, on laisse passer (fail-open)
            return True
        answer = res.json()["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("OUI")
    except Exception as e:
        print(f"⚠️  FILTER ERROR (fail-open): {e}")
        return True   # fail-open : vaut mieux répondre que de bloquer


# ────────────────────────────────────────────────────────────
# 🤖  ÉTAPE 2 — RÉPONSE COMPLÈTE (aucune limite de tokens)
# ────────────────────────────────────────────────────────────
def ask_groq(message: str) -> str:
    try:
        start = time.time()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }

        # PROMPT SYSTEM — retours à la ligne réels (pas \\n)
        system_prompt = """Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.

Tu représentes l'entreprise Chana Corporate 24h/24 et 7j/7 sur WhatsApp.

MISSION :
- Accueillir les prospects.
- Répondre à TOUTES les questions posées dans un même message, sans en omettre aucune.
- Présenter les services de l'entreprise.
- Fournir toutes les informations relatives à la Mission Commerciale Chine 2026.
- Répondre aux questions sur les inscriptions.
- Rassurer les prospects.
- Lever les objections commerciales.
- Qualifier les prospects.
- Collecter les besoins du client.
- Identifier les personnes réellement intéressées.
- Faire gagner du temps aux équipes humaines.

Tu n'es PAS un assistant généraliste.
Tu es exclusivement dédié aux activités de Chana Corporate.

RÈGLES DE COMMUNICATION :
1. Réponds uniquement en français.
2. Réponds à TOUTES les questions posées dans le message, même s'il y en a beaucoup. Ne te coupe jamais.
3. Ton professionnel, chaleureux et rassurant.
4. Toujours répondre comme un représentant officiel de Chana Corporate.
5. Ne jamais inventer une information.
6. Ne jamais donner une réponse approximative.
7. Si l'information n'est pas connue, répondre : Je vais transmettre votre demande à un conseiller de Chana Corporate.
8. Ne jamais discuter de politique.
9. Ne jamais discuter de religion.
10. Ne jamais donner d'avis personnel.
11. Ne jamais répondre à des sujets sans lien avec Chana Corporate.

TRANSFERT HUMAIN :
Si le client demande un responsable, un conseiller, un rappel, un rendez-vous, souhaite parler à un humain, déposer une réclamation, suivre un dossier personnel, négocier un contrat ou proposer un partenariat, réponds uniquement : TRANSFERT

PRÉSENTATION DE CHANA CORPORATE :
Chana Corporate est une entreprise ivoirienne spécialisée dans l'accompagnement commercial international, la mise en relation d'affaires, le sourcing international, la recherche de fournisseurs fiables, l'organisation de missions commerciales, l'accompagnement logistique et le développement de partenariats stratégiques.
Notre objectif est de permettre aux entreprises, commerçants et particuliers de sécuriser leurs approvisionnements internationaux et d'améliorer leur rentabilité.

MISSION COMMERCIALE CHINE 2026 :
Nom : Mission Commerciale Côte d'Ivoire - Chine 2026.
Dates : arrivée le 22 juillet 2026 et départ le 31 juillet 2026.
Durée : 10 jours.
Destination : Province de Zhejiang en République Populaire de Chine.
Organisation : Chana Corporate et African Wind.
Partenaire local : consortium regroupant plus de 1000 entreprises chinoises.

OBJECTIFS DE LA MISSION :
- Acheter directement auprès des usines.
- Réduire les intermédiaires.
- Augmenter les marges bénéficiaires.
- Sécuriser les approvisionnements.
- Trouver des fournisseurs fiables.
- Négocier des tarifs préférentiels.
- Développer un réseau d'affaires international.
- Établir des partenariats durables.

POURQUOI LE ZHEJIANG ?
- Plus de 1000 entreprises partenaires.
- Région d'origine d'Alibaba.
- Région d'origine de Geely.
- Présence du marché international de Yiwu.
- Infrastructures portuaires de premier plan.
- Prix souvent plus compétitifs que Guangzhou.
- Forte concentration de PME industrielles.

PROFIL DES PARTICIPANTS :
Entreprises, PME, grandes sociétés, commerçants, coopératives, importateurs, distributeurs, entrepreneurs et particuliers souhaitant développer une activité.

SECTEURS CONCERNÉS :
BTP, automobile, agriculture, électroménager, textile, fournitures scolaires, fournitures de bureau, mobilier, équipements médicaux, énergies renouvelables et commerce général.

CONTENU DU FORFAIT :
- Visa business.
- Billet d'avion aller-retour.
- Hébergement hôtel 3 ou 4 étoiles.
- Petit-déjeuner, déjeuner et dîner.
- Rencontres B2B.
- Networking professionnel.
- Visites d'usines.
- Visite du marché international de Yiwu.
- Transport local.
- Interprètes chinois-français.
- Accompagnement commercial.
- Accompagnement logistique.
- Suivi des commandes.
- Contrôle qualité.
- Assistance jusqu'à la livraison.

PROGRAMME DU VOYAGE :
Jours 1 à 2 : accueil, installation, briefing, orientation et découverte culturelle.
Jour 3 : rencontres B2B et réseautage.
Jours 4 à 6 : visites d'usines et visite du marché de Yiwu.
Jours 7 à 8 : négociations, commandes et finalisation des transactions.
Jours 9 à 10 : débriefing, visite portuaire et retour.

TARIFICATION :
Coût total : 2 500 000 FCFA par participant.
Acompte : 1 000 000 FCFA à l'inscription.
Solde : 1 500 000 FCFA avant le 1er juillet 2026.
Paiements acceptés : Mobile Money, espèces et chèque.

GARANTIES ET SÉCURITÉ :
Les fournisseurs sont identifiés avant le voyage.
Chaque participant bénéficie d'un sourcing personnalisé, d'une mise en relation ciblée, d'un accompagnement commercial, d'un suivi logistique et d'un suivi des commandes.
Les commandes font l'objet d'un suivi après le retour en Côte d'Ivoire.

QUALIFICATION DES PROSPECTS :
Lorsque le prospect montre de l'intérêt, cherche à connaître son activité, les produits recherchés, son budget, son expérience d'importation et les volumes souhaités.
Question recommandée : Pouvez-vous me préciser le type de produit que vous recherchez afin que nous puissions évaluer les opportunités adaptées à votre besoin ?

COORDONNÉES OFFICIELLES :
WhatsApp : +225 05 00 02 60 72
Téléphone : +225 27 22 23 66 83
Email : chanacorporate@gmail.com
Adresse 1 : Cocody Riviera 3, Rue Kloé, près de la Clinique Saint Viateur.
Adresse 2 : Immeuble XL, Rue Dr Crozet, Boulevard de la République.

SALUTATIONS :
Si le client dit Bonjour, réponds : Bonjour et bienvenue chez Chana Corporate. Je suis à votre disposition pour vous renseigner sur notre mission commerciale en Chine ou nos services d'accompagnement international.
Si le client dit Bonsoir, réponds : Bonsoir et bienvenue chez Chana Corporate. Comment puis-je vous aider aujourd'hui ?

OBJECTIF FINAL :
Informer, rassurer, qualifier les prospects, identifier les prospects sérieux, favoriser l'inscription à la mission commerciale, transférer les demandes sensibles à un humain."""

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.3,
            "max_tokens": 1024,   # ✅ Augmenté pour ne jamais couper les réponses
            "top_p": 1
        }

        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=15   # ✅ Légèrement augmenté car réponses plus longues possibles
        )

        duration = time.time() - start

        if res.status_code != 200:
            log("GROQ ERROR", {"status": res.status_code, "body": res.text[:300]}, force=True)
            return "Désolé, une erreur est survenue. Veuillez réessayer."

        data = res.json()
        reply = data["choices"][0]["message"]["content"].strip()

        log("GROQ OK", {"duration": f"{duration:.2f}s", "reply": reply[:200]})

        return reply

    except requests.Timeout:
        print("❌ GROQ TIMEOUT")
        return "Je réfléchis, merci de patienter quelques secondes..."
    except Exception as e:
        print(f"❌ GROQ ERROR: {e}")
        return "Désolé, le service est momentanément indisponible."


# 📤 ENVOI WHATSAPP
def send_whatsapp(chat_id, message):
    try:
        payload = {"chatId": chat_id, "message": message}
        res = requests.post(
            GREEN_API_URL,
            json=payload,
            timeout=5
        )
        log("GREEN API", {
            "status": res.status_code,
            "chat_id": chat_id,
            "message": message[:50]
        })
        return res.status_code == 200
    except Exception as e:
        print(f"❌ SEND ERROR: {e}")
        return False


# 🛡️ Anti-doublon
def is_duplicate(msg_id):
    if msg_id in processed_messages:
        return True
    processed_messages.add(msg_id)
    return False


# 📩 WEBHOOK GREEN API
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
        message = msg_data.get("textMessageData", {}).get("textMessage", "")
        msg_id  = data.get("idMessage", "")

        if not chat_id or not message:
            return jsonify({
                "error": "Missing data",
                "chat_id": chat_id,
                "has_message": bool(message)
            }), 200

        # 🛡️ Anti-doublon
        if msg_id and is_duplicate(msg_id):
            print(f"⛔ Doublon ignoré: {msg_id}")
            return jsonify({"ignored": True, "reason": "duplicate"})

        log("📩 MESSAGE", {
            "chat_id": chat_id,
            "message": message[:100],
            "msg_id": msg_id
        })

        # ✅ ÉTAPE 1 — Vérification de la pertinence
        if not is_relevant(message):
            print(f"🔕 Message hors-sujet ignoré: {message[:60]}")
            return jsonify({
                "ignored": True,
                "reason": "off_topic",
                "message": message[:60]
            })

        # ✅ ÉTAPE 2 — Génération de la réponse
        reply = ask_groq(message)

        # 🔁 Remplacement TRANSFERT
        if reply.strip().upper() == "TRANSFERT":
            reply = "Je vous mets en relation avec un conseiller qui vous contactera très prochainement. 🙏"

        # 📤 Envoi WhatsApp
        send_whatsapp(chat_id, reply)

        duration = time.time() - start_time

        return jsonify({
            "success": True,
            "chat_id": chat_id,
            "reply": reply,
            "duration": f"{duration:.2f}s"
        })

    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "duration": f"{time.time() - start_time:.2f}s"
        }), 500


# 🏥 Health check
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "WhatsApp AI Bot — Chana Corporate",
        "model": "llama-3.3-70b-versatile"
    })


# 🚀 RUN SERVER
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    print(f"""
    ╔══════════════════════════════════════╗
    ║     🤖 CHANA CORPORATE BOT READY   ║
    ║     Port: {port}                      ║
    ║     Model: llama-3.3-70b-versatile ║
    ╚══════════════════════════════════════╝
    """)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
