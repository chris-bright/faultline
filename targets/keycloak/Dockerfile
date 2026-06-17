FROM alpine AS downloader
RUN wget -O /dd-java-agent.jar \
    https://github.com/DataDog/dd-trace-java/releases/latest/download/dd-java-agent.jar

FROM quay.io/keycloak/keycloak:latest
COPY --from=downloader /dd-java-agent.jar /opt/keycloak/dd-java-agent.jar

USER keycloak
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start-dev"]
