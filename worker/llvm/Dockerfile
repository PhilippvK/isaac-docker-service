# FROM python:3.11
# FROM philippvk/isaac-quickstart-demo
FROM philippvk/isaac-quickstart-demo:cv32e40p-latest

WORKDIR /app

RUN cp /work/llvm/.seal5/settings.yml /opt/seal5-baseline.yml

RUN apt-get update && apt-get install -y zstd tar

COPY llvm/requirements.txt .
RUN pip install -r requirements.txt

COPY worker.py job_state.py ./
COPY llvm/prepare.py /scripts/prepare_llvm.py
COPY llvm/run_retarget.sh /scripts/run_retarget.sh

RUN chmod +x /scripts/run_retarget.sh

ARG ETISS_ARCH_REF=45e3067fcaac9e1cd79c4a008fa570c60055af92
RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git /tools/etiss_arch_riscv && \
    git -C /tools/etiss_arch_riscv fetch origin ${ETISS_ARCH_REF} && \
    git -C /tools/etiss_arch_riscv checkout FETCH_HEAD && \
    git -C /tools/etiss_arch_riscv submodule update --init --recursive

CMD ["python", "worker.py"]
ENTRYPOINT []
