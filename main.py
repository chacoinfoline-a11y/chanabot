from flask import Flask, request, jsonify
import requests
import os
import traceback
import json

app = Flask(__name__)

# 🔐 CONFIG
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN = os.getenv("API_TOKEN")

GREEN_API_URL = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN}"


# 🧠 LOG UTILITAIRE
def log(title, data):
    print("\n" + "="*60)
    print(f"🔥 {title}")
    print("="*60)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("="*60 + "\n")


# 🤖 IA GROQ (avec debug complet)
def ask_groq(message):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": "Tu es un assistant pro. Réponds en français, clair et court. Si transfert humain requis, réponds uniquement: TRANSFERT"
                },
                {
                    "role": "user",
                    "content": message
                }
            ]
        }

        res = requests.post(url, json=payload, headers=headers, timeout=20)

        log("GROQ STATUS", {"status_code": res.status_code})

        data = res.json()
        log("GROQ RESPONSE", data)

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        print("❌ GROQ ERROR:")
        traceback.print_exc()
        return f"Erreur IA: {str(e)}"


# 📩 WEBHOOK GREEN API
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        log("WEBHOOK RECU", data)

        # 🧠 Vérif type webhook
        if data.get("typeWebhook") != "incomingMessageReceived":
            print("⛔ Webhook ignoré:", data.get("typeWebhook"))
            return jsonify({"ignored": True, "type": data.get("typeWebhook")})

        # 📱 chatId safe
        chat_id = (
            data.get("senderData", {}).get("chatId")
            or data.get("chatId")
            or data.get("from")
        )

        # 💬 message safe
        message = (
            data.get("messageData", {})
            .get("textMessageData", {})
            .get("textMessage")
        )

        log("EXTRACTION", {"chat_id": chat_id, "message": message})

        if not chat_id or not message:
            return jsonify({
                "error": "Missing data",
                "chat_id": chat_id,
                "message": message
            })

        # 🤖 IA
        reply = ask_groq(message)

        # 🔁 TRANSFERT
        if reply == "TRANSFERT":
            reply = "Je vous mets en relation avec un conseiller 🙏"

        # 📤 ENVOI GREEN API
        payload = {
            "chatId": chat_id,
            "message": reply
        }

        res = requests.post(GREEN_API_URL, json=payload)

        log("GREEN API RESPONSE", {
            "status_code": res.status_code,
            "response": res.text
        })

        return jsonify({
            "success": True,
            "chat_id": chat_id,
            "reply": reply
        })

    except Exception as e:
        print("\n❌ GLOBAL ERROR:")
        traceback.print_exc()

        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500


# 🚀 RUN SERVER
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)