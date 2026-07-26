FROM ollama/ollama:latest

ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_MODELS=/workspace/.ollama/models \
    OLLAMA_NUM_PARALLEL=1

COPY start-ollama.sh /usr/local/bin/start-ollama.sh
RUN chmod 755 /usr/local/bin/start-ollama.sh

EXPOSE 11434

ENTRYPOINT ["/usr/local/bin/start-ollama.sh"]
