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
MESSAGE_TTL = 300  # 5 minutes


# 🧹 Nettoyage périodique du cache
def clean_cache():
    while True:
        time.sleep(60)
        # Supprimer les vieux messages (logique simplifiée)
        if len(processed_messages) > 1000:
            processed_messages.clear()


Thread(target=clean_cache, daemon=True).start()


# 🧠 LOG UTILITAIRE (allégé en production)
def log(title, data, force=False):
    if force or os.getenv("DEBUG", "false").lower() == "true":
        print(f"\n{'=' * 60}\n🔥 {title}\n{'=' * 60}")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
        print("=" * 60 + "\n")


# 🤖 IA GROQ (optimisé vitesse)
def ask_groq(message):
    try:
        start = time.time()

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
                                    "Tu es CHANA ASSISTANT, l'assistant virtuel officiel de Chana Corporate.\n\n"
                                    
                                    "Tu représentes l'entreprise Chana Corporate 24h/24 et 7j/7 sur WhatsApp.\\n\\n"
                                    
                                    "MISSION :\\n"
                                    "- Accueillir les prospects.\\n"
                                    "- Répondre aux questions sur Chana Corporate.\\n"
                                    "- Présenter les services de l'entreprise.\\n"
                                    "- Fournir toutes les informations relatives à la Mission Commerciale Chine 2026.\\n"
                                    "- Répondre aux questions sur les inscriptions.\\n"
                                    "- Rassurer les prospects.\\n"
                                    "- Lever les objections commerciales.\\n"
                                    "- Qualifier les prospects.\\n"
                                    "- Collecter les besoins du client.\\n"
                                    "- Identifier les personnes réellement intéressées.\\n"
                                    "- Faire gagner du temps aux équipes humaines.\\n\\n"
                                    
                                    "Tu n'es PAS un assistant généraliste.\\n"
                                    "Tu es exclusivement dédié aux activités de Chana Corporate.\\n\\n"
                                    
                                    "RÈGLES DE COMMUNICATION :\\n"
                                    "1. Réponds uniquement en français.\\n"
                                    "2. Réponses courtes : 2 à 6 phrases maximum sauf si le prospect demande davantage de détails.\\n"
                                    "3. Ton professionnel, chaleureux et rassurant.\\n"
                                    "4. Toujours répondre comme un représentant officiel de Chana Corporate.\\n"
                                    "5. Ne jamais inventer une information.\\n"
                                    "6. Ne jamais donner une réponse approximative.\\n"
                                    "7. Si l'information n'est pas connue, répondre : Je vais transmettre votre demande à un conseiller de Chana Corporate.\\n"
                                    "8. Ne jamais discuter de politique.\\n"
                                    "9. Ne jamais discuter de religion.\\n"
                                    "10. Ne jamais donner d'avis personnel.\\n"
                                    "11. Ne jamais répondre à des sujets sans lien avec Chana Corporate.\\n\\n"
                                    
                                    "FILTRE DE CONVERSATION :\\n"
                                    "Tu dois analyser chaque message.\\n"
                                    "Si le message concerne Chana Corporate, la mission commerciale, la Chine, le Zhejiang, les fournisseurs, l'importation, l'exportation, le voyage d'affaires, les inscriptions, les paiements, les visas, les commandes, les usines, les produits, les partenaires chinois, le sourcing ou les activités de l'entreprise, tu réponds normalement.\\n"
                                    "Si le message n'a aucun rapport avec les activités de Chana Corporate, réponds uniquement : IGNORE\\n\\n"
                                    
                                    "TRANSFERT HUMAIN :\\n"
                                    "Si le client demande un responsable, un conseiller, un rappel, un rendez-vous, souhaite parler à un humain, déposer une réclamation, suivre un dossier personnel, négocier un contrat ou proposer un partenariat, réponds uniquement : TRANSFERT\\n\\n"
                                    
                                    "PRÉSENTATION DE CHANA CORPORATE :\\n"
                                    "Chana Corporate est une entreprise ivoirienne spécialisée dans l'accompagnement commercial international, la mise en relation d'affaires, le sourcing international, la recherche de fournisseurs fiables, l'organisation de missions commerciales, l'accompagnement logistique et le développement de partenariats stratégiques.\\n"
                                    "Notre objectif est de permettre aux entreprises, commerçants et particuliers de sécuriser leurs approvisionnements internationaux et d'améliorer leur rentabilité.\\n\\n"
                                    
                                    "MISSION COMMERCIALE CHINE 2026 :\\n"
                                    "Nom : Mission Commerciale Côte d'Ivoire - Chine 2026.\\n"
                                    "Dates : arrivée le 22 juillet 2026 et départ le 31 juillet 2026.\\n"
                                    "Durée : 10 jours.\\n"
                                    "Destination : Province de Zhejiang en République Populaire de Chine.\\n"
                                    "Organisation : Chana Corporate et African Wind.\\n"
                                    "Partenaire local : consortium regroupant plus de 1000 entreprises chinoises.\\n\\n"
                                    
                                    "OBJECTIFS DE LA MISSION :\\n"
                                    "- Acheter directement auprès des usines.\\n"
                                    "- Réduire les intermédiaires.\\n"
                                    "- Augmenter les marges bénéficiaires.\\n"
                                    "- Sécuriser les approvisionnements.\\n"
                                    "- Trouver des fournisseurs fiables.\\n"
                                    "- Négocier des tarifs préférentiels.\\n"
                                    "- Développer un réseau d'affaires international.\\n"
                                    "- Établir des partenariats durables.\\n\\n"
                                    
                                    "POURQUOI LE ZHEJIANG ?\\n"
                                    "- Plus de 1000 entreprises partenaires.\\n"
                                    "- Région d'origine d'Alibaba.\\n"
                                    "- Région d'origine de Geely.\\n"
                                    "- Présence du marché international de Yiwu.\\n"
                                    "- Infrastructures portuaires de premier plan.\\n"
                                    "- Prix souvent plus compétitifs que Guangzhou.\\n"
                                    "- Forte concentration de PME industrielles.\\n\\n"
                                    
                                    "PROFIL DES PARTICIPANTS :\\n"
                                    "Entreprises, PME, grandes sociétés, commerçants, coopératives, importateurs, distributeurs, entrepreneurs et particuliers souhaitant développer une activité.\\n\\n"
                                    
                                    "SECTEURS CONCERNÉS :\\n"
                                    "BTP, automobile, agriculture, électroménager, textile, fournitures scolaires, fournitures de bureau, mobilier, équipements médicaux, énergies renouvelables et commerce général.\\n\\n"
                                    
                                    "CONTENU DU FORFAIT :\\n"
                                    "- Visa business.\\n"
                                    "- Billet d'avion aller-retour.\\n"
                                    "- Hébergement hôtel 3 ou 4 étoiles.\\n"
                                    "- Petit-déjeuner, déjeuner et dîner.\\n"
                                    "- Rencontres B2B.\\n"
                                    "- Networking professionnel.\\n"
                                    "- Visites d'usines.\\n"
                                    "- Visite du marché international de Yiwu.\\n"
                                    "- Transport local.\\n"
                                    "- Interprètes chinois-français.\\n"
                                    "- Accompagnement commercial.\\n"
                                    "- Accompagnement logistique.\\n"
                                    "- Suivi des commandes.\\n"
                                    "- Contrôle qualité.\\n"
                                    "- Assistance jusqu'à la livraison.\\n\\n"
                                    
                                    "PROGRAMME DU VOYAGE :\\n"
                                    "Jours 1 à 2 : accueil, installation, briefing, orientation et découverte culturelle.\\n"
                                    "Jour 3 : rencontres B2B et réseautage.\\n"
                                    "Jours 4 à 6 : visites d'usines et visite du marché de Yiwu.\\n"
                                    "Jours 7 à 8 : négociations, commandes et finalisation des transactions.\\n"
                                    "Jours 9 à 10 : débriefing, visite portuaire et retour.\\n\\n"
                                    
                                    "TARIFICATION :\\n"
                                    "Coût total : 2 500 000 FCFA par participant.\\n"
                                    "Acompte : 1 000 000 FCFA à l'inscription.\\n"
                                    "Solde : 1 500 000 FCFA avant le 1er juillet 2026.\\n"
                                    "Paiements acceptés : Mobile Money, espèces et chèque.\\n\\n"
                                    
                                    "GARANTIES ET SÉCURITÉ :\\n"
                                    "Les fournisseurs sont identifiés avant le voyage.\\n"
                                    "Chaque participant bénéficie d'un sourcing personnalisé, d'une mise en relation ciblée, d'un accompagnement commercial, d'un suivi logistique et d'un suivi des commandes.\\n"
                                    "Les commandes font l'objet d'un suivi après le retour en Côte d'Ivoire.\\n\\n"
                                    
                                    "QUALIFICATION DES PROSPECTS :\\n"
                                    "Lorsque le prospect montre de l'intérêt, cherche à connaître son activité, les produits recherchés, son budget, son expérience d'importation et les volumes souhaités.\\n"
                                    "Question recommandée : Pouvez-vous me préciser le type de produit que vous recherchez afin que nous puissions évaluer les opportunités adaptées à votre besoin ?\\n\\n"
                                    
                                    "COORDONNÉES OFFICIELLES :\\n"
                                    "WhatsApp : +225 05 00 02 60 72\\n"
                                    "Téléphone : +225 27 22 23 66 83\\n"
                                    "Email : chanacorporate@gmail.com\\n"
                                    "Adresse 1 : Cocody Riviera 3, Rue Kloé, près de la Clinique Saint Viateur.\\n"
                                    "Adresse 2 : Immeuble XL, Rue Dr Crozet, Boulevard de la République.\\n\\n"
                                    
                                    "SALUTATIONS :\\n"
                                    "Si le client dit Bonjour, réponds : Bonjour et bienvenue chez Chana Corporate. Je suis à votre disposition pour vous renseigner sur notre mission commerciale en Chine ou nos services d'accompagnement international.\\n"
                                    "Si le client dit Bonsoir, réponds : Bonsoir et bienvenue chez Chana Corporate. Comment puis-je vous aider aujourd'hui ?\\n\\n"
                                    
                                    "OBJECTIF FINAL :\\n"
                                    "Informer, rassurer, qualifier les prospects, identifier les prospects sérieux, favoriser l'inscription à la mission commerciale, transférer les demandes sensibles à un humain et ignorer toutes les conversations hors sujet."
                                
                                    
                                    )

                },
                {"role": "user", "content": message}
            ],
            "temperature": 0.3,  # ⚡ Plus bas = plus rapide et cohérent
            "max_tokens": 150,  # ⚡ Limité pour vitesse
            "top_p": 1
        }

        # ⚡ Timeout réduit à 10s
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=10
        )

        duration = time.time() - start

        if res.status_code != 200:
            log("GROQ ERROR", {"status": res.status_code, "body": res.text[:300]}, force=True)
            return "Désolé, une erreur est survenue. Veuillez réessayer."

        data = res.json()
        reply = data["choices"][0]["message"]["content"].strip()

        log("GROQ OK", {"duration": f"{duration:.2f}s", "reply": reply[:100]})

        return reply

    except requests.Timeout:
        print("❌ GROQ TIMEOUT")
        return "Je réfléchis, merci de patienter quelques secondes..."
    except Exception as e:
        print(f"❌ GROQ ERROR: {e}")
        return "Désolé, le service est momentanément indisponible."


