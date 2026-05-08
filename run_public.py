from pyngrok import ngrok, conf
from database import init_db
import app as flask_app
import sys

# ── Setup ─────────────────────────────────────────────────────────────────────
# Paste your ngrok authtoken here after signing up at https://ngrok.com
# (free account – takes 30 seconds)
NGROK_TOKEN = ""   # <-- paste token here

def main():
    init_db()

    if NGROK_TOKEN:
        ngrok.set_auth_token(NGROK_TOKEN)

    try:
        tunnel = ngrok.connect(5000, "http")
        public_url = tunnel.public_url
        print("\n" + "="*55)
        print("  Mythri Associates LMS – Public URL")
        print("="*55)
        print(f"  {public_url}")
        print("="*55)
        print("  Share this link with anyone.")
        print("  Login: GVR / admin123  (Admin)")
        print("  Login: Suresh01 / staff123  (Staff)")
        print("="*55 + "\n")
        flask_app.app.run(port=5000)
    except Exception as e:
        print(f"\nError starting tunnel: {e}")
        print("\nFalling back to local-only mode...")
        print("App running at: http://localhost:5000\n")
        flask_app.app.run(debug=True, host='0.0.0.0', port=5000)

if __name__ == '__main__':
    main()
