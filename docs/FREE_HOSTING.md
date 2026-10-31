# Free hosting

Host NEET Compass for **₹0 a month**. The whole app is one Python service: FastAPI serves the website (Jinja2
templates + HTMX) and the API from the same address.

| Part | Service | Free plan |
|---|---|---|
| Website + API (Python, Docker) | [Render](https://render.com) free web service | Sleeps after 15 min idle, ~1 min to wake; 750 hours/month |
| Database (PostgreSQL) | [Neon](https://neon.com) Free | 1 GB storage, scales to zero when idle |
| Email (guardian consent) | Any free SMTP service, e.g. [Brevo](https://www.brevo.com) | Enough for sign-up emails |
| Domain + DNS (optional) | [Cloudflare](https://www.cloudflare.com) Free | Free DNS and protection; you pay only for the domain |

The only running cost is AI usage on your OpenRouter key: about ₹0.05–0.17 per assistant question, and about
₹0.04 per new practice question.

## Trade-offs of the free plans

- **The site sleeps.** After 15 quiet minutes, Render stops the service. The next visitor waits about a minute for
  the first page while it wakes. Background question writing also pauses while it sleeps.
- **Uploaded files are temporary.** Render's free disk is wiped on every restart. Imported data (cutoffs, fees,
  questions) is safe because it lives in the database, but the raw uploaded PDF/CSV files are not kept. For
  permanent file storage, upgrade to a paid instance with a disk.
- **No uptime guarantee.** Fine for a pilot, a portfolio or early users, not for exam-week traffic.

To remove the sleep, the cheapest step is a paid Render instance (about $7/month). Everything else can stay free.

## Before you start

1. **Put the code on GitHub.** Render deploys from a GitHub repository.
   - Secrets are not committed: `backend/.env` and the other secret files are git-ignored. Check that no commit
     contains your OpenRouter key.
2. **Make an OpenRouter key for production** at openrouter.ai, with a monthly spending limit. Use a new key, not
   the one used during development.

## Step 1 — Database (Neon)

1. Sign up at neon.com and create a project.
   - **Region:** AWS Asia Pacific (Singapore), the closest to India and to Render's Singapore region.
   - **Postgres:** the default version.
2. On the project dashboard, choose **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.
   You can paste it exactly as given; the app adds the driver name itself.

## Step 2 — The site (Render)

1. Sign up at render.com with your GitHub account.
2. Choose **New → Blueprint** and pick your repository. Render reads `render.yaml` and creates the
   `neet-compass` service (free plan, Docker, Singapore).
3. Fill in the values Render asks for:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `PUBLIC_APP_URL` | the site's address, e.g. `https://neet-compass.onrender.com` (Render shows it after the first deploy; update it then, or when you add your own domain) |
| `SEED_DEMO_PASSWORD` | a long password for the demo accounts `admin@demo.test` / `student@demo.test` |
| `OPENROUTER_API_KEY` | your production OpenRouter key |
| `EMAIL_FROM`, `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | from your SMTP provider (for Brevo: SMTP & API → SMTP) |

   `JWT_SECRET` is generated for you.

4. **First deploy.** It takes about 5 minutes. On its first start the app:
   - creates the database tables;
   - loads the reference data and the clearly-labelled demo data (`SEED_ON_START=demo`);
   - imports the 657 ready-made practice questions in `backend/data/question_bank.json`.

   Later restarts skip anything already there.
5. **Check it.** Open `https://neet-compass.onrender.com/api/ready`. It should show
   `{"status":"ok","database":"ok"}`. Then open `https://neet-compass.onrender.com` for the website.

**No SMTP yet?** Set `ENV=staging` and `EMAIL_BACKEND=console` in Render. Everything works except under-18
sign-ups, because guardian-consent emails are only logged, not sent. Switch back to `ENV=production` once SMTP is
set up.

## Step 3 — After launch

- **Sign in as `admin@demo.test`** and open **/admin → Overview**. The readiness list shows what is still needed
  for real use: real data, the legal review, and an expert-reviewed question bank.
- **Real launch:** remove the demo data first. Set `SEED_ON_START=reference` in Render, then run
  `python -m app.seed --remove-demo` against the Neon database from your computer (set `DATABASE_URL` to the Neon
  string). The free Render plan has no shell.
- **Updates:** every push to GitHub redeploys automatically.
- **Keep an eye on usage:** Neon's dashboard shows storage (1 GB is plenty for this app), and OpenRouter shows AI
  spend.

## Step 4 — Your own domain on Cloudflare (optional)

Cloudflare's free plan manages your domain's DNS and adds DDoS protection. Render keeps serving the site.

**Cost:** the domain itself is the only expense. A `.com` or `.in` costs about ₹500–1,000 a year from any
registrar (Cloudflare Registrar sells some extensions at cost).

1. **Add the domain to Cloudflare.**
   - Sign up at cloudflare.com and choose **Add a domain**, picking the **Free** plan.
   - Cloudflare gives you two nameservers. Set them at the registrar where you bought the domain.
   - Wait until Cloudflare shows the domain as **Active**. This usually takes minutes, occasionally up to a day.
2. **Add the domain in Render.** Open the `neet-compass` service → **Settings → Custom Domains** and add both
   `example.in` and `www.example.in`. Render shows the DNS records it expects.
3. **Create the records in Cloudflare** (DNS → Records):
   - **CNAME** `www` → `neet-compass.onrender.com`
   - **CNAME** `@` (the bare domain) → `neet-compass.onrender.com` (Cloudflare allows this through CNAME flattening)

   Set the proxy status to **DNS only** (grey cloud), so Render can verify the domain and issue the HTTPS
   certificate itself.
4. **Wait for Render.** Each domain should show **Verified** and a certificate in Render. Render redirects the bare
   domain to `www` (or the other way round, as you choose).
5. **Update Render.** Set `PUBLIC_APP_URL` to `https://www.example.in` (your primary domain). It is used in
   guardian-consent email links.
6. **Optional, and free in Cloudflare:**
   - **Email routing:** forward `contact@example.in` to your Gmail.
   - **Email records:** add the SPF/DKIM records your SMTP provider gives you, so guardian emails don't land in
     spam.

## Fully free and always on (advanced)

Oracle Cloud's Always Free tier includes an ARM virtual machine that can run the whole stack with
`deploy/docker-compose.prod.yml`: PostgreSQL, Redis, the app and HTTPS (see [DEPLOYMENT.md](DEPLOYMENT.md)).

- **What you get:** nothing sleeps, and uploaded files are kept.
- **What it takes:** sign-up needs a card for identity checks, and you run and update the server yourself.
- **Domain:** use a free subdomain (e.g. DuckDNS) or your own domain for the HTTPS certificate.
