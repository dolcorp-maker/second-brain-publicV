# Setting Up Google Integration

This gives the bot access to your Google Calendar, Gmail, and Tasks.  
It takes about 15 minutes. You only do it once.

---

## What you're doing

Google requires you to create your own "app" in their developer console and authorize it to access your account. This sounds more complicated than it is. You're not publishing an app — you're just creating private credentials for your own use.

---

## Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Name it anything — `second-brain-bot` works
4. Click **Create**

---

## Step 2 — Enable the APIs

With your new project selected:

1. Go to **APIs & Services → Library**
2. Search for and enable each of these:
   - **Google Calendar API**
   - **Gmail API**
   - **Tasks API**

Each one: click it → click **Enable**.

---

## Step 3 — Create OAuth credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. If prompted to configure the consent screen first:
   - Click **Configure Consent Screen**
   - Choose **External**
   - Fill in App name (anything), your email for support and developer contact
   - Click **Save and Continue** through the rest — no need to add scopes here
   - On the last screen, click **Back to Dashboard**
4. Back in Credentials → **+ Create Credentials → OAuth client ID**
5. Application type: **Desktop app**
6. Name it anything → click **Create**
7. Click **Download JSON**
8. Rename the downloaded file to `credentials.json`

---

## Step 4 — Add yourself as a test user

Because the app is in "testing" mode, only explicitly added users can authorize it.

1. Go to **APIs & Services → OAuth consent screen**
2. Scroll to **Test users** → click **+ Add Users**
3. Add your Google account email
4. Click **Save**

---

## Step 5 — Place the credentials file

Copy `credentials.json` to your project root:

```bash
cp ~/Downloads/credentials.json /home/master/second-brain-bot/credentials.json
```

Make sure it's in `.gitignore` (it already is if you used this repo).

---

## Step 6 — Authorize the bot

Make sure `ENABLE_GOOGLE=true` is set in your `.env`, then start the bot:

```bash
source venv/bin/activate
python main.py
```

On first run with Google tools, you'll see a URL printed in the terminal. Open it in a browser, sign in with your Google account, allow the permissions, and you'll be redirected to a localhost URL. Copy that full URL and paste it back into the terminal when prompted.

This creates a `token.json` file in the project root. The bot uses this from now on — no need to re-authorize unless you revoke access or delete the file.

---

## Step 7 — Test it

Send your bot:
```
what's on my calendar today
```

If it responds with your events (or "nothing scheduled"), you're done.

---

## Troubleshooting

**"Access blocked: This app's request is invalid"**  
You skipped Step 4. Add your email as a test user.

**"The OAuth client was not found"**  
Wrong project selected, or credentials.json is from a different project. Re-download.

**"Token has been expired or revoked"**  
Delete `token.json` and restart the bot to re-authorize.

**Bot doesn't see new events after adding them**  
Calendar API has a small cache delay. Wait 30 seconds and try again.

---

## Keeping it

`credentials.json` and `token.json` are never committed to git (they're in `.gitignore`).  
Back them up somewhere safe — if you lose them you just redo this process.
