ARG SEAL5_BASE_IMAGE=philippvk/isaac-quickstart-seal5:latest
FROM ${SEAL5_BASE_IMAGE}

WORKDIR /app

ENV PATH="/work/venv/bin:${PATH}"

RUN cp /work/llvm/.seal5/settings.yml /opt/seal5-baseline.yml

RUN apt-get update && apt-get install -y zstd tar

COPY llvm/requirements.txt .
RUN pip install -r requirements.txt

COPY worker.py job_state.py ./
COPY llvm/prepare.py /scripts/prepare_llvm.py
COPY llvm/constant-barrier-matcher.patch /scripts/constant-barrier-matcher.patch
COPY llvm/run_retarget.sh /scripts/run_retarget.sh

# Use the same upstream typed model and Seal5 as GenIE local retargeting.
COPY seal5-main/install.sh /opt/genie-seal5/install.sh
COPY seal5-main/configure_baseline.py /opt/genie-seal5/configure_baseline.py
RUN bash /opt/genie-seal5/install.sh
COPY llvm/model-filenames.patch /opt/genie-seal5/model-filenames.patch
RUN git -C /opt/genie-seal5/src apply /opt/genie-seal5/model-filenames.patch
ENV PYTHONPATH="/opt/genie-seal5/src:/opt/m2isar"

RUN chmod +x /scripts/run_retarget.sh

ARG ETISS_ARCH_REF=45e3067fcaac9e1cd79c4a008fa570c60055af92
RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git /tools/etiss_arch_riscv && \
    git -C /tools/etiss_arch_riscv fetch origin ${ETISS_ARCH_REF} && \
    git -C /tools/etiss_arch_riscv checkout FETCH_HEAD && \
    git -C /tools/etiss_arch_riscv submodule update --init --recursive

CMD ["python", "worker.py"]
ENTRYPOINT []
