# FROM python:3.11
# FROM philippvk/isaac-quickstart-demo
FROM philippvk/isaac-quickstart-demo:cv32e40p-latest

WORKDIR /app

RUN apt-get update && apt-get install -y zstd tar

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY worker.py .
COPY run_retarget.sh /scripts/run_retarget.sh

RUN chmod +x /scripts/run_retarget.sh

RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git --recursive /tools/etiss_arch_riscv

CMD ["python", "worker.py"]
ENTRYPOINT []
