from flask import Flask, request, jsonify
import json
import os

app = Flask(__name__)

# ─────────────────────────────────────────
# 📋 COLLECTEUR DE CHAT IDs
# Lance ce script, envoie des messages depuis
# différents numéros/groupes, et lis les logs
# ─────────────────────────────────────────

seen_chats: dict = {}   # chatId → dernières infos


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False}), 400

    webhook_type = data.get("typeWebhook", "")
    sender       = data.get("senderData", {})
    msg_data     = data.get("messageData", {})

    chat_id      = sender.get("chatId", "")
    sender_name  = sender.get("senderName", "inconnu")
    chat_name    = sender.get("chatName", "")
    message      = msg_data.get("textMessageData", {}).get("textMessage", "")

    if not chat_id:
        return jsonify({"ok": True, "ignored": True})

    # Détermination du type de chat
    if chat_id.endswith("@g.us"):
        chat_type = "🟡 GROUPE"
    elif chat_id.endswith("@c.us"):
        chat_type = "🔵 INDIVIDUEL"
    else:
        chat_type = "⚪ AUTRE"

    # Stockage
    seen_chats[chat_id] = {
        "type":        chat_type,
        "chat_id":     chat_id,
        "sender_name": sender_name,
        "chat_name":   chat_name or sender_name,
        "last_msg":    message[:80],
        "webhook":     webhook_type,
    }

    # ─── LOG CONSOLE (lisible sur Render) ───
    print("\n" + "─" * 55)
    print(f"  {chat_type}")
    print(f"  CHAT ID    : {chat_id}")
    print(f"  NOM        : {chat_name or sender_name}")
    print(f"  MESSAGE    : {message[:80]}")
    print(f"  TYPE EVENT : {webhook_type}")
    print("─" * 55)

    return jsonify({"ok": True, "chat_id": chat_id})


# ─────────────────────────────────────────
# 📊 PAGE DE RÉSUMÉ — ouvre dans ton browser
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def summary():
    if not seen_chats:
        return (
            "<h2>Aucun chat détecté pour l'instant.</h2>"
            "<p>Envoie un message WhatsApp vers ton instance Green API "
            "et recharge cette page.</p>",
            200,
            {"Content-Type": "text/html"}
        )

    rows = ""
    for cid, info in seen_chats.items():
        rows += f"""
        <tr>
          <td>{info['type']}</td>
          <td><code style="background:#f0f0f0;padding:4px 8px;border-radius:4px;
                           font-size:14px;user-select:all">{cid}</code></td>
          <td>{info['chat_name']}</td>
          <td>{info['last_msg']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Chat IDs — Chana Corporate</title>
  <style>
    body {{ font-family: sans-serif; padding: 32px; background: #fafafa; }}
    h1   {{ color: #1a1a2e; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff;
             box-shadow: 0 2px 8px rgba(0,0,0,.08); border-radius: 8px;
             overflow: hidden; }}
    th   {{ background: #1a1a2e; color: #fff; padding: 12px 16px;
            text-align: left; font-weight: 500; }}
    td   {{ padding: 12px 16px; border-bottom: 1px solid #eee;
            vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .tip {{ background: #fff8e1; border-left: 4px solid #f9a825;
            padding: 12px 16px; margin-top: 24px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>📋 Chat IDs détectés</h1>
  <p>{len(seen_chats)} conversation(s) capturée(s) — recharge la page pour actualiser.</p>
  <table>
    <thead>
      <tr>
        <th>Type</th>
        <th>Chat ID (copie ce texte)</th>
        <th>Nom</th>
        <th>Dernier message</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="tip">
    <strong>💡 Pour trouver ton groupe interne :</strong><br>
    Envoie n'importe quel message dans le groupe WhatsApp concerné,
    le <code>chatId</code> du type <code>XXXXXXXXXX@g.us</code> apparaîtra ici.<br><br>
    Copie-le et colle-le dans la variable d'environnement
    <code>INTERNAL_GROUP_ID</code> sur Render.
  </div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html"}


# ─────────────────────────────────────────
# 📡 API JSON si tu préfères
# ─────────────────────────────────────────
@app.route("/chats", methods=["GET"])
def chats_json():
    return jsonify({
        "total": len(seen_chats),
        "chats": list(seen_chats.values())
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"""
    ╔══════════════════════════════════════════╗
    ║   🔍  CHAT ID COLLECTOR — EN ÉCOUTE     ║
    ║   Port : {port}                            ║
    ║   → Ouvre https://TON-APP.onrender.com  ║
    ║     pour voir tous les chat IDs          ║
    ╚══════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
