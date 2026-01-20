# Changes made

## 1. Caddyfile (new file)
- Caddy configuration with automatic SSL via Let’s Encrypt  
- Reverse proxy to Gunicorn on port `8000`  
- Serves tracking scripts (`/main.js`, `/lib.min.js`) with CORS headers  
- Single-domain setup optimized for self-hosting  

## 2. apps/tracker/views.py
- Added `asset_proxy` view that replaces the Cloudflare Worker  
- Proxies external resources with proper CORS headers  
- Handles caching headers  

## 3. config/urls.py
- Added `/asset-proxy` endpoint routing  

## 4. config/settings/base.py
- Added `APP_URL` and `EDGE_URL` environment variables  

## 5. apps/tracker/tools.py
- Updated `create_proxy_url()` to use configurable `APP_URL`  
- Domain exclusion list now uses the configured domain  

## 6. frontend/tracker_script/tracking_script.js
- Auto-detects URLs from the script `src` attribute  
- Supports `data-tracker-url` and `data-lib-url` overrides  
- Works with single-domain self-hosted setups  

## 7. apps/projects/utils.py
- Uses configurable `EDGE_URL` for the tracking script snippet  

## 8. .env.example (new file)
- Sample environment variables for deployment  

---

# Reviewer notes

- Users need to download **rrweb** (`lib.min.js`) and place it in  
  `frontend/tracker_script/`  
- The deploy script (`github-deploy.sh`) still restarts **Gunicorn** —  
  **Caddy** runs separately  
- For production, restart Caddy after config changes:  
  ```bash
  sudo systemctl restart caddy
