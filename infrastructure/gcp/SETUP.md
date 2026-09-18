# Setting up the GCP VM

Run these once, on your own machine, to create the server. After this,
`deploy.sh` does everything else and you never repeat these steps.

You need the `gcloud` CLI: https://cloud.google.com/sdk/docs/install

---

## Read this first — what this actually costs

Two separate things, and it is worth keeping them apart.

### The $300 trial credit — your first 90 days

A new account gets **$300 in credit, valid for 90 days**. It pays for anything
that is not covered by the free tier. So for the first 90 days this deployment
costs you **nothing on your card**, whatever the free tier does or does not
include.

Staying inside the free-tier monthly limits does **not** use up the credit. The
credit is only touched by what goes over.

**The real cliff is day 90, and it is not about money.** When the trial ends,
Google stops every resource you created and marks your data for deletion. From
Google's own documentation:

> All resources you created during the trial are stopped. Further, any data you
> stored in services like Compute Engine is marked for deletion and might be lost.

There is a **30-day grace period** to upgrade to a paid account and recover it.
After that it is permanently deleted. Nothing is charged automatically — if you
do nothing, the account simply closes and the demo disappears.

So put a reminder in your calendar for **day 85**. Losing the demo silently is a
worse outcome than a $3 bill.

### After you upgrade — the external IPv4 address

Always Free has no end date and continues after you upgrade. The open question
is the **public IP address**.

Google raised the price of an in-use external IPv4 address on a standard VM to
**$0.005/hour** on 1 February 2024, which is about **$3.65/month**.

**Whether the free-tier e2-micro is exempt is genuinely unclear.** I checked
Google's free-tier feature list, the Compute Engine getting-started page, and
Google's own external-IP pricing announcement. **None of the three mentions the
free tier in connection with external IPs.** Community answers contradict each
other, and there are forum posts from people billed a small amount for an
e2-micro they believed was free.

Do not trust a blog post on this, including one that sounds confident. **Your
billing report after 24–48 hours is the only real answer**, and by then you have
the $300 credit absorbing it anyway.

If it does turn out to be charged, there are only two real options:

- **Accept ~$3.65/month.** It is the entire cost of the deployment.
- **Move to a host that does not charge for the address.** Oracle Cloud Always
  Free has no time limit and no IP charge, and gives far more RAM. The stack is
  Docker Compose, so it is largely the same steps on a different machine.

**A tunnel does not help here, and this is worth stating because it looks like
it should.** Cloudflare Tunnel removes the need for an *inbound* public address,
but a GCP VM with no external IP cannot reach the internet **outbound** either —
and `cloudflared` has to dial out to Cloudflare to work at all. The only way to
give a VM outbound access without its own address is Cloud NAT, and **Cloud NAT
bills its own external IP at the same $0.005/hour**, plus $0.0014/hour of
gateway fee and $0.045/GiB of data processing. That is roughly $56/year against
$43.80 for simply keeping the address. Removing the IP to save money costs more
money.

The tunnel is still worth considering for *security* — the server stops being
directly reachable, and DDoS protection comes free — but not as a way to cut
the bill.

Everything else here is genuinely free and has no end date: instance hours, a
30GB standard disk, 5GB of Cloud Storage, and 1GB/month of outbound traffic.

**Free quotas do not stop when they run out. They stop being free.** Step 2 is
a budget alert for exactly this reason. Do it before creating anything.

---

## 1. Create the project

```bash
gcloud auth login

# Pick any unique id. Lowercase letters, digits and hyphens.
gcloud projects create careeriq-demo --name="CareerIQ"
gcloud config set project careeriq-demo
```

Now link a billing account. **Billing must be enabled even for free tier** —
Google still wants a card on file, and free resources simply bill at zero.

```bash
gcloud billing accounts list          # copy the ACCOUNT_ID
gcloud billing projects link careeriq-demo --billing-account=ACCOUNT_ID
```

---

## 2. Budget alert — do this before anything else

Easiest in the console: **Billing → Budgets & alerts → Create budget**.

- Amount: **$1**
- Alert at 50% and 100%
- Tick "Email alerts to billing admins"

Or with the CLI:

