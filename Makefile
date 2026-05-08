IMAGE_NAME     := lnbits-price-aggregator
CONTAINER_NAME := lnbits-price-aggregator

.PHONY: build run ruff test

build:
	docker build -t $(IMAGE_NAME) .

run:
	-docker rm -f $(CONTAINER_NAME) 2>/dev/null
	docker run -d -t -p 8000:8000 --name $(CONTAINER_NAME) --restart unless-stopped $(IMAGE_NAME)
	docker logs -f $(CONTAINER_NAME)

ruff:
	uv run ruff check app/ tests/

test:
	uv run pytest
