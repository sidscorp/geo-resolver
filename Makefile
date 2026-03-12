.PHONY: dev dev-api dev-frontend build deploy download-features build-features

dev-api:
	cd /home/snambiar/projects/geo-resolver && .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8012 --reload

dev-frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 dev-api dev-frontend

build:
	cd frontend && npm run build

deploy: build
	sudo cp -r frontend/dist/* /var/www/georesolver.snambiar.com/
	sudo chown -R www-data:www-data /var/www/georesolver.snambiar.com
	sudo systemctl restart geo-resolver

download-features:
	.venv/bin/python scripts/download_data.py --theme land water land_use place

build-features:
	.venv/bin/python scripts/build_db.py --source features places