```bash
gcloud billing budgets create \
  --billing-account=ACCOUNT_ID \
  --display-name="careeriq" \
  --budget-amount=1USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=1.0
```

A budget alert **tells you**, it does not stop spending. There is no hard cap
on GCP. This is your early warning, not a wall.

---

## 3. Enable the APIs

```bash
gcloud services enable compute.googleapis.com storage.googleapis.com
```

Takes a minute or two the first time.

---

## 4. Create the VM

Two details here decide whether this is free. Both are easy to get wrong in the
web console, which is why these are CLI commands.

```bash
gcloud compute instances create careeriq \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --boot-disk-type=pd-standard \
  --boot-disk-size=30GB \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --scopes=https://www.googleapis.com/auth/devstorage.read_write \
  --tags=http-server,https-server
```

- **`--machine-type=e2-micro`** — only e2-micro is free. e2-small is not.
- **`--boot-disk-type=pd-standard`** — the console defaults to `pd-balanced`,
  which is **not** in the free tier. This one silently costs money.
- **`--boot-disk-size=30GB`** — the free allowance. Do not go larger.
- **Region must be `us-central1`, `us-west1` or `us-east1`.** No other region is
  free, and none of them are near India. Expect ~250ms. That is the trade.
- **`--scopes=...devstorage.read_write`** lets the VM reach Cloud Storage with no
  key file. Credentials come from the metadata server, so no secret is stored.

---

## 5. Open ports 80 and 443

A new project allows SSH but not web traffic.

```bash
gcloud compute firewall-rules create allow-http \
  --allow=tcp:80 --target-tags=http-server

gcloud compute firewall-rules create allow-https \
  --allow=tcp:443 --target-tags=https-server
```

Port 80 is not optional. Caddy uses it to obtain the certificate.

---

## 6. Create the storage bucket

Resumes go here, never on the VM disk.

```bash
# The name must be globally unique across all of Google. Add something of yours.
gcloud storage buckets create gs://careeriq-uploads-CHANGEME \
  --location=us-central1 \
  --uniform-bucket-level-access
```

**Use a single US region, not `US` multi-region.** The 5GB free allowance is for
regional storage only.

Now let the VM write to it:

```bash
PROJECT_NUMBER=$(gcloud projects describe careeriq-demo --format='value(projectNumber)')

gcloud storage buckets add-iam-policy-binding gs://careeriq-uploads-CHANGEME \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role=roles/storage.objectAdmin
```

---

## 7. Get the IP address

```bash
gcloud compute instances describe careeriq --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

Write it down. If it prints `34.123.45.67`, your hostname is:

```
34-123-45-67.sslip.io
```

sslip.io resolves any name of that shape to the IP inside it. So you get a real
hostname, and a real certificate, without buying a domain.

> **This IP is ephemeral.** If you stop and start the VM it changes, the
> hostname changes, and the certificate no longer matches. A reboot is fine; a
> stop/start is not. If you plan to stop the VM, reserve a static IP — but note
> that an *unattached* static IP is charged at a higher rate than an attached
> one, so releasing it matters if you ever delete the VM.

---

## 8. Set up the machine

```bash
gcloud compute ssh careeriq --zone=us-central1-a
```

Everything below runs **on the VM**.

### Swap first

1GB of RAM has to hold Postgres, the API and Caddy. Swap is not an
optimisation here; without it the build gets killed.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h                      # should show 2.0Gi of swap
```

The `/etc/fstab` line is what makes swap come back after a reboot.

### Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Then SSH back in — group membership only applies to a new login.

```bash
gcloud compute ssh careeriq --zone=us-central1-a
docker run --rm hello-world     # should print a success message
```

---

## 9. Get the code onto the VM

