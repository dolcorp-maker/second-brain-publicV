"""
authorize_google.py - Manual OAuth flow for headless Pi.
Opens no browser. Prints a URL, you open it on your Mac,
paste the code back here, done.
"""

import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/tasks",
]

CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")

if not CREDENTIALS_FILE.exists():
    print("❌ credentials.json not found!")
    exit(1)

if TOKEN_FILE.exists():
    TOKEN_FILE.unlink()

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)

# Generate the auth URL without opening any browser
flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
auth_url, _ = flow.authorization_url(prompt="consent")

print("\n🔐 Google Authorization")
print("=" * 60)
print("\n1. Open this URL in your Mac browser:\n")
print(auth_url)
print("\n2. Sign in and click Allow")
print("3. Google will show you a code — paste it here\n")

code = input("Enter the authorization code: ").strip()

flow.fetch_token(code=code)
creds = flow.credentials

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

print("\n✅ Success! token.json saved on the Pi.")
print("   Your bot can now access Google Calendar, Gmail, and Tasks.")
