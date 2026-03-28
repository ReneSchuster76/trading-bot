from flask import Flask, request

app = Flask(__name__)

@app.route('/alert', methods=['POST'])
def alert():
    data = request.json
    print("ALERT:", data)
    return "OK", 200

@app.route('/')
def home():
    return "Bot läuft!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