If the repository is public:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/VamshiNITPV/careeriq.git
cd careeriq
```

If it is private, create a read-only deploy key on the VM and add it to GitHub
under **Settings → Deploy keys**:

```bash
ssh-keygen -t ed25519 -C "careeriq-vm" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub        # paste this into GitHub, read-only
git clone git@github.com:VamshiNITPV/careeriq.git
cd careeriq
```

---

## 10. Write the configuration

```bash
cp .env.production.example .env.production
nano .env.production
chmod 600 .env.production
```

Fill in every blank. The app refuses to start otherwise and tells you every
problem at once, so you will not be fixing them one at a time.

Generate the two secrets **on the VM**:

```bash
openssl rand -base64 24                                        # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(64))"  # JWT_SECRET_KEY
```

Set these three to your hostname from step 7:

```
SITE_ADDRESS=34-123-45-67.sslip.io
FRONTEND_BASE_URL=https://34-123-45-67.sslip.io
CORS_ORIGINS=https://34-123-45-67.sslip.io
```

And the bucket from step 6:

```
STORAGE_BUCKET=careeriq-uploads-CHANGEME
```

**Email needs a real provider.** `EMAIL_PROVIDER=console` is refused in
production, because password reset would silently never arrive and lock people
out with no error anywhere. Brevo and Resend both have free tiers that need no
card. Put the SMTP details in.

**`GEMINI_API_KEY`** is needed for resume tailoring. Without it, set
`LLM_PROVIDER=none` and that one feature answers 503 instead of inventing
anything. Everything else works.

> Never paste this file, or any key from it, into a chat, a screenshot, an
> issue, or a commit.

---

## 11. Deploy

```bash
./infrastructure/gcp/deploy.sh
```

It builds the images, starts Postgres, waits for it to be ready, runs the
migrations, builds the frontend, starts everything, and waits for the health
check. It is safe to re-run, and it is the same script for the first deploy and
every one after.

The first run takes a while — it is building two images on a small machine. The
frontend build itself is quick (tested at under a minute with this much swap);
installing the Python dependencies is the slow part.

Then open `https://34-123-45-67.sslip.io`. The certificate takes a few seconds
on the first request while Caddy obtains it.

---

## 12. Seed the demo

```bash
docker compose -f docker-compose.prod.yml run --rm backend python -m app.data.demo
```

Log in as `demo@careeriq.app` / `CareerIQDemo2026!`.

The account is shared, so reset it nightly:

```bash
crontab -e
```

Add this line (3am UTC):

```
0 3 * * * cd ~/careeriq && docker compose -f docker-compose.prod.yml run --rm backend python -m app.data.demo >> ~/demo-reset.log 2>&1
```

---

## Checking it worked

```bash
curl -fsS https://34-123-45-67.sslip.io/api/v1/health/ready
```

Then in a browser, logged in as the demo account:

1. Jobs list sorted by match shows **scores**, not an empty list.
2. Skill gaps show real gaps, not "no target roles set".
3. The applications board has cards in every column.

Finally, **reboot the VM and check it all comes back**:

```bash
gcloud compute instances reset careeriq --zone=us-central1-a
```

Postgres data lives in a named volume and the containers restart themselves, so
nothing should need doing by hand. If swap is missing after the reboot, the
`/etc/fstab` line in step 8 did not get written.

**Check the billing report after 24–48 hours.** That is the only real proof of
what this costs — and specifically, it is how you find out whether the external
IP address is being charged, which Google's documentation does not say.

Look for a line item named **"External IP Charge on a Standard VM"** (SKU
`C054-7F72-A02E`). If it is there, the answer is yes and it is ~$3.65/month. If
it is absent after two days, the free tier covers it.

**Set a calendar reminder for day 85 of the trial.** On day 90 everything stops
and your data is marked for deletion, with a 30-day grace period to upgrade and
recover it.

---

## If something goes wrong

```bash
docker compose -f docker-compose.prod.yml ps        # what is running
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f caddy
free -h                                             # is swap there?
```

**The site does not load at all.** Check the firewall rules from step 5 exist,
and that the IP still matches the hostname (step 7).

**Certificate errors.** Caddy needs port 80 reachable from the internet to get a
certificate. Check the `allow-http` rule, not just `allow-https`.

**The backend will not start.** It prints every configuration problem at once.
Read the list; it names the setting.

**Something was killed during the build.** That is memory. Check `free -h` shows
2GB of swap.

---

## Turning it off

```bash
gcloud compute instances delete careeriq --zone=us-central1-a
gcloud storage rm -r gs://careeriq-uploads-CHANGEME
```

Or delete the whole project, which is the only way to be certain nothing is
left running:

```bash
gcloud projects delete careeriq-demo
```
