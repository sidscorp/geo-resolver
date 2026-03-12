.PHONY: dev download-features build-features

dev:
	cd $(CURDIR) && .venv/bin/python -m uvicorn geo_resolver.api.main:app --host 127.0.0.1 --port 8012 --reload

download-features:
	.venv/bin/python scripts/download_data.py --theme land water land_use place

build-features:
	.venv/bin/python scripts/build_db.py --source features places
