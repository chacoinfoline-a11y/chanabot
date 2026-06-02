from flask import Flask, request, jsonify
import requests
import os
import traceback
import json
import time
import threading
from datetime import datetime

app = Flask(__name__)

# ─────────────────────────────────────────
# 🔐 CONFIG
# ─────────────────────────────────────────
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
ID_INSTANCE       = os.getenv("ID_INSTANCE")
API_TOKEN         = os.getenv("API_TOKEN")
# ✅ RENOMMÉ pour plus de clarté - supporte @c.us ET @g.us
OPERATOR_CHAT_ID  = os.getenv("OPERATOR_CHAT_ID", "")  # Ex: 2250500026072@c.us ou groupe@g.us

# ✅ Extraction du numéro du bot depuis l'instance ID
# Format standard Green API : le numéro est dans l'ID d'instance
BOT_PHONE_NUMBER = os.getenv("BOT_PHONE_NUMBER", "")  # Ex: 2250500026072
BOT_CHAT_ID = f"{BOT_PHONE_NUMBER}@c.us" if BOT_PHONE_NUMBER else ""

GREEN_API_BASE = f"https://api.green-api.com/waInstance{ID_INSTANCE}"

# ─────────────────────────────────────────
# 🔗 LIENS OFFICIELS
# ─────────────────────────────────────────
LINK_FORM_ONLINE = "https://docs.google.com/forms/d/e/1FAIpQLSf0erNIO6OeERQorJGPaYRPRl2x6gU8S61JabwIJ--pNBSbCA/viewform?usp=publish-editor"
LINK_BROCHURE    = "https://drive.google.com/file/d/1YEEsJEDARjkb2QBk1dw3SVDtVNm9O7p0/view?usp=sharing"
LINK_FORM_PDF    = "https://drive.google.com/file/d/1QtZaRDUHgVsRIal05i7RuhvVVz1gnZEz/view?usp=sharing"

# ─────────────────────────────────────────
# 🗂️  ÉTAT EN MÉMOIRE
# ─────────────────────────────────────────
user_state: dict[str, dict] = {}
processed_messages: set[str] = set()
conversation_history: dict[str, list] = {}

# ✅ Compteur pour les stats de notification
notification_stats = {
    "sent": 0,
    "failed": 0,
    "skipped_self": 0
}


# ─────────────────────────────────────────
# 🧹 Nettoyage mémoire
# ─────────────────────────────────────────
def clean_cache():
    while True:
        time.sleep(300)
        if len(processed_messages) > 2000:
            processed_messages.clear()

threading.Thread(target=clean_cache, daemon=True).start()


# ─────────────────────────────────────────
# 🧠 LOG
# ─────────────────────────────────────────
def log(title: str, data: dict, force: bool = False):
    if force or os.getenv("DEBUG", "false").lower() == "true":
        print(f"\n{'═' * 60}\n🔥 {title}\n{'═' * 60}")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:700])
        print("═" * 60 + "\n")


# ─────────────────────────────────────────
# ✅ VALIDATION DÉMARRAGE
# ─────────────────────────────────────────
def validate_config():
    """Vérifie que toutes les variables d'environnement requises sont présentes"""
    required_vars = {
        "GROQ_API_KEY": GROQ_API_KEY,
        "ID_INSTANCE": ID_INSTANCE,
        "API_TOKEN": API_TOKEN,
        "OPERATOR_CHAT_ID": OPERATOR_CHAT_ID,
    }
    
    missing = [k for k, v in required_vars.items() if not v]
    
    if missing:
        error_msg = f"""
        ╔══════════════════════════════════════════════╗
        ║   ❌ ERREUR DE CONFIGURATION                 ║
        ║   Variables manquantes :                     ║
        ╚══════════════════════════════════════════════╝
        """
        for var in missing:
            error_msg += f"\n   • {var}"
        error_msg += "\n\n   Le bot ne peut pas démarrer.\n"
        print(error_msg)
        return False
    
    # ✅ Validation du format OPERATOR_CHAT_ID
    if not (OPERATOR_CHAT_ID.endswith("@c.us") or OPERATOR_CHAT_ID.endswith("@g.us")):
        print(f"⚠️  ATTENTION : OPERATOR_CHAT_ID ({OPERATOR_CHAT_ID}) ne termine pas par @c.us ou @g.us")
        print("   L'envoi pourrait échouer. Format attendu : 225XXXXXXXX@c.us ou groupe@g.us")
    
    return True


