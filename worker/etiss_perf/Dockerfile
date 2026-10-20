FROM philippvk/isaac-quickstart-etiss-perf:latest
WORKDIR /app
RUN apt-get update && apt-get install -y zstd tar ccache
ENV PATH="/work/venv/bin:${PATH}"
ARG M2ISAR_REF=051d3354811e94f6ed61f4fdc54188370884e828
RUN git clone https://github.com/PhilippvK/M2-ISA-R.git /opt/m2isar && \
    git -C /opt/m2isar fetch origin ${M2ISAR_REF} && \
    git -C /opt/m2isar checkout FETCH_HEAD && pip install -e /opt/m2isar
ENV PYTHONPATH="/opt/m2isar"
COPY etiss/requirements.txt .
RUN pip install -r requirements.txt
COPY worker.py job_state.py ./
COPY etiss_perf/run_retarget.sh /scripts/run_etiss_perf.sh
COPY etiss_perf/dispatch.sh /scripts/run_retarget.sh
COPY etiss/retarget.sh /scripts/retarget_etiss.sh
COPY etiss_perf/retarget.sh /scripts/retarget_etiss_perf.sh
COPY etiss_perf/unpack_hls.py /scripts/unpack_hls.py
COPY etiss/fix_m2isar.py /scripts/fix_m2isar.py
RUN python /scripts/fix_m2isar.py /opt/m2isar
RUN chmod +x /scripts/*.sh
RUN git clone https://github.com/tum-ei-eda/etiss_arch_riscv.git --recursive /tools/etiss_arch_riscv
ENTRYPOINT []
CMD ["python", "worker.py"]
