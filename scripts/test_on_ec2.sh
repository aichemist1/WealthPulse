cd /opt/wealthpulse

# Restart everything
sudo docker compose --env-file prod.env down
sudo docker compose --env-file prod.env up -d

# If you changed code/env and want a clean rebuild
sudo docker compose --env-file prod.env up -d --build --force-recreate

# Check status
sudo docker compose ps

# Tail logs (most useful)
sudo docker compose logs -n 200 --no-color web
sudo docker compose logs -n 200 --no-color backend
sudo docker compose logs -n 200 --no-color db
