imageVersion=1.0.0
imageName= mariuscristian/numerous-requirements:${imageVersion}


install:
	pip3 install -e .

run-tests:
	python3 -m pytest

run-benchmark:
	python3 ./benchmark/tst.py 1000 100

benchmark:
	@echo python3 ./benchmark/tst.py $(filter-out $@,$(MAKECMDGOALS))

image:
	docker image build -t ${imageName} .
	docker push imageName

%:
	@:

