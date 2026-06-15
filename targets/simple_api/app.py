import os
import time
import random
from flask import Flask, jsonify

app = Flask(__name__)
START_TIME = time.time()


@app.route("/health")
def health():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return jsonify({"status": "degraded", "reason": "DATABASE_URL not set"}), 503

    return jsonify({
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
    })


@app.route("/work")
def work():
    # Simulates variable-cost work
    time.sleep(random.uniform(0.01, 0.05))
    return jsonify({"result": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