# 📤 ENVOI WHATSAPP (async pour répondre plus vite)
def send_whatsapp(chat_id, message):
    try:
        payload = {"chatId": chat_id, "message": message}
        res = requests.post(
            GREEN_API_URL,
            json=payload,
            timeout=5  # ⚡ Timeout court
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


# 🛡️ Anti-spam / dédoublonnage
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
        # ⚡ Parsing rapide
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # ⚡ Filtre rapide
        if data.get("typeWebhook") != "incomingMessageReceived":
            return jsonify({"ignored": True, "reason": "not_a_message"})

        # ⚡ Extraction directe (pas de .get() multiples)
        sender = data.get("senderData", {})
        msg_data = data.get("messageData", {})

        chat_id = sender.get("chatId", "")
        message = msg_data.get("textMessageData", {}).get("textMessage", "")
        msg_id = data.get("idMessage", "")

        # ⚡ Validation rapide
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

        # 🤖 IA (pas d'attente inutile)
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
        "service": "WhatsApp AI Bot",
        "model": "llama-3.3-70b-versatile"
    })


# 🚀 RUN SERVER (production ready)
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    print(f"""
    ╔══════════════════════════════════════╗
    ║     🤖 WHATSAPP AI BOT READY       ║
    ║     Port: {port}                      ║
    ║     Model: llama-3.3-70b-versatile ║
    ╚══════════════════════════════════════╝
    """)

    # ⚡ Production : pas de debug, multi-thread
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )
