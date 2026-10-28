ARG SPIKE_BASE_IMAGE=philippvk/isaac-quickstart-full:latest
FROM ${SPIKE_BASE_IMAGE}

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends zstd tar build-essential git python3-pip && \
    rm -rf /var/lib/apt/lists/*
ARG M2ISAR_REF=a2a9a9c87bdd97eca3ed6997af3656960b38c215
ARG ETISS_ARCH_REF=45e3067fcaac9e1cd79c4a008fa570c60055af92
RUN git clone https://github.com/PhilippvK/M2-ISA-R.git /opt/m2isar && \
    git -C /opt/m2isar fetch origin ${M2ISAR_REF} && \
    git -C /opt/m2isar checkout FETCH_HEAD && pip3 install /opt/m2isar
ENV PYTHONPATH="/opt/m2isar"
ENV MLONMCU_HOME=/environment
ENV SPIKE_INSTALL_DIR=/environment/deps/install/spike
ENV SPIKE_SOURCE_DIR=/environment/deps/src/spike
ENV SPIKE_BUILD_DIR=/environment/deps/build/spike
RUN mkdir -p "$SPIKE_BUILD_DIR" && cd "$SPIKE_BUILD_DIR" && \
    "$SPIKE_SOURCE_DIR/configure" --prefix="$SPIKE_INSTALL_DIR" --enable-misaligned && \
    make -j"$(nproc)" && make install
COPY etiss/requirements.txt ./requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt
RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git /tools/etiss_arch_riscv && \
    git -C /tools/etiss_arch_riscv fetch origin ${ETISS_ARCH_REF} && \
    git -C /tools/etiss_arch_riscv checkout FETCH_HEAD && \
    git -C /tools/etiss_arch_riscv submodule update --init --recursive

COPY worker.py job_state.py ./
COPY spike/run_retarget.sh /scripts/run_retarget.sh
COPY spike/retarget.py /scripts/retarget_spike.py
RUN chmod +x /scripts/run_retarget.sh

CMD ["python3", "worker.py"]
ENTRYPOINT []
