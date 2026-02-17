# Free hosting options for TEI-edit

You can buy a domain and point it at a **free** host so you pay only for the domain (typically €10–15/year). Below are options that offer free tiers suitable for a small Flask app like this.

---

## Always-free or long-term free

| Provider | What you get | Caveats |
|----------|--------------|--------|
| **Oracle Cloud Free Tier** | 2 small AMD VMs or 4 ARM VMs, always free. You get a real VPS: install Python, nginx/Caddy, run gunicorn, set up cron. | Requires credit card for signup (they don’t charge if you stay in free tier). Some users report verification issues. Good docs and community. |
| **PythonAnywhere** | Hosted Python environment; run a Flask app on their servers. Free tier: 1 web app, limited CPU/disk. **Custom domain requires a paid account.** | No custom reverse proxy; they handle HTTPS. Free tier has limits (e.g. outbound HTTP only from whitelisted hosts). Easiest if you want zero server admin. Step-by-step: [Deploy on PythonAnywhere](DEPLOY_PYTHONANYWHERE.md). |
| **Fly.io** | Free allowance: a few shared-cpu VMs, limited bandwidth. You deploy with `fly launch` and they run your container. | Free tier can run out if traffic grows. You may need to add a small payment method for verification. |

## Free tier with limits or spin-down

| Provider | What you get | Caveats |
|----------|--------------|--------|
| **Render** | Free web service tier. They run your app from GitHub. | Service **spins down after inactivity**; first request after idle can be slow (cold start). Fine for low-traffic or demo use. |
| **Railway** | Monthly free credit. You connect the repo and they run the app. | Credit runs out; then you pay or the app stops. Good for trying things out. |

## Practical recommendation

- **No server admin, minimal setup:** **PythonAnywhere** free tier. Point your domain at their instructions, set env vars in their UI, run the app. Check their docs for Flask and for any limits on file uploads/outbound requests.
- **Real VPS, no monthly cost:** **Oracle Cloud Free Tier**. Create an “Always Free” VM, install Python + Caddy (or nginx), clone your repo, follow [DEPLOY.md](../DEPLOY.md). You pay only for the domain.
- **Containers, okay with usage limits:** **Fly.io** free allowance. Deploy with a `Dockerfile` or use their Python buildpack; set `SECRET_KEY` and other env in their dashboard; point your domain at the app.

## Domain only

Once you have a host, buy a domain from any registrar (e.g. Namecheap, Gandi, Cloudflare Registrar, your university may offer subdomains). Set an **A record** (or the host’s **CNAME**) to the IP or hostname the host gives you. No need to pay for “hosting” from the registrar; you only need DNS.

## Summary

You can run TEI-edit at **no monthly hosting cost** by using Oracle Cloud Free Tier (VPS) or PythonAnywhere (managed Python hosting), and pay only for a domain. For Oracle you’ll do the proxy and cron setup from [DEPLOY.md](../DEPLOY.md); for PythonAnywhere you follow their Flask and static files docs instead.
