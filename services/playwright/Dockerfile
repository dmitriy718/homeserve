FROM mcr.microsoft.com/playwright:v1.62.1-noble

USER root
WORKDIR /opt/playwright-test
COPY package.json package-lock.json test.js seccomp_profile.json ./
RUN npm ci --omit=dev \
 && chown -R pwuser:pwuser /opt/playwright-test
USER pwuser
CMD ["node", "test.js"]

