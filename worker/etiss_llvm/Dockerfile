ARG COMBINED_BASE_IMAGE=philippvk/isaac-quickstart-full:latest
FROM ${COMBINED_BASE_IMAGE}

WORKDIR /app

RUN cp /work/llvm/.seal5/settings.yml /opt/seal5-baseline.yml

ENV PATH="/work/venv/bin:${PATH}"

RUN apt-get update && apt-get install -y zstd tar ccache

COPY etiss_llvm/requirements.txt .
RUN pip install -r requirements.txt

COPY worker.py job_state.py ./
COPY llvm/prepare.py /scripts/prepare_llvm.py
COPY etiss_llvm/run_retarget.sh /scripts/run_retarget.sh
COPY llvm/run_retarget.sh /scripts/retarget_llvm.sh
COPY etiss/retarget.sh /scripts/retarget_etiss.sh


# Use the same upstream typed model and Seal5 as GenIE local retargeting.
COPY seal5-main/install.sh /opt/genie-seal5/install.sh
COPY seal5-main/configure_baseline.py /opt/genie-seal5/configure_baseline.py
RUN bash /opt/genie-seal5/install.sh
ENV PYTHONPATH="/opt/genie-seal5/src:/opt/m2isar"

RUN chmod +x /scripts/*.sh

RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git --recursive /tools/etiss_arch_riscv

CMD ["python", "worker.py"]
ENTRYPOINT []
