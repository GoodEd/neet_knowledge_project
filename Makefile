AWS_REGION ?= ap-south-1
ECS_CLUSTER ?= np-pgrest
STREAMLIT_SERVICE ?= neet-knowledge-dev-streamlit
WORKER_SERVICE ?= neet-knowledge-dev-worker

.PHONY: deploy ecs-shell-worker ecs-shell-streamlit faiss-probe

deploy:
	cd deploy && terraform apply -auto-approve

ecs-shell-worker:
	./deploy/ecs_shell.sh $(AWS_REGION) $(ECS_CLUSTER) $(WORKER_SERVICE) worker

ecs-shell-streamlit:
	./deploy/ecs_shell.sh $(AWS_REGION) $(ECS_CLUSTER) $(STREAMLIT_SERVICE) streamlit

faiss-probe:
	@if [ -z "$(QUERY)" ]; then echo "Usage: make faiss-probe QUERY='your phrase' [TOP_K=5]"; exit 1; fi
	./faiss_probe.sh "$(QUERY)" --top-k $${TOP_K:-5}
