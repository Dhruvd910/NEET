# Free hosting

Host NEET Compass for **₹0 a month** with three free services:

| Part | Service | Free plan |
|---|---|---|
| Website (Next.js) | [Vercel](https://vercel.com) Hobby | Free forever; **personal, non-commercial use only** |
| API (FastAPI, Docker) | [Render](https://render.com) free web service | Sleeps after 15 min idle, ~1 min to wake; 750 hours/month |
| Database (PostgreSQL) | [Neon](https://neon.com) Free | 1 GB storage, scales to zero when idle |
| Email (guardian consent) | Any free SMTP service, e.g. [Brevo](https://www.brevo.com) | Enough for sign-up emails |
| Domain + DNS (optional) | [Cloudflare](https://www.cloudflare.com) Free | Free DNS and protection; you pay only for the domain |

The only running cost is AI usage on your OpenRouter key: about ₹0.05–0.17 per assistant question, and about
₹0.04 per new practice question.

## Trade-offs of the free plans

- **The API sleeps.** After 15 quiet minutes, Render stops the API. The next visitor waits about a minute while it
  wakes; the website retries automatically and shows "The server is waking up" if something can't wait.
  Background question writing also pauses while it sleeps.
- **Uploaded files are temporary.** Render's free disk is wiped on every restart. Imported data (cutoffs, fees,
  questions) is safe because it lives in the database, but the raw uploaded PDF/CSV files are not kept. For
  permanent file storage, upgrade the API to a paid instance with a disk.
- **Vercel Hobby is for non-commercial use.** If you start charging students or run ads, move to Vercel Pro, or host
  the website on Netlify or Cloudflare Pages instead.
- **No uptime guarantee.** Fine for a pilot, a portfolio or early users, not for exam-week traffic.

To remove the sleep, the cheapest step is a paid Render instance for the API (about $7/month). Everything else can
stay free.

## Before you start

1. **Put the code on GitHub.** All three services deploy from a GitHub repository.
   - Create an empty **private** repository on github.com, for example `neet-compass`.
   - Push this project to it, using GitHub Desktop or `git push`.
   - Secrets are not committed: `backend/.env` and the other secret files are git-ignored. Check that the first
     commit does **not** contain your OpenRouter key.
2. **Make an OpenRouter key for production** at openrouter.ai, with a monthly spending limit. Use a new key, not
   the one used during development.

## Step 1 — Database (Neon)

1. Sign up at neon.com and create a project.
   - **Region:** AWS Asia Pacific (Singapore), the closest to India and to Render's Singapore region.
   - **Postgres:** the default version.
2. On the project dashboard, choose **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.
   You can paste it exactly as given; the app adds the driver name itself.

## Step 2 — API (Render)

1. Sign up at render.com with your GitHub account.
2. Choose **New → Blueprint** and pick your repository. Render reads `render.yaml` and creates the
   `neet-compass-api` service (free plan, Docker, Singapore).
3. Fill in the values Render asks for:

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `PUBLIC_APP_URL` | your Vercel address from Step 3, e.g. `https://neet-compass.vercel.app`. Put a placeholder now and update it after Step 3 |
| `CORS_ORIGINS` | the same address as a JSON list: `["https://neet-compass.vercel.app"]` |
| `SEED_DEMO_PASSWORD` | a long password for the demo accounts `admin@demo.test` / `student@demo.test` |
| `OPENROUTER_API_KEY` | your production OpenRouter key |
| `EMAIL_FROM`, `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | from your SMTP provider (for Brevo: SMTP & API → SMTP) |

   `JWT_SECRET` is generated for you.

4. **First deploy.** It takes about 5 minutes. On its first start the API:
   - creates the database tables;
   - loads the reference data and the clearly-labelled demo data (`SEED_ON_START=demo`);
   - imports the 657 ready-made practice questions in `backend/data/question_bank.json`.

   Later restarts skip anything already there.
5. **Check it.** Open `https://neet-compass-api.onrender.com/api/ready`. It should show
   `{"status":"ok","database":"ok"}`.

**No SMTP yet?** Set `ENV=staging` and `EMAIL_BACKEND=console` in Render. Everything works except under-18
sign-ups, because guardian-consent emails are only logged, not sent. Switch back to `ENV=production` once SMTP is
set up.

## Step 3 — Website (Vercel)

1. Sign up at vercel.com with your GitHub account and choose **Add New → Project**, then your repository.
2. Set **Root Directory** to `frontend`. Vercel detects Next.js.
3. Add one environment variable: `API_ORIGIN` = `https://neet-compass-api.onrender.com`, your Render address,
   with no trailing slash.
4. Deploy. Your site is live at `https://<project>.vercel.app`.
5. Go back to Render and set `PUBLIC_APP_URL` and `CORS_ORIGINS` to this address. Render redeploys by itself.

The website forwards every `/api/...` request to Render, so the browser only ever talks to your Vercel address.
That keeps the sign-in cookie first-party and secure.

## Step 4 — After launch

- **Sign in as `admin@demo.test`** and open **/admin → Overview**. The readiness list shows what is still needed
  for real use: real data, the legal review, and an expert-reviewed question bank.
- **Real launch:** remove the demo data first. Set `SEED_ON_START=reference` in Render, then run
  `python -m app.seed --remove-demo` against the Neon database from your computer (set `DATABASE_URL` to the Neon
  string). The free Render plan has no shell.
- **Updates:** every push to GitHub redeploys both services automatically.
- **Custom domain:** see Step 5 (Cloudflare).
- **Keep an eye on usage:** Neon's dashboard shows storage (1 GB is plenty for this app), and OpenRouter shows AI
  spend.

## Step 5 — Your own domain on Cloudflare (optional)

Cloudflare's free plan manages your domain's DNS and adds DDoS protection. Vercel keeps serving the website.

**Cost:** the domain itself is the only expense. A `.com` or `.in` costs about ₹500–1,000 a year from any
registrar (Cloudflare Registrar sells some extensions at cost).

1. **Add the domain to Cloudflare.**
   - Sign up at cloudflare.com and choose **Add a domain**, picking the **Free** plan.
   - Cloudflare gives you two nameservers. Set them at the registrar where you bought the domain.
   - Wait until Cloudflare shows the domain as **Active**. This usually takes minutes, occasionally up to a day.
2. **Add the domain in Vercel.** Go to your project → **Settings → Domains** and add both `example.in` and
   `www.example.in`. Vercel then shows the exact DNS records it wants, usually:
   - an **A** record for `@` (the bare domain), and
   - a **CNAME** record for `www`.
3. **Create those records in Cloudflare** (DNS → Records), using the exact values Vercel shows. Set the proxy
   status to **DNS only** (grey cloud).
   - Vercel then issues the HTTPS certificate itself.
   - With the orange cloud on, Vercel can't renew certificates and you can get redirect loops. Vercel recommends
     DNS only.
4. **Wait for Vercel.** Each domain should show "Valid Configuration" in Vercel. Choose which one is primary; the
   other redirects to it.
5. **Update Render.** Set `PUBLIC_APP_URL` to `https://www.example.in` (your primary domain) and `CORS_ORIGINS` to
   `["https://www.example.in"]`. These are used in guardian-consent email links.
6. **Optional, and free in Cloudflare:**
   - **Email routing:** forward `contact@example.in` to your Gmail.
   - **Email records:** add the SPF/DKIM records your SMTP provider gives you, so guardian emails don't land in
     spam.

The API stays at its Render address. The website forwards `/api` to it, so the API needs no domain of its own.

## Fully free and always on (advanced)

Oracle Cloud's Always Free tier includes an ARM virtual machine that can run the whole stack with
`deploy/docker-compose.prod.yml`: PostgreSQL, Redis, the API, the website and HTTPS (see
[DEPLOYMENT.md](DEPLOYMENT.md)).

- **What you get:** nothing sleeps, and uploaded files are kept.
- **What it takes:** sign-up needs a card for identity checks, and you run and update the server yourself.
- **Domain:** use a free subdomain (e.g. DuckDNS) or your own domain for the HTTPS certificate.
