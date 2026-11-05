# Separate verifier image (Harbor builds it from tests/ because this file
# exists). Holds the verifier code and expected-policy fixture; no ops sidecar.
FROM python:3.12-slim@sha256:e70237b264442328526ff29d6b3c43bd8abcf6cbab78a949322fb69b7d91d6b6

ENV PYTHONDONTWRITEBYTECODE=1
COPY . /tests/
RUN chmod 755 /tests/test.sh
WORKDIR /tests