# ─────────────────────────────────────────
# 📤 ENVOI WHATSAPP (CORRIGÉ)
# ─────────────────────────────────────────
def send_whatsapp(chat_id: str, message: str) -> bool:
    """
    Envoie un message WhatsApp via Green API.
    
    Returns:
        bool: True si envoyé avec succès, False sinon
    """
    # ✅ Sécurité : ne pas envoyer au bot lui-même
    if BOT_CHAT_ID and chat_id == BOT_CHAT_ID:
        log("⛔ AUTO-ENVOI BLOQUÉ", {
            "chat_id": chat_id,
            "reason": "Tentative d'envoi au numéro du bot - WhatsApp ne livre pas"
        }, force=True)
        notification_stats["skipped_self"] += 1
        return False
    
    # ✅ Validation du format
    if not (chat_id.endswith("@c.us") or chat_id.endswith("@g.us")):
        log("⚠️ FORMAT INVALIDE", {
            "chat_id": chat_id,
            "reason": "Ne termine pas par @c.us ou @g.us"
        }, force=True)
        return False
    
    url = f"{GREEN_API_BASE}/sendMessage/{API_TOKEN}"
    payload = {"chatId": chat_id, "message": message}
    
    try:
        # ✅ Log AVANT l'envoi
        log("📤 ENVOI WHATSAPP", {
            "url": url,
            "payload": payload,
            "message_preview": message[:80]
        })
        
        res = requests.post(url, json=payload, timeout=10)
        
        # ✅ Log détaillé de la réponse
        response_info = {
            "to": chat_id,
            "status_code": res.status_code,
            "response_body": res.text[:500],
            "success": res.status_code == 200
        }
        
        if res.status_code == 200:
            log("✅ ENVOI RÉUSSI", response_info)
            notification_stats["sent"] += 1
            return True
        else:
            log("❌ ÉCHEC ENVOI", response_info, force=True)
            notification_stats["failed"] += 1
            return False
            
    except requests.Timeout:
        log("⏱️ TIMEOUT ENVOI", {"to": chat_id, "error": "Timeout après 10s"}, force=True)
        notification_stats["failed"] += 1
        return False
    except Exception as e:
        log("💥 ERREUR ENVOI", {
            "to": chat_id,
            "error": str(e),
            "traceback": traceback.format_exc()[:500]
        }, force=True)
        notification_stats["failed"] += 1
        return False


# ─────────────────────────────────────────
# 🧵 ENVOI THREADÉ SÉCURISÉ
# ─────────────────────────────────────────
def send_whatsapp_async(chat_id: str, message: str):
    """
    Envoi WhatsApp dans un thread avec logs complets.
    Capture et log les erreurs pour éviter les échecs silencieux.
    """
    def _send_with_logging():
        thread_name = threading.current_thread().name
        log("🧵 THREAD DÉMARRÉ", {
            "thread": thread_name,
            "target": chat_id,
            "message_preview": message[:80]
        })
        
        try:
            success = send_whatsapp(chat_id, message)
            log("🧵 THREAD TERMINÉ", {
                "thread": thread_name,
                "success": success,
                "target": chat_id
            })
        except Exception as e:
            log("💥 ERREUR THREAD", {
                "thread": thread_name,
                "error": str(e),
                "traceback": traceback.format_exc()[:500]
            }, force=True)
    
    thread = threading.Thread(
        target=_send_with_logging,
        name=f"WA-{chat_id[:15]}-{int(time.time())}",
        daemon=True
    )
    thread.start()
    return thread


# ─────────────────────────────────────────
# 🚨 ALERTE OPÉRATEUR (CORRIGÉ)
# ─────────────────────────────────────────
def alert_operator_escalation(chat_id: str, last_message: str):
    """Alerte après 5 échanges IA"""
    # ✅ Validation avant envoi
    if not OPERATOR_CHAT_ID:
        log("❌ ALERTE IMPOSSIBLE", {
            "reason": "OPERATOR_CHAT_ID non configuré"
        }, force=True)
        return
    
    ts    = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🔔 *CLIENT PRÊT POUR PRISE EN CHARGE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Dernier message : \"{last_message[:250]}\"\n"
        f"📊 Statut : *5 échanges IA complétés*\n"
        f"⏱️  Heure : {ts}\n\n"
        f"👉 Ce client a été informé qu'un conseiller va le contacter."
    )
    
    # ✅ Utilisation de la fonction threadée avec logs
    log("🔔 ESCALADE", {
        "client": chat_id,
        "operator_target": OPERATOR_CHAT_ID,
        "exchanges": user_state.get(chat_id, {}).get("exchanges", "?")
    }, force=True)
    
    send_whatsapp_async(OPERATOR_CHAT_ID, alert)
    print(f"🔔 Alerte escalade envoyée → {chat_id}")


