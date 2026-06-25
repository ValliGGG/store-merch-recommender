# Cloud-hosted refresh — runs without your computer

The local Windows Task Scheduler entry (`ARTMiE_Recommender_Daily`) only runs
when your PC is on. To run the refresh from the cloud (so it works 24/7
regardless of whether your computer is on), use GitHub Actions.

**One-time setup** (~5 minutes total):

## 1. Create a GitHub repo

1. Go to https://github.com/new
2. Repo name: `artmie-recomander` (or anything you like)
3. **Set to Private**
4. Don't initialize with README/license/.gitignore (we have those)
5. Click "Create repository"

## 2. Push this project

In a terminal at `C:\Users\Valerian\Desktop\Claude 1TEST\artmie_recomander\`:

```bash
git init
git add .
git commit -m "Initial commit: ARTMiE recommender"
git branch -M main
git remote add origin git@github.com:<YOUR-USERNAME>/artmie-recomander.git
git push -u origin main
```

(If you don't have SSH keys set up, use the HTTPS URL GitHub shows on
the repo page — `https://github.com/<USERNAME>/artmie-recomander.git`)

## 3. Add the Shopify token as a secret

1. On the GitHub repo page → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**, add:

   | Name | Value |
   |---|---|
   | `ARTMIE_SK_STORE_URL` | `20a254-6e.myshopify.com` |
   | `ARTMIE_SK_API_TOKEN` | `shpat_…` (from your `.env` — never paste real tokens into tracked files) |

## 4. Done — automation is live

- The workflow `.github/workflows/daily_refresh.yml` runs **every day at 02:00 UTC** (~03:00 Bratislava in winter, ~04:00 in summer)
- It runs the same scripts the Windows task does — exact same logic
- Each run takes 25–35 min on a free GitHub Actions runner
- Free tier: 2,000 minutes/month — daily runs ≈ 900 min/month, well within limits
- Logs are saved as workflow artifacts (downloadable from the **Actions** tab)
- You can trigger a manual run any time from **Actions → daily_refresh → Run workflow**

## 5. Disable the local Windows task (optional)

Once you confirm the GitHub workflow is running successfully:

```powershell
schtasks /Delete /TN "ARTMiE_Recommender_Daily" /F
```

The cloud workflow takes over and your PC no longer needs to be on.

---

## What runs in each refresh

1. `02a_incremental_export.py` — pulls new orders since last run
2. `02b_refresh_products.py` — refreshes products + brand + inventory + sale data
3. `03b_compute_bestsellers.py` — re-sorts every collection (with sale-pin, Artmie-pin, season multiplier, **OOS multiplier**)
4. `04_compute_recommendations.py` — refreshes FBT (writes to `custom.recommended_products`)
5. `05_compute_alternatives.py` — refreshes same-category subs (writes to `custom.alternative_products`)

**Daily refresh ensures:** when products come back in stock, they automatically
re-surface to their proper position **within 24 hours**.

---

## Monitoring

- **GitHub UI**: Repo → **Actions** tab shows green/red status of every run
- **Email alerts**: GitHub auto-emails you on the first failure of a workflow
- **Logs**: Every run uploads logs to the workflow artifacts (downloadable, 14-day retention)