def alert_operator_human_request(chat_id: str, last_message: str):
    """Alerte immédiate si le client demande explicitement un humain"""
    if not OPERATOR_CHAT_ID:
        log("❌ ALERTE IMPOSSIBLE", {
            "reason": "OPERATOR_CHAT_ID non configuré"
        }, force=True)
        return
    
    ts    = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    alert = (
        f"🚨 *DEMANDE HUMAIN EXPLICITE*\n\n"
        f"📞 Client : {chat_id}\n"
        f"💬 Message : \"{last_message[:250]}\"\n"
        f"📌 TYPE : *URGENT — CLIENT DEMANDE UN CONSEILLER*\n"
        f"⏱️  Heure : {ts}"
    )
    
    log("🚨 ALERTE HUMAIN", {
        "client": chat_id,
        "operator_target": OPERATOR_CHAT_ID,
        "message": last_message[:100]
    }, force=True)
    
    send_whatsapp_async(OPERATOR_CHAT_ID, alert)
    print(f"🚨 Alerte humain urgent envoyée → {chat_id}")


# ─────────────────────────────────────────
# 🧪 FONCTION DE TEST WHATSAPP
# ─────────────────────────────────────────
def test_whatsapp():
    """
    Test d'envoi WhatsApp à l'opérateur.
    À appeler au démarrage ou via une route de test.
    """
    if not OPERATOR_CHAT_ID:
        print("❌ TEST IMPOSSIBLE : OPERATOR_CHAT_ID non configuré")
        return False
    
    print(f"\n{'═' * 60}")
    print("🧪 TEST WHATSAPP")
    print(f"   Cible : {OPERATOR_CHAT_ID}")
    print(f"   Instance : {ID_INSTANCE}")
    print(f"{'═' * 60}\n")
    
    test_message = (
        f"✅ *Test WhatsApp - Chana Bot v5*\n\n"
        f"🕐 Heure : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"📊 Statut : Bot opérationnel\n\n"
        f"_Ceci est un message de test automatique._"
    )
    
    success = send_whatsapp(OPERATOR_CHAT_ID, test_message)
    
    if success:
        print("✅ TEST RÉUSSI - Message envoyé à l'opérateur")
    else:
        print("❌ TEST ÉCHOUÉ - Vérifiez les logs ci-dessus")
    
    return success


# ─────────────────────────────────────────
# 🤖 RÉPONSE IA (Groq) - INCHANGÉ
# ─────────────────────────────────────────
# [Le reste du code reste identique : SYSTEM_PROMPT, ask_groq, etc.]
# ... (conservez votre code existant pour ces fonctions)


# ─────────────────────────────────────────
# 🏥 HEALTH CHECK (AMÉLIORÉ)
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    steps: dict = {}
    for s in user_state.values():
        k = s.get("step", "unknown")
        steps[k] = steps.get(k, 0) + 1

    return jsonify({
        "status":             "ok",
        "service":            "Chana Corporate WhatsApp Bot v5.1",
        "model":              "llama-3.3-70b-versatile",
        "total_users":        len(user_state),
        "processed_messages": len(processed_messages),
        "steps_breakdown":    steps,
        # ✅ Nouvelles stats
        "operator_chat_id":   OPERATOR_CHAT_ID,
        "bot_chat_id":        BOT_CHAT_ID or "non configuré",
        "self_send_protection": bool(BOT_CHAT_ID),
        "notifications":      notification_stats
    })


# ─────────────────────────────────────────
# 🧪 ROUTE DE TEST
# ─────────────────────────────────────────
@app.route("/test-whatsapp", methods=["GET"])
def test_whatsapp_route():
    """Route pour tester l'envoi WhatsApp"""
    success = test_whatsapp()
    return jsonify({
        "test": "whatsapp_send",
        "success": success,
        "target": OPERATOR_CHAT_ID,
        "timestamp": datetime.now().isoformat()
    })


# ─────────────────────────────────────────
# 🚀 DÉMARRAGE (AVEC VALIDATION)
# ─────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    
    print(f"""
    ╔══════════════════════════════════════════════╗
    ║   🤖  CHANA CORPORATE BOT  v5.1  READY      ║
    ║   Port   : {port}                              ║
    ║   Model  : llama-3.3-70b-versatile           ║
    ║   Escalade : après 5 échanges IA             ║
    ╚══════════════════════════════════════════════╝
    """)
    
    # ✅ Validation de la configuration au démarrage
    if not validate_config():
        print("\n❌ ARRÊT DU BOT - Configuration invalide")
        exit(1)
    
    # ✅ Affichage config
    print(f"""
    📋 Configuration :
    • OPERATOR_CHAT_ID : {OPERATOR_CHAT_ID}
    • BOT_CHAT_ID      : {BOT_CHAT_ID or 'NON CONFIGURÉ'}
    • ID_INSTANCE      : {ID_INSTANCE}
    • GROQ_API_KEY     : {'✅ Configurée' if GROQ_API_KEY else '❌ MANQUANTE'}
    """)
    
    # ✅ Test WhatsApp automatique au démarrage (optionnel)
    if os.getenv("TEST_ON_STARTUP", "false").lower() == "true":
        print("\n🔍 Test WhatsApp automatique...")
        test_whatsapp()
    
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
